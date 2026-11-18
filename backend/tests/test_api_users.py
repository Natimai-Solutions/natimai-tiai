"""Console user management: CRUD, admin reset, self-service change, and the
mailed "forgot password" flow.

DB-backed tests require TIAI_TEST_DATABASE_URL; the unit tests at the bottom
always run.
"""

import asyncio
from datetime import timedelta

import pytest

# --- Helpers ---------------------------------------------------------------

STRONG = "correct-horse-battery"  # >= PASSWORD_MIN_LENGTH


async def _login(client, email: str, password: str):
    return await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )


async def _headers(client, db_session, email: str, group, password: str = STRONG):
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=password, groups=[group])
    resp = await _login(client, email, password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client, db_session, email: str = "admin@test.local"):
    """An administrator on a database carrying the three built-in groups, as
    the migration and the seed script leave it."""
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.ensure_builtin_groups(db_session)
    await db_session.commit()
    return await _headers(client, db_session, email, BuiltinGroup.ADMIN)


async def _readonly(client, db_session, email: str = "ro@test.local"):
    from app.features.user.permissions import BuiltinGroup

    return await _headers(client, db_session, email, BuiltinGroup.READONLY)


async def _group_id(client, headers, key: str) -> str:
    """Id of a built-in group, as the console would learn it."""
    groups = (await client.get("/api/v1/groups", headers=headers)).json()
    return next(g["id"] for g in groups if g["builtin_key"] == key)


def _code(resp) -> str:
    return resp.json()["error"]["code"]


# --- Access control --------------------------------------------------------


async def test_readonly_cannot_reach_user_management(client, db_session):
    headers = await _readonly(client, db_session)
    resp = await client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 403
    assert _code(resp) == "auth.permission.denied"


async def test_anonymous_cannot_list_users(client, db_session):
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


# --- Create ----------------------------------------------------------------


async def test_admin_creates_account_that_can_log_in(client, db_session):
    headers = await _admin(client, db_session)
    readonly = await _group_id(client, headers, "readonly")
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "marie@test.local",
            "password": STRONG,
            "full_name": "Marie Dupont",
            "group_ids": [readonly],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "marie@test.local"
    assert [g["name"] for g in body["groups"]] == ["Lecture seule"]
    assert body["is_active"] is True
    assert "password" not in body and "hashed_password" not in body

    assert (await _login(client, "marie@test.local", STRONG)).status_code == 200


async def test_duplicate_email_is_rejected(client, db_session):
    headers = await _admin(client, db_session)
    payload = {"email": "dup@test.local", "password": STRONG}
    assert (
        await client.post("/api/v1/users", headers=headers, json=payload)
    ).status_code == 201
    resp = await client.post("/api/v1/users", headers=headers, json=payload)
    assert resp.status_code == 409
    assert _code(resp) == "user.email.taken"


async def test_short_password_is_rejected(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "weak@test.local", "password": "short"},
    )
    assert resp.status_code == 422
    assert _code(resp) == "request.validation_error"


# --- Update ----------------------------------------------------------------


async def test_admin_updates_name_groups_and_activation(client, db_session):
    headers = await _admin(client, db_session)
    admin_group = await _group_id(client, headers, "admin")
    created = (
        await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": "bob@test.local", "password": STRONG},
        )
    ).json()
    # No groups asked for, none granted: the account exists and sees nothing.
    assert created["groups"] == []

    resp = await client.patch(
        f"/api/v1/users/{created['id']}",
        headers=headers,
        json={"full_name": "Bob", "group_ids": [admin_group], "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Bob"
    assert [g["name"] for g in body["groups"]] == ["Administrateurs"]
    assert body["is_active"] is False

    # Deactivated accounts can no longer authenticate.
    assert (await _login(client, "bob@test.local", STRONG)).status_code == 401


async def test_update_to_an_existing_email_is_rejected(client, db_session):
    headers = await _admin(client, db_session)
    for email in ("a@test.local", "b@test.local"):
        await client.post(
            "/api/v1/users", headers=headers, json={"email": email, "password": STRONG}
        )
    users = (await client.get("/api/v1/users", headers=headers)).json()["items"]
    target = next(u for u in users if u["email"] == "b@test.local")

    resp = await client.patch(
        f"/api/v1/users/{target['id']}", headers=headers, json={"email": "a@test.local"}
    )
    assert resp.status_code == 409
    assert _code(resp) == "user.email.taken"


async def test_unknown_user_is_404(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000000000", headers=headers
    )
    assert resp.status_code == 404
    assert _code(resp) == "user.not_found"


# --- Self-protection (keeps at least one admin standing) -------------------


@pytest.mark.parametrize(
    "payload",
    [{"is_active": False}, {"group_ids": []}],
    ids=["deactivate", "demote"],
)
async def test_admin_cannot_lock_themselves_out(client, db_session, payload):
    headers = await _admin(client, db_session)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()

    resp = await client.patch(
        f"/api/v1/users/{me['id']}", headers=headers, json=payload
    )
    assert resp.status_code == 400
    assert _code(resp) == "user.self.forbidden"


async def test_admin_cannot_delete_themselves(client, db_session):
    headers = await _admin(client, db_session)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()

    resp = await client.delete(f"/api/v1/users/{me['id']}", headers=headers)
    assert resp.status_code == 400
    assert _code(resp) == "user.self.forbidden"


async def test_admin_may_rename_themselves(client, db_session):
    """Self-protection covers lock-out only — editing one's own name is fine."""
    headers = await _admin(client, db_session)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()

    resp = await client.patch(
        f"/api/v1/users/{me['id']}", headers=headers, json={"full_name": "Chef"}
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Chef"


# --- Delete ----------------------------------------------------------------


async def test_delete_removes_the_account_and_its_reset_tokens(client, db_session):
    """A pending reset link must not outlive the account it belongs to."""
    from app.features.user import crud

    headers = await _admin(client, db_session)
    created = (
        await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": "gone@test.local", "password": STRONG},
        )
    ).json()

    user = await crud.get_by_email(db_session, "gone@test.local")
    assert user is not None
    await crud.create_reset_token(db_session, user)
    await db_session.commit()

    resp = await client.delete(f"/api/v1/users/{created['id']}", headers=headers)
    assert resp.status_code == 204, resp.text
    assert (await _login(client, "gone@test.local", STRONG)).status_code == 401

    # Asserted and not assumed: the token now goes with the account through the
    # foreign key's ON DELETE CASCADE, where it used to be deleted by hand
    # because the model did not declare the constraint the migration had. This
    # line is what proves the two schemas agree.
    from sqlmodel import select

    from app.features.user.models import PasswordResetToken

    assert (await db_session.exec(select(PasswordResetToken))).all() == []


# --- Admin-driven reset ----------------------------------------------------


async def test_reset_password_generates_a_usable_password(client, db_session):
    headers = await _admin(client, db_session)
    created = (
        await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": "reset@test.local", "password": STRONG},
        )
    ).json()

    resp = await client.post(
        f"/api/v1/users/{created['id']}/reset-password", headers=headers, json={}
    )
    assert resp.status_code == 200, resp.text
    generated = resp.json()["password"]
    assert generated and generated != STRONG

    assert (await _login(client, "reset@test.local", STRONG)).status_code == 401
    assert (await _login(client, "reset@test.local", generated)).status_code == 200


async def test_reset_password_accepts_an_explicit_password(client, db_session):
    headers = await _admin(client, db_session)
    created = (
        await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": "chosen@test.local", "password": STRONG},
        )
    ).json()

    chosen = "brand-new-passphrase"
    resp = await client.post(
        f"/api/v1/users/{created['id']}/reset-password",
        headers=headers,
        json={"password": chosen},
    )
    assert resp.status_code == 200
    assert resp.json()["password"] == chosen
    assert (await _login(client, "chosen@test.local", chosen)).status_code == 200


async def test_reset_password_ends_the_target_existing_sessions(client, db_session):
    """A reset is the answer to a compromised account: its live tokens must die."""
    from app.features.user.permissions import BuiltinGroup

    victim = await _headers(
        client, db_session, "victim@test.local", BuiltinGroup.READONLY
    )
    assert (await client.get("/api/v1/auth/me", headers=victim)).status_code == 200

    # No waiting for the clock to tick past the token's `iat`: the reset revokes
    # the victim's sessions, and the next request is refused on that alone.
    admin = await _admin(client, db_session)
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    target = next(u for u in users if u["email"] == "victim@test.local")
    await client.post(
        f"/api/v1/users/{target['id']}/reset-password", headers=admin, json={}
    )

    assert (await client.get("/api/v1/auth/me", headers=victim)).status_code == 401


# --- Self-service change ---------------------------------------------------


async def test_user_changes_own_password(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _headers(
        client, db_session, "self@test.local", BuiltinGroup.READONLY
    )
    new = "my-new-passphrase"

    resp = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": STRONG, "new_password": new},
    )
    assert resp.status_code == 204, resp.text
    assert (await _login(client, "self@test.local", STRONG)).status_code == 401
    assert (await _login(client, "self@test.local", new)).status_code == 200


async def test_password_change_requires_the_current_password(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _headers(
        client, db_session, "wrong@test.local", BuiltinGroup.READONLY
    )
    resp = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={
            "current_password": "not-my-password",
            "new_password": "another-one-here",
        },
    )
    assert resp.status_code == 400
    assert _code(resp) == "password.current.invalid"


async def test_password_change_rejects_a_short_new_password(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _headers(
        client, db_session, "shortnew@test.local", BuiltinGroup.READONLY
    )
    resp = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": STRONG, "new_password": "abc"},
    )
    assert resp.status_code == 422


# --- Forgot-password flow --------------------------------------------------


async def test_reset_request_is_204_for_an_unknown_address(client, db_session):
    """Anti-enumeration: the answer must not reveal whether the account exists."""
    known = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@test.local"}
    )
    assert known.status_code == 204


async def test_reset_request_issues_a_token_for_a_known_address(client, db_session):
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    await crud.create_user(db_session, email="forgot@test.local", password=STRONG)

    resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "forgot@test.local"}
    )
    assert resp.status_code == 204

    rows = (await db_session.exec(select(PasswordResetToken))).all()
    assert len(rows) == 1
    assert rows[0].used_at is None


async def test_a_second_reset_request_keeps_the_link_just_sent(client, db_session):
    """Audit S14: anyone may ask, but not void the link a user is opening,
    nor fill the inbox. The cooldown is the requesting address's (T34)."""
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    await crud.create_user(db_session, email="forgot@test.local", password=STRONG)
    hashes = []
    for _ in range(2):
        resp = await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "forgot@test.local"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert resp.status_code == 204
        db_session.expire_all()
        rows = (await db_session.exec(select(PasswordResetToken))).all()
        assert len(rows) == 1
        hashes.append(rows[0].token_hash)
    # The link mailed first is still the one that works.
    assert hashes[0] == hashes[1]


async def test_changing_the_email_voids_a_pending_reset_link(client, db_session):
    """Audit S15: a link mailed to the old address dies with it."""
    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="boss@test.local",
        password=STRONG,
        groups=[BuiltinGroup.ADMIN],
    )
    target = await crud.create_user(db_session, email="old@test.local", password=STRONG)
    target_id = str(target.id)
    login = await client.post(
        "/api/v1/auth/login", data={"username": "boss@test.local", "password": STRONG}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "old@test.local"}
    )
    assert len((await db_session.exec(select(PasswordResetToken))).all()) == 1
    resp = await client.patch(
        f"/api/v1/users/{target_id}", headers=headers, json={"email": "new@test.local"}
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert (await db_session.exec(select(PasswordResetToken))).all() == []


async def test_reset_confirm_sets_the_new_password_once(client, db_session):
    from app.features.user import crud

    user = await crud.create_user(
        db_session, email="confirm@test.local", password=STRONG
    )
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    new = "reset-passphrase-ok"
    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": new},
    )
    assert resp.status_code == 204, resp.text
    assert (await _login(client, "confirm@test.local", new)).status_code == 200

    # Single use: replaying the same link fails.
    replay = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "yet-another-pass"},
    )
    assert replay.status_code == 400
    assert _code(replay) == "password.reset_token.invalid"


async def test_reset_confirm_rejects_an_unknown_token(client, db_session):
    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "whatever-passphrase"},
    )
    assert resp.status_code == 400
    assert _code(resp) == "password.reset_token.invalid"


async def test_reset_confirm_rejects_an_expired_token(client, db_session):
    from app.features.base import utcnow
    from app.features.user import crud

    user = await crud.create_user(
        db_session, email="expired@test.local", password=STRONG
    )
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    from sqlmodel import select

    from app.features.user.models import PasswordResetToken

    row = (await db_session.exec(select(PasswordResetToken))).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    db_session.add(row)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "whatever-passphrase"},
    )
    assert resp.status_code == 400
    assert _code(resp) == "password.reset_token.invalid"


async def test_a_new_link_keeps_the_previous_one_until_one_is_redeemed(
    client, db_session
):
    """Audit S14 (T34): a request more than five minutes after the first
    issues a second link without voiding the first; redeeming either voids
    the other."""
    from datetime import timedelta

    from sqlalchemy import update
    from sqlmodel import select

    from app.features.base import utcnow
    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    user = await crud.create_user(db_session, email="twice@test.local", password=STRONG)
    first = await crud.create_reset_token(db_session, user)
    await db_session.commit()
    await db_session.exec(
        update(PasswordResetToken).values(created_at=utcnow() - timedelta(minutes=6))
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "twice@test.local"}
    )
    assert resp.status_code == 204
    db_session.expire_all()
    assert len((await db_session.exec(select(PasswordResetToken))).all()) == 2

    ok = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": first, "new_password": "whatever-passphrase"},
    )
    assert ok.status_code == 204, ok.text
    db_session.expire_all()
    rows = (await db_session.exec(select(PasswordResetToken))).all()
    # Only the redeemed one is left, spent.
    assert len(rows) == 1 and rows[0].used_at is not None


async def test_reset_links_alive_at_once_are_capped(client, db_session):
    """Audit S14 (T34): three links still valid, a fourth request sends
    nothing and voids nothing."""
    from datetime import timedelta

    from sqlalchemy import update
    from sqlmodel import select

    from app.core.config import settings
    from app.features.base import utcnow
    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    user = await crud.create_user(db_session, email="cap@test.local", password=STRONG)
    for _ in range(settings.PASSWORD_RESET_MAX_LIVE_LINKS):
        await db_session.refresh(user)
        # Asked from the test client's own address: the cap is per address.
        await crud.create_reset_token(db_session, user, "127.0.0.1")
        await db_session.commit()
    await db_session.exec(
        update(PasswordResetToken).values(created_at=utcnow() - timedelta(hours=1))
    )
    await db_session.commit()
    before = {r.token_hash for r in (await db_session.exec(select(PasswordResetToken)))}

    resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "cap@test.local"}
    )
    assert resp.status_code == 204
    db_session.expire_all()
    after = {r.token_hash for r in (await db_session.exec(select(PasswordResetToken)))}
    assert after == before


async def test_concurrent_reset_requests_issue_one_link(client, db_session):
    """Audit S14 (T34): four requests at the same instant from one address
    used to leave two links (and two mails): the account's row serialises
    them."""
    import asyncio

    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    await crud.create_user(db_session, email="race@test.local", password=STRONG)

    async def ask(i):
        return await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "race@test.local"},
            headers={"X-Forwarded-For": "10.0.1.7"},
        )

    answers = await asyncio.gather(*(ask(i) for i in range(4)))
    assert [r.status_code for r in answers] == [204] * 4
    db_session.expire_all()
    assert len((await db_session.exec(select(PasswordResetToken))).all()) == 1


async def _ask_reset(client, email: str, ip: str):
    return await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": email},
        headers={"X-Forwarded-For": ip},
    )


async def _age_reset_links(db_session, minutes: int) -> None:
    """Move every link's issue time back, past the cooldown."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.features.base import utcnow
    from app.features.user.models import PasswordResetToken

    await db_session.exec(
        update(PasswordResetToken).values(
            created_at=utcnow() - timedelta(minutes=minutes)
        )
    )
    await db_session.commit()


async def _live_links(db_session) -> list:
    from sqlmodel import select

    from app.features.user.models import PasswordResetToken

    db_session.expire_all()
    return list((await db_session.exec(select(PasswordResetToken))).all())


async def test_a_third_party_spends_its_own_reset_budget_not_the_owners(
    client, db_session
):
    """Audit T34 (accepted limit, fixed): three requests an hour from anybody
    used to spend the account's budget, and the owner's own request then
    sent nothing. The budget is the requesting address's."""
    from app.core.config import settings
    from app.features.user import crud

    await crud.create_user(db_session, email="target@test.local", password=STRONG)
    for _ in range(settings.PASSWORD_RESET_MAX_LIVE_LINKS):
        assert (
            await _ask_reset(client, "target@test.local", "10.6.6.6")
        ).status_code == 204
        await _age_reset_links(db_session, 10)
    links = await _live_links(db_session)
    assert len(links) == settings.PASSWORD_RESET_MAX_LIVE_LINKS
    assert {r.requested_ip for r in links} == {"10.6.6.6"}
    # The third party's budget is spent: one more request from it sends nothing.
    await _ask_reset(client, "target@test.local", "10.6.6.6")
    assert len(await _live_links(db_session)) == settings.PASSWORD_RESET_MAX_LIVE_LINKS

    # The owner, from their own poste: a link, mailed.
    assert (
        await _ask_reset(client, "target@test.local", "10.0.0.10")
    ).status_code == 204
    links = await _live_links(db_session)
    assert len(links) == settings.PASSWORD_RESET_MAX_LIVE_LINKS + 1
    assert sum(r.requested_ip == "10.0.0.10" for r in links) == 1


async def test_the_account_ceiling_bounds_links_from_many_addresses(
    client, db_session, monkeypatch
):
    """Per address alone, a botnet would fill the inbox: the links alive for
    one account are capped whatever the addresses — except for a request
    from one of the owner's usual postes."""
    from app.core.config import settings
    from app.features.base import utcnow
    from app.features.user import addresses, crud

    monkeypatch.setattr(settings, "PASSWORD_RESET_ACCOUNT_MAX_LIVE_LINKS", 4)
    user = await crud.create_user(db_session, email="flood@test.local", password=STRONG)
    await addresses.note_success(db_session, user.id, "10.0.0.10", utcnow())
    await db_session.commit()
    for i in range(6):
        await _ask_reset(client, "flood@test.local", f"10.7.{i}.1")
    assert len(await _live_links(db_session)) == 4

    # The owner's usual poste is not held to the account's ceiling.
    await _ask_reset(client, "flood@test.local", "10.0.0.10")
    links = await _live_links(db_session)
    assert len(links) == 5
    assert any(r.requested_ip == "10.0.0.10" for r in links)


async def test_a_reset_request_answers_in_the_same_time_whatever_the_account(
    client, db_session, monkeypatch
):
    """Audit T34 (accepted limit, fixed): issuing a link writes to the
    database where an unknown address only reads, and the answer's delay told
    which addresses have an account. Every outcome now answers after the same
    floor. The writes are slowed down here (as on a loaded server) so that
    the gap is plain without the floor."""
    import statistics
    import time

    from app.api.routes import auth
    from app.features.user import crud

    floor = 0.25
    monkeypatch.setattr(auth, "PASSWORD_RESET_REQUEST_SECONDS", floor)
    issue = crud.create_reset_token

    async def slow_issue(*args, **kwargs):
        await asyncio.sleep(0.12)
        return await issue(*args, **kwargs)

    monkeypatch.setattr(crud, "create_reset_token", slow_issue)
    await crud.create_user(db_session, email="known@test.local", password=STRONG)

    async def timed(email: str, ip: str) -> float:
        started = time.monotonic()
        resp = await _ask_reset(client, email, ip)
        assert resp.status_code == 204
        return time.monotonic() - started

    unknown, issued, refused = [], [], []
    for i in range(3):
        unknown.append(await timed("nobody@test.local", f"10.8.{i}.1"))
        # A fresh address each time: a link is issued (and mailed).
        issued.append(await timed("known@test.local", f"10.8.{i}.2"))
        # Same address again within the cooldown: nothing issued.
        refused.append(await timed("known@test.local", f"10.8.{i}.2"))
    assert len(await _live_links(db_session)) == 3

    medians = [statistics.median(t) for t in (unknown, issued, refused)]
    for t in unknown + issued + refused:
        assert floor - 0.01 <= t < floor + 0.1, (unknown, issued, refused)
    assert max(medians) - min(medians) < 0.04, medians


async def test_redeeming_a_link_takes_the_account_lock_first(engine, db_session):
    """Audit S14 (T34), third pass: a reset request locks the account's row,
    then touches its tokens; a redemption did it the other way round, and the
    two could deadlock — one of them answered a 500. Both now lock the
    account first."""
    import pytest
    from sqlalchemy.exc import OperationalError
    from sqlmodel import col, select
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.user import crud
    from app.features.user.models import User

    user = await crud.create_user(db_session, email="order@test.local", password=STRONG)
    user_id = user.id
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    async with AsyncSession(engine) as redeeming, AsyncSession(engine) as asking:
        assert await crud.consume_reset_token(redeeming, token) is not None
        # The redemption has not committed: the account is its own.
        with pytest.raises(OperationalError):
            await asking.exec(
                select(User.id)
                .where(col(User.id) == user_id)
                .with_for_update(nowait=True)
            )
        await asking.rollback()
        await redeeming.rollback()


async def test_a_link_redeemed_while_another_is_requested(client, db_session):
    """The two at the same instant, with a spent link lying around (what made
    them wait on each other): both are answered, nothing but the new
    password's own state is left."""
    import asyncio
    from datetime import timedelta

    from sqlmodel import select

    from app.features.base import utcnow
    from app.features.user import crud
    from app.features.user.models import PasswordResetToken

    for i in range(6):
        email = f"both{i}@test.local"
        user = await crud.create_user(db_session, email=email, password=STRONG)
        spent = await crud.create_reset_token(db_session, user)
        live = await crud.create_reset_token(db_session, user)
        await db_session.commit()
        rows = (await db_session.exec(select(PasswordResetToken))).all()
        for row in rows:
            row.created_at = utcnow() - timedelta(minutes=30)
            if row.token_hash == crud.security.hash_token(spent):
                row.used_at = utcnow() - timedelta(minutes=20)
            db_session.add(row)
        await db_session.commit()

        redeemed, asked = await asyncio.gather(
            client.post(
                "/api/v1/auth/password-reset/confirm",
                json={"token": live, "new_password": "a-brand-new-password-1"},
            ),
            client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": email},
                headers={"X-Forwarded-For": f"10.0.2.{i}"},
            ),
        )
        assert redeemed.status_code == 204, redeemed.text
        assert asked.status_code == 204, asked.text


# --- Unit tests (no database) ----------------------------------------------


def test_reset_link_is_none_without_a_console_url(monkeypatch):
    from app.core.config import settings
    from app.features.user import emails

    monkeypatch.setattr(settings, "CONSOLE_BASE_URL", None)
    assert emails.reset_link("tok") is None


def test_reset_link_uses_the_console_url(monkeypatch):
    from app.core.config import settings
    from app.features.user import emails

    monkeypatch.setattr(settings, "CONSOLE_BASE_URL", "https://tiai.local/")
    assert emails.reset_link("tok") == "https://tiai.local/reset-password?token=tok"


def test_email_field_accepts_special_use_domains():
    """The console must accept on-prem AD addresses (user@natimai.local) that
    RFC validators reject as special-use — and the test park itself runs on
    ``.local`` addresses, so this is also what keeps the API tests honest.
    """
    from pydantic import TypeAdapter

    from app.api.fields import Email

    adapter = TypeAdapter(Email)
    for ok in ("admin@natimai.local", "a@test.local", "user@natimai.solutions"):
        assert adapter.validate_python(ok) == ok
    for bad in ("not-an-email", "user@nodot", "two words@x.y", "@x.y", "a@"):
        try:
            adapter.validate_python(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")


def test_generated_password_is_long_enough():
    from app.core.config import settings
    from app.core.security import generate_password

    password = generate_password()
    assert len(password) >= settings.PASSWORD_MIN_LENGTH
    assert password != generate_password()


def test_model_datetime_columns_are_timezone_aware():
    """Every datetime column must be TIMESTAMPTZ, matching the migrations.

    A bare ``datetime`` annotation would map to a naive TIMESTAMP in the schema
    ``create_all`` builds for the tests, making values read back naive here but
    aware in production — the same comparison then behaves differently in each.
    """
    from sqlmodel import SQLModel

    import app.features.models  # noqa: F401  (populate SQLModel.metadata)

    naive = [
        f"{table.name}.{column.name}"
        for table in SQLModel.metadata.tables.values()
        for column in table.columns
        if column.type.__class__.__name__ in ("DateTime", "TIMESTAMP")
        and not getattr(column.type, "timezone", False)
    ]
    assert naive == [], f"naive datetime columns: {naive}"


# --- E-mail cadence --------------------------------------------------------


async def test_new_account_defaults_to_the_daily_digest(client, db_session):
    """The default matters: a fleet whose operators never opted in is watched."""
    headers = await _admin(client, db_session)

    resp = await client.get("/api/v1/auth/me", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["email_preference"] == "digest_daily"


async def test_a_user_sets_their_own_cadence(client, db_session):
    headers = await _readonly(client, db_session)

    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"email_preference": "immediate"}
    )

    assert resp.status_code == 200
    assert resp.json()["email_preference"] == "immediate"
    assert (await client.get("/api/v1/auth/me", headers=headers)).json()[
        "email_preference"
    ] == "immediate"


async def test_an_unknown_cadence_is_refused(client, db_session):
    headers = await _readonly(client, db_session)

    resp = await client.patch(
        "/api/v1/auth/me", headers=headers, json={"email_preference": "hourly"}
    )

    assert resp.status_code == 422


async def test_self_service_cannot_reach_beyond_the_cadence(client, db_session):
    """A read-only operator editing their own row must not gain a group.

    Extra fields are ignored rather than applied: ``ProfileUpdate`` declares one
    field, so ``group_ids`` never reaches the model.
    """
    headers = await _readonly(client, db_session)
    admin_group = "00000000-0000-0000-0000-000000000000"

    resp = await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={
            "email_preference": "none",
            "group_ids": [admin_group],
            "is_active": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["email_preference"] == "none"
    assert [g["name"] for g in body["groups"]] == ["Lecture seule"]
    assert "user:write" not in body["permissions"]


async def test_an_admin_sees_and_sets_another_account_cadence(client, db_session):
    headers = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "ops@test.local", "password": STRONG},
    )
    user_id = created.json()["id"]
    assert created.json()["email_preference"] == "digest_daily"

    resp = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=headers,
        json={"email_preference": "none"},
    )

    assert resp.status_code == 200
    assert resp.json()["email_preference"] == "none"


async def test_cadence_is_stored_as_its_value_not_the_enum_repr(client, db_session):
    """The column is a plain string; a stored "EmailPreference.NONE" would make
    every recipient query miss."""
    from sqlmodel import select

    from app.features.user.models import User

    headers = await _readonly(client, db_session, "stored@test.local")
    await client.patch(
        "/api/v1/auth/me", headers=headers, json={"email_preference": "digest_events"}
    )

    stored = (
        await db_session.exec(
            select(User.email_preference).where(User.email == "stored@test.local")
        )
    ).one()
    assert stored == "digest_events"


async def test_the_password_policy_is_public(client):
    """Audit B24: the console reads the configured rules."""
    from app.core.config import settings

    resp = await client.get("/api/v1/auth/password-policy")
    assert resp.status_code == 200
    assert resp.json() == {
        "min_length": settings.PASSWORD_MIN_LENGTH,
        "max_bytes": 72,
        "reset_expire_minutes": settings.PASSWORD_RESET_EXPIRE_MINUTES,
    }


async def test_a_required_field_sent_as_null_is_a_422(client, db_session):
    """Audit B27: not a 500."""
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="boss@test.local",
        password=STRONG,
        groups=[BuiltinGroup.ADMIN],
    )
    target = await crud.create_user(db_session, email="t@test.local", password=STRONG)
    target_id = str(target.id)
    login = await client.post(
        "/api/v1/auth/login", data={"username": "boss@test.local", "password": STRONG}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    for body in (
        {"email": None},
        {"is_active": None},
        {"email_preference": None},
        # Used to reach the groups check as None: a TypeError, a 500 (T41).
        {"group_ids": None},
    ):
        resp = await client.patch(
            f"/api/v1/users/{target_id}", headers=headers, json=body
        )
        assert resp.status_code == 422, (body, resp.text)
    groups = (await client.get("/api/v1/groups", headers=headers)).json()
    for body in ({"name": None}, {"permissions": None}):
        resp = await client.patch(
            f"/api/v1/groups/{groups[0]['id']}", headers=headers, json=body
        )
        assert resp.status_code == 422, (body, resp.text)
    building = await client.post(
        "/api/v1/buildings", headers=headers, json={"name": "Bât. A"}
    )
    assert building.status_code == 201, building.text
    resp = await client.patch(
        f"/api/v1/buildings/{building.json()['id']}",
        headers=headers,
        json={"name": None},
    )
    assert resp.status_code == 422, resp.text
    room = await client.post("/api/v1/rooms", headers=headers, json={"name": "B12"})
    assert room.status_code == 201, room.text
    resp = await client.patch(
        f"/api/v1/rooms/{room.json()['id']}", headers=headers, json={"name": None}
    )
    assert resp.status_code == 422, resp.text
    # Where null means something, it is still accepted: out of its building.
    resp = await client.patch(
        f"/api/v1/rooms/{room.json()['id']}",
        headers=headers,
        json={"building_id": None},
    )
    assert resp.status_code == 200, resp.text


# --- Concurrency and bounds (acceptance, 2026-11) -----------------------------


async def test_two_last_admins_deactivating_each_other_leave_one(
    client, db_session, monkeypatch
):
    """Two administrators, the last two, deactivate each other at the same
    instant: one change goes through, the other is refused — never zero
    administrators. The commit is held back so that both changes are counted
    before either commits, the window the guard used to leave open."""
    import asyncio

    from sqlmodel import select

    from app.features.user import crud
    from app.features.user.models import User

    first = await _admin(client, db_session, "a1@test.local")
    second = await _admin(client, db_session, "a2@test.local")
    ids = {
        u["email"]: u["id"]
        for u in (await client.get("/api/v1/users", headers=first)).json()["items"]
    }
    counted = crud.users_holding

    async def slow_count(session, permission):
        # Counted, then a pause before the commit: without the lock, the
        # other change counts during it, sees this one's target still active,
        # and both commit.
        held = await counted(session, permission)
        await asyncio.sleep(0.3)
        return held

    monkeypatch.setattr(crud, "users_holding", slow_count)
    results = await asyncio.gather(
        client.patch(
            f"/api/v1/users/{ids['a2@test.local']}",
            headers=first,
            json={"is_active": False},
        ),
        client.patch(
            f"/api/v1/users/{ids['a1@test.local']}",
            headers=second,
            json={"is_active": False},
        ),
    )
    assert sorted(r.status_code for r in results) == [200, 409], [
        r.text for r in results
    ]
    db_session.expire_all()
    active = (
        await db_session.exec(select(User).where(User.is_active.is_(True)))  # type: ignore[attr-defined]
    ).all()
    assert len(active) == 1


async def test_concurrent_creations_of_one_address_answer_409(client, db_session):
    """Eight requests creating the same address at once: one account, and
    seven « déjà utilisée » — never a 500."""
    import asyncio

    headers = await _admin(client, db_session)
    results = await asyncio.gather(
        *(
            client.post(
                "/api/v1/users",
                headers=headers,
                json={"email": "twin@test.local", "password": STRONG},
            )
            for _ in range(8)
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 7, [r.text for r in results]
    assert all(_code(r) == "user.email.taken" for r in results if r.status_code == 409)


async def test_concurrent_renames_to_one_address_answer_409(client, db_session):
    import asyncio

    headers = await _admin(client, db_session)
    ids = []
    for i in range(4):
        resp = await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": f"u{i}@test.local", "password": STRONG},
        )
        ids.append(resp.json()["id"])
    results = await asyncio.gather(
        *(
            client.patch(
                f"/api/v1/users/{uid}",
                headers=headers,
                json={"email": "same@test.local"},
            )
            for uid in ids
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200] + [409] * 3, [r.text for r in results]


async def test_a_full_name_is_trimmed_and_bounded(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "long@test.local", "password": STRONG, "full_name": "x" * 256},
    )
    assert resp.status_code == 422, resp.text
    assert "255" in resp.json()["error"]["details"]["errors"][0]["msg"]
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "blank@test.local", "password": STRONG, "full_name": "   "},
    )
    assert resp.status_code == 422
    assert "vide" in resp.json()["error"]["details"]["errors"][0]["msg"]
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "trim@test.local", "password": STRONG, "full_name": "  Marie  "},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["full_name"] == "Marie"
    uid = resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/users/{uid}", headers=headers, json={"full_name": "é" * 300}
    )
    assert resp.status_code == 422
    # Clearing the name is still a null, not a blank.
    resp = await client.patch(
        f"/api/v1/users/{uid}", headers=headers, json={"full_name": None}
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] is None


async def test_the_search_term_is_trimmed(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.get(
        "/api/v1/users", headers=headers, params={"search": "  admin@test.local "}
    )
    assert resp.json()["total"] == 1


async def test_a_password_bcrypt_would_cut_is_refused(client, db_session):
    """bcrypt reads 72 bytes: a longer password would have its end ignored.
    Counted in bytes — « é » weighs two."""
    from app.core.security import PASSWORD_MAX_BYTES

    headers = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "bytes@test.local", "password": "a" * PASSWORD_MAX_BYTES},
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "accents@test.local", "password": "é" * 37},
    )
    assert resp.status_code == 422
    assert "72 octets" in resp.json()["error"]["details"]["errors"][0]["msg"]
    resp = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": STRONG, "new_password": "b" * 73},
    )
    assert resp.status_code == 422
    policy = (await client.get("/api/v1/auth/password-policy")).json()
    assert policy["max_bytes"] == PASSWORD_MAX_BYTES


async def test_the_new_password_must_differ_from_the_current_one(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _headers(
        client, db_session, "same@test.local", BuiltinGroup.READONLY
    )
    resp = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": STRONG, "new_password": STRONG},
    )
    assert resp.status_code == 400
    assert _code(resp) == "password.unchanged"
    # Nothing ended: the session still works.
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200


async def _check_link(client, token: str):
    return await client.post("/api/v1/auth/password-reset/check", json={"token": token})


async def test_a_reset_link_can_be_checked_without_being_spent(
    client, db_session, monkeypatch
):
    """POST /auth/password-reset/check: 204 while the link is usable, the
    confirm route's 400 otherwise, and checking never consumes it."""
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    user = await crud.create_user(
        db_session,
        email="forgot@test.local",
        password=STRONG,
        groups=[BuiltinGroup.READONLY],
    )
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    for _ in range(2):
        resp = await _check_link(client, token)
        assert resp.status_code == 204, resp.text
    resp = await _check_link(client, "nope")
    assert resp.status_code == 400
    assert _code(resp) == "password.reset_token.invalid"

    # Still redeemable after being checked; dead once redeemed.
    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "a-brand-new-passphrase"},
    )
    assert resp.status_code == 204, resp.text
    resp = await _check_link(client, token)
    assert resp.status_code == 400


async def test_a_reset_link_is_never_checked_through_a_url(client, db_session):
    """Verification of v1.2.1, F8: the check took the token in the query
    string, and the access log wrote it down — a link still good for an
    hour, in a file its owner never sees. It travels in a body, like the
    confirmation; the GET is gone, not kept beside it."""
    from app.features.user import crud

    user = await crud.create_user(db_session, email="url@test.local", password=STRONG)
    token = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/auth/password-reset/check", params={"token": token}
    )
    assert resp.status_code == 405
    # Nor from the query string of a POST: only the body is read.
    resp = await client.post(
        "/api/v1/auth/password-reset/check", params={"token": token}
    )
    assert resp.status_code == 422
    assert (await _check_link(client, token)).status_code == 204
    # An empty or oversized token is a dead link like any other.
    assert (await _check_link(client, "")).status_code == 400
    assert (await _check_link(client, "a" * 6000)).status_code == 400


async def test_checking_reset_links_is_rate_limited(client, db_session):
    statuses = [(await _check_link(client, f"t{i}")).status_code for i in range(21)]
    assert statuses[:20] == [400] * 20
    assert statuses[20] == 429


@pytest.mark.parametrize("write", ["patch", "reset_password"])
async def test_an_edit_racing_a_deletion_does_not_fail(
    client, db_session, monkeypatch, write
):
    """An account edited (or its password reset) while another administrator
    deletes it: the edit had read the row, the deletion committed, and the
    edit's write then matched nothing — a 500. The row is locked as it is
    read: the two are answered one after the other, each in full."""
    from app.features.user import crud

    admin = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/users",
        headers=admin,
        json={"email": "going@test.local", "password": STRONG},
    )
    user_id = created.json()["id"]

    deleted = asyncio.Event()
    authority = crud.user_authority
    calls = 0

    async def authority_then_wait(*args, **kwargs):
        # Called by each route right after it has read the account. The
        # first caller is the edit: it gives the deletion half a second to
        # go through — which it does when nothing holds the row.
        nonlocal calls
        calls += 1
        first = calls == 1
        found = await authority(*args, **kwargs)
        if first:
            try:
                await asyncio.wait_for(deleted.wait(), 0.5)
            except TimeoutError:
                pass
        return found

    monkeypatch.setattr(crud, "user_authority", authority_then_wait)

    async def edit():
        if write == "patch":
            return await client.patch(
                f"/api/v1/users/{user_id}", headers=admin, json={"full_name": "Parti"}
            )
        return await client.post(
            f"/api/v1/users/{user_id}/reset-password", headers=admin, json={}
        )

    async def delete():
        while calls == 0:
            await asyncio.sleep(0.01)
        resp = await client.delete(f"/api/v1/users/{user_id}", headers=admin)
        deleted.set()
        return resp

    edited, gone = await asyncio.gather(edit(), delete())
    assert (edited.status_code, gone.status_code) == (200, 204)
    assert (
        await client.get(f"/api/v1/users/{user_id}", headers=admin)
    ).status_code == 404

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


async def _headers(client, db_session, email: str, role, password: str = STRONG):
    from app.features.user import crud

    await crud.create_user(db_session, email=email, password=password, role=role)
    resp = await _login(client, email, password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client, db_session, email: str = "admin@test.local"):
    from app.features.user.models import Role

    return await _headers(client, db_session, email, Role.ADMIN)


async def _readonly(client, db_session, email: str = "ro@test.local"):
    from app.features.user.models import Role

    return await _headers(client, db_session, email, Role.READONLY)


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
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "marie@test.local",
            "password": STRONG,
            "full_name": "Marie Dupont",
            "role": "readonly",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "marie@test.local"
    assert body["role"] == "readonly"
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


async def test_admin_updates_name_role_and_activation(client, db_session):
    headers = await _admin(client, db_session)
    created = (
        await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": "bob@test.local", "password": STRONG},
        )
    ).json()

    resp = await client.patch(
        f"/api/v1/users/{created['id']}",
        headers=headers,
        json={"full_name": "Bob", "role": "admin", "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Bob"
    assert body["role"] == "admin"
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
    [{"is_active": False}, {"role": "readonly"}],
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
    from app.features.user.models import Role

    victim = await _headers(client, db_session, "victim@test.local", Role.READONLY)
    assert (await client.get("/api/v1/auth/me", headers=victim)).status_code == 200

    # `iat` has one-second granularity, so let the clock tick past the second
    # the token was minted in before invalidating it.
    await asyncio.sleep(1.1)

    admin = await _admin(client, db_session)
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    target = next(u for u in users if u["email"] == "victim@test.local")
    await client.post(
        f"/api/v1/users/{target['id']}/reset-password", headers=admin, json={}
    )

    assert (await client.get("/api/v1/auth/me", headers=victim)).status_code == 401


# --- Self-service change ---------------------------------------------------


async def test_user_changes_own_password(client, db_session):
    from app.features.user.models import Role

    headers = await _headers(client, db_session, "self@test.local", Role.READONLY)
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
    from app.features.user.models import Role

    headers = await _headers(client, db_session, "wrong@test.local", Role.READONLY)
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
    from app.features.user.models import Role

    headers = await _headers(client, db_session, "shortnew@test.local", Role.READONLY)
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


async def test_issuing_a_new_reset_token_drops_the_previous_one(client, db_session):
    from app.features.user import crud

    user = await crud.create_user(db_session, email="twice@test.local", password=STRONG)
    first = await crud.create_reset_token(db_session, user)
    await db_session.commit()
    # The commit expired the instance; reload it before handing it back to the
    # crud layer, whose attribute access would otherwise lazy-load in async.
    await db_session.refresh(user)
    second = await crud.create_reset_token(db_session, user)
    await db_session.commit()

    stale = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": first, "new_password": "whatever-passphrase"},
    )
    assert stale.status_code == 400

    ok = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": second, "new_password": "whatever-passphrase"},
    )
    assert ok.status_code == 204


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

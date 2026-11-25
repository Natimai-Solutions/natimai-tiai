"""The second factor (C7): enrolment, the login challenge, the lock, the
obligation by group, the enrolment-only session, backup codes, reset."""

import uuid

import pytest
from sqlmodel import select

from app.core import totp
from tests.scope_helpers import STRONG, account, group

LOGIN = "/api/v1/auth/login"
STEP2 = "/api/v1/auth/login/second-factor"


class Clock:
    """The TOTP step, set by the test: codes of one step are good once."""

    def __init__(self) -> None:
        self.step = 60_000_000

    def tick(self) -> int:
        self.step += 1
        return self.step


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(totp, "current_step", lambda now=None: c.step)
    return c


async def _password(client, email, password=STRONG):
    return await client.post(LOGIN, data={"username": email, "password": password})


async def _enrol(client, headers, clock) -> tuple[str, list[str]]:
    resp = await client.post(
        "/api/v1/auth/totp/setup", headers=headers, json={"current_password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    secret = resp.json()["secret"]
    assert resp.json()["otpauth_uri"].startswith("otpauth://totp/")
    code = totp.code_at(secret, clock.step)
    resp = await client.post(
        "/api/v1/auth/totp/confirm", headers=headers, json={"code": code}
    )
    assert resp.status_code == 200, resp.text
    return secret, resp.json()["backup_codes"]


async def _user(db_session, email):
    from app.features.user.models import User

    return (await db_session.exec(select(User).where(User.email == email))).one()


async def _second_step(client, challenge, code):
    return await client.post(STEP2, json={"challenge": challenge, "code": code})


async def test_login_without_second_factor_is_unchanged(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    await account(client, db_session, "plain@test.local", [BuiltinGroup.READONLY])
    resp = await _password(client, "plain@test.local")
    assert set(resp.json()) == {"access_token", "token_type"}
    assert "tiai_refresh" in resp.headers.get("set-cookie", "")


async def test_enrol_then_log_in_with_a_code(client, db_session, clock):
    from app.features.auth_session.models import AuthSession
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ana@test.local", [BuiltinGroup.ADMIN])
    secret, codes = await _enrol(client, headers, clock)
    assert len(codes) == 10
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert (me["second_factor_enabled"], me["backup_codes_left"]) == (True, 10)

    sessions_before = len((await db_session.exec(select(AuthSession))).all())
    resp = await _password(client, "ana@test.local")
    body = resp.json()
    assert body["second_factor_required"] is True and "access_token" not in body
    assert "set-cookie" not in resp.headers
    assert len((await db_session.exec(select(AuthSession))).all()) == sessions_before

    # The code of the step the enrolment used is spent: replay refused.
    resp = await _second_step(
        client, body["challenge"], totp.code_at(secret, clock.step)
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth.second_factor.invalid"

    clock.tick()
    resp = await _second_step(
        client, body["challenge"], totp.code_at(secret, clock.step)
    )
    assert resp.status_code == 200, resp.text
    assert "tiai_refresh" in resp.headers.get("set-cookie", "")
    token = resp.json()["access_token"]
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    row = (
        await db_session.exec(
            select(AuthSession).order_by(AuthSession.created_at.desc())  # type: ignore[attr-defined]
        )
    ).first()
    assert row.auth_method == "password+totp"

    # A challenge opens one session at most.
    clock.tick()
    resp = await _second_step(
        client, body["challenge"], totp.code_at(secret, clock.step)
    )
    assert resp.status_code == 401


async def test_wrong_password_answers_as_before(client, db_session, clock):
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "bo@test.local", [BuiltinGroup.ADMIN])
    await _enrol(client, headers, clock)
    for email in ("bo@test.local", "nobody@test.local"):
        resp = await _password(client, email, "wrong-password-123")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "auth.credentials.invalid"


async def test_password_alone_neither_resets_the_lock_nor_knows_the_address(
    client, db_session, clock
):
    from app.features.user.models import LoginAddress
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "cy@test.local", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    user = await _user(db_session, "cy@test.local")
    await db_session.exec(
        LoginAddress.__table__.delete().where(LoginAddress.user_id == user.id)  # type: ignore[attr-defined]
    )
    await db_session.commit()
    await _password(client, "cy@test.local", "wrong-password-123")
    resp = await _password(client, "cy@test.local")
    challenge = resp.json()["challenge"]

    await db_session.refresh(user)
    assert user.failed_login_attempts == 1
    known = (
        await db_session.exec(
            select(LoginAddress).where(
                LoginAddress.user_id == user.id,
                LoginAddress.last_success_at.is_not(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    assert known == []

    clock.tick()
    resp = await _second_step(client, challenge, totp.code_at(secret, clock.step))
    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0


async def test_wrong_codes_lock_the_second_factor(client, db_session, clock):
    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "di@test.local", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    # Five wrong codes over two challenges: the count is the account's.
    for attempts in (3, 2):
        challenge = (await _password(client, "di@test.local")).json()["challenge"]
        for _ in range(attempts):
            resp = await _second_step(client, challenge, "000000")
            assert resp.status_code == 401
    entries = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "user.second_factor_locked")
        )
    ).all()
    assert len(entries) == 1
    clock.tick()
    challenge = (await _password(client, "di@test.local")).json()["challenge"]
    resp = await _second_step(client, challenge, totp.code_at(secret, clock.step))
    assert resp.status_code == 401


async def test_challenge_is_bounded(client, db_session, clock):
    from app.features.auth_session.models import LoginChallenge
    from app.features.base import utcnow
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ed@test.local", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    challenge = (await _password(client, "ed@test.local")).json()["challenge"]
    row = (await db_session.exec(select(LoginChallenge))).one()
    row.expires_at = utcnow()
    db_session.add(row)
    await db_session.commit()
    clock.tick()
    resp = await _second_step(client, challenge, totp.code_at(secret, clock.step))
    assert resp.status_code == 401
    resp = await _second_step(client, "not-a-challenge", "123456")
    assert resp.status_code == 401


async def test_backup_code_is_good_once(client, db_session, clock):
    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "fa@test.local", [BuiltinGroup.ADMIN])
    _, codes = await _enrol(client, headers, clock)
    challenge = (await _password(client, "fa@test.local")).json()["challenge"]
    resp = await _second_step(client, challenge, codes[0].lower().replace("-", " "))
    assert resp.status_code == 200
    challenge = (await _password(client, "fa@test.local")).json()["challenge"]
    resp = await _second_step(client, challenge, codes[0])
    assert resp.status_code == 401
    entry = (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "auth.backup_code_used")
        )
    ).one()
    assert entry.details["remaining"] == 9


async def test_dedicated_key_set_later_keeps_second_factors(
    client, db_session, clock, monkeypatch
):
    from app.core import secretbox
    from app.core.config import settings
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "ge@test.local", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    monkeypatch.setattr(
        settings, "TOTP_ENCRYPTION_KEY", "a-dedicated-key-0123456789-abcdefgh"
    )
    user = await _user(db_session, "ge@test.local")
    assert secretbox.totp_needs_resealing(user.totp_secret)
    clock.tick()
    challenge = (await _password(client, "ge@test.local")).json()["challenge"]
    resp = await _second_step(client, challenge, totp.code_at(secret, clock.step))
    assert resp.status_code == 200
    await db_session.refresh(user)
    assert not secretbox.totp_needs_resealing(user.totp_secret)


async def test_unreadable_secret_leaves_the_backup_codes(
    client, db_session, clock, monkeypatch
):
    from app.core.config import settings
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "gu@test.local", [BuiltinGroup.ADMIN])
    secret, codes = await _enrol(client, headers, clock)
    # SECRET_KEY changed without a dedicated key: the secret is unreadable.
    monkeypatch.setattr(
        settings, "SECRET_KEY", "another-key-entirely-0123456789-abcdefgh"
    )
    clock.tick()
    # The app's codes cannot match, and are not counted: six of them leave
    # the backup codes usable.
    for _ in range(3):
        challenge = (await _password(client, "gu@test.local")).json()["challenge"]
        for _ in range(2):
            resp = await _second_step(
                client, challenge, totp.code_at(secret, clock.step)
            )
            assert resp.status_code == 401
    challenge = (await _password(client, "gu@test.local")).json()["challenge"]
    resp = await _second_step(client, challenge, codes[1])
    assert resp.status_code == 200


async def test_group_requires_it_enrolment_only_session(client, db_session, clock):
    from app.features.user.permissions import ALL_PERMISSIONS

    g = await group(db_session, "Admins MFA", ALL_PERMISSIONS, None)
    from app.features.user.models import Group

    row = await db_session.get(Group, g.id)
    row.mfa_required = True
    db_session.add(row)
    await db_session.commit()
    headers = await account(client, db_session, "hu@test.local", [g.id])

    resp = await client.get("/api/v1/machines", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "auth.second_factor.not_enrolled"
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["enrolment_only"] is True and me["second_factor_required"] is True

    await _enrol(client, headers, clock)
    assert (await client.get("/api/v1/machines", headers=headers)).status_code == 200

    # Required: it cannot be turned off.
    clock.tick()
    resp = await client.post(
        "/api/v1/auth/totp/disable",
        headers=headers,
        json={"current_password": STRONG, "code": "000000"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "auth.second_factor.required_by_group"


async def test_disable_needs_password_and_code(client, db_session, clock):
    from app.features.user.models import UserBackupCode
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "io@test.local", [BuiltinGroup.ADMIN])
    secret, _ = await _enrol(client, headers, clock)
    clock.tick()
    code = totp.code_at(secret, clock.step)
    resp = await client.post(
        "/api/v1/auth/totp/disable",
        headers=headers,
        json={"current_password": "wrong-password-123", "code": code},
    )
    assert resp.status_code == 400
    resp = await client.post(
        "/api/v1/auth/totp/disable",
        headers=headers,
        json={"current_password": STRONG, "code": "000000"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "auth.second_factor.code_invalid"
    resp = await client.post(
        "/api/v1/auth/totp/disable",
        headers=headers,
        json={"current_password": STRONG, "code": code},
    )
    assert resp.status_code == 204
    user = await _user(db_session, "io@test.local")
    assert user.totp_secret is None
    assert (
        await db_session.exec(
            select(UserBackupCode).where(UserBackupCode.user_id == user.id)
        )
    ).all() == []
    assert set((await _password(client, "io@test.local")).json()) == {
        "access_token",
        "token_type",
    }


async def test_regenerate_codes_and_setup_refused_while_on(client, db_session, clock):
    from app.features.user.permissions import BuiltinGroup

    headers = await account(client, db_session, "jo@test.local", [BuiltinGroup.ADMIN])
    secret, old = await _enrol(client, headers, clock)
    resp = await client.post(
        "/api/v1/auth/totp/setup", headers=headers, json={"current_password": STRONG}
    )
    assert resp.status_code == 409
    clock.tick()
    resp = await client.post(
        "/api/v1/auth/totp/backup-codes",
        headers=headers,
        json={"code": totp.code_at(secret, clock.step)},
    )
    new = resp.json()["backup_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    challenge = (await _password(client, "jo@test.local")).json()["challenge"]
    assert (await _second_step(client, challenge, old[0])).status_code == 401
    assert (await _second_step(client, challenge, new[0])).status_code == 200


async def test_admin_resets_a_second_factor(client, db_session, clock):
    from app.features.audit.models import AuditEntry
    from app.features.auth_session.models import AuthSession
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ka@test.local", [BuiltinGroup.ADMIN])
    member = await account(client, db_session, "lu@test.local", [BuiltinGroup.READONLY])
    await _enrol(client, member, clock)
    target = await _user(db_session, "lu@test.local")
    me_id = (await client.get("/api/v1/auth/me", headers=admin)).json()["id"]

    resp = await client.post(
        f"/api/v1/users/{me_id}/reset-second-factor", headers=admin
    )
    assert resp.status_code == 400
    resp = await client.post(
        f"/api/v1/users/{target.id}/reset-second-factor", headers=admin
    )
    assert resp.status_code == 204
    await db_session.refresh(target)
    assert target.totp_secret is None
    live = (
        await db_session.exec(
            select(AuthSession).where(
                AuthSession.user_id == target.id,
                AuthSession.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    assert live == []
    assert (
        await db_session.exec(
            select(AuditEntry).where(AuditEntry.action == "user.second_factor_reset")
        )
    ).one().resource_id == str(target.id)
    users = (await client.get("/api/v1/users", headers=admin)).json()["items"]
    assert {u["email"]: u["second_factor_enabled"] for u in users}[
        "lu@test.local"
    ] is False
    assert (
        await client.post(
            f"/api/v1/users/{uuid.uuid4()}/reset-second-factor", headers=admin
        )
    ).status_code == 404


async def test_group_flag_through_the_api(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ma@test.local", [BuiltinGroup.ADMIN])
    resp = await client.post(
        "/api/v1/groups",
        headers=admin,
        json={
            "name": "Techs MFA",
            "permissions": ["machine:read"],
            "mfa_required": True,
        },
    )
    assert resp.status_code == 201 and resp.json()["mfa_required"] is True
    gid = resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/groups/{gid}", headers=admin, json={"mfa_required": False}
    )
    assert resp.json()["mfa_required"] is False
    resp = await client.patch(
        f"/api/v1/groups/{gid}", headers=admin, json={"mfa_required": None}
    )
    assert resp.status_code == 422

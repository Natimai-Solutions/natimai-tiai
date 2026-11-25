"""Personal API tokens (C8): made once, read-only by default, within the
account's rights and scope, never on the account itself, revoked."""

from datetime import timedelta

from sqlmodel import select

from tests.scope_helpers import STRONG, account, group, two_sites

API = "/api/v1/auth/api-tokens"


async def _token(client, headers, **fields):
    body = {"name": "Script", "current_password": STRONG, **fields}
    resp = await client.post(API, headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body, {"Authorization": f"Bearer {body['token']}"}


async def test_made_once_and_listed_without_the_value(client, db_session):
    from app.features.audit.models import AuditEntry
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "aa@lycee.test", [BuiltinGroup.ADMIN])
    body, _ = await _token(client, admin, days=30)
    assert body["token"].startswith("tiai_pat_") and body["can_write"] is False
    assert body["prefix"] == body["token"][:13]
    listed = (await client.get(API, headers=admin)).json()
    assert "token" not in listed[0] and listed[0]["prefix"] == body["prefix"]
    actions = [
        e.action
        for e in (
            await db_session.exec(
                select(AuditEntry).where(AuditEntry.action.like("api_token.%"))  # type: ignore[attr-defined]
            )
        ).all()
    ]
    assert actions == ["api_token.create"]
    # Bounds: a year at most, a name.
    assert (
        await client.post(
            API,
            headers=admin,
            json={"name": "x", "days": 366, "current_password": STRONG},
        )
    ).status_code == 422
    assert (
        await client.post(
            API, headers=admin, json={"name": "  ", "current_password": STRONG}
        )
    ).status_code == 422


async def test_needs_the_right_to_make_one(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    tech = await account(client, db_session, "ab@lycee.test", [BuiltinGroup.TECHNICIAN])
    resp = await client.post(
        API, headers=tech, json={"name": "x", "current_password": STRONG}
    )
    assert resp.status_code == 403


async def test_read_only_by_default_write_when_asked(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    sites = await two_sites(client, db_session)
    _, read = await _token(client, sites.admin)
    _, write = await _token(client, sites.admin, name="Écriture", can_write=True)
    assert (await client.get("/api/v1/machines", headers=read)).status_code == 200
    resp = await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=read, json={}
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/machines/{sites.a.id}/check", headers=write, json={}
    )
    assert resp.status_code == 201, resp.text
    _ = BuiltinGroup


async def test_never_on_the_account_itself(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ac@lycee.test", [BuiltinGroup.ADMIN])
    _, token = await _token(client, admin, can_write=True)
    assert (await client.get("/api/v1/auth/me", headers=token)).status_code == 200
    for method, path, body in (
        (
            "POST",
            "/api/v1/auth/password",
            {"current_password": STRONG, "new_password": "x" * 20},
        ),
        ("GET", "/api/v1/auth/sessions", None),
        ("POST", API, {"name": "more"}),
        ("GET", API, None),
        ("PATCH", "/api/v1/auth/me", {"language": "en"}),
        ("POST", "/api/v1/auth/totp/setup", {"current_password": STRONG}),
    ):
        resp = await client.request(method, path, headers=token, json=body)
        assert resp.status_code == 403, (method, path, resp.text)
        assert resp.json()["error"]["code"] == "api_token.forbidden_here"


async def test_scope_follows_the_account(client, db_session):
    sites = await two_sites(client, db_session)
    from app.features.user.scope import Scope
    from tests.scope_helpers import SITE_A

    # Confined like the account's own group: an unrestricted one would widen it.
    tokens = await group(
        db_session, "Jetons", {"api_token:write"}, Scope(locations=frozenset({SITE_A}))
    )
    from app.features.user import crud
    from app.features.user.models import User

    tech = (
        await db_session.exec(select(User).where(User.email == "tech-a@test.local"))
    ).one()
    groups = await crud.groups_of_users(db_session, [tech.id])
    await crud.set_user_groups(
        db_session, tech, [g.id for g in groups[tech.id]] + [tokens.id]
    )
    await db_session.commit()
    _, token = await _token(client, sites.scoped)
    hosts = {
        m["hostname"]
        for m in (await client.get("/api/v1/machines", headers=token)).json()["items"]
    }
    assert hosts == {"PC-A"}
    assert (
        await client.get(f"/api/v1/machines/{sites.b.id}", headers=token)
    ).status_code == 404


async def test_revoked_expired_or_account_gone(client, db_session):
    from app.features.api_token.models import ApiToken
    from app.features.base import utcnow
    from app.features.user.permissions import BuiltinGroup

    admin = await account(client, db_session, "ad@lycee.test", [BuiltinGroup.ADMIN])
    other = await account(client, db_session, "ae@lycee.test", [BuiltinGroup.ADMIN])
    body, token = await _token(client, admin)
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 200
    row = (await db_session.exec(select(ApiToken))).one()
    await db_session.refresh(row)
    assert row.last_used_at is not None

    # Revoked by its owner — not by someone else's id.
    assert (
        await client.delete(f"{API}/{body['id']}", headers=other)
    ).status_code == 404
    assert (
        await client.delete(f"{API}/{body['id']}", headers=admin)
    ).status_code == 204
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 401

    # Expired.
    body, token = await _token(client, admin, name="Court")
    row = await db_session.get(ApiToken, body["id"])
    row.expires_at = utcnow() - timedelta(seconds=1)
    db_session.add(row)
    await db_session.commit()
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 401

    # A password reset by an administrator ends the account's tokens.
    _, token = await _token(client, admin, name="Long")
    me_id = (await client.get("/api/v1/auth/me", headers=admin)).json()["id"]
    resp = await client.post(
        f"/api/v1/users/{me_id}/reset-password", headers=other, json={}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/v1/machines", headers=token)).status_code == 401
    assert (
        await client.get(
            "/api/v1/machines", headers={"Authorization": "Bearer tiai_pat_nope"}
        )
    ).status_code == 401

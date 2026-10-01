"""Audit log: what is recorded, and how the console reads it back.

DB-backed tests require TIAI_TEST_DATABASE_URL.
"""

from datetime import UTC, datetime, timedelta

STRONG = "correct-horse-battery"


async def _headers(client, db_session, email: str, group) -> dict[str, str]:
    from app.features.user import crud

    await crud.ensure_builtin_groups(db_session)
    await crud.create_user(db_session, email=email, password=STRONG, groups=[group])
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": STRONG}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client, db_session, email: str = "admin@test.local"):
    from app.features.user.permissions import BuiltinGroup

    return await _headers(client, db_session, email, BuiltinGroup.ADMIN)


async def _enroll(client, machine_uuid: str, **fields) -> dict:
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **fields},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _entries(client, headers, **params) -> dict:
    resp = await client.get("/api/v1/audit", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed(db_session, *rows: tuple[str, str, str, datetime]) -> None:
    """Write entries directly, with chosen timestamps and actors."""
    from app.features.audit.models import AuditEntry

    for actor, action, resource_type, at in rows:
        db_session.add(
            AuditEntry(
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id="r",
                at=at,
            )
        )


# --- Access ------------------------------------------------------------------


async def test_readonly_cannot_read_the_audit_log(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    headers = await _headers(client, db_session, "ro@test.local", BuiltinGroup.READONLY)
    assert (await client.get("/api/v1/audit", headers=headers)).status_code == 403
    assert (
        await client.get("/api/v1/audit/actions", headers=headers)
    ).status_code == 403


async def test_anonymous_cannot_read_the_audit_log(client, db_session):
    assert (await client.get("/api/v1/audit")).status_code == 401


# --- What is recorded ----------------------------------------------------------


async def test_merge_is_audited_with_the_deleted_source_identity(client, db_session):
    headers = await _admin(client, db_session)
    kept = await _enroll(client, "audit-kept", hostname="PC-KEPT")
    dup = await _enroll(client, "audit-dup", hostname="PC-DUP")

    resp = await client.post(
        f"/api/v1/machines/{kept['machine_id']}/merge",
        headers=headers,
        json={"source_id": dup["machine_id"]},
    )
    assert resp.status_code == 200, resp.text

    page = await _entries(client, headers, action="machine.merge")
    assert page["total"] == 1
    entry = page["items"][0]
    assert entry["actor"] == "admin@test.local"
    assert entry["resource_type"] == "machine"
    assert entry["resource_id"] == kept["machine_id"]
    # The source row is gone: the trace is the only place that still names it.
    assert entry["details"]["source_id"] == dup["machine_id"]
    assert entry["details"]["source_hostname"] == "PC-DUP"
    assert entry["details"]["source_machine_uuid"] == "audit-dup"
    assert entry["details"]["hostname"] == "PC-KEPT"


async def test_refused_merge_leaves_no_trace(client, db_session):
    headers = await _admin(client, db_session)
    kept = await _enroll(client, "audit-self")

    resp = await client.post(
        f"/api/v1/machines/{kept['machine_id']}/merge",
        headers=headers,
        json={"source_id": kept["machine_id"]},
    )
    assert resp.status_code == 400
    assert (await _entries(client, headers))["total"] == 0


async def test_admin_password_reset_is_audited_without_the_password(client, db_session):
    headers = await _admin(client, db_session)
    groups = (await client.get("/api/v1/groups", headers=headers)).json()
    readonly = next(g["id"] for g in groups if g["builtin_key"] == "readonly")
    created = (
        await client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "email": "target@test.local",
                "password": STRONG,
                "group_ids": [readonly],
            },
        )
    ).json()

    generated = await client.post(
        f"/api/v1/users/{created['id']}/reset-password", headers=headers, json={}
    )
    assert generated.status_code == 200
    typed = await client.post(
        f"/api/v1/users/{created['id']}/reset-password",
        headers=headers,
        json={"password": "another-strong-password"},
    )
    assert typed.status_code == 200

    page = await _entries(client, headers, action="user.reset_password")
    assert page["total"] == 2
    newest, oldest = page["items"]
    assert newest["resource_id"] == created["id"]
    assert newest["details"] == {"email": "target@test.local", "generated": False}
    assert oldest["details"] == {"email": "target@test.local", "generated": True}
    # Neither password is anywhere in the trace.
    raw = str(page)
    assert generated.json()["password"] not in raw
    assert "another-strong-password" not in raw


# --- Reading -----------------------------------------------------------------


async def test_filters_by_actor_substring_case_insensitively(client, db_session):
    headers = await _admin(client, db_session)
    now = datetime.now(UTC)
    _seed(
        db_session,
        ("Alice@Example.org", "room.create", "room", now),
        ("bob@example.org", "room.create", "room", now),
    )
    await db_session.commit()

    page = await _entries(client, headers, actor="alice")
    assert [e["actor"] for e in page["items"]] == ["Alice@Example.org"]


async def test_actor_filter_treats_like_wildcards_literally(client, db_session):
    headers = await _admin(client, db_session)
    now = datetime.now(UTC)
    _seed(
        db_session,
        ("a_b@example.org", "room.create", "room", now),
        ("axb@example.org", "room.create", "room", now),
    )
    await db_session.commit()

    page = await _entries(client, headers, actor="a_b")
    assert [e["actor"] for e in page["items"]] == ["a_b@example.org"]


async def test_filters_by_resource_type(client, db_session):
    headers = await _admin(client, db_session)
    now = datetime.now(UTC)
    _seed(
        db_session,
        ("x@test.local", "room.create", "room", now),
        ("x@test.local", "group.create", "group", now),
    )
    await db_session.commit()

    page = await _entries(client, headers, resource_type="group")
    assert [e["action"] for e in page["items"]] == ["group.create"]


async def test_period_is_since_inclusive_until_exclusive(client, db_session):
    headers = await _admin(client, db_session)
    day = datetime(2026, 9, 15, tzinfo=UTC)
    _seed(
        db_session,
        ("x@test.local", "a.before", "room", day - timedelta(seconds=1)),
        ("x@test.local", "a.start", "room", day),
        ("x@test.local", "a.inside", "room", day + timedelta(hours=12)),
        ("x@test.local", "a.end", "room", day + timedelta(days=1)),
    )
    await db_session.commit()

    page = await _entries(
        client,
        headers,
        since=day.isoformat(),
        until=(day + timedelta(days=1)).isoformat(),
    )
    assert [e["action"] for e in page["items"]] == ["a.inside", "a.start"]


async def test_period_honours_the_time_zone_offset(client, db_session):
    headers = await _admin(client, db_session)
    # 2026-09-15 10:00 UTC is 2026-09-15 00:00 in Tahiti (UTC-10).
    _seed(
        db_session,
        (
            "x@test.local",
            "a.local_midnight",
            "room",
            datetime(2026, 9, 15, 10, tzinfo=UTC),
        ),
        (
            "x@test.local",
            "a.utc_midnight",
            "room",
            datetime(2026, 9, 15, 0, tzinfo=UTC),
        ),
    )
    await db_session.commit()

    page = await _entries(client, headers, since="2026-09-15T00:00:00-10:00")
    assert [e["action"] for e in page["items"]] == ["a.local_midnight"]


async def test_naive_period_bound_is_refused(client, db_session):
    headers = await _admin(client, db_session)
    resp = await client.get(
        "/api/v1/audit", headers=headers, params={"since": "2026-09-15T00:00:00"}
    )
    assert resp.status_code == 422


async def test_newest_first_and_paginated(client, db_session):
    headers = await _admin(client, db_session)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    _seed(
        db_session,
        *[
            ("x@test.local", f"a.{i}", "room", start + timedelta(minutes=i))
            for i in range(5)
        ],
    )
    await db_session.commit()

    first = await _entries(client, headers, page=1, page_size=2)
    second = await _entries(client, headers, page=2, page_size=2)
    assert first["total"] == 5
    assert [e["action"] for e in first["items"]] == ["a.4", "a.3"]
    assert [e["action"] for e in second["items"]] == ["a.2", "a.1"]


async def test_actions_lists_distinct_slugs_sorted(client, db_session):
    headers = await _admin(client, db_session)
    now = datetime.now(UTC)
    _seed(
        db_session,
        ("x@test.local", "room.update", "room", now),
        ("x@test.local", "group.create", "group", now),
        ("y@test.local", "room.update", "room", now),
    )
    await db_session.commit()

    resp = await client.get("/api/v1/audit/actions", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == ["group.create", "room.update"]

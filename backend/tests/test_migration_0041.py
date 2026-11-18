"""Migration 0041: every poste that exists at the upgrade holds a *used*
enrollment token (requires TIAI_TEST_DATABASE_URL).

The safe side of the one choice the migration makes: a poste whose token
would have read as « never used » under the old rule — ``last_seen`` not past
``token_issued_at`` — is not answered a second enrollment after the upgrade,
it waits for an approval like any established poste.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0041_enrollment_token_unused.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0041", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(step: str):
    def run(conn: sa.Connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(MigrationContext.configure(conn)):
            getattr(_migration(), step)()

    return run


FP = {"machine_guid": "guid-1", "smbios_uuid": "4c4c4544-0042-1111-2222-333344445555"}


async def _enroll(client, machine_uuid: str):
    from app.core.config import settings

    return await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, "fingerprint": FP},
    )


async def test_every_existing_poste_counts_as_used(client, engine, db_session):
    # Enrolled a moment before the upgrade, never heard from since: the very
    # row the timestamps called « unused ».
    fresh = await _enroll(client, "mig-fresh")
    assert fresh.status_code == 200, fresh.text
    established = await _enroll(client, "mig-established")
    beat = await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {established.json()['token']}"},
        json={},
    )
    assert beat.status_code == 200, beat.text
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("ALTER TABLE machines DROP COLUMN enrollment_token_unused")
        )

    async with engine.begin() as conn:
        await conn.run_sync(_run("upgrade"))

    async with engine.begin() as conn:
        rows = await conn.execute(
            sa.text("SELECT machine_uuid, enrollment_token_unused FROM machines")
        )
        assert dict(rows.all()) == {"mig-fresh": False, "mig-established": False}
        # NOT NULL with a default: a row written by anything but the model
        # (an older API process during a rolling upgrade) counts as used too.
        await conn.execute(
            sa.text(
                "INSERT INTO machines (id, machine_uuid, needs_verification, "
                "wu_reboot_required, hw_is_virtual, token_revoked, token_issued_at, "
                "first_seen, last_seen, created_at, updated_at) VALUES "
                "(gen_random_uuid(), 'mig-raw', false, false, false, false, now(), "
                "now(), now(), now(), now())"
            )
        )
        raw = await conn.execute(
            sa.text(
                "SELECT enrollment_token_unused FROM machines "
                "WHERE machine_uuid = 'mig-raw'"
            )
        )
        assert raw.scalar_one() is False

    for machine_uuid in ("mig-fresh", "mig-established"):
        again = await _enroll(client, machine_uuid)
        assert again.status_code == 403, (machine_uuid, again.text)
        assert again.json()["error"]["code"] == "machine.enrollment.approval_required"
    # The tokens in place are untouched.
    assert (
        await client.post(
            "/api/v1/agent/heartbeat",
            headers={"Authorization": f"Bearer {fresh.json()['token']}"},
            json={},
        )
    ).status_code == 200


async def test_the_downgrade_drops_the_column(engine):
    async def has_column() -> bool:
        async with engine.connect() as conn:
            found = await conn.execute(
                sa.text(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = "
                    "'machines' AND column_name = 'enrollment_token_unused'"
                )
            )
            return found.first() is not None

    async with engine.begin() as conn:
        await conn.run_sync(_run("downgrade"))
    assert not await has_column()
    async with engine.begin() as conn:
        await conn.run_sync(_run("upgrade"))
    assert await has_column()

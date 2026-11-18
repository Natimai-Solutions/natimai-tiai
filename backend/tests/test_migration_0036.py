"""Migration 0036: its two backfills, run against a real database (requires
TIAI_TEST_DATABASE_URL).

Both decide how rows written before the upgrade read after it: which closed
commands are final (``agent_verdict_at``), and from when a stored signature
age is aged (``signature_reported_at``). A backfill dropped or widened would
leave every other test green — they all start from an empty schema.
"""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa

_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "alembic"
    / "versions"
    / "0036_verdict_signature_age.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0036", _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(step: str):
    """The migration's own ``upgrade()`` or ``downgrade()``, as alembic runs it."""

    def run(conn: sa.Connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(MigrationContext.configure(conn)):
            getattr(_migration(), step)()

    return run


async def _columns(engine, table: str) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": table},
        )
        return {r[0] for r in rows}


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


async def _seed(db_session) -> dict[str, uuid.UUID]:
    """A parc as 0035 left it: two postes, and one command of every fate."""
    from app.features.command.models import Command
    from app.features.machine.models import Machine

    reported = Machine(
        machine_uuid="mig-reported",
        signature_age_days=3,
        last_seen=NOW - timedelta(days=12),
    )
    silent = Machine(machine_uuid="mig-never-reported", last_seen=NOW)
    relay = Machine(machine_uuid="mig-relay", last_seen=NOW)
    db_session.add_all([reported, silent, relay])
    await db_session.flush()
    ids = {"reported": reported.id, "silent": silent.id}

    def command(name: str, kind: str, status: str, finished: bool, **fields) -> None:
        row = Command(
            machine_id=reported.id,
            type=kind,
            status=status,
            expires_at=NOW + timedelta(days=1),
            finished_at=NOW - timedelta(hours=len(ids)) if finished else None,
            **fields,
        )
        db_session.add(row)
        ids[name] = row.id

    command("succeeded", "quick_scan", "succeeded", True, result_output="ok")
    command("failed by the poste", "quick_scan", "failed", True, error="0x80070005")
    command("unanswered", "full_scan", "failed", True, error="Sans réponse du poste")
    command("expired", "full_scan", "expired", False)
    command("pending", "full_scan", "pending", False)
    command("delivered", "full_scan", "delivered", False, delivered_at=NOW)
    command("wake", "wake_on_lan", "succeeded", True, result_output="Paquet émis")
    command(
        "relayed wake",
        "wake_on_lan",
        "succeeded",
        True,
        result_output="Relayé par PC-2 — paquet émis",
        relay_machine_id=relay.id,
    )
    await db_session.commit()
    return ids


async def _before_0036(engine) -> None:
    """The schema as 0035 left it: neither column."""
    async with engine.begin() as conn:
        await conn.execute(sa.text("ALTER TABLE commands DROP COLUMN agent_verdict_at"))
        await conn.execute(
            sa.text("ALTER TABLE machines DROP COLUMN signature_reported_at")
        )


async def test_only_a_postes_success_is_backfilled_as_its_verdict(engine, db_session):
    """A success is only ever a poste's — except a wake, which the server (or
    a relay, for the sleeping poste) writes closed. Every other closure may
    be the server's, and must stay open to the poste's late verdict."""
    ids = await _seed(db_session)
    await _before_0036(engine)

    async with engine.begin() as conn:
        await conn.run_sync(_run("upgrade"))

    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text("SELECT id, agent_verdict_at, finished_at FROM commands")
        )
        verdicts = {row[0]: (row[1], row[2]) for row in rows}
    names = {v: k for k, v in ids.items()}
    closed = {names[i] for i, (verdict, _) in verdicts.items() if verdict is not None}
    assert closed == {"succeeded"}
    verdict, finished = verdicts[ids["succeeded"]]
    assert verdict == finished


async def test_a_backfilled_verdict_is_final_and_the_others_are_not(
    client, engine, db_session
):
    """What the backfill is for, through the API: after the upgrade the
    success cannot be rewritten, and « sans réponse » still can."""
    from app.core.config import settings
    from app.features.command.models import Command

    enrolled = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": "mig-live"},
    )
    assert enrolled.status_code == 200, enrolled.text
    auth = {"Authorization": f"Bearer {enrolled.json()['token']}"}
    machine_id = uuid.UUID(enrolled.json()["machine_id"])
    rows = {
        "succeeded": Command(
            machine_id=machine_id,
            type="quick_scan",
            status="succeeded",
            expires_at=NOW,
            finished_at=NOW,
            result_output="clean",
        ),
        "unanswered": Command(
            machine_id=machine_id,
            type="full_scan",
            status="failed",
            expires_at=NOW,
            finished_at=NOW,
            error="Sans réponse du poste",
        ),
    }
    # Read before the commit expires the rows.
    ids = {name: row.id for name, row in rows.items()}
    db_session.add_all(rows.values())
    await db_session.commit()
    await _before_0036(engine)
    async with engine.begin() as conn:
        await conn.run_sync(_run("upgrade"))

    async def verdict(name: str, **body) -> str:
        resp = await client.post(
            f"/api/v1/agent/commands/{ids[name]}/result", headers=auth, json=body
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["status"]

    assert await verdict("succeeded", status="failed", error="replayed") == "ignored"
    assert await verdict("unanswered", status="succeeded", output="done") == "ok"
    db_session.expire_all()
    kept = await db_session.get(Command, ids["succeeded"])
    assert (kept.status, kept.result_output, kept.error) == ("succeeded", "clean", None)
    late = await db_session.get(Command, ids["unanswered"])
    assert (late.status, late.result_output, late.error) == ("succeeded", "done", None)


async def test_a_stored_signature_age_is_dated_by_the_last_contact(engine, db_session):
    """The last heartbeat is the best date there is for an age already
    stored; a poste that never reported one has nothing to date."""
    from app.features.machine.models import Machine
    from app.features.machine.status import effective_signature_age

    ids = await _seed(db_session)
    await _before_0036(engine)

    async with engine.begin() as conn:
        await conn.run_sync(_run("upgrade"))

    db_session.expire_all()
    reported = await db_session.get(Machine, ids["reported"])
    assert reported.signature_reported_at == reported.last_seen
    # Silent for twelve days on an age of three: fifteen today, not three.
    assert (
        effective_signature_age(
            reported.signature_age_days, reported.signature_reported_at, NOW
        )
        == 15
    )
    silent = await db_session.get(Machine, ids["silent"])
    assert (silent.signature_age_days, silent.signature_reported_at) == (None, None)


async def test_the_downgrade_drops_both_columns_and_the_upgrade_comes_back(
    engine, db_session
):
    await _seed(db_session)
    async with engine.begin() as conn:
        await conn.run_sync(_run("downgrade"))
    assert "agent_verdict_at" not in await _columns(engine, "commands")
    assert "signature_reported_at" not in await _columns(engine, "machines")
    async with engine.begin() as conn:
        await conn.run_sync(_run("upgrade"))
    assert "agent_verdict_at" in await _columns(engine, "commands")
    assert "signature_reported_at" in await _columns(engine, "machines")

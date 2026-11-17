"""State shared by several API processes, kept in PostgreSQL (audit T09, T36):
the package files an upload holds against the store sweep, and the software
catalogue budgets.

A second engine on the test database stands for another API process: it
shares the database with this one, not the memory of the process.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import contextlib
import hashlib
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.test_api_packages import (
    _admin,
    _deploy,
    _enroll,
    _pronote,
    _sweep_before_commit,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PACKAGES_DIR", str(tmp_path / "packages"))
    return tmp_path / "packages"


@pytest_asyncio.fixture
async def other_process(engine):
    """Another API process: its own engine, its own connections."""
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(engine.url)
    yield eng
    await eng.dispose()


# --- Package files held by an upload (T09) -------------------------------------


async def test_the_sweep_keeps_a_file_another_process_holds(
    client, db_session, store, other_process
):
    """A file held by an upload's transaction in another process stays;
    released, it goes."""
    from app.features.package import crud

    admin = await _admin(client, db_session)
    await _pronote(client, admin)
    sha = "cd" * 32
    (store / sha).write_bytes(b"stored, not committed yet")
    async with AsyncSession(other_process) as upload:
        await crud.hold_file(upload, sha)
        assert await crud.sweep_store(db_session) == 0
        assert (store / sha).exists()
        await upload.rollback()
    assert await crud.sweep_store(db_session) == 1
    assert not (store / sha).exists()


async def test_a_hold_ends_with_the_process_that_took_it(
    client, db_session, store, other_process
):
    """A process that dies mid-upload leaves nothing held: the database
    releases the lock with the connection — no expiry to wait for."""
    from app.features.package import crud

    admin = await _admin(client, db_session)
    await _pronote(client, admin)
    sha = "ce" * 32
    (store / sha).write_bytes(b"left by an upload that died")
    upload = AsyncSession(other_process)
    await crud.hold_file(upload, sha)
    pid = (await upload.exec(select(func.pg_backend_pid()))).one()
    assert await crud.sweep_store(db_session) == 0
    # The process is killed: its connection goes without a commit.
    async with AsyncSession(db_session.bind) as admin_session:
        await admin_session.exec(select(func.pg_terminate_backend(pid)))
    for _ in range(50):
        if await crud.sweep_store(db_session) == 1:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("the dead process's hold was never released")
    with contextlib.suppress(Exception):
        await upload.close()
    assert not (store / sha).exists()


class _Upload:
    """The part of an UploadFile ``storage.save`` reads."""

    def __init__(self, content: bytes) -> None:
        self.left = content

    async def read(self, _size: int) -> bytes:
        chunk, self.left = self.left, b""
        return chunk


async def test_an_upload_waits_for_a_sweep_deleting_its_file_and_stores_it_again(
    client, db_session, store, other_process
):
    """The other order: a sweep in another process has locked the
    unreferenced blob the upload's content hashes to, and deletes it. The
    upload waits for it, then finds the blob gone and puts its own there,
    rather than trust a file about to vanish."""
    from app.features.package import crud, storage

    admin = await _admin(client, db_session)
    await _pronote(client, admin)
    content = b"[Setup]\nthe same bytes\n"
    sha = hashlib.sha256(content).hexdigest()
    (store / sha).write_bytes(content)

    async with (
        AsyncSession(other_process) as sweep,
        AsyncSession(db_session.bind) as upload,
    ):
        assert await crud._claim_file(sweep, sha)
        saving = asyncio.create_task(
            storage.save(_Upload(content), 1 << 20, lambda h: crud.hold_file(upload, h))
        )
        await asyncio.sleep(0.3)
        assert not saving.done()  # waiting for the sweep's lock
        storage.remove_unreferenced(sha)
        await sweep.commit()
        stored = await asyncio.wait_for(saving, 5)
        assert stored.sha256 == sha
        assert (store / sha).read_bytes() == content
        # Held now: a sweep anywhere leaves it until the upload's
        # transaction ends.
        async with AsyncSession(other_process) as elsewhere:
            assert await crud.sweep_store(elsewhere) == 0
        assert (store / sha).exists()
        await upload.rollback()


async def test_a_sweep_in_another_process_during_an_upload_keeps_the_file(
    client, db_session, store, other_process, monkeypatch
):
    """The regression of v1.2.0 (T09), with the sweep in another process: it
    runs between the upload's save and its commit. The upload answers 200 and
    its files are there to download — new content, and content whose blob
    was already in the store unreferenced."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    orphan = b"[Setup]\nleft by a removed package file\n"
    (store / hashlib.sha256(orphan).hexdigest()).write_bytes(orphan)

    from app.features.package import crud

    original = crud.refresh_manifest
    swept = _sweep_before_commit(monkeypatch, other_process)
    up = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[
            ("files", ("new.ini", b"[Options]\nfresh\n")),
            ("files", ("reused.ini", orphan)),
        ],
    )
    assert up.status_code == 200, up.text
    assert swept == [0]
    monkeypatch.setattr(crud, "refresh_manifest", original)

    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    (command,) = hb.json()["commands"]
    files = {f["name"]: f["sha256"] for f in command["package"]["files"]}
    for name, content in (("new.ini", b"[Options]\nfresh\n"), ("reused.ini", orphan)):
        got = await client.get(
            f"/api/v1/agent/packages/{package['id']}/files/{files[name]}",
            headers=agent,
        )
        assert got.status_code == 200, (name, got.text)
        assert got.content == content


async def test_an_upload_that_commits_while_the_sweep_looks_is_seen(
    client, db_session, store, other_process, monkeypatch
):
    """The sweep has asked whether a file is wanted — no — and, before it
    locks it, an upload in another process holds it, names it and commits.
    The sweep, which gets the lock then, asks again and keeps the file."""
    import uuid

    from app.features.package import crud
    from app.features.package.models import PackageFile

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    content = b"[Setup]\nuploaded meanwhile\n"
    sha = hashlib.sha256(content).hexdigest()
    (store / sha).write_bytes(content)
    original = crud.sha_in_use
    asked: list[bool] = []

    async def meanwhile(session, sha256):
        wanted = await original(session, sha256)
        if sha256 == sha and not asked:
            asked.append(wanted)
            async with AsyncSession(other_process) as upload:
                await crud.hold_file(upload, sha)
                upload.add(
                    PackageFile(
                        package_id=uuid.UUID(package["id"]),
                        name="meanwhile.ini",
                        sha256=sha,
                        size=len(content),
                    )
                )
                await upload.commit()
        return wanted

    monkeypatch.setattr(crud, "sha_in_use", meanwhile)
    assert await crud.sweep_store(db_session) == 0
    assert asked == [False]
    assert (store / sha).exists()


async def test_a_sweep_releases_what_it_locked(client, db_session, store):
    """The sweep holds a file's lock only while deleting it: after it, an
    upload of that content does not wait."""
    from app.features.package import crud

    admin = await _admin(client, db_session)
    await _pronote(client, admin)
    sha = "cf" * 32
    (store / sha).write_bytes(b"an orphan")
    assert await crud.sweep_store(db_session) == 1
    async with AsyncSession(db_session.bind) as upload:
        await asyncio.wait_for(crud.hold_file(upload, sha), 2)
        await upload.rollback()


# --- The software catalogue budgets (T36) ---------------------------------------


@pytest.fixture
def budgets(monkeypatch):
    """Small budgets: (per poste, fleet)."""
    from app.features.inventory import budget

    def set_budgets(poste: int, fleet: int) -> None:
        monkeypatch.setattr(budget.software_quota, "units", poste)
        monkeypatch.setattr(budget.software_fleet_quota, "units", fleet)

    return set_budgets


async def _reserve(eng, key: str, wanted: int) -> int:
    """A reservation committed by a request of the process ``eng`` stands
    for."""
    from app.features.inventory import budget

    async with AsyncSession(eng) as session:
        grant = await budget.reserve(session, key, wanted)
        await session.commit()
        return grant.units if grant else 0


async def _left(eng, key: str) -> tuple[int, int]:
    from app.features.inventory import budget

    async with AsyncSession(eng) as session:
        return (
            await budget.poste_budget_left(session, key),
            await budget.fleet_budget_left(session),
        )


async def test_a_poste_is_granted_the_smaller_of_its_budget_and_the_fleets(
    engine, budgets
):
    """The per-poste budget does not bound many postes; the fleet's does."""
    from app.features.inventory import budget

    budgets(4, 6)
    assert await _reserve(engine, "a", 10) == 4
    assert await _left(engine, "a") == (0, 2)
    assert await _left(engine, "b") == (4, 2)
    async with AsyncSession(engine) as session:
        assert await budget.budget_left(session, "b") == 2
        grant = await budget.reserve(session, "b", 10)
        assert grant is not None and grant.units == 2
        assert await budget.reserve(session, "c", 10) is None
        assert await budget.fleet_budget_left(session) == 0
        # What was reserved and never used comes back to both budgets.
        await budget.release(engine, grant)
        assert await budget.fleet_budget_left(session) == 2
        assert await budget.budget_left(session, "b") == 2
        assert await budget.budget_left(session, "c") == 2


async def test_a_budget_spent_in_one_process_is_seen_by_another(
    engine, other_process, budgets
):
    budgets(5, 8)
    assert await _reserve(engine, "a", 3) == 3
    assert await _left(other_process, "a") == (2, 5)
    # Granted only what the first one left — of the poste's and the fleet's.
    assert await _reserve(other_process, "a", 10) == 2
    assert await _reserve(other_process, "b", 10) == 3
    assert await _left(engine, "a") == (0, 0)


async def test_a_budget_survives_a_restart(engine, budgets):
    """A restart used to hand out a fresh budget: a token in a loop got its
    2,000 entries again each time the API came back."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.features.counter import quota

    budgets(5, 100)
    assert await _reserve(engine, "a", 5) == 5
    # The process ends: its engines and whatever it kept in memory go.
    quota._side_engines.clear()
    restarted = create_async_engine(engine.url)
    try:
        assert await _left(restarted, "a") == (0, 95)
        assert await _reserve(restarted, "a", 1) == 0
    finally:
        await restarted.dispose()


async def test_concurrent_reservations_do_not_exceed_the_fleet_budget(
    engine, other_process, budgets
):
    """Forty postes at once, from two processes: the fleet's budget is
    granted once, not once per process or per request in flight."""
    from app.features.counter.models import SharedCounter

    budgets(10, 25)
    granted = await asyncio.gather(
        *(
            _reserve(engine if n % 2 else other_process, f"pc-{n}", 10)
            for n in range(40)
        )
    )
    assert sum(granted) == 25
    async with AsyncSession(engine) as session:
        charged = await session.scalar(
            select(func.sum(SharedCounter.used)).where(
                col(SharedCounter.name) == "software_entries_fleet"
            )
        )
    assert charged == 25


async def test_concurrent_heartbeats_do_not_exceed_the_fleet_budget(
    client, db_session, budgets
):
    from app.features.inventory.models import Software
    from tests.test_api_software_quota import _enroll as enroll
    from tests.test_api_software_quota import _heartbeat, _inventory

    budgets(10, 25)
    postes = [await enroll(client, f"pc-{n}") for n in range(6)]
    await asyncio.gather(
        *(
            _heartbeat(
                client, poste, **_inventory([f"p{n}-{i}" for i in range(10)], f"h{n}")
            )
            for n, poste in enumerate(postes)
        )
    )
    created = await db_session.scalar(select(func.count()).select_from(Software))
    assert created == 25


@pytest.mark.parametrize("ending", ["rollback", "close"])
async def test_a_transaction_that_does_not_commit_gives_the_budget_back(
    engine, other_process, budgets, ending
):
    """Rendu si la transaction échoue: what a request reserved and did not
    commit is back for every process as soon as its transaction has ended."""
    from app.features.inventory import crud

    budgets(10, 100)
    session = AsyncSession(engine)
    assert await crud._reserve_until_commit(session, "a", 4) == 4
    assert await _left(other_process, "a") == (6, 96)
    if ending == "rollback":
        await session.rollback()
    await session.close()
    assert await _left(other_process, "a") == (10, 100)

    # Committed, it stays spent.
    async with AsyncSession(engine) as session:
        assert await crud._reserve_until_commit(session, "a", 4) == 4
        await session.commit()
    assert await _left(other_process, "a") == (6, 96)


async def test_a_grant_counts_for_the_window_then_comes_back(engine, budgets):
    from app.features.counter.models import SharedCounter
    from app.features.inventory import budget

    budgets(10, 100)
    assert await _reserve(engine, "a", 7) == 7

    async def age(delta: timedelta) -> None:
        async with AsyncSession(engine) as session:
            await session.exec(
                text("UPDATE shared_counter SET bucket = bucket - :d").bindparams(
                    d=delta
                )
            )
            await session.commit()

    # A day less a minute later: still counted.
    await age(timedelta(hours=23, minutes=59))
    assert await _left(engine, "a") == (3, 93)
    # Past the window and its minute: back.
    await age(timedelta(minutes=2))
    assert await _left(engine, "a") == (10, 100)
    assert budget.software_quota.window_seconds == 24 * 3600

    # And purged by the housekeeping once no window reaches it.
    await age(timedelta(days=1))
    assert await _reserve(engine, "b", 1) == 1
    async with AsyncSession(engine) as session:
        from app.features.counter import quota

        assert await quota.purge_expired(session) == 2
        kept = (await session.exec(select(SharedCounter.key))).all()
    assert sorted(kept) == ["b", "fleet"]


async def test_the_worker_purges_the_counters(engine, monkeypatch, budgets):
    from app.core import worker
    from app.features.counter.models import SharedCounter

    budgets(10, 100)
    monkeypatch.setattr(worker, "engine", engine)
    assert await _reserve(engine, "a", 1) == 1
    async with AsyncSession(engine) as session:
        await session.exec(
            text("UPDATE shared_counter SET bucket = bucket - interval '3 days'")
        )
        await session.commit()
    assert await worker.purge_shared_counters() == 2
    async with AsyncSession(engine) as session:
        assert (await session.exec(select(SharedCounter))).all() == []

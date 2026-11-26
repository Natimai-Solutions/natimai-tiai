"""The attachment store (C11): its sweep, its locks, and the package store
it shares its code with, parameterised by a directory and a sniff.

DB-backed tests require TIAI_TEST_DATABASE_URL.
"""

import hashlib
import os
import time
import uuid
from pathlib import Path

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

ORPHAN = "ab" * 32


@pytest.fixture
def store() -> Path:
    from app.core.config import settings

    path = Path(settings.ATTACHMENTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _named(db_session, sha: str) -> None:
    """A poste, a line, and an attachment row naming ``sha``."""
    from app.features.attachment.models import InterventionAttachment
    from app.features.intervention.models import Intervention
    from app.features.machine.models import Machine

    machine = Machine(machine_uuid=str(uuid.uuid4()), hostname="PC-1")
    db_session.add(machine)
    await db_session.flush()
    line = Intervention(machine_id=machine.id, kind="incident", performed_by="a")
    db_session.add(line)
    await db_session.flush()
    db_session.add(
        InterventionAttachment(
            intervention_id=line.id,
            sha256=sha,
            size=1,
            content_type="image/png",
            filename="a.png",
            uploaded_by="a",
        )
    )
    await db_session.commit()


async def test_the_sweep_removes_orphans_and_keeps_what_is_named_or_held(
    engine, db_session, store
):
    from app.features.attachment import crud

    named, held = "cd" * 32, "ef" * 32
    for sha in (ORPHAN, named, held):
        (store / sha).write_bytes(b"x")
    await _named(db_session, named)
    async with AsyncSession(engine) as upload:
        await crud.hold_file(upload, held)
        assert await crud.sweep_store(db_session) == 1
        await upload.rollback()
    assert sorted(p.name for p in store.iterdir()) == sorted([named, held])
    # Released: the held file, named by nothing, goes at the next sweep.
    assert await crud.sweep_store(db_session) == 1
    assert [p.name for p in store.iterdir()] == [named]


async def test_the_sweep_keeps_everything_without_any_poste(engine, db_session, store):
    from app.features.attachment import crud

    (store / ORPHAN).write_bytes(b"x")
    assert await crud.sweep_store(db_session) == 0
    assert (store / ORPHAN).exists()


async def test_the_sweep_removes_abandoned_uploads_only(engine, db_session, store):
    from app.features.attachment import crud

    await _named(db_session, "cd" * 32)
    stale = store / ".upload-stale"
    fresh = store / ".upload-fresh"
    stale.write_bytes(b"x")
    fresh.write_bytes(b"x")
    old = time.time() - 25 * 3600
    os.utime(stale, (old, old))
    assert await crud.sweep_store(db_session) == 1
    assert not stale.exists()
    assert fresh.exists()


async def test_the_sweep_survives_a_read_only_volume(
    engine, db_session, store, monkeypatch
):
    from app.features.attachment import crud, storage

    await _named(db_session, "cd" * 32)
    (store / ORPHAN).write_bytes(b"x")

    def refuse(_sha):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(storage, "remove_unreferenced", refuse)
    assert await crud.sweep_store(db_session) == 0
    assert (store / ORPHAN).exists()
    # And the session is usable after.
    assert await crud.sha_in_use(db_session, ORPHAN) is False


async def test_the_lock_spaces_are_distinct(engine):
    """Holding a package file never stops the claim of an attachment whose
    hash starts alike, nor the other way round; within one space it does."""
    from app.features.attachment import crud as attachment_crud
    from app.features.package import crud as package_crud

    sha = "12345678" + "0" * 56
    async with AsyncSession(engine) as holder, AsyncSession(engine) as sweeper:
        await package_crud.hold_file(holder, sha)
        assert await attachment_crud._claim_file(sweeper, sha)
        assert not await package_crud._claim_file(sweeper, sha)
        await sweeper.rollback()
        await holder.rollback()

        await attachment_crud.hold_file(holder, sha)
        assert await package_crud._claim_file(sweeper, sha)
        assert not await attachment_crud._claim_file(sweeper, sha)
        await sweeper.rollback()
        await holder.rollback()


async def test_discard_if_orphan_keeps_a_named_file(engine, db_session, store):
    from app.features.attachment import crud

    named = "cd" * 32
    (store / named).write_bytes(b"x")
    (store / ORPHAN).write_bytes(b"x")
    await _named(db_session, named)
    assert await crud.discard_if_orphan(db_session, named) is False
    assert await crud.discard_if_orphan(db_session, ORPHAN) is True
    assert [p.name for p in store.iterdir()] == [named]


class _Upload:
    """The part of an UploadFile ``storage.save`` reads."""

    def __init__(self, content: bytes) -> None:
        self.left = content

    async def read(self, size: int) -> bytes:
        chunk, self.left = self.left[:size], self.left[size:]
        return chunk


async def _no_hold(_sha: str) -> None:
    return None


async def test_the_package_store_writes_in_the_directory_given(tmp_path):
    from app.core.config import settings
    from app.features.package import storage

    elsewhere = tmp_path / "elsewhere"
    content = b"%PDF-1.4 a document"
    stored = await storage.save(
        _Upload(content),  # type: ignore[arg-type]
        1 << 20,
        _no_hold,
        directory=str(elsewhere),
        sniff=lambda head: "application/pdf" if head.startswith(b"%PDF-") else None,
    )
    sha = hashlib.sha256(content).hexdigest()
    assert stored.sha256 == sha
    assert stored.content_type == "application/pdf"
    assert (elsewhere / sha).read_bytes() == content
    assert storage.exists(sha, str(elsewhere))
    assert not storage.exists(sha)  # not in PACKAGES_DIR
    assert storage.stored_shas(str(elsewhere)) == [sha]
    assert not Path(settings.PACKAGES_DIR, sha).exists()
    storage.remove_unreferenced(sha, str(elsewhere))
    assert not (elsewhere / sha).exists()


async def test_the_package_store_refuses_before_writing(tmp_path):
    from app.features.package import storage

    elsewhere = tmp_path / "elsewhere"
    with pytest.raises(storage.Unrecognised):
        await storage.save(
            _Upload(b"<svg/>"),  # type: ignore[arg-type]
            1 << 20,
            _no_hold,
            directory=str(elsewhere),
            sniff=lambda _head: None,
        )
    # Nothing at all: not even the directory, nor a temporary file.
    assert not elsewhere.exists()


async def test_without_a_sniff_the_package_store_is_unchanged(tmp_path):
    from app.core.config import settings
    from app.features.package import storage

    stored = await storage.save(_Upload(b""), 10, _no_hold)  # type: ignore[arg-type]
    assert stored.size == 0
    assert stored.content_type is None
    assert stored.path.parent == Path(settings.PACKAGES_DIR)
    with pytest.raises(storage.TooLarge):
        await storage.save(_Upload(b"x" * 11), 10, _no_hold)  # type: ignore[arg-type]
    assert not list(Path(settings.PACKAGES_DIR).glob(".upload-*"))

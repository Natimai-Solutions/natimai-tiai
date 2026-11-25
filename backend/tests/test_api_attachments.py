"""Attachments of the journal (C11): recognised from their content, bounded,
counted and checked under a lock, served as attachments only, within the
scope and rights of their line, swept from the disk once nothing names them,
purged by age.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import hashlib
import os
import time
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from sqlmodel import col, select

from tests.scope_helpers import account, group, two_sites

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"j" * 200
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"p" * 200
WEBP = b"RIFF\x00\x01\x00\x00WEBPVP8 " + b"w" * 200
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" + b"d" * 200


def _jpeg(n: int) -> bytes:
    """A distinct JPEG per ``n``."""
    return JPEG + f"-{n}-".encode()


@pytest.fixture
def store() -> Path:
    from app.core.config import settings

    return Path(settings.ATTACHMENTS_DIR)


def _files(store: Path) -> list[str]:
    return sorted(p.name for p in store.iterdir()) if store.exists() else []


async def _line(client, headers, machine_id, **body):
    resp = await client.post(
        f"/api/v1/machines/{machine_id}/interventions",
        headers=headers,
        json={"kind": "incident", **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload(client, headers, line_id, content, name="photo.jpg", ctype=None):
    return await client.post(
        f"/api/v1/interventions/{line_id}/attachments",
        headers=headers,
        files={"file": (name, content, ctype or "application/octet-stream")},
    )


async def _attach(client, headers, line_id, content, name="photo.jpg"):
    resp = await _upload(client, headers, line_id, content, name)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _journal(client, headers, machine_id):
    resp = await client.get(
        f"/api/v1/machines/{machine_id}/interventions?page_size=200", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _audit(db_session, action):
    from app.features.audit.models import AuditEntry

    rows = await db_session.exec(
        select(AuditEntry)
        .where(col(AuditEntry.action) == action)
        .order_by(col(AuditEntry.at))
    )
    return list(rows.all())


async def _count_rows(db_session) -> int:
    from sqlalchemy import func

    from app.features.attachment.models import InterventionAttachment

    return (
        await db_session.scalar(
            select(func.count()).select_from(InterventionAttachment)
        )
        or 0
    )


async def _setup(client, db_session):
    sites = await two_sites(client, db_session)
    line = await _line(client, sites.admin, sites.a.id)
    return sites, line


def _meet_in_save(monkeypatch, parties: int = 2, patience: float = 1.0):
    """Make the uploads meet in ``storage.save``: both have passed the
    pre-check before either reaches the lock."""
    from app.features.attachment import storage

    original = storage.save
    everyone = asyncio.Event()
    arrived = 0

    async def save(upload, max_bytes, hold):
        nonlocal arrived
        arrived += 1
        if arrived >= parties:
            everyone.set()
        try:
            await asyncio.wait_for(everyone.wait(), patience)
        except TimeoutError:
            pass
        return await original(upload, max_bytes, hold)

    monkeypatch.setattr(storage, "save", save)


# --- Types, names, sizes ---------------------------------------------------------


@pytest.mark.parametrize(
    "content, expected",
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (PDF, "application/pdf"),
    ],
)
async def test_each_type_is_recognised_from_its_content(
    client, db_session, store, content, expected
):
    sites, line = await _setup(client, db_session)
    # The client's type says HTML: ignored.
    resp = await _upload(client, sites.admin, line, content, "f", "text/html")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["content_type"] == expected
    assert body["size"] == len(content)
    assert body["uploaded_by"] == "admin@test.local"
    sha = hashlib.sha256(content).hexdigest()
    assert (store / sha).read_bytes() == content


@pytest.mark.parametrize(
    "content, name",
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "a.svg"),
        (b"<!doctype html><script>alert(1)</script>", "a.html"),
        (b"GIF89a\x01\x00\x01\x00", "a.gif"),
        (b"", "vide.jpg"),
        (b"<html><body>pas une photo</body></html>", "photo.jpg"),
    ],
)
async def test_other_types_are_refused_and_leave_nothing(
    client, db_session, store, content, name
):
    sites, line = await _setup(client, db_session)
    resp = await _upload(client, sites.admin, line, content, name, "image/jpeg")
    assert resp.status_code == 415, resp.text
    error = resp.json()["error"]
    assert error["code"] == "attachment.type_refused"
    assert error["details"]["types"] == [
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
    ]
    assert _files(store) == []
    assert await _count_rows(db_session) == 0
    assert await _audit(db_session, "intervention.attachment_add") == []


async def test_a_png_named_pdf_is_served_as_a_png(client, db_session):
    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, PNG, "x.pdf")
    assert body["filename"] == "x.pdf.png"
    assert body["content_type"] == "image/png"
    resp = await client.get(
        f"/api/v1/attachments/{body['id']}/content", headers=sites.admin
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_names_are_cleaned():
    from app.features.attachment.storage import clean_filename

    assert clean_filename("C:\\Users\\prof\\panne.jpg", "image/jpeg") == "panne.jpg"
    assert clean_filename("../../etc/panne.jpeg", "image/jpeg") == "panne.jpeg"
    assert clean_filename("pan\x00ne\x1b\u202e.png", "image/png") == "panne.png"
    assert clean_filename("panne.html", "image/png") == "panne.html.png"
    assert clean_filename("PANNE.PDF", "application/pdf") == "PANNE.PDF"
    assert clean_filename("", "image/png") == "piece-jointe.png"
    assert clean_filename(None, "image/webp") == "piece-jointe.webp"
    assert clean_filename("  \x07 ", "application/pdf") == "piece-jointe.pdf"
    assert clean_filename("..", "image/png") == "piece-jointe.png"
    long = clean_filename("a" * 300 + ".jpg", "image/jpeg")
    assert len(long) == 200 and long.endswith(".jpg")
    long = clean_filename("b" * 300, "image/png")
    assert len(long) == 200 and long.endswith(".png")
    # Kept: the download header is Starlette's to escape.
    assert clean_filename('a"b;c\\d.jpg', "image/jpeg") == "d.jpg"
    assert clean_filename('a"b;c.jpg', "image/jpeg") == 'a"b;c.jpg'


async def test_a_name_with_a_path_is_stored_without_it(client, db_session):
    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, JPEG, "C:\\Photos\\écran.jpg")
    assert body["filename"] == "écran.jpg"


async def test_too_large_is_refused_and_leaves_nothing(
    client, db_session, store, monkeypatch
):
    from app.core.config import settings

    sites, line = await _setup(client, db_session)
    monkeypatch.setattr(settings, "ATTACHMENT_MAX_BYTES", 100)
    resp = await _upload(client, sites.admin, line, JPEG)
    assert resp.status_code == 413
    error = resp.json()["error"]
    assert error["code"] == "attachment.too_large"
    assert error["details"] == {"max_bytes": 100}
    assert _files(store) == []
    assert await _count_rows(db_session) == 0


# --- Count, duplicates, races ----------------------------------------------------


async def test_the_eleventh_file_of_a_line_is_refused(client, db_session, store):
    sites, line = await _setup(client, db_session)
    for n in range(10):
        await _attach(client, sites.admin, line, _jpeg(n))
    resp = await _upload(client, sites.admin, line, _jpeg(10))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "attachment.too_many"
    assert resp.json()["error"]["details"] == {"max": 10}
    assert len(_files(store)) == 10


async def test_two_uploads_of_the_tenth_file_at_once_one_passes(
    client, db_session, store, monkeypatch
):
    sites, line = await _setup(client, db_session)
    for n in range(9):
        await _attach(client, sites.admin, line, _jpeg(n))
    _meet_in_save(monkeypatch)
    one, two = await asyncio.gather(
        _upload(client, sites.admin, line, _jpeg(100)),
        _upload(client, sites.admin, line, _jpeg(101)),
    )
    statuses = sorted([one.status_code, two.status_code])
    assert statuses == [201, 409], (one.text, two.text)
    loser = one if one.status_code == 409 else two
    assert loser.json()["error"]["code"] == "attachment.too_many"
    assert await _count_rows(db_session) == 10
    # The refused file is not left on the disk.
    assert len(_files(store)) == 10


async def test_the_same_file_twice_on_a_line_is_refused(client, db_session, store):
    sites, line = await _setup(client, db_session)
    other = await _line(client, sites.admin, sites.a.id)
    await _attach(client, sites.admin, line, JPEG)
    resp = await _upload(client, sites.admin, line, JPEG, "encore.jpg")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "attachment.duplicate"
    # On another line: the file is shared.
    await _attach(client, sites.admin, other, JPEG)
    assert _files(store) == [hashlib.sha256(JPEG).hexdigest()]
    assert await _count_rows(db_session) == 2


async def test_a_line_deleted_during_the_upload_is_a_404(
    client, db_session, store, engine, monkeypatch
):
    from sqlalchemy import text
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.attachment import crud

    sites, line = await _setup(client, db_session)
    original = crud.hold_file

    async def hold_then_delete(session, sha):
        async with AsyncSession(engine) as other:
            await other.exec(
                text("DELETE FROM interventions WHERE id = :id").bindparams(
                    id=uuid.UUID(line)
                )
            )
            await other.commit()
        await original(session, sha)

    monkeypatch.setattr(crud, "hold_file", hold_then_delete)
    resp = await _upload(client, sites.admin, line, JPEG)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "intervention.not_found"
    assert _files(store) == []


async def test_a_unique_violation_at_insertion_is_a_409(
    client, db_session, store, engine, monkeypatch
):
    """The checks under the lock are what answer; the constraint is what
    holds if they ever miss: a 409, never a 500."""
    from app.features.attachment import crud

    sites, line = await _setup(client, db_session)
    await _attach(client, sites.admin, line, JPEG)

    async def never(*_args):
        return False

    monkeypatch.setattr(crud, "named_on", never)
    resp = await _upload(client, sites.admin, line, JPEG)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "attachment.duplicate"
    # Still named by the first: kept.
    assert _files(store) == [hashlib.sha256(JPEG).hexdigest()]


# --- Quota -----------------------------------------------------------------------


async def test_the_quota_refuses_and_removes_the_file(
    client, db_session, store, monkeypatch
):
    from app.core.config import settings

    sites, line = await _setup(client, db_session)
    other = await _line(client, sites.admin, sites.a.id)
    first = _jpeg(1)
    monkeypatch.setattr(settings, "ATTACHMENT_QUOTA_BYTES", len(first) + 100)
    await _attach(client, sites.admin, line, first)
    resp = await _upload(client, sites.admin, line, _jpeg(2))
    assert resp.status_code == 413
    error = resp.json()["error"]
    assert error["code"] == "attachment.quota_exceeded"
    assert error["details"] == {"quota_bytes": len(first) + 100}
    assert _files(store) == [hashlib.sha256(first).hexdigest()]
    # The same file again, on another line: takes no more room.
    await _attach(client, sites.admin, other, first)
    resp = await client.get("/api/v1/attachments/policy", headers=sites.admin)
    assert resp.json()["used_bytes"] == len(first)


async def test_two_uploads_at_once_cannot_both_pass_the_quota(
    client, db_session, store, monkeypatch
):
    from app.core.config import settings

    sites, line = await _setup(client, db_session)
    monkeypatch.setattr(settings, "ATTACHMENT_QUOTA_BYTES", len(_jpeg(1)) + 10)
    _meet_in_save(monkeypatch)
    one, two = await asyncio.gather(
        _upload(client, sites.admin, line, _jpeg(1)),
        _upload(client, sites.admin, line, _jpeg(2)),
    )
    assert sorted([one.status_code, two.status_code]) == [201, 413]
    assert await _count_rows(db_session) == 1
    assert len(_files(store)) == 1


def test_the_quota_lock_is_its_own():
    from app.features.attachment.crud import ATTACHMENT_QUOTA_LOCK
    from app.features.counter.quota import QUOTA_LOCK
    from app.features.user.crud import ACCOUNT_MANAGEMENT_LOCK

    assert len({ATTACHMENT_QUOTA_LOCK, QUOTA_LOCK, ACCOUNT_MANAGEMENT_LOCK}) == 3
    assert 0 < ATTACHMENT_QUOTA_LOCK < 1 << 63


# --- The volume ------------------------------------------------------------------


async def test_without_the_volume_uploads_are_refused_the_rest_works(
    client, db_session, monkeypatch
):
    from app.core.config import settings

    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, JPEG)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(os.path, "ismount", lambda _path: False)
    resp = await _upload(client, sites.admin, line, PNG)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "attachment.store_unavailable"
    policy = (
        await client.get("/api/v1/attachments/policy", headers=sites.admin)
    ).json()
    assert policy["store_available"] is False
    resp = await client.get(
        f"/api/v1/attachments/{body['id']}/content", headers=sites.admin
    )
    assert resp.status_code == 200
    resp = await client.delete(f"/api/v1/attachments/{body['id']}", headers=sites.admin)
    assert resp.status_code == 204
    # Mounted: accepted again.
    monkeypatch.setattr(os.path, "ismount", lambda _path: True)
    assert (await _upload(client, sites.admin, line, PNG)).status_code == 201


async def test_the_policy_names_the_limits(client, db_session, monkeypatch):
    from app.core.config import settings

    sites, line = await _setup(client, db_session)
    monkeypatch.setattr(settings, "ATTACHMENT_QUOTA_BYTES", 10**9)
    await _attach(client, sites.admin, line, JPEG)
    policy = (
        await client.get("/api/v1/attachments/policy", headers=sites.admin)
    ).json()
    assert policy == {
        "max_bytes": settings.ATTACHMENT_MAX_BYTES,
        "max_per_intervention": 10,
        "types": ["image/jpeg", "image/png", "image/webp", "application/pdf"],
        "quota_bytes": 10**9,
        "used_bytes": len(JPEG),
        "retention_days": 0,
        "store_available": True,
    }


# --- Download --------------------------------------------------------------------


async def test_the_download_is_an_attachment_and_runs_nothing(
    client, db_session, store
):
    from sqlalchemy import update

    from app.features.attachment.models import InterventionAttachment

    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, PDF, "panne.pdf")
    # A name with a quote, a semicolon and accents, as a browser may send
    # it (httpx percent-encodes the quote of a multipart name itself).
    name = 'pan"ne; été.pdf'
    await db_session.exec(
        update(InterventionAttachment)
        .where(col(InterventionAttachment.id) == uuid.UUID(body["id"]))
        .values(filename=name)
    )
    await db_session.commit()
    resp = await client.get(
        f"/api/v1/attachments/{body['id']}/content", headers=sites.admin
    )
    assert resp.status_code == 200
    assert resp.content == PDF
    disposition = resp.headers["content-disposition"]
    assert disposition == "attachment; filename*=utf-8''" + quote(name)
    assert '"' not in disposition
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in resp.headers["content-security-policy"]
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    assert "no-store" in resp.headers["cache-control"]
    assert resp.headers["content-type"] == "application/pdf"
    # An ASCII name: quoted by Starlette all the same.
    body = await _attach(client, sites.admin, line, PNG, "ecran.png")
    resp = await client.get(
        f"/api/v1/attachments/{body['id']}/content", headers=sites.admin
    )
    assert resp.headers["content-disposition"] == 'attachment; filename="ecran.png"'
    assert resp.headers["content-type"] == "image/png"


async def test_a_file_missing_from_the_disk_is_said(client, db_session, store):
    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, JPEG)
    (store / hashlib.sha256(JPEG).hexdigest()).unlink()
    resp = await client.get(
        f"/api/v1/attachments/{body['id']}/content", headers=sites.admin
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "attachment.file_missing"
    # The line still lists it.
    [item] = [
        i for i in await _journal(client, sites.admin, sites.a.id) if i["id"] == line
    ]
    assert [a["id"] for a in item["attachments"]] == [body["id"]]


async def test_an_unknown_attachment_is_a_404(client, db_session):
    sites, _ = await _setup(client, db_session)
    resp = await client.get(
        f"/api/v1/attachments/{uuid.uuid4()}/content", headers=sites.admin
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "attachment.not_found"


# --- Scope and rights ------------------------------------------------------------


async def test_out_of_scope_is_not_found(client, db_session):
    sites = await two_sites(client, db_session)
    line_b = await _line(client, sites.admin, sites.b.id)
    body = await _attach(client, sites.admin, line_b, JPEG)
    resp = await client.get(
        f"/api/v1/machines/{sites.b.id}/interventions", headers=sites.scoped
    )
    assert resp.status_code == 404
    resp = await _upload(client, sites.scoped, line_b, PNG)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "intervention.not_found"
    resp = await client.get(
        f"/api/v1/attachments/{body['id']}/content", headers=sites.scoped
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "attachment.not_found"
    resp = await client.delete(
        f"/api/v1/attachments/{body['id']}", headers=sites.scoped
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "attachment.not_found"
    assert await _count_rows(db_session) == 1
    # In its own scope it works; the parc's total is not its to read.
    line_a = await _line(client, sites.scoped, sites.a.id)
    await _attach(client, sites.scoped, line_a, PNG)
    policy = (
        await client.get("/api/v1/attachments/policy", headers=sites.scoped)
    ).json()
    assert policy["used_bytes"] is None
    policy = (
        await client.get("/api/v1/attachments/policy", headers=sites.admin)
    ).json()
    assert policy["used_bytes"] == len(JPEG) + len(PNG)


async def test_rights_are_those_of_the_journal(client, db_session):
    from tests.test_api_tokens import _token

    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, JPEG)
    nothing = await group(db_session, "Rien", {"machine:read"}, None)
    reader = await group(
        db_session, "Lecteurs", {"machine:read", "intervention:read"}, None
    )
    blind = await account(client, db_session, "blind@test.local", [nothing.id])
    read = await account(client, db_session, "read@test.local", [reader.id])
    for headers, status in ((blind, 403), (read, 200)):
        resp = await client.get("/api/v1/attachments/policy", headers=headers)
        assert resp.status_code == status
        resp = await client.get(
            f"/api/v1/attachments/{body['id']}/content", headers=headers
        )
        assert resp.status_code == status
    resp = await _upload(client, read, line, PNG)
    assert resp.status_code == 403
    resp = await client.delete(f"/api/v1/attachments/{body['id']}", headers=read)
    assert resp.status_code == 403
    # A read-only API token downloads, and adds nothing.
    _, token = await _token(client, sites.admin)
    resp = await client.get(f"/api/v1/attachments/{body['id']}/content", headers=token)
    assert resp.status_code == 200
    assert (await _upload(client, token, line, PNG)).status_code == 403


# --- Journal and audit -----------------------------------------------------------


async def test_add_and_delete_are_audited(client, db_session):
    sites, line = await _setup(client, db_session)
    body = await _attach(client, sites.admin, line, JPEG, "écran.jpg")
    sha = hashlib.sha256(JPEG).hexdigest()
    [entry] = await _audit(db_session, "intervention.attachment_add")
    assert entry.resource_type == "intervention"
    assert entry.resource_id == line
    assert entry.details == {
        "machine_id": str(sites.a.id),
        "attachment_id": body["id"],
        "filename": "écran.jpg",
        "size": len(JPEG),
        "sha256": sha,
        "content_type": "image/jpeg",
    }
    # A refused upload writes nothing.
    await _upload(client, sites.admin, line, JPEG)
    assert len(await _audit(db_session, "intervention.attachment_add")) == 1
    resp = await client.delete(f"/api/v1/attachments/{body['id']}", headers=sites.admin)
    assert resp.status_code == 204
    [entry] = await _audit(db_session, "intervention.attachment_delete")
    assert entry.resource_id == line
    assert entry.details["attachment_id"] == body["id"]
    assert entry.details["sha256"] == sha


async def test_the_page_carries_its_attachments_in_one_query(
    client, db_session, engine
):
    from sqlalchemy import event

    from app.features.attachment.models import InterventionAttachment
    from app.features.base import utcnow
    from app.features.intervention.models import Intervention

    sites = await two_sites(client, db_session)
    now = utcnow()
    lines = []
    for n in range(25):
        row = Intervention(
            machine_id=sites.a.id,
            kind="incident",
            performed_by="a@test.local",
            performed_at=now - timedelta(minutes=n),
        )
        db_session.add(row)
        await db_session.flush()
        lines.append(row.id)
        for k in (1, 0):  # the second written first, but created later
            db_session.add(
                InterventionAttachment(
                    intervention_id=row.id,
                    sha256=f"{n:02d}{k}".ljust(64, "a"),
                    size=10,
                    content_type="image/png",
                    filename=f"{n}-{k}.png",
                    uploaded_by="a@test.local",
                    created_at=now + timedelta(seconds=k),
                )
            )
    await db_session.commit()

    seen: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        if "intervention_attachments" in statement:
            seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        resp = await client.get(
            f"/api/v1/machines/{sites.a.id}/interventions?page_size=25",
            headers=sites.admin,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 25
    assert len(seen) == 1
    for item in items:
        n = lines.index(uuid.UUID(item["id"]))
        assert [a["filename"] for a in item["attachments"]] == [
            f"{n}-0.png",
            f"{n}-1.png",
        ]


async def test_creation_and_edit_answer_without_attachments(client, db_session):
    sites, line = await _setup(client, db_session)
    await _attach(client, sites.admin, line, JPEG)
    resp = await client.patch(
        f"/api/v1/interventions/{line}", headers=sites.admin, json={"note": "x"}
    )
    assert resp.status_code == 200
    assert resp.json()["attachments"] == []


# --- Deletions -------------------------------------------------------------------


async def test_a_deleted_attachment_leaves_the_disk_unless_shared(
    client, db_session, store
):
    sites, line = await _setup(client, db_session)
    other = await _line(client, sites.admin, sites.a.id)
    sha = hashlib.sha256(JPEG).hexdigest()
    one = await _attach(client, sites.admin, line, JPEG)
    two = await _attach(client, sites.admin, other, JPEG)
    alone = await _attach(client, sites.admin, line, PNG)
    resp = await client.delete(
        f"/api/v1/attachments/{alone['id']}", headers=sites.admin
    )
    assert resp.status_code == 204
    assert _files(store) == [sha]
    # Shared: kept while the other line names it.
    await client.delete(f"/api/v1/attachments/{one['id']}", headers=sites.admin)
    assert _files(store) == [sha]
    await client.delete(f"/api/v1/attachments/{two['id']}", headers=sites.admin)
    assert _files(store) == []


async def test_a_deleted_line_takes_its_attachments(client, db_session, store):
    sites, line = await _setup(client, db_session)
    other = await _line(client, sites.admin, sites.a.id)
    await _attach(client, sites.admin, line, JPEG)
    await _attach(client, sites.admin, line, PNG)
    await _attach(client, sites.admin, other, PNG)
    resp = await client.delete(f"/api/v1/interventions/{line}", headers=sites.admin)
    assert resp.status_code == 204
    [entry] = await _audit(db_session, "intervention.delete")
    assert entry.details["attachments"] == 2
    # The JPEG went at once; the PNG stays, named by the other line.
    assert _files(store) == [hashlib.sha256(PNG).hexdigest()]
    assert await _count_rows(db_session) == 1


async def test_a_deleted_visit_takes_its_lines_attachments(client, db_session, store):
    from app.features.intervention.models import Intervention
    from app.features.maintenance.models import Maintenance

    sites = await two_sites(client, db_session)
    visit = Maintenance(performed_by="admin@test.local")
    db_session.add(visit)
    await db_session.flush()
    line = Intervention(
        machine_id=sites.a.id,
        kind="maintenance",
        performed_by="admin@test.local",
        maintenance_id=visit.id,
    )
    db_session.add(line)
    visit_id, line_id = visit.id, line.id
    await db_session.commit()
    await _attach(client, sites.admin, line_id, JPEG)
    resp = await client.delete(f"/api/v1/maintenance/{visit_id}", headers=sites.admin)
    assert resp.status_code == 204, resp.text
    [entry] = await _audit(db_session, "maintenance.delete")
    assert entry.details["attachments"] == 1
    assert await _count_rows(db_session) == 0
    assert _files(store) == []


async def test_a_merge_carries_the_attachments_over(client, db_session):
    from tests.scope_helpers import machine

    sites = await two_sites(client, db_session)
    dup = await machine(db_session, "PC-A", location="Lycée A")
    line = await _line(client, sites.admin, dup.id)
    body = await _attach(client, sites.admin, line, JPEG)
    resp = await client.post(
        f"/api/v1/machines/{sites.a.id}/merge",
        headers=sites.admin,
        json={"source_id": str(dup.id)},
    )
    assert resp.status_code == 200, resp.text
    [item] = await _journal(client, sites.admin, sites.a.id)
    assert [a["id"] for a in item["attachments"]] == [body["id"]]


# --- Retention -------------------------------------------------------------------


@pytest.fixture
def worker(engine, monkeypatch):
    from app.core import worker as module

    monkeypatch.setattr(module, "engine", engine)
    return module


async def test_retention_purges_old_rows_then_the_sweep_their_files(
    client, db_session, store, worker
):
    from sqlalchemy import update

    from app.features.attachment import crud
    from app.features.attachment.models import InterventionAttachment
    from app.features.base import utcnow

    sites, line = await _setup(client, db_session)
    old = await _attach(client, sites.admin, line, JPEG)
    await _attach(client, sites.admin, line, PNG)
    await db_session.exec(
        update(InterventionAttachment)
        .where(col(InterventionAttachment.id) == uuid.UUID(old["id"]))
        .values(created_at=utcnow() - timedelta(days=40))
    )
    await db_session.commit()

    # 0: kept.
    assert await worker.purge_attachments() == 0
    assert await _count_rows(db_session) == 2

    resp = await client.patch(
        "/api/v1/settings", headers=sites.admin, json={"attachment_retention_days": 30}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["attachment_retention_days"] == 30
    assert await worker.purge_attachments() == 1
    rows = (await db_session.exec(select(InterventionAttachment))).all()
    assert [r.content_type for r in rows] == ["image/png"]
    # The worker touched no file; the API's sweep removes the orphan.
    assert len(_files(store)) == 2
    assert await crud.sweep_store(db_session) == 1
    assert _files(store) == [hashlib.sha256(PNG).hexdigest()]


async def test_the_retention_setting_starts_from_the_environment(
    client, db_session, monkeypatch
):
    from app.core.config import settings

    sites = await two_sites(client, db_session)
    monkeypatch.setattr(settings, "ATTACHMENT_RETENTION_DAYS", 1825)
    body = (await client.get("/api/v1/settings", headers=sites.admin)).json()
    assert body["attachment_retention_days"] == 1825
    assert body["env_attachment_retention_days"] == 1825
    policy = (
        await client.get("/api/v1/attachments/policy", headers=sites.admin)
    ).json()
    assert policy["retention_days"] == 1825
    resp = await client.patch(
        "/api/v1/settings",
        headers=sites.admin,
        json={"attachment_retention_days": 3651},
    )
    assert resp.status_code == 422
    resp = await client.patch(
        "/api/v1/settings", headers=sites.admin, json={"attachment_retention_days": 0}
    )
    assert resp.json()["attachment_retention_days"] == 0


async def test_the_api_sweeps_the_attachments_at_start(
    client, db_session, store, engine, monkeypatch
):
    from app.core import db
    from app.features.attachment import crud
    from app.main import app

    sites, line = await _setup(client, db_session)
    await _attach(client, sites.admin, line, JPEG)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(crud, "SWEEP_INTERVAL_SECONDS", 0.05)
    orphan = store / ("e0" * 32)
    orphan.write_bytes(b"orphan")
    async with app.router.lifespan_context(app):
        assert not orphan.exists()
        later = store / ("e1" * 32)
        later.write_bytes(b"orphan made after start-up")
        deadline = time.monotonic() + 10
        while later.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert not later.exists()
    assert _files(store) == [hashlib.sha256(JPEG).hexdigest()]

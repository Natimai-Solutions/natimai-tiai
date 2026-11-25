"""Procedure notes per hardware model (C11): written by the technicians who
see every poste, read within the scope, never lost to a concurrent write,
every write audited with the text it replaced.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import uuid

from sqlmodel import col, select

from tests.scope_helpers import SITE_A, SITE_B, account, group, machine, two_sites

API = "/api/v1/procedures"
MODEL = "OptiPlex 7090"


async def _sites(client, db_session):
    """Two sites, each poste of its own model, and a poste of a shared one
    on each; the confined account holds the procedure rights."""
    sites = await two_sites(client, db_session)
    from sqlalchemy import update

    from app.features.machine.models import Machine

    await db_session.exec(
        update(Machine).where(col(Machine.id) == sites.a.id).values(hw_model=MODEL)
    )
    await db_session.exec(
        update(Machine).where(col(Machine.id) == sites.b.id).values(hw_model="HP 400")
    )
    await db_session.commit()
    return sites


async def _create(client, headers, hw_model=MODEL, body="F10 ouvre le BIOS."):
    return await client.post(
        API, headers=headers, json={"hw_model": hw_model, "body": body}
    )


async def _created(client, headers, **fields):
    resp = await _create(client, headers, **fields)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _audit(db_session, action):
    from app.features.audit.models import AuditEntry

    rows = await db_session.exec(
        select(AuditEntry)
        .where(col(AuditEntry.action) == action)
        .order_by(col(AuditEntry.at))
    )
    return list(rows.all())


async def _retire(db_session, machine_id):
    from app.features.asset.models import Asset, AssetStatus

    db_session.add(Asset(machine_id=machine_id, status=AssetStatus.RETIRED))
    await db_session.commit()


# --- Creation --------------------------------------------------------------------


async def test_a_note_is_created_for_a_known_model_and_audited(client, db_session):
    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin, hw_model=f"  {MODEL} ", body=" F10 \n")
    assert note["hw_model"] == MODEL
    assert note["body"] == "F10"
    assert note["created_by"] == note["updated_by"] == "admin@test.local"
    [entry] = await _audit(db_session, "procedure.create")
    assert entry.resource_type == "procedure"
    assert entry.resource_id == note["id"]
    assert entry.details == {"hw_model": MODEL, "length": 3}


async def test_an_unknown_model_is_refused_before_a_duplicate(client, db_session):
    sites = await _sites(client, db_session)
    resp = await _create(client, sites.admin, hw_model="Inconnu 1")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "procedure.model_unknown"
    await _created(client, sites.admin)
    resp = await _create(client, sites.admin)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "procedure.exists"


async def test_a_model_on_a_retired_poste_only_is_known(client, db_session):
    sites = await _sites(client, db_session)
    old = await machine(db_session, "PC-OLD", location=SITE_A, hw_model="Vieux 1")
    await _retire(db_session, old.id)
    await _created(client, sites.admin, hw_model="Vieux 1")


async def test_bounds_of_the_model_and_the_text(client, db_session):
    sites = await _sites(client, db_session)
    assert (await _create(client, sites.admin, hw_model="m" * 201)).status_code == 422
    assert (await _create(client, sites.admin, body="   ")).status_code == 422
    assert (await _create(client, sites.admin, body="x" * 5001)).status_code == 422
    await _created(client, sites.admin, body="x" * 5000)


# --- Edit and deletion -----------------------------------------------------------


async def test_an_edit_needs_the_version_it_was_made_from(client, db_session):
    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin, body="Avant")
    resp = await client.patch(
        f"{API}/{note['id']}",
        headers=sites.admin,
        json={"body": "Après", "expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 200, resp.text
    edited = resp.json()
    assert edited["body"] == "Après"
    assert edited["updated_at"] != note["updated_at"]
    [entry] = await _audit(db_session, "procedure.update")
    assert entry.details == {"hw_model": MODEL, "previous": "Avant", "length": 5}
    # From the old version: refused, nothing written.
    resp = await client.patch(
        f"{API}/{note['id']}",
        headers=sites.admin,
        json={"body": "Écrasé", "expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "procedure.changed"
    resp = await client.get(
        f"/api/v1/machines/{sites.a.id}/procedure", headers=sites.admin
    )
    assert resp.json()["procedure"]["body"] == "Après"
    assert len(await _audit(db_session, "procedure.update")) == 1
    for body in ("", "  ", "x" * 5001):
        resp = await client.patch(
            f"{API}/{note['id']}",
            headers=sites.admin,
            json={"body": body, "expected_updated_at": edited["updated_at"]},
        )
        assert resp.status_code == 422
    resp = await client.patch(
        f"{API}/{uuid.uuid4()}",
        headers=sites.admin,
        json={"body": "x", "expected_updated_at": edited["updated_at"]},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "procedure.not_found"


async def test_a_deletion_needs_the_version_too(client, db_session):
    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin, body="Texte")
    resp = await client.delete(
        f"{API}/{note['id']}",
        headers=sites.admin,
        params={"expected_updated_at": "2020-01-01T00:00:00Z"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "procedure.changed"
    resp = await client.delete(
        f"{API}/{note['id']}",
        headers=sites.admin,
        params={"expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 204
    [entry] = await _audit(db_session, "procedure.delete")
    assert entry.details == {"hw_model": MODEL, "previous": "Texte"}
    resp = await client.delete(
        f"{API}/{note['id']}",
        headers=sites.admin,
        params={"expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 404


async def test_two_edits_from_one_version_one_passes(client, db_session):
    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin)
    one, two = await asyncio.gather(
        *(
            client.patch(
                f"{API}/{note['id']}",
                headers=sites.admin,
                json={"body": text, "expected_updated_at": note["updated_at"]},
            )
            for text in ("Un", "Deux")
        )
    )
    assert sorted([one.status_code, two.status_code]) == [200, 409]
    loser = one if one.status_code == 409 else two
    assert loser.json()["error"]["code"] == "procedure.changed"
    winner = one if one.status_code == 200 else two
    resp = await client.get(
        f"/api/v1/machines/{sites.a.id}/procedure", headers=sites.admin
    )
    assert resp.json()["procedure"]["body"] == winner.json()["body"]


async def test_two_creations_of_one_model_one_passes(client, db_session, monkeypatch):
    """Both pass the check for an existing note; the unique index answers
    the second with a 409, never a 500."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    sites = await _sites(client, db_session)
    original = AsyncSession.exec
    arrived = 0
    everyone = asyncio.Event()

    async def meet(self, statement, *args, **kwargs):
        nonlocal arrived
        result = await original(self, statement, *args, **kwargs)
        # After each request's « already one? » question.
        if "FROM procedures" in str(statement) and "procedures.id" in str(statement):
            arrived += 1
            if arrived >= 2:
                everyone.set()
            try:
                await asyncio.wait_for(everyone.wait(), 1.0)
            except TimeoutError:
                pass
        return result

    monkeypatch.setattr(AsyncSession, "exec", meet)
    one, two = await asyncio.gather(
        _create(client, sites.admin, body="Un"),
        _create(client, sites.admin, body="Deux"),
    )
    assert sorted([one.status_code, two.status_code]) == [201, 409], (
        one.text,
        two.text,
    )
    loser = one if one.status_code == 409 else two
    assert loser.json()["error"]["code"] == "procedure.exists"


# --- Reading ---------------------------------------------------------------------


async def test_the_fiche_reads_the_note_of_its_model(client, db_session):
    sites = await _sites(client, db_session)
    resp = await client.get(
        f"/api/v1/machines/{sites.a.id}/procedure", headers=sites.admin
    )
    assert resp.json() == {
        "hw_model": MODEL,
        "procedure": None,
        "scope_limited": False,
    }
    note = await _created(client, sites.admin)
    resp = await client.get(
        f"/api/v1/machines/{sites.a.id}/procedure", headers=sites.admin
    )
    assert resp.json()["procedure"]["id"] == note["id"]
    bare = await machine(db_session, "PC-NU", location=SITE_A)
    resp = await client.get(
        f"/api/v1/machines/{bare.id}/procedure", headers=sites.admin
    )
    assert resp.json() == {"hw_model": None, "procedure": None, "scope_limited": False}
    # A confined account reads the note of a poste in its scope, and is told
    # it does not write it (the console hides its buttons).
    resp = await client.get(
        f"/api/v1/machines/{sites.a.id}/procedure", headers=sites.scoped
    )
    assert resp.json()["procedure"]["id"] == note["id"]
    assert resp.json()["scope_limited"] is True
    resp = await client.get(
        f"/api/v1/machines/{sites.b.id}/procedure", headers=sites.scoped
    )
    assert resp.status_code == 404


async def test_the_list_follows_the_scope_and_counts_postes_in_service(
    client, db_session
):
    sites = await _sites(client, db_session)
    await machine(db_session, "PC-A2", location=SITE_A, hw_model=MODEL)
    retired = await machine(db_session, "PC-A3", location=SITE_A, hw_model=MODEL)
    await _retire(db_session, retired.id)
    await machine(db_session, "PC-B2", location=SITE_B, hw_model=MODEL)
    await _created(client, sites.admin)
    await _created(client, sites.admin, hw_model="HP 400")

    resp = await client.get(API, headers=sites.admin)
    assert resp.status_code == 200
    assert [(p["hw_model"], p["machine_count"]) for p in resp.json()] == [
        ("HP 400", 1),
        (MODEL, 3),
    ]
    resp = await client.get(API, headers=sites.scoped)
    assert [(p["hw_model"], p["machine_count"]) for p in resp.json()] == [(MODEL, 2)]


async def test_a_confined_account_reads_and_writes_nothing(client, db_session):
    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin)
    resp = await _create(client, sites.scoped, hw_model=MODEL)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "procedure.scope_limited"
    resp = await client.patch(
        f"{API}/{note['id']}",
        headers=sites.scoped,
        json={"body": "x", "expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "procedure.scope_limited"
    resp = await client.delete(
        f"{API}/{note['id']}",
        headers=sites.scoped,
        params={"expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "procedure.scope_limited"


async def test_an_unconfined_account_edits_a_note_without_postes(client, db_session):
    from sqlalchemy import update

    from app.features.machine.models import Machine

    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin, hw_model="HP 400")
    await db_session.exec(
        update(Machine).where(col(Machine.id) == sites.b.id).values(hw_model=None)
    )
    await db_session.commit()
    resp = await client.get(API, headers=sites.admin)
    assert [(p["hw_model"], p["machine_count"]) for p in resp.json()] == [("HP 400", 0)]
    resp = await client.patch(
        f"{API}/{note['id']}",
        headers=sites.admin,
        json={"body": "Plus de poste", "expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 200


async def test_rights(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin)
    readonly = await account(
        client, db_session, "ro@test.local", [BuiltinGroup.READONLY]
    )
    tech = await account(
        client, db_session, "tech@test.local", [BuiltinGroup.TECHNICIAN]
    )
    readers = await group(
        db_session, "Lecteurs", {"machine:read", "procedure:read"}, None
    )
    reader = await account(client, db_session, "reader@test.local", [readers.id])
    assert (await client.get(API, headers=readonly)).status_code == 403
    resp = await client.get(
        f"/api/v1/machines/{sites.a.id}/procedure", headers=readonly
    )
    assert resp.status_code == 403
    assert (await client.get(API, headers=reader)).status_code == 200
    resp = await client.patch(
        f"{API}/{note['id']}",
        headers=reader,
        json={"body": "x", "expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 403
    assert (await _create(client, reader, hw_model="HP 400")).status_code == 403
    # The technicians write.
    resp = await client.patch(
        f"{API}/{note['id']}",
        headers=tech,
        json={"body": "Par un technicien", "expected_updated_at": note["updated_at"]},
    )
    assert resp.status_code == 200, resp.text


async def test_a_merge_leaves_the_notes_alone(client, db_session):
    sites = await _sites(client, db_session)
    note = await _created(client, sites.admin)
    dup = await machine(db_session, "PC-A", location=SITE_A, hw_model=MODEL)
    resp = await client.post(
        f"/api/v1/machines/{sites.a.id}/merge",
        headers=sites.admin,
        json={"source_id": str(dup.id)},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.get(API, headers=sites.admin)
    assert [p["id"] for p in resp.json()] == [note["id"]]

"""Reading the directory through designated postes (plan-lecture-annuaire.md,
mode relay): designation, the reading asked and delivered, what a reader may
answer, the verdicts, the rooms, two readers, the held moves."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import col, select

from tests.test_api_inventory import _admin_headers, _enroll, _heartbeat

SID = "S-1-5-21-1111-2222-3333"
OU_DN = "OU=Salle B12,OU=Postes,DC=lycee,DC=local"


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.DIRECTORY_VERIFY", "relay")
    monkeypatch.setattr("app.core.config.settings.DIRECTORY_CONFIRM_MOVES", 20)


async def _poste(client, host, domain="LYCEE", **fields):
    enrolled = await _enroll(
        client, str(uuid.uuid4()), hostname=host, domain=domain, **fields
    )
    return enrolled


async def _machine(db_session, enrolled):
    from app.features.machine.models import Machine

    m = await db_session.get(Machine, uuid.UUID(enrolled["machine_id"]))
    await db_session.refresh(m)
    return m


async def _reader_with_command(client, db_session, admin):

    reader = await _poste(client, "SRV-ADM")
    resp = await client.post(
        f"/api/v1/directory/readers/{reader['machine_id']}", headers=admin
    )
    assert resp.status_code == 200, resp.text
    return reader


def _obj(host, dn=None, guid=None, location=None, disabled=False):
    return {
        "object_guid": guid or str(uuid.uuid4()),
        "sam_account_name": f"{host}$",
        "dns_host_name": f"{host.lower()}.lycee.local",
        "distinguished_name": dn or f"CN={host},{OU_DN}",
        "location": location,
        "disabled": disabled,
    }


def _reading(objects, netbios="LYCEE", sid=SID):
    return {
        "domain": {"name": "lycee.local", "netbios_name": netbios, "sid": sid},
        "objects": objects,
        "subnets": [{"subnet": "10.1.0.0/16", "site": "Taravao"}],
    }


async def _deliver(client, db_session, monkeypatch, reader):
    """Queue a reading and have the reader's heartbeat pick it up."""
    from app.core import worker

    monkeypatch.setattr(worker, "engine", db_session.bind)
    assert await worker.sync_directory() == 1
    resp = await _heartbeat(client, reader["token"])
    assert resp.status_code == 200, resp.text
    reads = [c for c in resp.json()["commands"] if c["type"] == "directory_read"]
    assert len(reads) == 1
    return reads[0]


async def test_designation_needs_the_mode_and_a_domain(client, db_session, monkeypatch):
    admin = await _admin_headers(client, db_session)
    poste = await _poste(client, "PC-1")
    resp = await client.post(
        f"/api/v1/directory/readers/{poste['machine_id']}", headers=admin
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "directory.off"

    monkeypatch.setattr("app.core.config.settings.DIRECTORY_VERIFY", "relay")
    workgroup = await _poste(client, "PC-WG", domain=None)
    resp = await client.post(
        f"/api/v1/directory/readers/{workgroup['machine_id']}", headers=admin
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "directory.not_eligible"

    resp = await client.post(
        f"/api/v1/directory/readers/{poste['machine_id']}", headers=admin
    )
    assert resp.status_code == 200
    state = (await client.get("/api/v1/directory", headers=admin)).json()
    assert state["mode"] == "relay"
    assert [r["hostname"] for r in state["readers_waiting"]] == ["PC-1"]
    assert state["domains_without_reader"] == []

    resp = await client.delete(
        f"/api/v1/directory/readers/{poste['machine_id']}", headers=admin
    )
    assert resp.status_code == 204
    state = (await client.get("/api/v1/directory", headers=admin)).json()
    assert state["readers_waiting"] == []
    assert state["domains_without_reader"] == ["lycee"]

    from app.features.audit.models import AuditEntry

    actions = (
        await db_session.exec(
            select(AuditEntry.action).where(col(AuditEntry.action).like("directory.%"))
        )
    ).all()
    assert sorted(actions) == ["directory.reader_designate", "directory.reader_revoke"]


async def test_a_reading_is_asked_delivered_and_matched(
    client, db_session, monkeypatch, relay
):
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    pc2 = await _poste(client, "PC-2")
    pc3 = await _poste(client, "PC-3")
    await _poste(client, "PC-OTHER", domain="AUTRE")

    command = await _deliver(client, db_session, monkeypatch, reader)
    # The names of its own domain, itself included; not another domain's.
    assert command["directory"]["names"] == ["PC-1", "PC-2", "PC-3", "SRV-ADM"]
    # One at a time: nothing more is queued while it is open.
    from app.core import worker

    assert await worker.sync_directory() == 0

    # PC-1 declares the DN read; PC-2 declares another; PC-3 is disabled in
    # AD; SRV-ADM is not in the reading; an object not asked is dropped.
    await _heartbeat(
        client,
        pc1["token"],
        inventory={
            "hash": "a",
            "directory": {"distinguished_name": f"CN=PC-1,{OU_DN}"},
        },
    )
    await _heartbeat(
        client,
        pc2["token"],
        inventory={
            "hash": "b",
            "directory": {"distinguished_name": "CN=PC-2,OU=Profs,DC=lycee,DC=local"},
        },
    )
    resp = await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading(
            [
                _obj("PC-1"),
                _obj("PC-2"),
                _obj("PC-3", disabled=True),
                _obj("PC-NOT-ASKED"),
                {"object_guid": "nope", "sam_account_name": "x$"},
            ]
        ),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["verified"], body["mismatch"], body["stale"], body["unknown"]) == (
        1,
        1,
        1,
        1,
    )
    m1, m2, m3 = [await _machine(db_session, p) for p in (pc1, pc2, pc3)]
    assert m1.directory_status == "verified"
    assert m1.dir_ou == "Salle B12" and m1.directory_domain_sid == SID
    assert m2.directory_status == "mismatch"
    assert m3.directory_status == "stale"

    from app.features.directory.models import DirectoryRecord

    sams = sorted(
        (await db_session.exec(select(DirectoryRecord.sam_account_name))).all()
    )
    assert sams == ["PC-1$", "PC-2$", "PC-3$"]

    # The list filters on it, the state page counts it.
    resp = await client.get(
        "/api/v1/machines", headers=admin, params={"directory_status": "mismatch"}
    )
    assert [m["hostname"] for m in resp.json()["items"]] == ["PC-2"]
    state = (await client.get("/api/v1/directory", headers=admin)).json()
    assert state["domains"][0]["netbios_name"] == "LYCEE"
    assert state["domains"][0]["last_reader"] == "SRV-ADM"
    assert state["status_counts"]["verified"] == 1

    # The agent moves back in line on its next report: verified again.
    await _heartbeat(
        client,
        pc2["token"],
        inventory={
            "hash": "c",
            "directory": {"distinguished_name": f"CN=PC-2,{OU_DN}"},
        },
    )
    assert (await _machine(db_session, pc2)).directory_status == "verified"


async def test_what_a_reader_may_not_answer(client, db_session, monkeypatch, relay):
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    other = await _poste(client, "PC-1")
    command = await _deliver(client, db_session, monkeypatch, reader)

    def post(token, payload, cmd=command["id"]):
        return client.post(
            f"/api/v1/agent/directory/{cmd}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

    # Another domain than its own.
    resp = await post(reader["token"], _reading([_obj("PC-1")], netbios="AUTRE"))
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "directory.other_domain"
    # A poste that is no reader, with the reader's command.
    resp = await post(other["token"], _reading([_obj("PC-1")]))
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "directory.not_reader"
    # A command that is not one.
    resp = await post(reader["token"], _reading([]), cmd=str(uuid.uuid4()))
    assert resp.status_code == 409
    # Not a domain SID.
    resp = await post(reader["token"], _reading([], sid="S-1-5-32-544"))
    assert resp.status_code == 422

    # The console cannot queue one.
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={"type": "directory_read", "machine_ids": [other["machine_id"]]},
    )
    assert resp.status_code == 422


async def test_the_reading_files_the_rooms_with_the_domain_in_the_key(
    client, db_session, monkeypatch, relay
):
    from app.features.room.models import Room

    monkeypatch.setattr("app.core.config.settings.ROOM_SOURCE", "ad_ou")
    admin = await _admin_headers(client, db_session)
    # A room filed by the agents' word before the directory was read.
    legacy = Room(name="Salle B12", ad_key=OU_DN)
    db_session.add(legacy)
    await db_session.commit()
    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    pc2 = await _poste(client, "PC-2")
    command = await _deliver(client, db_session, monkeypatch, reader)
    resp = await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading([_obj("PC-1"), _obj("PC-2")]),
    )
    assert resp.json()["moved"] == 2
    await db_session.refresh(legacy)
    assert legacy.ad_key == f"{SID}|{OU_DN}"
    for p in (pc1, pc2):
        assert (await _machine(db_session, p)).room_id == legacy.id

    # A poste whose agent claims another OU stays where the reading files it.
    await _heartbeat(
        client,
        pc1["token"],
        inventory={
            "hash": "x",
            "directory": {
                "distinguished_name": "CN=PC-1,OU=Salle C1,DC=lycee,DC=local",
                "ou": "Salle C1",
                "ou_dn": "OU=Salle C1,DC=lycee,DC=local",
            },
        },
    )
    m1 = await _machine(db_session, pc1)
    assert m1.room_id == legacy.id and m1.directory_status == "mismatch"
    assert (
        await db_session.exec(select(Room).where(Room.name == "Salle C1"))
    ).first() is None


async def test_many_moves_wait_for_a_confirmation(
    client, db_session, monkeypatch, relay
):
    monkeypatch.setattr("app.core.config.settings.ROOM_SOURCE", "ad_ou")
    monkeypatch.setattr("app.core.config.settings.DIRECTORY_CONFIRM_MOVES", 1)
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    pcs = [await _poste(client, f"PC-{i}") for i in range(3)]
    command = await _deliver(client, db_session, monkeypatch, reader)
    resp = await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading([_obj(f"PC-{i}") for i in range(3)]),
    )
    assert resp.json()["held"] == 3 and resp.json()["moved"] == 0
    assert [(await _machine(db_session, p)).room_id for p in pcs] == [None] * 3
    state = (await client.get("/api/v1/directory", headers=admin)).json()
    domain = state["domains"][0]
    assert domain["pending_count"] == 3
    assert {m["to_room"] for m in domain["pending_moves"]} == {"Salle B12"}

    # A heartbeat carrying the poste's directory block does not apply a move
    # that waits for the confirmation.
    await _heartbeat(
        client,
        pcs[0]["token"],
        inventory={
            "hash": "h",
            "directory": {"distinguished_name": f"CN=PC-0,{OU_DN}"},
        },
    )
    assert (await _machine(db_session, pcs[0])).room_id is None

    resp = await client.post(f"/api/v1/directory/domains/{SID}/discard", headers=admin)
    assert resp.status_code == 204
    resp = await client.post(f"/api/v1/directory/domains/{SID}/confirm", headers=admin)
    assert resp.status_code == 409

    # Held again by a new reading, then confirmed.
    from app.features.directory import crud
    from app.features.directory.models import DirectoryDomain

    domain_row = await db_session.get(DirectoryDomain, SID)
    await crud.reconcile(db_session, domain_row, datetime.now(UTC))
    await db_session.commit()
    resp = await client.post(f"/api/v1/directory/domains/{SID}/confirm", headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved"] == 3
    assert None not in [(await _machine(db_session, p)).room_id for p in pcs]


async def test_two_readers_that_disagree_move_nothing(
    client, db_session, monkeypatch, relay
):
    from app.features.directory import crud
    from app.features.directory.models import DirectoryDomain, DirectoryRecord

    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    command = await _deliver(client, db_session, monkeypatch, reader)
    guid = str(uuid.uuid4())
    await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading([_obj("PC-1", guid=guid)]),
    )
    assert (await _machine(db_session, pc1)).directory_status == "verified"

    # A second reader read the same object elsewhere.
    db_session.add(
        DirectoryRecord(
            object_guid=guid,
            domain_sid=SID,
            sam_account_name="PC-1$",
            distinguished_name="CN=PC-1,OU=Ailleurs,DC=lycee,DC=local",
            source="relay:other",
        )
    )
    await db_session.commit()
    domain = await db_session.get(DirectoryDomain, SID)
    result = await crud.reconcile(db_session, domain, datetime.now(UTC))
    await db_session.commit()
    assert result.disagreement
    m1 = await _machine(db_session, pc1)
    assert m1.dir_ou == "Salle B12"
    state = (await client.get("/api/v1/directory", headers=admin)).json()
    assert state["domains"][0]["disagreement"][0]["sam"] == "PC-1$"


async def test_a_name_claimed_twice_is_attributed_to_neither(
    client, db_session, monkeypatch, relay
):
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    a = await _poste(client, "PC-1")
    b = await _poste(client, "PC-1")
    command = await _deliver(client, db_session, monkeypatch, reader)
    await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading([_obj("PC-1")]),
    )
    for p in (a, b):
        m = await _machine(db_session, p)
        assert m.directory_status == "unknown"
        assert m.directory_object_guid is None
        assert m.needs_verification


async def test_a_designation_falls_with_the_token_and_a_domain_goes_stale(
    client, db_session, monkeypatch, relay
):
    from app.core import worker
    from app.features.directory import crud
    from app.features.directory.models import DirectoryDomain

    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    command = await _deliver(client, db_session, monkeypatch, reader)
    await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading([_obj("PC-1")]),
    )
    resp = await client.post(
        f"/api/v1/machines/{reader['machine_id']}/revoke-token", headers=admin
    )
    assert resp.status_code in (200, 204), resp.text
    await worker.sync_directory()
    assert not (await _machine(db_session, reader)).directory_reader

    # Not read for longer than DIRECTORY_STALE_HOURS: verifies nothing.
    domain = await db_session.get(DirectoryDomain, SID)
    domain.last_read_at = datetime.now(UTC) - timedelta(hours=100)
    db_session.add(domain)
    await db_session.commit()
    assert await crud.mark_stale(db_session, datetime.now(UTC)) == 1
    await db_session.commit()
    assert (await _machine(db_session, pc1)).directory_status == "stale"


def test_parent_ou_matches_the_agent():
    from app.features.directory.crud import legacy_key, parent_ou, room_key
    from app.features.machine.models import Machine

    assert parent_ou("CN=PC\\, 1,OU=Salle B12,DC=x") == (
        "Salle B12",
        "OU=Salle B12,DC=x",
    )
    assert parent_ou("CN=PC1,CN=Computers,DC=x") == (None, None)
    m = Machine(
        machine_uuid="u",
        directory_domain_sid=SID,
        dir_ou="B",
        dir_ou_dn="OU=B" + "x" * 600,
    )
    key, name = room_key(m, "ad_ou")
    assert key.startswith(f"{SID}|sha256:") and name == "B"
    assert legacy_key(key) is None
    assert legacy_key(f"{SID}|OU=B") == "OU=B"


async def test_a_reading_never_answered_does_not_block_the_next(
    client, db_session, monkeypatch, relay
):
    from app.core import worker
    from app.features.command.models import Command, CommandType

    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    command = await _deliver(client, db_session, monkeypatch, reader)
    # Delivered a minute ago: still open, nothing more is asked.
    assert await worker.sync_directory() == 0
    # Delivered long ago and never answered (the agent was stopped): the
    # reader is asked again at the next interval.
    cmd = await db_session.get(Command, uuid.UUID(command["id"]))
    await db_session.refresh(cmd)
    cmd.created_at = datetime.now(UTC) - timedelta(hours=2)
    cmd.delivered_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.add(cmd)
    await db_session.commit()
    assert await worker.sync_directory() == 1
    rows = await db_session.exec(
        select(Command).where(col(Command.type) == CommandType.DIRECTORY_READ)
    )
    assert len(rows.all()) == 2

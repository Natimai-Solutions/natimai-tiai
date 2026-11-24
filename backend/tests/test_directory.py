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

    seen = {
        "pending_since": domain["pending_since"],
        "pending_count": domain["pending_count"],
    }
    # Not the moves the person was shown: refused.
    resp = await client.post(
        f"/api/v1/directory/domains/{SID}/confirm",
        headers=admin,
        json={**seen, "pending_count": 2},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "directory.pending_changed"
    resp = await client.post(
        f"/api/v1/directory/domains/{SID}/discard", headers=admin, json=seen
    )
    assert resp.status_code == 204
    resp = await client.post(
        f"/api/v1/directory/domains/{SID}/confirm", headers=admin, json=seen
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "directory.nothing_pending"

    # Held again by a new reading, then confirmed.
    from app.features.directory import crud
    from app.features.directory.models import DirectoryDomain

    domain_row = await db_session.get(DirectoryDomain, SID)
    await crud.reconcile(db_session, domain_row, datetime.now(UTC))
    await db_session.commit()
    domain = (await client.get("/api/v1/directory", headers=admin)).json()["domains"][0]
    resp = await client.post(
        f"/api/v1/directory/domains/{SID}/confirm",
        headers=admin,
        json={
            "pending_since": domain["pending_since"],
            "pending_count": domain["pending_count"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved"] == 3
    assert None not in [(await _machine(db_session, p)).room_id for p in pcs]


async def _second_reader(client, db_session, admin, host="SRV-2"):
    reader = await _poste(client, host)
    resp = await client.post(
        f"/api/v1/directory/readers/{reader['machine_id']}", headers=admin
    )
    assert resp.status_code == 200, resp.text
    return reader


async def _read(client, db_session, monkeypatch, reader, objects, **reading):
    """Have ``reader`` pick up its pending reading and answer it."""
    from app.core import worker

    monkeypatch.setattr(worker, "engine", db_session.bind)
    await worker.sync_directory()
    resp = await _heartbeat(client, reader["token"])
    [command] = [c for c in resp.json()["commands"] if c["type"] == "directory_read"]
    return await client.post(
        f"/api/v1/agent/directory/{command['id']}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading(objects, **reading),
    )


async def test_two_readers_that_disagree_move_nothing(
    client, db_session, monkeypatch, relay
):
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    guid = str(uuid.uuid4())
    resp = await _read(
        client,
        db_session,
        monkeypatch,
        reader,
        [_obj("PC-1", guid=guid), _obj("SRV-ADM")],
    )
    assert resp.status_code == 200, resp.text
    assert (await _machine(db_session, pc1)).directory_status == "verified"

    # A second reader reads the same object elsewhere: nothing moves.
    second = await _second_reader(client, db_session, admin)
    elsewhere = "CN=PC-1,OU=Ailleurs,DC=lycee,DC=local"
    resp = await _read(
        client,
        db_session,
        monkeypatch,
        second,
        [_obj("PC-1", guid=guid, dn=elsewhere), _obj("SRV-ADM"), _obj("SRV-2")],
    )
    assert resp.json()["disagreement"] is True
    assert (await _machine(db_session, pc1)).dir_ou == "Salle B12"
    state = (await client.get("/api/v1/directory", headers=admin)).json()
    names = {o["sam"] for o in state["domains"][0]["disagreement"]}
    assert "PC-1$" in names

    # The same name under another GUID is a disagreement too: a reader
    # cannot slip its own object past the comparison.
    from app.features.directory import crud
    from app.features.directory.models import DirectoryRecord

    a = DirectoryRecord(
        object_guid="a", domain_sid=SID, sam_account_name="X$", source="s1"
    )
    b = DirectoryRecord(
        object_guid="b", domain_sid=SID, sam_account_name="X$", source="s2"
    )
    assert crud._disagreements({"s1": [a], "s2": [b]}) == [{"sam": "X$"}]
    # And an object one reader did not find.
    assert crud._disagreements({"s1": [a], "s2": []}) == [{"sam": "X$"}]
    assert crud._disagreements({"s1": [a]}) == []

    # The reader in doubt is withdrawn: what it read goes with it, and the
    # other's reading stands again at once.
    resp = await client.delete(
        f"/api/v1/directory/readers/{second['machine_id']}", headers=admin
    )
    assert resp.status_code == 204
    from sqlmodel import func

    left = await db_session.scalar(
        select(func.count())
        .select_from(DirectoryRecord)
        .where(DirectoryRecord.source == f"relay:{second['machine_id']}")
    )
    assert left == 0


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
        assert m.directory_status == "contested"
        assert m.directory_object_guid is None
        # Flagged for a decision, not knocked out of everything else: a
        # forged poste bearing a name must not disable the real one.
        assert not m.needs_verification
    resp = await client.get(
        "/api/v1/machines", headers=admin, params={"directory_status": "contested"}
    )
    assert len(resp.json()["items"]) == 2


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


# --- Relecture : ce qui borne un lecteur ---------------------------------------


async def test_a_forged_poste_cannot_knock_a_reader_out(
    client, db_session, monkeypatch, relay
):
    """A poste taking the reader's name before its first reading: the name
    is contested, the reader stays designated and keeps reading."""
    from app.core import worker

    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    await _poste(client, "SRV-ADM")  # the forged twin
    resp = await _read(client, db_session, monkeypatch, reader, [_obj("SRV-ADM")])
    assert resp.status_code == 200, resp.text
    await worker.sync_directory()
    m = await _machine(db_session, reader)
    assert m.directory_reader and not m.needs_verification
    assert m.directory_status == "contested"


async def test_a_revoked_duplicate_claims_nothing(
    client, db_session, monkeypatch, relay
):
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    old = await _poste(client, "PC-1")
    resp = await client.post(
        f"/api/v1/machines/{old['machine_id']}/revoke-token", headers=admin
    )
    assert resp.status_code in (200, 204)
    new = await _poste(client, "PC-1")
    await _read(client, db_session, monkeypatch, reader, [_obj("PC-1")])
    assert (await _machine(db_session, new)).directory_status == "verified"
    assert (await _machine(db_session, old)).directory_status != "verified"


async def test_a_reader_answers_once_for_its_domain_and_its_sid(
    client, db_session, monkeypatch, relay
):
    from app.core import worker

    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    await _poste(client, "PC-1")
    command = await _deliver(client, db_session, monkeypatch, reader)

    def post(payload):
        return client.post(
            f"/api/v1/agent/directory/{command['id']}",
            headers={"Authorization": f"Bearer {reader['token']}"},
            json=payload,
        )

    assert (await post(_reading([_obj("PC-1")]))).status_code == 200
    # The same command a second time: refused — or DIRECTORY_CONFIRM_MOVES
    # would be passed a few postes at a time.
    resp = await post(_reading([_obj("PC-1")]))
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "directory.command"

    # Later, with another SID than the one it first read: refused.
    other_sid = "S-1-5-21-9-9-9"
    monkeypatch.setattr("app.core.config.settings.DIRECTORY_SYNC_MINUTES", 5)

    async def next_command():
        from app.features.command.models import Command, CommandStatus, CommandType

        rows = await db_session.exec(
            select(Command).where(col(Command.type) == CommandType.DIRECTORY_READ)
        )
        for c in rows.all():
            c.status = CommandStatus.SUCCEEDED
            c.created_at = datetime.now(UTC) - timedelta(hours=2)
            db_session.add(c)
        await db_session.commit()
        await worker.sync_directory()
        resp = await _heartbeat(client, reader["token"])
        [c] = [c for c in resp.json()["commands"] if c["type"] == "directory_read"]
        return c["id"]

    cid = await next_command()
    resp = await client.post(
        f"/api/v1/agent/directory/{cid}",
        headers={"Authorization": f"Bearer {reader['token']}"},
        json=_reading([_obj("PC-1")], sid=other_sid),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "directory.other_sid"

    # It starts declaring another domain: no longer the reader designated.
    await _heartbeat(client, reader["token"], domain="AUTRE")
    await worker.sync_directory()
    assert not (await _machine(db_session, reader)).directory_reader


async def test_a_netbios_name_names_one_domain(client, db_session, monkeypatch, relay):
    """A second reader inventing another SID for a name already read does
    not create a twin domain that would unsettle the first's postes."""
    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    await _read(
        client, db_session, monkeypatch, reader, [_obj("PC-1"), _obj("SRV-ADM")]
    )
    second = await _second_reader(client, db_session, admin)
    resp = await _read(
        client, db_session, monkeypatch, second, [_obj("PC-1")], sid="S-1-5-21-7-7-7"
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["reason"] == "directory.name_taken"
    assert (await _machine(db_session, pc1)).directory_status == "verified"

    # Rebuilt under a new SID for good: an administrator forgets the old one.
    resp = await client.delete(f"/api/v1/directory/domains/{SID}", headers=admin)
    assert resp.status_code == 204
    m = await _machine(db_session, pc1)
    assert m.directory_status is None and m.directory_object_guid is None


async def test_a_reading_does_not_take_over_a_room_made_by_hand(
    client, db_session, monkeypatch, relay
):
    from app.features.room.models import Room

    monkeypatch.setattr("app.core.config.settings.ROOM_SOURCE", "ad_ou")
    admin = await _admin_headers(client, db_session)
    by_hand = Room(name="Salle B12")
    # Another domain's room filed under the same DN, with its own postes.
    theirs = Room(name="Autre", ad_key="OU=Profs,DC=lycee,DC=local")
    db_session.add(by_hand)
    db_session.add(theirs)
    await db_session.commit()
    await db_session.refresh(theirs)
    theirs_id = theirs.id
    other = await _poste(client, "PC-X", domain="AUTRE")
    from app.features.machine.models import Machine

    row = await db_session.get(Machine, uuid.UUID(other["machine_id"]))
    row.room_id = theirs_id
    db_session.add(row)
    await db_session.commit()

    reader = await _reader_with_command(client, db_session, admin)
    pc1 = await _poste(client, "PC-1")
    pc2 = await _poste(client, "PC-2")
    resp = await _read(
        client,
        db_session,
        monkeypatch,
        reader,
        [
            _obj("PC-1"),
            _obj("PC-2", dn="CN=PC-2,OU=Profs,DC=lycee,DC=local"),
            _obj("SRV-ADM", dn="CN=SRV-ADM,OU=Serveurs,DC=lycee,DC=local"),
        ],
    )
    body = resp.json()
    # PC-1 names the room made by hand: undecided, not adopted, not counted
    # as moved. PC-2 names an OU whose legacy room holds another domain's
    # poste: a room of its own. SRV-ADM gets a new room.
    assert body["undecided"] == 1 and body["moved"] == 2
    await db_session.refresh(by_hand)
    await db_session.refresh(theirs)
    assert by_hand.ad_key is None
    assert theirs.ad_key == "OU=Profs,DC=lycee,DC=local"
    assert (await _machine(db_session, pc1)).room_id is None
    assert (await _machine(db_session, pc2)).room_id not in (None, theirs_id)


async def test_the_directory_is_not_a_confined_accounts(
    client, db_session, monkeypatch, relay
):
    from app.features.user.scope import Scope
    from tests.scope_helpers import ALL_PERMISSIONS, account, group

    g = await group(
        db_session, "Site A", ALL_PERMISSIONS, Scope(locations=frozenset({"Site A"}))
    )
    confined = await account(client, db_session, "conf@test.local", [g.id])
    poste = await _poste(client, "PC-1", location="Site A")
    resp = await client.post(
        f"/api/v1/directory/readers/{poste['machine_id']}", headers=confined
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/directory/domains/{SID}/confirm",
        headers=confined,
        json={"pending_since": datetime.now(UTC).isoformat(), "pending_count": 1},
    )
    assert resp.status_code == 403
    state = (await client.get("/api/v1/directory", headers=confined)).json()
    assert state["restricted"] is True and state["domains"] == []


async def test_reenrolment_forgets_the_match(client, db_session, monkeypatch, relay):
    from app.features.machine.models import Machine

    admin = await _admin_headers(client, db_session)
    reader = await _reader_with_command(client, db_session, admin)
    machine_uuid = str(uuid.uuid4())
    pc1 = await _enroll(client, machine_uuid, hostname="PC-1", domain="LYCEE")
    await _read(
        client, db_session, monkeypatch, reader, [_obj("PC-1"), _obj("SRV-ADM")]
    )
    assert (await _machine(db_session, pc1)).directory_status == "verified"
    resp = await client.post(
        f"/api/v1/machines/{pc1['machine_id']}/allow-reenroll", headers=admin
    )
    assert resp.status_code in (200, 204), resp.text
    await _enroll(client, machine_uuid, hostname="PC-1", domain="LYCEE")
    m = await db_session.get(Machine, uuid.UUID(pc1["machine_id"]))
    await db_session.refresh(m)
    assert m.directory_status is None and m.directory_object_guid is None

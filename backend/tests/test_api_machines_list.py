"""Machine list pagination/sorting and duplicate detection (need a database).

Both features exist because of the same class of bug: a console that quietly
shows part of the truth. The list used to serve the server's default page and
sort it client-side, so a parc of 340 postes read as 50; the duplicate search
used to match on a raw SMBIOS value, so a batch of whiteboxes read as one
machine reported forty times.
"""

from datetime import UTC, datetime, timedelta


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.models import Role

    await crud.create_user(
        db_session, email="admin@list.local", password="pw", role=Role.ADMIN
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "admin@list.local", "password": "pw"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _machines(db_session, specs: list[dict]) -> list[str]:
    """Insert machines from ``specs`` and return their ids, in order.

    Ids and not the instances: a later commit in the same session expires them,
    and reading an expired attribute would lazy-load synchronously inside the
    event loop (MissingGreenlet).
    """
    from app.features.machine.models import Machine

    created = []
    for spec in specs:
        machine = Machine(**spec)
        db_session.add(machine)
        created.append(machine)
    await db_session.commit()
    ids = []
    for machine in created:
        await db_session.refresh(machine)
        ids.append(str(machine.id))
    return ids


# --- pagination -------------------------------------------------------------


async def test_list_reports_the_true_total_not_the_page(client, db_session):
    """``total`` is what tells the console there is more than it is showing."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": f"page-{i:02d}", "last_seen": now - timedelta(minutes=i)}
            for i in range(12)
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines?page=1&page_size=5", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 5
    assert body["total"] == 12
    assert body["page"] == 1
    assert body["page_size"] == 5


async def test_pages_partition_the_fleet_without_gaps_or_repeats(client, db_session):
    """Rows sharing a sort key must not drift between pages.

    Twelve postes with the *same* ``last_seen`` is the pathological case: with
    no tiebreaker, PostgreSQL is free to order them differently for each page,
    and a row would appear twice while another is never shown at all.
    """
    stamp = datetime.now(UTC)
    await _machines(
        db_session,
        [{"machine_uuid": f"tie-{i:02d}", "last_seen": stamp} for i in range(12)],
    )
    headers = await _admin_headers(client, db_session)

    seen: list[str] = []
    for page in (1, 2, 3):
        resp = await client.get(
            f"/api/v1/machines?page={page}&page_size=5", headers=headers
        )
        seen += [m["machine_uuid"] for m in resp.json()["items"]]

    assert len(seen) == 12
    assert len(set(seen)) == 12


async def test_sorting_happens_on_the_server(client, db_session):
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "s-1", "hostname": "charlie", "last_seen": now},
            {"machine_uuid": "s-2", "hostname": "alpha", "last_seen": now},
            {"machine_uuid": "s-3", "hostname": "bravo", "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        "/api/v1/machines?sort_by=hostname&sort_desc=false", headers=headers
    )
    assert [m["hostname"] for m in resp.json()["items"]] == [
        "alpha",
        "bravo",
        "charlie",
    ]

    resp = await client.get(
        "/api/v1/machines?sort_by=hostname&sort_desc=true", headers=headers
    )
    assert [m["hostname"] for m in resp.json()["items"]] == [
        "charlie",
        "bravo",
        "alpha",
    ]


async def test_hostname_sort_ignores_case(client, db_session):
    """Under a C collation "ZEUS" would otherwise sort before "alpha"."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "c-1", "hostname": "ZEUS", "last_seen": now},
            {"machine_uuid": "c-2", "hostname": "alpha", "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        "/api/v1/machines?sort_by=hostname&sort_desc=false", headers=headers
    )
    assert [m["hostname"] for m in resp.json()["items"]] == ["alpha", "ZEUS"]


async def test_never_reported_sorts_last_in_both_directions(client, db_session):
    """A NULL count is an absence, not a value, and must not lead the list."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "n-1", "wu_pending_count": 5, "last_seen": now},
            {"machine_uuid": "n-2", "wu_pending_count": None, "last_seen": now},
            {"machine_uuid": "n-3", "wu_pending_count": 0, "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    for descending in ("true", "false"):
        resp = await client.get(
            f"/api/v1/machines?sort_by=wu_pending_count&sort_desc={descending}",
            headers=headers,
        )
        counts = [m["wu_pending_count"] for m in resp.json()["items"]]
        assert counts[-1] is None, counts


async def test_an_unknown_sort_column_is_refused(client, db_session):
    """The sort is a whitelist, never an ORDER BY built from a request."""
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines?sort_by=hashed_password", headers=headers)

    assert resp.status_code == 422


async def test_filters_still_apply_across_pages(client, db_session):
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": f"dom-{i}", "domain": "CORP", "last_seen": now}
            for i in range(4)
        ]
        + [{"machine_uuid": "other", "domain": "LAB", "last_seen": now}],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        "/api/v1/machines?domain=CORP&page=1&page_size=2", headers=headers
    )

    body = resp.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2


# --- duplicates -------------------------------------------------------------


async def test_a_shared_firmware_constant_is_not_a_duplicate(client, db_session):
    """The false positive that could have deleted a real machine.

    Whitebox motherboards ship the same SMBIOS UUID on every unit. Matching on
    it raw made each of them a merge candidate for all the others — and a merge
    deletes the source row.
    """
    constant = "03000200-0400-0500-0006-000700080009"
    machine_ids = await _machines(
        db_session,
        [
            {"machine_uuid": "white-1", "hostname": "PC-1", "smbios_uuid": constant},
            {"machine_uuid": "white-2", "hostname": "PC-2", "smbios_uuid": constant},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    assert resp.status_code == 200
    assert resp.json() == []


async def test_a_shared_real_anchor_is_a_duplicate(client, db_session):
    machine_ids = await _machines(
        db_session,
        [
            {
                "machine_uuid": "anchor-old",
                "hostname": "PC-9",
                "smbios_uuid": "4c4c4544-real",
            },
            {
                "machine_uuid": "4c4c4544-real",
                "hostname": "PC-9",
                "smbios_uuid": "4c4c4544-real",
            },
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[1]}/duplicates", headers=headers
    )

    body = resp.json()
    assert [c["machine_uuid"] for c in body] == ["anchor-old"]
    assert body[0]["match_reason"] == "smbios_uuid"
    # The two fields that let a reader tell the records apart on screen.
    assert body[0]["first_seen"]
    assert body[0]["machine_uuid"] != "4c4c4544-real"


async def test_the_tpm_anchors_a_poste_with_no_usable_smbios(client, db_session):
    machine_ids = await _machines(
        db_session,
        [
            {"machine_uuid": "tpm-a", "hostname": "PC-T", "tpm_ek_hash": "ek-123"},
            {"machine_uuid": "tpm-b", "hostname": "PC-T", "tpm_ek_hash": "ek-123"},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    body = resp.json()
    assert [c["machine_uuid"] for c in body] == ["tpm-b"]
    assert body[0]["match_reason"] == "tpm_ek_hash"


async def test_a_drifted_anchor_finds_a_record_that_never_had_one(client, db_session):
    """The common shape of the "empreinte divergente" case.

    The record being retired usually predates fingerprinting, so it carries no
    anchor at all — nothing contradicts the name, and the pair is offered.
    """
    machine_ids = await _machines(
        db_session,
        [
            {
                "machine_uuid": "drift-a",
                "hostname": "PC-42",
                "smbios_uuid": "anchor-new",
            },
            {"machine_uuid": "drift-b", "hostname": "PC-42"},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    body = resp.json()
    assert [c["machine_uuid"] for c in body] == ["drift-b"]
    # Reported as the weak signal it is: a replaced poste can inherit a name.
    assert body[0]["match_reason"] == "hostname"


async def test_two_real_anchors_that_differ_are_never_offered_automatically(
    client, db_session
):
    """The deliberate limit of automatic detection, and why it is the safe one.

    Two records with the same name and two *different* real anchors are either
    one box whose anchor drifted, or two boxes sharing a name — and no query can
    tell those apart. Offering them would mean offering to delete a live poste
    over a naming coincidence, so the automatic list stays silent and the merge
    dialog's manual search is where an administrator resolves a genuine drift,
    deliberately and with both UUIDs in front of them.
    """
    machine_ids = await _machines(
        db_session,
        [
            {
                "machine_uuid": "both-a",
                "hostname": "PC-42",
                "smbios_uuid": "anchor-new",
            },
            {
                "machine_uuid": "both-b",
                "hostname": "PC-42",
                "smbios_uuid": "anchor-old",
            },
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    assert resp.json() == []


async def test_hardware_evidence_is_listed_before_a_name_match(client, db_session):
    machine_ids = await _machines(
        db_session,
        [
            {
                "machine_uuid": "rank-self",
                "hostname": "PC-R",
                "smbios_uuid": "anchor-r",
            },
            {"machine_uuid": "rank-name", "hostname": "PC-R"},
            {
                "machine_uuid": "rank-anchor",
                "hostname": "OTHER",
                "smbios_uuid": "anchor-r",
            },
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    assert [c["match_reason"] for c in resp.json()] == ["smbios_uuid", "hostname"]


async def test_a_poste_is_never_its_own_duplicate(client, db_session):
    machine_ids = await _machines(
        db_session,
        [{"machine_uuid": "alone", "hostname": "PC-ALONE", "smbios_uuid": "anchor-1"}],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    assert resp.json() == []


async def test_merging_a_poste_into_itself_is_refused(client, db_session):
    machine_ids = await _machines(db_session, [{"machine_uuid": "self-merge"}])
    headers = await _admin_headers(client, db_session)

    resp = await client.post(
        f"/api/v1/machines/{machine_ids[0]}/merge",
        headers=headers,
        json={"source_id": machine_ids[0]},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "machine.merge.self"


async def test_merge_keeps_the_path_machine_and_moves_the_history(client, db_session):
    import uuid as uuid_module

    from sqlmodel import select

    from app.features.machine.models import Machine
    from app.features.threat.models import Threat

    kept, removed = await _machines(
        db_session,
        [
            {"machine_uuid": "keep-me", "hostname": "PC-K"},
            {"machine_uuid": "remove-me", "hostname": "PC-K"},
        ],
    )
    db_session.add(
        Threat(
            machine_id=uuid_module.UUID(removed),
            detection_id="moved-1",
            status="active",
        )
    )
    await db_session.commit()

    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        f"/api/v1/machines/{kept}/merge",
        headers=headers,
        json={"source_id": removed},
    )

    assert resp.status_code == 200
    assert resp.json()["machine_uuid"] == "keep-me"

    threat = (
        await db_session.exec(select(Threat).where(Threat.detection_id == "moved-1"))
    ).one()
    assert str(threat.machine_id) == kept
    assert await db_session.get(Machine, uuid_module.UUID(removed)) is None


async def test_merging_is_refused_to_a_read_only_operator(client, db_session):
    from app.features.user import crud
    from app.features.user.models import Role

    kept, removed = await _machines(
        db_session,
        [{"machine_uuid": "ro-keep"}, {"machine_uuid": "ro-remove"}],
    )
    await crud.create_user(
        db_session, email="ro@list.local", password="pw", role=Role.READONLY
    )
    login = await client.post(
        "/api/v1/auth/login", data={"username": "ro@list.local", "password": "pw"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/machines/{kept}/merge",
        headers=headers,
        json={"source_id": removed},
    )

    assert resp.status_code == 403


async def test_a_shared_name_with_different_hardware_is_not_a_duplicate(
    client, db_session
):
    """Freshly imaged postes answer to the image's name until they are renamed.

    Each carries its own real SMBIOS UUID, so the hardware settles it: same
    name, different machines. Offering them would be offering to delete a live
    poste over a naming coincidence.
    """
    machine_ids = await _machines(
        db_session,
        [
            {
                "machine_uuid": "img-1",
                "hostname": "WIN-IMAGE",
                "smbios_uuid": "4c4c4544-aaaa",
            },
            {
                "machine_uuid": "img-2",
                "hostname": "WIN-IMAGE",
                "smbios_uuid": "4c4c4544-bbbb",
            },
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    assert resp.json() == []


async def test_a_shared_name_with_different_tpms_is_not_a_duplicate(client, db_session):
    machine_ids = await _machines(
        db_session,
        [
            {"machine_uuid": "tpm-x", "hostname": "PC-SAME", "tpm_ek_hash": "ek-aaa"},
            {"machine_uuid": "tpm-y", "hostname": "PC-SAME", "tpm_ek_hash": "ek-bbb"},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    assert resp.json() == []


async def test_a_shared_name_still_matches_when_hardware_is_silent(client, db_session):
    """A missing anchor is a missing reading, never evidence of difference."""
    machine_ids = await _machines(
        db_session,
        [
            {"machine_uuid": "quiet-1", "hostname": "PC-QUIET"},
            {"machine_uuid": "quiet-2", "hostname": "PC-QUIET"},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        f"/api/v1/machines/{machine_ids[0]}/duplicates", headers=headers
    )

    body = resp.json()
    assert [c["machine_uuid"] for c in body] == ["quiet-2"]
    assert body[0]["match_reason"] == "hostname"


async def test_threat_history_pages_do_not_overlap(client, db_session):
    """Defender stamps a whole scan with one instant — the tie case.

    Without a tiebreaker behind ``detected_at`` these rows may be ordered
    differently for each OFFSET, showing a detection on two pages while another
    is unreachable.
    """
    from app.features.machine.models import Machine
    from app.features.threat.models import Threat

    machine = Machine(machine_uuid="threat-pages")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    machine_id = machine.id

    stamp = datetime.now(UTC)
    for i in range(12):
        db_session.add(
            Threat(
                machine_id=machine_id,
                detection_id=f"TIE-{i:02d}",
                status="active",
                detected_at=stamp,
            )
        )
    await db_session.commit()

    headers = await _admin_headers(client, db_session)
    seen: list[str] = []
    for page in (1, 2, 3):
        resp = await client.get(
            f"/api/v1/threats?machine_id={machine_id}&page={page}&page_size=5",
            headers=headers,
        )
        seen += [t["detection_id"] for t in resp.json()["items"]]

    assert len(seen) == 12
    assert len(set(seen)) == 12


async def test_undated_detections_do_not_lead_the_history(client, db_session):
    """DESC defaults to NULLS FIRST, which would open with the undated rows."""
    from app.features.machine.models import Machine
    from app.features.threat.models import Threat

    machine = Machine(machine_uuid="threat-nulls")
    db_session.add(machine)
    await db_session.commit()
    await db_session.refresh(machine)
    machine_id = machine.id

    db_session.add(
        Threat(machine_id=machine_id, detection_id="UNDATED", status="active")
    )
    db_session.add(
        Threat(
            machine_id=machine_id,
            detection_id="DATED",
            status="active",
            detected_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    headers = await _admin_headers(client, db_session)
    resp = await client.get(f"/api/v1/threats?machine_id={machine_id}", headers=headers)

    assert [t["detection_id"] for t in resp.json()["items"]] == ["DATED", "UNDATED"]

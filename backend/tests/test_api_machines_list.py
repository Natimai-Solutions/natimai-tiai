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


async def test_online_filter_splits_the_fleet_on_the_heartbeat_window(
    client, db_session
):
    """`online=true` keeps the postes whose agent is phoning home right now.

    Same window as the per-row `is_online` dot (OFFLINE_AFTER_SECONDS, 180 by
    default): the list a filter shows must be exactly the rows whose dot is
    green. `online=false` selects the complement — the postes a wake targets.
    """
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "on-1", "last_seen": now - timedelta(seconds=30)},
            {"machine_uuid": "on-2", "last_seen": now - timedelta(seconds=170)},
            {"machine_uuid": "off-1", "last_seen": now - timedelta(seconds=600)},
            {"machine_uuid": "off-2", "last_seen": now - timedelta(days=40)},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines?online=true", headers=headers)
    body = resp.json()
    assert body["total"] == 2
    assert {m["machine_uuid"] for m in body["items"]} == {"on-1", "on-2"}
    assert all(m["is_online"] for m in body["items"])

    resp = await client.get("/api/v1/machines?online=false", headers=headers)
    body = resp.json()
    assert body["total"] == 2
    assert {m["machine_uuid"] for m in body["items"]} == {"off-1", "off-2"}


async def test_online_filter_combines_with_the_antivirus_status(client, db_session):
    """The everyday question: outdated *and* on, so a scan sent now will land."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "on-late", "last_seen": now, "is_up_to_date": False},
            {"machine_uuid": "on-ok", "last_seen": now, "is_up_to_date": True},
            {
                "machine_uuid": "off-late",
                "last_seen": now - timedelta(hours=2),
                "is_up_to_date": False,
            },
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        "/api/v1/machines?online=true&status=outdated", headers=headers
    )

    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["machine_uuid"] == "on-late"


async def test_search_finds_a_poste_by_mac_whatever_the_notation(client, db_session):
    """The MAC on screen comes from a switch or ipconfig, not from this console.

    Stored colon-separated, but an administrator pastes it hyphenated (Windows),
    dotted (Cisco) or bare — every notation must land on the same poste.
    """
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {
                "machine_uuid": "mac-1",
                "hostname": "PC-MAC",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "last_seen": now,
            },
            {"machine_uuid": "mac-2", "hostname": "PC-OTHER", "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    for term in ("aa-bb-cc", "AABB.CC", "aa:bb:cc:dd:ee:ff", "ddeeff"):
        resp = await client.get(f"/api/v1/machines?search={term}", headers=headers)
        assert [m["machine_uuid"] for m in resp.json()["items"]] == ["mac-1"], term


async def test_a_hostname_search_still_matches_hostnames_not_macs(client, db_session):
    """ "PC-01" is not hex once stripped: the MAC leg must not swallow it."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "host-1", "hostname": "PC-01", "last_seen": now},
            {
                "machine_uuid": "host-2",
                "hostname": "SRV-9",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "last_seen": now,
            },
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines?search=PC-01", headers=headers)

    assert [m["machine_uuid"] for m in resp.json()["items"]] == ["host-1"]


async def test_os_filter_gathers_every_build_of_a_version(client, db_session):
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "os-1", "os_version": "Windows 11 23H2", "last_seen": now},
            {"machine_uuid": "os-2", "os_version": "Windows 11 24H2", "last_seen": now},
            {"machine_uuid": "os-3", "os_version": "Windows 10 22H2", "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines?os_version=Windows 11", headers=headers)

    body = resp.json()
    assert body["total"] == 2
    assert {m["machine_uuid"] for m in body["items"]} == {"os-1", "os-2"}


async def test_os_versions_lists_the_fleet_most_widespread_first(client, db_session):
    """The dropdown's data, with the silent postes (NULL/empty) left out."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {
                "machine_uuid": "osv-1",
                "os_version": "Windows 11 23H2",
                "last_seen": now,
            },
            {
                "machine_uuid": "osv-2",
                "os_version": "Windows 11 23H2",
                "last_seen": now,
            },
            {
                "machine_uuid": "osv-3",
                "os_version": "Windows 10 22H2",
                "last_seen": now,
            },
            {"machine_uuid": "osv-4", "os_version": None, "last_seen": now},
            {"machine_uuid": "osv-5", "os_version": "", "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines/os-versions", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == [
        {"name": "Windows 11 23H2", "count": 2},
        {"name": "Windows 10 22H2", "count": 1},
    ]


# --- scan freshness ----------------------------------------------------------


async def _scan_fleet(db_session) -> None:
    """Four postes: freshly scanned, quick-stale, full-stale, never scanned."""
    now = datetime.now(UTC)
    fresh = now - timedelta(days=1)
    stale = now - timedelta(days=10)
    await _machines(
        db_session,
        [
            {
                "machine_uuid": "scan-fresh",
                "last_quick_scan": fresh,
                "last_full_scan": fresh,
                "last_seen": now,
            },
            {
                "machine_uuid": "scan-quick-stale",
                "last_quick_scan": stale,
                "last_full_scan": fresh,
                "last_seen": now,
            },
            {
                "machine_uuid": "scan-full-stale",
                "last_quick_scan": fresh,
                "last_full_scan": stale,
                "last_seen": now,
            },
            {"machine_uuid": "scan-never", "last_seen": now},
        ],
    )


async def test_scan_filter_selects_the_overdue_postes_per_scan_type(client, db_session):
    """Each scan type is its own axis, and "both" is their intersection."""
    await _scan_fleet(db_session)
    headers = await _admin_headers(client, db_session)

    expected = {
        "quick": {"scan-quick-stale", "scan-never"},
        "full": {"scan-full-stale", "scan-never"},
        "both": {"scan-never"},
    }
    for scan_type, uuids in expected.items():
        resp = await client.get(
            f"/api/v1/machines?scan_type={scan_type}", headers=headers
        )
        assert {m["machine_uuid"] for m in resp.json()["items"]} == uuids, scan_type


async def test_a_never_scanned_poste_is_overdue_at_any_cutoff(client, db_session):
    """NULL is further behind than any date — the poste the filter exists for."""
    await _scan_fleet(db_session)
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        "/api/v1/machines?scan_type=quick&scan_older_than_days=30", headers=headers
    )

    # At 30 days the 10-day-old scan is recent enough; only the silent one stays.
    assert {m["machine_uuid"] for m in resp.json()["items"]} == {"scan-never"}


async def test_an_unknown_scan_type_is_refused(client, db_session):
    headers = await _admin_headers(client, db_session)

    resp = await client.get("/api/v1/machines?scan_type=deep", headers=headers)

    assert resp.status_code == 422


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


# --- location ---------------------------------------------------------------


async def test_filter_by_location_is_exact(client, db_session):
    """ "Lycée" must not gather every lycée: the dropdown feeds exact values."""
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "loc-1", "location": "Lycée de Taravao", "last_seen": now},
            {"machine_uuid": "loc-2", "location": "Lycée de Taravao", "last_seen": now},
            {"machine_uuid": "loc-3", "location": "Lycée du Diadème", "last_seen": now},
            {"machine_uuid": "loc-4", "location": None, "last_seen": now},
        ],
    )
    headers = await _admin_headers(client, db_session)

    resp = await client.get(
        "/api/v1/machines?location=Lyc%C3%A9e%20de%20Taravao", headers=headers
    )
    assert resp.status_code == 200
    assert sorted(m["machine_uuid"] for m in resp.json()["items"]) == ["loc-1", "loc-2"]
    assert all(m["location"] == "Lycée de Taravao" for m in resp.json()["items"])

    listing = await client.get("/api/v1/machines/locations", headers=headers)
    assert listing.json() == [
        {"name": "Lycée de Taravao", "count": 2},
        {"name": "Lycée du Diadème", "count": 1},
    ]

    resp = await client.get(
        "/api/v1/machines?sort_by=location&sort_desc=false", headers=headers
    )
    ordered = [m["machine_uuid"] for m in resp.json()["items"]]
    # The two Taravao rows tie on every key but the id, in any order.
    assert sorted(ordered[:2]) == ["loc-1", "loc-2"]
    assert ordered[2:] == ["loc-3", "loc-4"]  # never reported sorts last


async def test_a_command_can_target_a_location(client, db_session):
    now = datetime.now(UTC)
    await _machines(
        db_session,
        [
            {"machine_uuid": "tl-1", "location": "Lycée de Taravao", "last_seen": now},
            {
                "machine_uuid": "tl-2",
                "location": "Collège de Papeete",
                "last_seen": now,
            },
        ],
    )
    headers = await _admin_headers(client, db_session)
    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "quick_scan", "target_location": "Lycée de Taravao"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1

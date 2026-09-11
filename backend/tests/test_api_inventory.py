"""Inventory integration tests (require TIAI_TEST_DATABASE_URL).

Covers the inventory J1: the heartbeat's ``inventory`` block (the machine's
cardinality-one columns, the five hardware sets and the software catalogue),
its replacement semantics, the unchanged-hash short circuit, and what the
console list and detail payloads expose.
"""


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="inv-admin@test.local",
        password="pw",
        groups=[BuiltinGroup.ADMIN],
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "inv-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _enroll(client, machine_uuid: str, **fields) -> dict:
    from app.core.config import settings

    resp = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": machine_uuid, **fields},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _heartbeat(client, token: str, **body):
    return await client.post(
        "/api/v1/agent/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def _detail(client, headers, enrolled) -> dict:
    resp = await client.get(
        f"/api/v1/machines/{enrolled['machine_id']}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _inventory(**overrides) -> dict:
    """A full inventory as the agent reports it."""
    body = {
        "hash": "h1",
        "hw_manufacturer": "Dell Inc.",
        "hw_model": "OptiPlex 7010",
        "hw_serial": "7XK2P03",
        "hw_chassis_type": "desktop",
        "hw_is_virtual": False,
        "mb_manufacturer": "Dell Inc.",
        "mb_model": "0T10XW",
        "mb_serial": "/7XK2P03/",
        "bios_vendor": "Dell Inc.",
        "bios_version": "A29",
        "bios_date": "2024-01-15",
        "secure_boot": True,
        "tpm_version": "2.0",
        "cpu_model": "Intel(R) Core(TM) i7-13700",
        "cpu_manufacturer": "GenuineIntel",
        "cpu_cores": 16,
        "cpu_threads": 24,
        "cpu_speed_mhz": 2100,
        "cpu_count": 1,
        "ram_total_mb": 32768,
        "ram_slots_total": 4,
        "ram_slots_used": 2,
        "os_architecture": "64-bit",
        "os_install_date": "2025-03-04T09:12:00Z",
        "last_boot_time": "2026-08-30T06:02:00Z",
        "memory_modules": [
            {
                "slot": "DIMM A1",
                "capacity_mb": 16384,
                "type": "DDR5",
                "speed_mhz": 4800,
                "manufacturer": "Samsung",
                "serial": "S1",
                "form_factor": "DIMM",
            },
            {"slot": "DIMM B1", "capacity_mb": 16384, "type": "DDR5"},
        ],
        "disks": [
            {
                "device_id": r"\\.\PHYSICALDRIVE0",
                "model": "SAMSUNG MZVL2512",
                "serial": "S64ANS0T",
                "media_type": "SSD",
                "bus_type": "NVMe",
                "size_mb": 488386,
                "health_status": "Healthy",
            }
        ],
        "volumes": [
            {
                "letter": "c:",
                "label": "Windows",
                "filesystem": "NTFS",
                "total_mb": 486000,
                "free_mb": 41000,
                "is_system": True,
                "encryption_status": "FullyEncrypted",
            },
            {"letter": "D:", "filesystem": "NTFS", "total_mb": 1000, "free_mb": 900},
        ],
        "nics": [
            {
                "key": "AA:BB:CC:DD:EE:FF",
                "name": "Intel(R) Ethernet Connection I219-LM",
                "mac": "AA:BB:CC:DD:EE:FF",
                "type": "ethernet",
                "speed_mbps": 1000,
                "is_up": True,
                "ip_address": "10.4.1.20",
                "ip_prefix_length": 16,
                "is_dhcp": True,
                "gateway": "10.4.0.1",
            },
            {"key": "vEthernet", "name": "Hyper-V Virtual Switch", "is_virtual": True},
        ],
        "gpus": [
            {
                "name": "Intel(R) UHD Graphics 770",
                "memory_mb": 1024,
                "driver_version": "31.0.101.5186",
                "driver_date": "2024-05-02",
                "resolution": "1920x1080",
            }
        ],
        "software": [
            {
                "name": "7-Zip 24.09 (x64)",
                "version": "24.09",
                "publisher": "Igor Pavlov",
                "install_date": "2025-06-01",
                "arch": "x64",
                "source": "registry",
            },
            {
                "name": "Mozilla Firefox (x64 fr)",
                "version": "142.0",
                "publisher": "Mozilla",
                "arch": "x64",
                "source": "registry",
            },
        ],
    }
    body.update(overrides)
    return body


# --- Heartbeat: the block lands ---------------------------------------------


async def test_heartbeat_stores_full_inventory(client, db_session):
    """Every section of one report reaches the detail payload."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-full")

    resp = await _heartbeat(client, enrolled["token"], inventory=_inventory())
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert body["hw_manufacturer"] == "Dell Inc."
    assert body["hw_model"] == "OptiPlex 7010"
    assert body["hw_chassis_type"] == "desktop"
    assert body["hw_is_virtual"] is False
    assert body["mb_model"] == "0T10XW"
    assert body["bios_version"] == "A29"
    assert body["bios_date"] == "2024-01-15"
    assert body["secure_boot"] is True
    assert body["tpm_version"] == "2.0"
    assert body["cpu_cores"] == 16
    assert body["cpu_threads"] == 24
    assert body["cpu_count"] == 1
    assert body["ram_total_mb"] == 32768
    assert body["ram_slots_used"] == 2
    assert body["os_architecture"] == "64-bit"
    assert body["inventory_last_seen"] is not None

    assert [m["slot"] for m in body["memory_modules"]] == ["DIMM A1", "DIMM B1"]
    assert body["disks"][0]["media_type"] == "SSD"
    assert body["gpus"][0]["driver_date"] == "2024-05-02"
    # Connected adapters first, whatever order they were reported in.
    assert body["nics"][0]["is_up"] is True
    assert body["nics"][1]["is_virtual"] is True
    # Volume letters are upper-cased server-side: one poste's "c:" and another's
    # "C:" have to be the same volume to a fleet-wide query.
    assert [v["letter"] for v in body["volumes"]] == ["C:", "D:"]
    # Sorted case-folded by name.
    assert [s["name"] for s in body["software"]] == [
        "7-Zip 24.09 (x64)",
        "Mozilla Firefox (x64 fr)",
    ]
    assert body["software"][0]["publisher"] == "Igor Pavlov"
    assert body["software"][0]["install_date"] == "2025-06-01"


async def test_system_volume_figures_are_derived(client, db_session):
    """The two machine columns come from the reported system volume."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-sysvol")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())

    body = await _detail(client, headers, enrolled)
    assert body["system_volume_total_mb"] == 486000
    assert body["system_volume_free_mb"] == 41000
    # Only the volume flagged as the system one — D: is bigger news for nobody.
    assert body["volumes"][1]["letter"] == "D:"


async def test_heartbeat_without_inventory_changes_nothing(client, db_session):
    """An absent block leaves every stored value alone, like the Defender one."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-absent")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())

    resp = await _heartbeat(client, enrolled["token"], hostname="PC-42")
    assert resp.status_code == 200

    body = await _detail(client, headers, enrolled)
    assert body["hostname"] == "PC-42"
    assert body["hw_model"] == "OptiPlex 7010"
    assert len(body["software"]) == 2
    assert len(body["disks"]) == 1


# --- Replacement semantics ---------------------------------------------------


async def test_inventory_replaces_sets_and_keeps_first_seen(client, db_session):
    """Hardware that is gone disappears; what stays keeps its first_seen."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-replace")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())
    before = await _detail(client, headers, enrolled)
    kept_first_seen = before["memory_modules"][0]["slot"]
    assert kept_first_seen == "DIMM A1"

    # One stick pulled, one program uninstalled, the second volume gone.
    second = _inventory(
        hash="h2",
        memory_modules=[{"slot": "DIMM A1", "capacity_mb": 16384, "type": "DDR5"}],
        volumes=[
            {
                "letter": "C:",
                "filesystem": "NTFS",
                "total_mb": 486000,
                "free_mb": 30000,
                "is_system": True,
            }
        ],
        software=[
            {
                "name": "7-Zip 24.09 (x64)",
                "version": "24.09",
                "publisher": "Igor Pavlov",
            }
        ],
    )
    await _heartbeat(client, enrolled["token"], inventory=second)

    body = await _detail(client, headers, enrolled)
    assert [m["slot"] for m in body["memory_modules"]] == ["DIMM A1"]
    assert [v["letter"] for v in body["volumes"]] == ["C:"]
    assert [s["name"] for s in body["software"]] == ["7-Zip 24.09 (x64)"]
    # The row that survived kept the date it was first reported on.
    assert body["software"][0]["first_seen"] == before["software"][0]["first_seen"]
    # And the derived figure followed the new report.
    assert body["system_volume_free_mb"] == 30000


async def test_empty_software_list_clears_it(client, db_session):
    """``[]`` is the report of a poste whose software collection is switched off.

    It has to *clear* what an earlier cycle stored: the GPO switch is a privacy
    guarantee, and one that leaves the previous list lying in the database is
    not a guarantee at all. ``null`` is the other case — see the test below.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-nosoft")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())

    await _heartbeat(
        client, enrolled["token"], inventory=_inventory(hash="h2", software=[])
    )

    body = await _detail(client, headers, enrolled)
    assert body["software"] == []
    # The hardware is untouched: only the software switch was flipped.
    assert len(body["disks"]) == 1


async def test_null_section_leaves_it_alone(client, db_session):
    """``null`` is "could not read", and must not wipe a good list."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-nullsec")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())

    await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(hash="h2", software=None, disks=None),
    )

    body = await _detail(client, headers, enrolled)
    assert len(body["software"]) == 2
    assert len(body["disks"]) == 1


async def test_software_catalogue_is_shared(client, db_session):
    """Two machines carrying one program share one catalogue row."""
    from sqlmodel import select

    from app.features.inventory.models import Software

    headers = await _admin_headers(client, db_session)
    first = await _enroll(client, "m-inv-cat-a")
    second = await _enroll(client, "m-inv-cat-b")
    await _heartbeat(client, first["token"], inventory=_inventory())
    await _heartbeat(client, second["token"], inventory=_inventory(hash="h-b"))

    rows = await db_session.exec(select(Software))
    entries = rows.all()
    assert len(entries) == 2  # the two programs, not four rows

    # And both machines still list both programs.
    for enrolled in (first, second):
        body = await _detail(client, headers, enrolled)
        assert len(body["software"]) == 2
    # The parc-wide handle is the same on both.
    a = await _detail(client, headers, first)
    b = await _detail(client, headers, second)
    assert [s["software_id"] for s in a["software"]] == [
        s["software_id"] for s in b["software"]
    ]


async def test_duplicate_keys_in_one_report_collapse(client, db_session):
    """A section that names one key twice must not blow up the upsert."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-dupes")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(
            volumes=[
                {"letter": "C:", "total_mb": 100, "free_mb": 10, "is_system": True},
                {"letter": "c:", "total_mb": 200, "free_mb": 20, "is_system": True},
            ]
        ),
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert len(body["volumes"]) == 1
    # Last one reported wins — an arbitrary but stable rule.
    assert body["volumes"][0]["total_mb"] == 200


async def test_entries_without_a_key_are_dropped(client, db_session):
    """No key, no row: a blank one would collapse every such entry onto one."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-nokey")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(
            memory_modules=[{"slot": "", "capacity_mb": 8192}],
            software=[{"name": "", "version": "1.0"}],
        ),
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert body["memory_modules"] == []
    assert body["software"] == []


# --- The unchanged-hash short circuit ---------------------------------------


async def test_same_hash_skips_the_write(client, db_session):
    """A re-sent inventory only refreshes the date it was taken.

    The observable proof is that a *changed* body carrying the *same* hash is
    ignored: the server trusted the hash and never looked.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-hash")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())
    before = await _detail(client, headers, enrolled)

    await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(hw_model="Latitude 5540", software=[]),
    )

    body = await _detail(client, headers, enrolled)
    assert body["hw_model"] == "OptiPlex 7010"
    assert len(body["software"]) == 2
    # But the inventory is dated again: the poste did report it.
    assert body["inventory_last_seen"] >= before["inventory_last_seen"]


async def test_blank_hash_never_short_circuits(client, db_session):
    """An agent that reports no hash gets its inventory written every time."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-nohash")
    await _heartbeat(client, enrolled["token"], inventory=_inventory(hash=""))

    await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(hash="", hw_model="Latitude 5540"),
    )

    body = await _detail(client, headers, enrolled)
    assert body["hw_model"] == "Latitude 5540"


# --- Bounds and tolerance ----------------------------------------------------


async def test_absurd_figures_land_as_null_not_422(client, db_session):
    """A firmware's "unknown" sentinel must not become a petabyte on screen."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-bounds")

    resp = await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(
            cpu_cores=-1,
            ram_total_mb=0xFFFFFFFF,
            cpu_speed_mhz=999_999_999,
        ),
    )
    assert resp.status_code == 200, resp.text

    body = await _detail(client, headers, enrolled)
    assert body["cpu_cores"] is None
    assert body["ram_total_mb"] is None
    assert body["cpu_speed_mhz"] is None
    # And the rest of the heartbeat still landed.
    assert body["hw_model"] == "OptiPlex 7010"


async def test_unknown_nic_type_normalises(client, db_session):
    """Anything that is not wifi or ethernet is "other", never a 422."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-nictype")

    await _heartbeat(
        client,
        enrolled["token"],
        inventory=_inventory(
            nics=[{"key": "A", "type": "Bluetooth PAN"}, {"key": "B", "type": "WiFi"}]
        ),
    )

    body = await _detail(client, headers, enrolled)
    types = {n["ip_address"]: n["type"] for n in body["nics"]}
    assert sorted(n["type"] for n in body["nics"]) == ["other", "wifi"]
    assert types is not None


async def test_machine_deletion_cascades(client, db_session):
    """Removing a machine takes its whole inventory with it."""
    from sqlmodel import select

    from app.features.inventory.models import Disk, MachineSoftware

    await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-cascade")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())

    from app.features.machine.models import Machine

    machine = await db_session.get(Machine, enrolled["machine_id"])
    await db_session.delete(machine)
    await db_session.commit()

    assert (await db_session.exec(select(Disk))).all() == []
    assert (await db_session.exec(select(MachineSoftware))).all() == []
    # The catalogue survives: it describes the parc, not one machine.
    from app.features.inventory.models import Software

    assert len((await db_session.exec(select(Software))).all()) == 2


# --- Console list ------------------------------------------------------------


async def test_list_carries_three_inventory_fields(client, db_session):
    """The list gets what a list is scanned for, and not the fiche's twenty-five."""
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-list")
    await _heartbeat(client, enrolled["token"], inventory=_inventory())

    resp = await client.get("/api/v1/machines", headers=headers)
    assert resp.status_code == 200, resp.text
    row = next(m for m in resp.json()["items"] if m["id"] == enrolled["machine_id"])
    assert row["hw_model"] == "OptiPlex 7010"
    assert row["ram_total_mb"] == 32768
    assert row["system_volume_free_mb"] == 41000
    assert "software" not in row
    assert "cpu_model" not in row


# --- The command -------------------------------------------------------------


async def test_inventory_scan_round_trip(client, db_session):
    """One new type, and no migration behind it: creatable, deliverable, closeable.

    This is the coverage ``test_catalogue_is_fully_covered_below`` in
    tests/test_api_console.py points at for this value.
    """
    headers = await _admin_headers(client, db_session)
    enrolled = await _enroll(client, "m-inv-cmd")

    resp = await client.post(
        "/api/v1/commands",
        headers=headers,
        json={"type": "inventory_scan", "machine_ids": [enrolled["machine_id"]]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1

    hb = await _heartbeat(client, enrolled["token"])
    delivered = hb.json()["commands"]
    assert [c["type"] for c in delivered] == ["inventory_scan"]

    res = await client.post(
        f"/api/v1/agent/commands/{delivered[0]['id']}/result",
        headers={"Authorization": f"Bearer {enrolled['token']}"},
        json={"status": "succeeded", "output": "312 logiciels, 2 volumes"},
    )
    assert res.status_code == 200, res.text

    listed = await client.get(
        f"/api/v1/commands?machine_id={enrolled['machine_id']}", headers=headers
    )
    row = next(c for c in listed.json()["items"] if c["id"] == delivered[0]["id"])
    assert row["status"] == "succeeded"

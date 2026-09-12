"""Fleet-wide inventory queries (require TIAI_TEST_DATABASE_URL).

Covers the inventory J2: the software catalogue, the machine list's inventory
facets, the distinct-value listings, the two CSV exports and the dashboard KPIs.
"""

import io
from datetime import date, datetime

from openpyxl import load_workbook

from tests.test_api_inventory import (  # noqa: F401  (fixtures come from conftest)
    _enroll,
    _heartbeat,
    _inventory,
)


async def _admin_headers(client, db_session) -> dict[str, str]:
    from app.features.user import crud
    from app.features.user.permissions import BuiltinGroup

    await crud.create_user(
        db_session,
        email="fleet-admin@test.local",
        password="pw",
        groups=[BuiltinGroup.ADMIN],
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "fleet-admin@test.local", "password": "pw"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _software(name: str, version: str = "1.0", publisher: str = "Acme") -> dict:
    return {"name": name, "version": version, "publisher": publisher}


async def _poste(client, uuid: str, hostname: str | None = None, **overrides):
    """Enrol a machine and give it one inventory.

    ``hostname`` is a heartbeat attribute, not an inventory field — the block
    ignores what it does not know, so passing it through ``overrides`` would
    silently do nothing.
    """
    enrolled = await _enroll(client, uuid)
    body: dict = {"inventory": _inventory(hash=uuid, **overrides)}
    if hostname is not None:
        body["hostname"] = hostname
    await _heartbeat(client, enrolled["token"], **body)
    return enrolled


# --- The software catalogue --------------------------------------------------


async def test_catalogue_counts_machines_per_entry(client, db_session):
    """One row per (name, version, publisher), carrying how much of the parc has it."""
    headers = await _admin_headers(client, db_session)
    shared = _software("7-Zip", "24.09")
    await _poste(client, "fleet-a", software=[shared, _software("Only-A")])
    await _poste(client, "fleet-b", software=[shared])

    resp = await client.get("/api/v1/software", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert resp.json()["total"] == 2
    # Most widespread first, which is the order the page is read in.
    assert items[0]["name"] == "7-Zip"
    assert items[0]["machine_count"] == 2
    assert items[1]["name"] == "Only-A"
    assert items[1]["machine_count"] == 1


async def test_catalogue_hides_entries_nobody_carries(client, db_session):
    """Deleting a machine leaves its programs behind; the page must not list them.

    The rows stay — they are the stable ids a deployed package will hang on —
    but a page titled "logiciels du parc" listing programs no poste has is
    telling the reader something false.
    """
    from sqlmodel import select

    from app.features.inventory.models import Software
    from app.features.machine.models import Machine

    headers = await _admin_headers(client, db_session)
    enrolled = await _poste(client, "fleet-gone", software=[_software("Ghost")])

    machine = await db_session.get(Machine, enrolled["machine_id"])
    await db_session.delete(machine)
    await db_session.commit()

    resp = await client.get("/api/v1/software", headers=headers)
    assert resp.json()["items"] == []
    # But the catalogue row is still there.
    assert len((await db_session.exec(select(Software))).all()) == 1


async def test_catalogue_search_and_sort(client, db_session):
    """Search covers name and publisher; sorting is on the four visible columns."""
    headers = await _admin_headers(client, db_session)
    await _poste(
        client,
        "fleet-search",
        software=[
            _software("Zulu Client", "3.0", publisher="Zulu SA"),
            _software("Alpha Tool", "1.2", publisher="Mozilla"),
        ],
    )

    by_publisher = await client.get("/api/v1/software?search=mozilla", headers=headers)
    assert [i["name"] for i in by_publisher.json()["items"]] == ["Alpha Tool"]

    by_name = await client.get(
        "/api/v1/software?sort_by=name&sort_desc=false", headers=headers
    )
    assert [i["name"] for i in by_name.json()["items"]] == ["Alpha Tool", "Zulu Client"]


async def test_catalogue_export_is_a_spreadsheet(client, db_session):
    """Semicolons and a BOM: this file is opened in Excel, not parsed by a script."""
    headers = await _admin_headers(client, db_session)
    await _poste(client, "fleet-csv", software=[_software("Café Tool", "1.0")])

    resp = await client.get("/api/v1/software/export.csv", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    assert "logiciels.csv" in resp.headers["content-disposition"]
    text = resp.text
    assert text.startswith("﻿")
    assert "Nom;Version;Éditeur;Postes" in text
    # The accent survives the round trip, which is the whole reason for the BOM.
    assert "Café Tool;1.0;Acme;1" in text


async def test_catalogue_export_as_excel(client, db_session):
    """Same rows as the CSV, with a real date in the last column."""
    headers = await _admin_headers(client, db_session)
    await _poste(client, "fleet-xlsx", software=[_software("Café Tool", "1.0")])

    resp = await client.get("/api/v1/software/export.xlsx?search=café", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "spreadsheetml" in resp.headers["content-type"]
    assert "logiciels.xlsx" in resp.headers["content-disposition"]

    sheet = load_workbook(io.BytesIO(resp.content))["Logiciels"]
    assert [c.value for c in sheet[1]] == [
        "Nom",
        "Version",
        "Éditeur",
        "Postes",
        "Vu pour la première fois",
    ]
    row = [c.value for c in sheet[2]]
    assert row[:4] == ["Café Tool", "1.0", "Acme", 1]
    assert isinstance(row[4], (date, datetime))
    assert sheet.freeze_panes == "A2"

    # The search bounds the export exactly as it bounds the list.
    none = await client.get(
        "/api/v1/software/export.xlsx?search=nothing", headers=headers
    )
    assert load_workbook(io.BytesIO(none.content))["Logiciels"].max_row == 1


# --- The machine list's inventory facets -------------------------------------


async def _ids(resp) -> set[str]:
    return {m["id"] for m in resp.json()["items"]}


async def test_filter_by_model_and_manufacturer(client, db_session):
    """Substring on both: "OptiPlex" has to gather the 7010 and the 7020."""
    headers = await _admin_headers(client, db_session)
    dell = await _poste(client, "fleet-dell", hw_model="OptiPlex 7020")
    lenovo = await _poste(
        client, "fleet-lenovo", hw_model="ThinkPad T14", hw_manufacturer="LENOVO"
    )

    resp = await client.get("/api/v1/machines?hw_model=OptiPlex", headers=headers)
    assert await _ids(resp) == {dell["machine_id"]}

    resp = await client.get("/api/v1/machines?hw_manufacturer=lenovo", headers=headers)
    assert await _ids(resp) == {lenovo["machine_id"]}


async def test_filter_by_free_disk_percentage(client, db_session):
    """A percentage, not megabytes: 40 Go left on a 4 To disk is not news."""
    headers = await _admin_headers(client, db_session)
    full = await _poste(
        client,
        "fleet-full",
        volumes=[
            {"letter": "C:", "total_mb": 100_000, "free_mb": 4_000, "is_system": True}
        ],
    )
    roomy = await _poste(
        client,
        "fleet-roomy",
        volumes=[
            {"letter": "C:", "total_mb": 100_000, "free_mb": 60_000, "is_system": True}
        ],
    )
    # Never reported an inventory at all: an absence is not a full disk.
    silent = await _enroll(client, "fleet-silent")

    resp = await client.get("/api/v1/machines?disk_free_below=10", headers=headers)
    found = await _ids(resp)
    assert found == {full["machine_id"]}
    assert roomy["machine_id"] not in found
    assert silent["machine_id"] not in found


async def test_filter_by_software(client, db_session):
    """The drill-down behind every row of the catalogue."""
    headers = await _admin_headers(client, db_session)
    java = _software("Java 8", "1.8.0_202", publisher="Oracle")
    with_java = await _poste(client, "fleet-java", software=[java])
    await _poste(client, "fleet-nojava", software=[_software("Firefox", "142.0")])

    catalogue = await client.get("/api/v1/software?search=Java", headers=headers)
    java_id = catalogue.json()["items"][0]["id"]

    resp = await client.get(f"/api/v1/machines?software_id={java_id}", headers=headers)
    assert await _ids(resp) == {with_java["machine_id"]}
    assert resp.json()["total"] == 1


async def test_sort_by_free_disk_percentage(client, db_session):
    """Sortable like any other column, though it has none of its own."""
    headers = await _admin_headers(client, db_session)
    await _poste(
        client,
        "fleet-sort-a",
        volumes=[{"letter": "C:", "total_mb": 1000, "free_mb": 900, "is_system": True}],
    )
    await _poste(
        client,
        "fleet-sort-b",
        volumes=[{"letter": "C:", "total_mb": 1000, "free_mb": 50, "is_system": True}],
    )

    resp = await client.get(
        "/api/v1/machines?sort_by=disk_free_percent&sort_desc=false", headers=headers
    )
    percents = [
        m["system_volume_free_mb"]
        for m in resp.json()["items"]
        if m["system_volume_free_mb"]
    ]
    assert percents == sorted(percents)


async def test_models_and_manufacturers_listings(client, db_session):
    """Fleet data, most widespread first — the shape /os-versions established."""
    headers = await _admin_headers(client, db_session)
    await _poste(client, "fleet-m1", hw_model="OptiPlex 7010")
    await _poste(client, "fleet-m2", hw_model="OptiPlex 7010")
    await _poste(client, "fleet-m3", hw_model="ThinkPad T14")

    models = await client.get("/api/v1/machines/models", headers=headers)
    assert models.status_code == 200, models.text
    assert models.json()[0] == {"name": "OptiPlex 7010", "count": 2}

    makers = await client.get("/api/v1/machines/manufacturers", headers=headers)
    assert makers.json()[0]["name"] == "Dell Inc."


async def test_fleet_export_honours_the_filters(client, db_session):
    """An export that ignored the filters would be worse than no export."""
    headers = await _admin_headers(client, db_session)
    await _poste(client, "fleet-x1", hostname="PC-ONE", hw_model="OptiPlex 7010")
    await _poste(client, "fleet-x2", hostname="PC-TWO", hw_model="ThinkPad T14")

    resp = await client.get(
        "/api/v1/machines/export.csv?hw_model=OptiPlex", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert "parc.csv" in resp.headers["content-disposition"]
    assert "PC-ONE" in resp.text
    assert "PC-TWO" not in resp.text
    # The percentage is a whole number, not a float with fifteen decimals.
    assert ";8;" in resp.text  # 41000 / 486000


async def test_export_is_forbidden_for_the_unauthenticated(client, db_session):
    """Both exports sit behind the same read permission as the list."""
    for path in (
        "/api/v1/machines/export.csv",
        "/api/v1/software/export.csv",
        "/api/v1/software/export.xlsx",
    ):
        resp = await client.get(path)
        assert resp.status_code == 401, path


# --- Dashboard KPIs ----------------------------------------------------------


async def test_overview_inventory_kpis(client, db_session):
    """Four counts, each one a list an administrator can open and act on."""
    headers = await _admin_headers(client, db_session)
    await _poste(
        client,
        "fleet-kpi-full",
        volumes=[
            {
                "letter": "C:",
                "total_mb": 100_000,
                "free_mb": 2_000,
                "is_system": True,
                "encryption_status": "FullyDecrypted",
            }
        ],
        bios_date="2015-06-01",
        software=[_software("7-Zip", "24.09")],
    )
    await _poste(
        client,
        "fleet-kpi-ok",
        volumes=[
            {
                "letter": "C:",
                "total_mb": 100_000,
                "free_mb": 80_000,
                "is_system": True,
                "encryption_status": "FullyEncrypted",
            }
        ],
        bios_date="2025-06-01",
        software=[_software("7-Zip", "24.09"), _software("Firefox", "142.0")],
    )

    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["machines_low_disk"] == 1
    assert body["machines_unencrypted"] == 1
    assert body["machines_aging"] == 1
    # Two distinct programs across the parc, though one is on both machines.
    assert body["software_count"] == 2
    # The thresholds ride along so the cards can name them.
    assert body["low_disk_free_percent"] == 10
    assert body["hardware_aging_years"] == 5


async def test_unread_encryption_is_not_counted_as_unencrypted(client, db_session):
    """BitLocker's namespace is absent on some SKUs; "not read" is not "not safe"."""
    headers = await _admin_headers(client, db_session)
    await _poste(
        client,
        "fleet-kpi-unknown",
        volumes=[
            {"letter": "C:", "total_mb": 100_000, "free_mb": 80_000, "is_system": True}
        ],
    )

    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.json()["machines_unencrypted"] == 0

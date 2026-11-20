"""Assets (require TIAI_TEST_DATABASE_URL): a poste's asset, equipment
without an agent, the scope and the right of their own, the import, the
labels' token, the merge, and what a retired poste leaves out."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta

from openpyxl import Workbook

from tests.scope_helpers import SITE_A, group, machine, two_sites
from tests.test_api_maintenance import _admin, _tech

TODAY = datetime.now(UTC).date()


async def _room(client, headers, name, location=None):
    resp = await client.post(
        "/api/v1/rooms",
        headers=headers,
        json={
            "name": name,
            **({"location": location} if location else {}),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_a_postes_asset_is_written_under_the_poste(client, db_session):
    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1", hw_serial="SN-1", hw_model="OptiPlex")
    url = f"/api/v1/machines/{m.id}/asset"

    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200 and resp.json() is None

    resp = await client.put(
        url,
        headers=headers,
        json={
            "inventory_number": " INV-001 ",
            "purchase_date": "2021-09-01",
            "warranty_end": "2026-09-01",
            "purchase_price": "749.90",
            "supplier": "Dell",
            # A poste's name and hardware are its machine's: ignored.
            "name": "ignored",
            "serial_number": "ignored",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "PC-1"
    assert body["serial_number"] == "SN-1"
    assert body["model"] == "OptiPlex"
    assert body["inventory_number"] == "INV-001"
    assert body["purchase_price"] == "749.90"
    assert body["status"] == "in_service"
    assert body["kind"] == "computer"
    token = body["public_token"]
    assert len(token) >= 20

    # A second write updates the same asset.
    resp = await client.put(
        url, headers=headers, json={"status": "on_loan", "borrower": "M. Teva"}
    )
    assert resp.json()["id"] == body["id"]
    assert resp.json()["borrower"] == "M. Teva"

    # The label leads to the poste.
    resp = await client.get(f"/api/v1/assets/by-token/{token}", headers=headers)
    assert resp.json()["machine_id"] == str(m.id)
    resp = await client.get("/api/v1/assets/by-token/nope", headers=headers)
    assert resp.status_code == 404

    # A new token retires the old one.
    resp = await client.post(f"/api/v1/assets/{body['id']}/token", headers=headers)
    assert resp.json()["public_token"] != token
    resp = await client.get(f"/api/v1/assets/by-token/{token}", headers=headers)
    assert resp.status_code == 404


async def test_inventory_numbers_are_unique(client, db_session):
    headers, _ = await _admin(client, db_session)
    a = await machine(db_session, "PC-A")
    b = await machine(db_session, "PC-B")
    resp = await client.put(
        f"/api/v1/machines/{a.id}/asset",
        headers=headers,
        json={"inventory_number": "X1"},
    )
    assert resp.status_code == 200
    resp = await client.put(
        f"/api/v1/machines/{b.id}/asset",
        headers=headers,
        json={"inventory_number": "X1"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "asset.inventory_number.taken"


async def test_equipment_without_an_agent(client, db_session):
    headers, _ = await _admin(client, db_session)
    room = await _room(client, headers, "A101")
    resp = await client.post(
        "/api/v1/assets",
        headers=headers,
        json={
            "name": "Vidéoprojecteur A101",
            "kind": "projector",
            "room_id": room,
            "manufacturer": "Epson",
            "serial_number": "EPS-9",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["display_name"] == "Vidéoprojecteur A101"
    assert body["room_name"] == "A101"
    assert body["kind"] == "projector"

    resp = await client.post("/api/v1/assets", headers=headers, json={"name": "  "})
    assert resp.status_code == 422

    resp = await client.patch(
        f"/api/v1/assets/{body['id']}", headers=headers, json={"status": "in_repair"}
    )
    assert resp.json()["status"] == "in_repair"

    resp = await client.get(
        "/api/v1/assets", headers=headers, params={"with_machine": "false"}
    )
    assert [a["display_name"] for a in resp.json()["items"]] == ["Vidéoprojecteur A101"]
    resp = await client.get(
        "/api/v1/assets", headers=headers, params={"search": "eps-9"}
    )
    assert resp.json()["total"] == 1

    resp = await client.delete(f"/api/v1/assets/{body['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/assets/{body['id']}", headers=headers)
    assert resp.status_code == 404


async def test_a_right_of_its_own_and_the_scope(client, db_session):
    from app.features.user.permissions import ALL_PERMISSIONS

    sites = await two_sites(client, db_session)
    for m in (sites.a, sites.b):
        resp = await client.put(
            f"/api/v1/machines/{m.id}/asset",
            headers=sites.admin,
            json={"purchase_price": "100"},
        )
        assert resp.status_code == 200

    resp = await client.get("/api/v1/assets", headers=sites.scoped)
    assert [a["display_name"] for a in resp.json()["items"]] == ["PC-A"]
    resp = await client.get(
        f"/api/v1/machines/{sites.b.id}/asset", headers=sites.scoped
    )
    assert resp.status_code == 404

    # A technician reads the parc, not what it cost.
    tech, _ = await _tech(client, db_session)
    resp = await client.get("/api/v1/assets", headers=tech)
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/machines/{sites.a.id}/asset", headers=tech)
    assert resp.status_code == 403
    assert "asset:read" in ALL_PERMISSIONS


async def _upload(client, headers, content, filename="parc.csv", dry_run=True):
    return await client.post(
        "/api/v1/assets/import",
        headers=headers,
        params={"dry_run": str(dry_run).lower()},
        files={"file": (filename, content, "application/octet-stream")},
    )


def _csv(rows):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    for row in rows:
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


async def test_import_previews_then_writes(client, db_session):
    headers, _ = await _admin(client, db_session)
    one = await machine(db_session, "PC-1", hw_serial="SN-1")
    await machine(db_session, "PC-2", hw_serial="sn-2")
    await machine(db_session, "DUP-A", hw_serial="SN-DUP")
    await machine(db_session, "DUP-B", hw_serial="SN-DUP")
    await client.put(
        f"/api/v1/machines/{one.id}/asset",
        headers=headers,
        json={"inventory_number": "INV-1", "supplier": "Dell"},
    )
    content = _csv(
        [
            [
                "N° de série",
                "N° d'inventaire",
                "Date d'achat",
                "Fin de garantie",
                "Prix",
                "Statut",
                "Autre",
            ],
            [
                "SN-1",
                "INV-1",
                "01/09/2021",
                "2026-09-01",
                "1 234,50",
                "En service",
                "x",
            ],
            ["SN-2", "INV-2", "", "", "", "prêté", ""],
            ["SN-404", "INV-3", "", "", "", "", ""],
            ["SN-DUP", "", "", "", "", "", ""],
            ["SN-BAD", "", "32/13/2021", "", "", "", ""],
            ["", "INV-9", "", "", "", "", ""],
            ["SN-2b", "INV-1", "", "", "", "", ""],
        ]
    )
    resp = await _upload(client, headers, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_line = {r["line"]: r for r in body["rows"]}
    assert by_line[2]["action"] == "update"
    assert by_line[2]["changes"] == {
        "purchase_date": "2021-09-01",
        "warranty_end": "2026-09-01",
        "purchase_price": "1234.50",
        # « En service » is what the asset already says: not a change.
    }
    assert by_line[3]["action"] == "create" and by_line[3]["hostname"] == "PC-2"
    assert by_line[3]["changes"]["status"] == "on_loan"
    assert by_line[4]["action"] == "unmatched"
    assert by_line[5]["action"] == "ambiguous"
    assert by_line[6]["action"] == "invalid" and by_line[6]["errors"] == [
        "purchase_date"
    ]
    assert by_line[7]["errors"] == ["serial"]
    assert "inventory_number_taken" in by_line[8]["errors"]
    assert body["dry_run"] is True

    # Nothing written by the preview.
    resp = await client.get("/api/v1/assets", headers=headers)
    assert resp.json()["total"] == 1

    resp = await _upload(client, headers, content, dry_run=False)
    assert resp.json()["counts"]["create"] == 1
    resp = await client.get("/api/v1/assets", headers=headers)
    items = {a["display_name"]: a for a in resp.json()["items"]}
    assert items["PC-1"]["purchase_date"] == "2021-09-01"
    assert items["PC-1"]["supplier"] == "Dell"  # an empty cell leaves it alone
    assert items["PC-2"]["status"] == "on_loan"

    # Imported again: nothing to change.
    resp = await _upload(client, headers, content)
    assert {r["line"]: r["action"] for r in resp.json()["rows"]}[2] == "unchanged"


async def test_import_reads_excel_and_refuses_the_unreadable(client, db_session):
    headers, _ = await _admin(client, db_session)
    await machine(db_session, "PC-1", hw_serial="SN-1")
    wb = Workbook()
    ws = wb.active
    ws.append(["Serial number", "Purchase date", "Price"])
    ws.append(["SN-1", datetime(2022, 3, 4), 999.5])
    buffer = io.BytesIO()
    wb.save(buffer)
    resp = await _upload(client, headers, buffer.getvalue(), "parc.xlsx")
    assert resp.status_code == 200, resp.text
    [row] = resp.json()["rows"]
    assert row["changes"] == {"purchase_date": "2022-03-04", "purchase_price": "999.50"}

    resp = await _upload(client, headers, b"nom;prix\nPC;1\n")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "asset.import.unreadable"
    resp = await _upload(client, headers, b"PK\x03\x04garbage", "parc.xlsx")
    assert resp.status_code == 422


async def test_merge_moves_the_asset(db_session):
    from app.features.asset import crud
    from app.features.asset.models import Asset
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    source = await machine(db_session, "DUP")
    target = await machine(db_session, "KEPT")
    db_session.add(Asset(machine_id=source.id, inventory_number="I-1"))
    await db_session.commit()
    await machine_crud.merge_into(
        db_session,
        target=await db_session.get(Machine, target.id),
        source=await db_session.get(Machine, source.id),
    )
    await db_session.commit()
    asset = await crud.for_machine(db_session, target.id)
    assert asset is not None and asset.inventory_number == "I-1"


async def test_retired_postes_leave_the_counts_and_the_alerts(client, db_session):
    from app.features.alert import crud as alert_crud
    from app.features.asset.models import Asset, AssetStatus

    headers, _ = await _admin(client, db_session)
    kept = await machine(
        db_session, "KEPT", system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    gone = await machine(
        db_session, "GONE", system_volume_total_mb=100_000, system_volume_free_mb=1_000
    )
    db_session.add(Asset(machine_id=gone.id, status=AssetStatus.RETIRED))
    await db_session.commit()

    resp = await client.get("/api/v1/stats/overview", headers=headers)
    body = resp.json()
    assert body["total"] == 1
    assert body["machines_low_disk"] == 1
    assert body["machines_retired"] == 1

    result = await alert_crud.evaluate(db_session, datetime.now(UTC))
    await db_session.commit()
    assert {a.machine_id for a in result.opened} == {kept.id}

    resp = await client.get(
        "/api/v1/machines", headers=headers, params={"asset_status": "retired"}
    )
    assert [m["hostname"] for m in resp.json()["items"]] == ["GONE"]
    resp = await client.get(
        "/api/v1/machines", headers=headers, params={"asset_status": "none"}
    )
    assert [m["hostname"] for m in resp.json()["items"]] == ["KEPT"]


async def test_age_counts_from_the_purchase_date(client, db_session):
    from app.features.asset.models import Asset

    headers, _ = await _admin(client, db_session)
    # A new BIOS on an old purchase, and an old BIOS without one.
    bought = await machine(db_session, "BOUGHT", bios_date=TODAY)
    await machine(db_session, "OLD-BIOS", bios_date=date(2015, 1, 1))
    await machine(db_session, "NEW", bios_date=TODAY)
    db_session.add(Asset(machine_id=bought.id, purchase_date=date(2016, 1, 1)))
    await db_session.commit()
    resp = await client.get(
        "/api/v1/machines", headers=headers, params={"hardware_aging": "true"}
    )
    assert sorted(m["hostname"] for m in resp.json()["items"]) == ["BOUGHT", "OLD-BIOS"]


async def test_windows_11_readiness(client, db_session):
    headers, _ = await _admin(client, db_session)
    seen = datetime.now(UTC)
    ready = await machine(
        db_session,
        "READY",
        os_version="Windows 10 Pro 22H2 (Build 19045)",
        inventory_last_seen=seen,
        tpm_version="2.0",
        ram_total_mb=8000,
        system_volume_total_mb=240_000,
        os_architecture="64 bits",
        secure_boot=True,
    )
    await machine(
        db_session,
        "OLD",
        os_version="Windows 10 Pro 22H2 (Build 19045)",
        inventory_last_seen=seen,
        tpm_version="1.2",
        ram_total_mb=8000,
        system_volume_total_mb=240_000,
    )
    await machine(db_session, "W11", os_version="Windows 11 Pro 24H2 (Build 26100)")
    resp = await client.get(f"/api/v1/machines/{ready.id}", headers=headers)
    w = resp.json()["windows11"]
    # The processor list is not in the product: « à vérifier » at best.
    assert w["verdict"] == "ready" and w["processor"] == "check" and w["tpm"] == "ok"

    resp = await client.get(
        "/api/v1/machines", headers=headers, params={"win11_blocked": "true"}
    )
    assert [m["hostname"] for m in resp.json()["items"]] == ["OLD"]
    resp = await client.get("/api/v1/stats/overview", headers=headers)
    assert resp.json()["machines_win11_blocked"] == 1


async def test_warranty_alert(db_session):
    from app.features.alert import crud as alert_crud
    from app.features.asset.models import Asset

    soon = await machine(db_session, "SOON")
    later = await machine(db_session, "LATER")
    over = await machine(db_session, "OVER")
    db_session.add(Asset(machine_id=soon.id, warranty_end=TODAY + timedelta(days=10)))
    db_session.add(Asset(machine_id=later.id, warranty_end=TODAY + timedelta(days=90)))
    db_session.add(Asset(machine_id=over.id, warranty_end=TODAY - timedelta(days=1)))
    await db_session.commit()
    result = await alert_crud.evaluate(db_session, datetime.now(UTC))
    warranty = [a for a in result.opened if a.rule == "warranty_ending"]
    assert [a.machine_id for a in warranty] == [soon.id]
    assert warranty[0].detail["threshold_days"] == 30


async def test_scoped_equipment_needs_a_room_in_scope(client, db_session):
    from app.features.user.permissions import ALL_PERMISSIONS
    from app.features.user.scope import Scope
    from tests.scope_helpers import account

    admin, _ = await _admin(client, db_session)
    inside = await _room(client, admin, "A101", location=SITE_A)
    outside = await _room(client, admin, "B201", location="Ailleurs")
    g = await group(
        db_session, "Site A", ALL_PERMISSIONS, Scope(locations=frozenset({SITE_A}))
    )
    scoped = await account(client, db_session, "a@test.local", [g.id])

    resp = await client.post(
        "/api/v1/assets", headers=scoped, json={"name": "Écran", "room_id": inside}
    )
    assert resp.status_code == 201
    resp = await client.post(
        "/api/v1/assets", headers=scoped, json={"name": "Écran", "room_id": outside}
    )
    assert resp.status_code == 404
    resp = await client.post("/api/v1/assets", headers=scoped, json={"name": "Écran"})
    assert resp.status_code == 404
    resp = await client.post(
        "/api/v1/assets", headers=admin, json={"name": "Imprimante", "room_id": outside}
    )
    other = resp.json()["id"]
    resp = await client.get(f"/api/v1/assets/{other}", headers=scoped)
    assert resp.status_code == 404
    assert uuid.UUID(other)


async def test_export_offers_asset_columns_to_asset_readers_only(client, db_session):
    from app.features.asset.models import Asset

    admin, _ = await _admin(client, db_session)
    tech, _ = await _tech(client, db_session)
    m = await machine(db_session, "PC-1")
    db_session.add(
        Asset(
            machine_id=m.id,
            inventory_number="INV-7",
            status="on_loan",
            warranty_end=date(2027, 1, 31),
        )
    )
    await db_session.commit()

    resp = await client.get("/api/v1/machines/export-columns", headers=admin)
    assert "asset_inventory_number" in {c["key"] for c in resp.json()}
    resp = await client.get("/api/v1/machines/export-columns", headers=tech)
    assert "asset_inventory_number" not in {c["key"] for c in resp.json()}

    params = {
        "columns": "hostname,asset_inventory_number,asset_status,asset_warranty_end"
    }
    resp = await client.get("/api/v1/machines/export.csv", headers=admin, params=params)
    assert resp.status_code == 200, resp.text
    rows = list(
        csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";")
    )
    assert rows[1][:3] == ["PC-1", "INV-7", "Prêté"]
    assert rows[1][3]  # the warranty end, in the file's date format
    resp = await client.get("/api/v1/machines/export.csv", headers=tech, params=params)
    assert resp.status_code == 422

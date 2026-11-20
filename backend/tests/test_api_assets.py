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


# --- Review: the import, the scope, the audit, the labels, the merge ----------


async def test_import_stays_within_the_scope(client, db_session):
    """A site-A account's sheet holding a site-B serial: the row is
    « unmatched » — no hostname shown, nothing written there."""
    from app.features.machine.models import Machine

    sites = await two_sites(client, db_session)
    for m, serial in ((sites.a, "SN-A"), (sites.b, "SN-B")):
        row = await db_session.get(Machine, m.id)
        row.hw_serial = serial
        db_session.add(row)
    await db_session.commit()
    content = _csv([["Serial", "Fournisseur"], ["SN-A", "Dell"], ["SN-B", "HP"]])
    for dry_run in (True, False):
        resp = await _upload(client, sites.scoped, content, dry_run=dry_run)
        assert resp.status_code == 200, resp.text
        by_serial = {r["serial"]: r for r in resp.json()["rows"]}
        assert by_serial["SN-A"]["hostname"] == "PC-A"
        assert by_serial["SN-B"]["action"] == "unmatched"
        assert by_serial["SN-B"]["hostname"] is None
    resp = await client.get(f"/api/v1/machines/{sites.b.id}/asset", headers=sites.admin)
    assert resp.json() is None
    resp = await client.get(f"/api/v1/machines/{sites.a.id}/asset", headers=sites.admin)
    assert resp.json()["supplier"] == "Dell"


async def test_import_preview_says_what_the_import_does(client, db_session):
    """A row that writes nothing reserves no inventory number; a serial twice
    in the file is refused on its second row, in the preview as in the
    import."""
    headers, _ = await _admin(client, db_session)
    await machine(db_session, "PC-1", hw_serial="SN-1")
    await machine(db_session, "PC-2", hw_serial="SN-2")
    content = _csv(
        [
            ["Serial", "Inventaire", "Fournisseur"],
            ["SN-404", "I-1", ""],
            ["SN-1", "I-1", ""],
            ["SN-2", "", "Dell"],
            ["SN-2", "", "HP"],
            ["SN-1b", "I-1", ""],
        ]
    )
    preview = await _upload(client, headers, content)
    assert preview.status_code == 200, preview.text
    rows = {r["line"]: r for r in preview.json()["rows"]}
    assert rows[2]["action"] == "unmatched"
    assert rows[3]["action"] == "create" and rows[3]["errors"] == []
    assert rows[4]["action"] == "create"
    assert rows[5]["action"] == "invalid"
    assert rows[5]["errors"] == ["duplicate_serial"]
    # Written by a row above: taken.
    assert "inventory_number_taken" in rows[6]["errors"]

    done = await _upload(client, headers, content, dry_run=False)
    assert done.json()["counts"] == preview.json()["counts"]
    resp = await client.get("/api/v1/assets", headers=headers)
    items = {a["display_name"]: a for a in resp.json()["items"]}
    assert items["PC-1"]["inventory_number"] == "I-1"
    assert items["PC-2"]["supplier"] == "Dell"


async def test_import_limits_say_what_to_do(client, db_session):
    from app.api.routes import assets as routes
    from app.features.asset import importer

    headers, _ = await _admin(client, db_session)
    resp = await _upload(
        client, headers, b"Serial;Prix\n" + b"x" * routes.MAX_IMPORT_BYTES
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "asset.import.too_large"
    assert error["details"]["cause"] == {
        "code": "file_too_large",
        "params": {"max_mb": 8},
    }

    rows = "\n".join(f"SN-{i};1" for i in range(importer.MAX_ROWS + 1))
    resp = await _upload(client, headers, f"Serial;Prix\n{rows}\n".encode())
    error = resp.json()["error"]
    assert error["code"] == "asset.import.too_large"
    assert error["details"]["cause"] == {
        "code": "too_many_rows",
        "params": {"max": importer.MAX_ROWS},
    }

    resp = await _upload(client, headers, b"nom;prix\nPC;1\n")
    error = resp.json()["error"]
    assert error["code"] == "asset.import.unreadable"
    assert error["details"]["cause"] == {"code": "no_serial_column"}


async def test_labels_resolve_within_the_scope(client, db_session):
    """A label out of scope is « introuvable »; equipment resolves to no
    poste; a technician without asset:read still follows a label."""
    sites = await two_sites(client, db_session)
    tokens = {}
    for m in (sites.a, sites.b):
        resp = await client.put(
            f"/api/v1/machines/{m.id}/asset", headers=sites.admin, json={}
        )
        tokens[m.hostname] = resp.json()["public_token"]
    resp = await client.post(
        "/api/v1/assets", headers=sites.admin, json={"name": "Projecteur"}
    )
    loose = resp.json()

    url = "/api/v1/assets/by-token/{}"
    resp = await client.get(url.format(tokens["PC-B"]), headers=sites.scoped)
    assert resp.status_code == 404
    resp = await client.get(url.format(tokens["PC-A"]), headers=sites.scoped)
    assert resp.status_code == 200 and resp.json()["machine_id"] == str(sites.a.id)

    tech, _ = await _tech(client, db_session)
    resp = await client.get(url.format(tokens["PC-A"]), headers=tech)
    assert resp.status_code == 200, resp.text

    resp = await client.get(url.format(loose["public_token"]), headers=sites.admin)
    body = resp.json()
    assert body["machine_id"] is None and body["asset_id"] == loose["id"]
    # In no room: an unrestricted account's alone.
    resp = await client.get(url.format(loose["public_token"]), headers=sites.scoped)
    assert resp.status_code == 404


async def test_writes_stay_within_the_scope(client, db_session):
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
    a = await machine(db_session, "PC-A", location=SITE_A, hw_serial="SN-A")
    b = await machine(db_session, "PC-B", location="Ailleurs")

    resp = await client.post(
        "/api/v1/assets", headers=scoped, json={"name": "Écran", "room_id": inside}
    )
    screen = resp.json()["id"]
    # Out of its scope, or out of every room: refused.
    for room in (outside, None):
        resp = await client.patch(
            f"/api/v1/assets/{screen}", headers=scoped, json={"room_id": room}
        )
        assert resp.status_code == 404, room
    resp = await client.patch(
        f"/api/v1/assets/{screen}", headers=scoped, json={"name": "  "}
    )
    assert resp.status_code == 422
    # A status is left out, never null — refused in words the console has.
    resp = await client.patch(
        f"/api/v1/assets/{screen}", headers=scoped, json={"status": None}
    )
    assert resp.status_code == 422
    [item] = resp.json()["error"]["details"]["errors"]
    assert item["type"] == "tiai_null_refused"
    resp = await client.put(f"/api/v1/machines/{b.id}/asset", headers=scoped, json={})
    assert resp.status_code == 404

    # A poste's asset keeps its machine's name, room and serial.
    resp = await client.put(f"/api/v1/machines/{a.id}/asset", headers=scoped, json={})
    asset_id = resp.json()["id"]
    resp = await client.put(
        f"/api/v1/machines/{a.id}/asset", headers=scoped, json={"status": None}
    )
    assert resp.status_code == 422
    resp = await client.patch(
        f"/api/v1/assets/{asset_id}",
        headers=scoped,
        json={
            "name": "x",
            "serial_number": "y",
            "room_id": inside,
            "status": "in_repair",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "PC-A"
    assert body["name"] is None
    assert body["serial_number"] == "SN-A"
    assert body["room_id"] is None
    assert body["status"] == "in_repair"


async def test_merge_when_both_records_have_an_asset(db_session):
    """The kept record's asset wins; the duplicate's fills what it leaves
    empty — the sticker's inventory number — and is dropped, not left as a
    nameless asset holding that number."""
    from sqlmodel import select

    from app.features.asset import crud
    from app.features.asset.models import Asset
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    source = await machine(db_session, "DUP")
    target = await machine(db_session, "KEPT")
    db_session.add(
        Asset(
            machine_id=source.id,
            inventory_number="I-7",
            supplier="Dell",
            purchase_date=date(2020, 1, 1),
        )
    )
    db_session.add(Asset(machine_id=target.id, purchase_date=date(2021, 1, 1)))
    await db_session.commit()
    await machine_crud.merge_into(
        db_session,
        target=await db_session.get(Machine, target.id),
        source=await db_session.get(Machine, source.id),
    )
    await db_session.commit()
    db_session.expire_all()
    [asset] = (await db_session.exec(select(Asset))).all()
    assert asset.machine_id == target.id
    assert asset.inventory_number == "I-7"
    assert asset.supplier == "Dell"
    assert asset.purchase_date == date(2021, 1, 1)
    assert (await crud.for_machine(db_session, source.id)) is None


async def test_asset_writes_are_audited_without_the_price(client, db_session):
    from sqlmodel import col, select

    from app.features.audit.models import AuditEntry

    headers, _ = await _admin(client, db_session)
    m = await machine(db_session, "PC-1", hw_serial="SN-1")
    resp = await client.put(
        f"/api/v1/machines/{m.id}/asset",
        headers=headers,
        json={"purchase_price": "10", "supplier": "Dell"},
    )
    asset_id = resp.json()["id"]
    await client.post(f"/api/v1/assets/{asset_id}/token", headers=headers)
    resp = await client.post("/api/v1/assets", headers=headers, json={"name": "Écran"})
    screen = resp.json()["id"]
    await client.patch(
        f"/api/v1/assets/{screen}", headers=headers, json={"purchase_price": "99"}
    )
    await client.delete(f"/api/v1/assets/{screen}", headers=headers)
    await _upload(
        client,
        headers,
        _csv([["Serial", "Fournisseur"], ["SN-1", "HP"]]),
        dry_run=False,
    )

    db_session.expire_all()
    entries = (
        await db_session.exec(
            select(AuditEntry)
            .where(col(AuditEntry.resource_type) == "asset")
            .order_by(col(AuditEntry.at))
        )
    ).all()
    actions = [e.action for e in entries]
    for action in (
        "asset.create",
        "asset.update",
        "asset.token_renew",
        "asset.delete",
        "asset.import",
    ):
        assert action in actions, action
    assert {e.actor for e in entries} == {"admin@test.local"}
    priced = [e for e in entries if "purchase_price" in (e.details or {})]
    assert len(priced) == 2
    assert all(e.details["purchase_price"] == "•" for e in priced)
    assert not any("10" == v or "99" == v for e in entries for v in e.details.values())


async def test_list_filters_and_warranty_window(client, db_session):
    """The filters the Matériels page and the labels sheet use; « bientôt
    terminée » over the warranty alert's days, set in Paramètres."""
    from app.features.setting.crud import KEY_ALERT_WARRANTY_DAYS, set_value

    headers, _ = await _admin(client, db_session)
    room = await _room(client, headers, "A101")

    async def equipment(name, **fields):
        resp = await client.post(
            "/api/v1/assets", headers=headers, json={"name": name, **fields}
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    soon = await equipment(
        "SOON", warranty_end=str(TODAY + timedelta(days=10)), kind="printer"
    )
    later = await equipment("LATER", warranty_end=str(TODAY + timedelta(days=45)))
    over = await equipment(
        "OVER", warranty_end=str(TODAY - timedelta(days=1)), status="in_repair"
    )
    none = await equipment("NONE")
    seated = await machine(db_session, "PC-ROOM", room_id=uuid.UUID(room))
    await client.put(f"/api/v1/machines/{seated.id}/asset", headers=headers, json={})

    async def names(**params):
        resp = await client.get("/api/v1/assets", headers=headers, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(a["display_name"] for a in resp.json()["items"])

    assert await names(ids=f"{soon},{over}") == ["OVER", "SOON"]
    resp = await client.get("/api/v1/assets", headers=headers, params={"ids": "nope"})
    assert resp.status_code == 422
    assert await names(warranty="soon") == ["SOON"]
    assert await names(warranty="expired") == ["OVER"]
    assert await names(warranty="active") == ["LATER", "SOON"]
    assert await names(warranty="none") == ["NONE", "PC-ROOM"]
    assert await names(status="in_repair") == ["OVER"]
    assert await names(kind="printer") == ["SOON"]
    # A poste's room is its machine's.
    assert await names(room_id=room) == ["PC-ROOM"]

    resp = await client.get(f"/api/v1/assets/{later}", headers=headers)
    assert resp.json()["warranty_state"] == "active"
    await set_value(db_session, KEY_ALERT_WARRANTY_DAYS, 60, actor="test")
    await db_session.commit()
    assert await names(warranty="soon") == ["LATER", "SOON"]
    resp = await client.get(f"/api/v1/assets/{later}", headers=headers)
    assert resp.json()["warranty_state"] == "soon"
    states = {
        a["display_name"]: a["warranty_state"]
        for a in (await client.get("/api/v1/assets", headers=headers)).json()["items"]
    }
    assert states == {
        "SOON": "soon",
        "LATER": "soon",
        "OVER": "expired",
        "NONE": "none",
        "PC-ROOM": "none",
    }
    assert none


async def test_retired_postes_leave_every_figure(client, db_session):
    """Decision 5: out of the dashboard's figures — threats, verifications,
    maintenance, usage, alerts — of the digest, and of the lists the cards
    open with ``in_parc=true``."""
    from app.features.alert.models import MachineAlert
    from app.features.asset.models import Asset, AssetStatus
    from app.features.check.models import MachineCheck
    from app.features.notification.digest import build_digest
    from app.features.threat.models import Threat

    headers, _ = await _admin(client, db_session)
    long_ago = datetime.now(UTC) - timedelta(days=400)
    now = datetime.now(UTC)
    ids = {}
    for name in ("KEPT", "GONE"):
        m = await machine(
            db_session,
            name,
            first_seen=long_ago,
            last_seen=long_ago,
            wu_pending_count=2,
        )
        ids[name] = m.id
        db_session.add(
            Threat(
                machine_id=m.id,
                detection_id=f"D-{name}",
                threat_name="Trojan",
                status="active",
                detected_at=now,
            )
        )
        db_session.add(MachineCheck(machine_id=m.id, requested_by="x"))
        db_session.add(
            MachineAlert(machine_id=m.id, rule="inactive", opened_at=now, detail={})
        )
    db_session.add(Asset(machine_id=ids["GONE"], status=AssetStatus.RETIRED))
    await db_session.commit()
    resp = await client.patch(
        "/api/v1/settings",
        headers=headers,
        json={"maintenance_default_cycle_days": 30},
    )
    assert resp.status_code == 200, resp.text

    body = (await client.get("/api/v1/stats/overview", headers=headers)).json()
    assert body["total"] == 1
    assert body["machines_retired"] == 1
    for key in (
        "with_active_threats",
        "open_checks",
        "machines_maintenance_overdue",
        "machines_usage_low",
        "machines_with_alerts",
        "inactive",
        "machines_wu_pending",
    ):
        assert body[key] == 1, key
    assert body["alerts_by_rule"]["inactive"] == 1

    digest = await build_digest(db_session)
    assert digest.total == 1
    assert digest.inactive == 1
    assert digest.with_active_threats == 1
    assert digest.new_threats_24h == 1
    assert digest.alerts_by_rule == {"inactive": 1}
    assert [line.hostname for line in digest.threat_lines] == ["KEPT"]

    async def hosts(**params):
        resp = await client.get("/api/v1/machines", headers=headers, params=params)
        assert resp.status_code == 200, resp.text
        return sorted(m["hostname"] for m in resp.json()["items"])

    assert await hosts(status="inactive") == ["GONE", "KEPT"]
    assert await hosts(status="inactive", in_parc="true") == ["KEPT"]
    assert await hosts(in_parc="false") == ["GONE"]


async def test_a_rooms_postes_get_their_assets_for_its_labels(client, db_session):
    """« Étiquettes » from a room: its postes without an asset get one, those
    the caller does not see are left alone, nothing twice."""
    from app.features.user.permissions import ALL_PERMISSIONS
    from app.features.user.scope import Scope
    from tests.scope_helpers import account

    admin, _ = await _admin(client, db_session)
    room = await _room(client, admin, "A101", location=SITE_A)
    elsewhere = await _room(client, admin, "B201", location="Ailleurs")
    g = await group(
        db_session, "Site A", ALL_PERMISSIONS, Scope(locations=frozenset({SITE_A}))
    )
    scoped = await account(client, db_session, "a@test.local", [g.id])
    for name in ("PC-1", "PC-2", "PC-3"):
        await machine(db_session, name, location=SITE_A, room_id=uuid.UUID(room))
    await machine(db_session, "PC-OUT", room_id=uuid.UUID(elsewhere))
    had = await machine(db_session, "PC-HAD", location=SITE_A, room_id=uuid.UUID(room))
    await client.put(
        f"/api/v1/machines/{had.id}/asset",
        headers=admin,
        json={"inventory_number": "I-1"},
    )

    url = f"/api/v1/assets/rooms/{room}/complete"
    resp = await client.post(url, headers=scoped)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"created": 3}
    resp = await client.post(url, headers=scoped)
    assert resp.json() == {"created": 0}
    resp = await client.get("/api/v1/assets", headers=admin, params={"room_id": room})
    names = sorted(a["display_name"] for a in resp.json()["items"])
    assert names == ["PC-1", "PC-2", "PC-3", "PC-HAD"]
    assert all(
        a["status"] == "in_service" and a["kind"] == "computer"
        for a in resp.json()["items"]
    )

    resp = await client.post(
        f"/api/v1/assets/rooms/{elsewhere}/complete", headers=scoped
    )
    assert resp.status_code == 404
    tech, _ = await _tech(client, db_session)
    resp = await client.post(url, headers=tech)
    assert resp.status_code == 403


async def test_a_merge_records_the_asset_it_drops(client, db_session):
    """Both records had their asset: the duplicate's goes, what it held is in
    the audit (price masked), and its loan is not copied onto an asset in
    service, where the console would never show it."""
    from sqlmodel import col, select

    from app.features.asset.models import Asset
    from app.features.audit.models import AuditEntry

    headers, _ = await _admin(client, db_session)
    source = await machine(db_session, "DUP")
    target = await machine(db_session, "KEPT")
    db_session.add(
        Asset(
            machine_id=source.id,
            inventory_number="I-OLD",
            status="on_loan",
            borrower="Jean",
            loan_due=date(2027, 1, 1),
            purchase_price=749,
            supplier="Dell",
        )
    )
    db_session.add(Asset(machine_id=target.id, inventory_number="I-NEW"))
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/machines/{target.id}/merge",
        headers=headers,
        json={"source_id": str(source.id)},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    [asset] = (await db_session.exec(select(Asset))).all()
    assert asset.inventory_number == "I-NEW"
    assert asset.supplier == "Dell"
    assert asset.status == "in_service"
    assert asset.borrower is None and asset.loan_due is None

    [entry] = (
        await db_session.exec(
            select(AuditEntry).where(col(AuditEntry.action) == "asset.delete")
        )
    ).all()
    assert entry.actor == "admin@test.local"
    assert entry.details["inventory_number"] == "I-OLD"
    assert entry.details["status"] == "on_loan"
    assert entry.details["borrower"] == "Jean"
    assert entry.details["purchase_price"] == "•"
    assert entry.details["merged_into"] == str(target.id)


async def test_a_merge_onto_an_asset_on_loan_takes_the_loan(db_session):
    from sqlmodel import select

    from app.features.asset.models import Asset
    from app.features.machine import crud as machine_crud
    from app.features.machine.models import Machine

    source = await machine(db_session, "DUP")
    target = await machine(db_session, "KEPT")
    db_session.add(Asset(machine_id=source.id, borrower="Jean"))
    db_session.add(Asset(machine_id=target.id, status="on_loan"))
    await db_session.commit()
    await machine_crud.merge_into(
        db_session,
        target=await db_session.get(Machine, target.id),
        source=await db_session.get(Machine, source.id),
    )
    await db_session.commit()
    db_session.expire_all()
    [asset] = (await db_session.exec(select(Asset))).all()
    assert asset.borrower == "Jean"

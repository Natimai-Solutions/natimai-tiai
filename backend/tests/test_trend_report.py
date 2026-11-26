"""``GET /stats/report.xlsx`` (C9, plan-tendances-indicateurs §5): sheets by
rights, languages, text cells. Requires TIAI_TEST_DATABASE_URL."""

import io
from datetime import UTC, datetime, timedelta

from openpyxl import load_workbook

from app.features.user.permissions import ALL_PERMISSIONS
from tests.scope_helpers import account, group, machine


async def _workbook(client, headers, query: str = ""):
    resp = await client.get(f"/api/v1/stats/report.xlsx?{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return resp, load_workbook(io.BytesIO(resp.content))


async def _headers(client, db_session, email: str, permissions) -> dict:
    g = await group(db_session, email, permissions, None)
    return await account(client, db_session, email, [g.id])


async def _incidents(db_session, machine_id, count: int) -> None:
    from app.features.intervention.models import Intervention

    for _ in range(count):
        db_session.add(
            Intervention(
                machine_id=machine_id,
                kind="incident",
                performed_by="t@test.local",
                performed_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    await db_session.commit()


async def test_the_report_has_a_sheet_for_what_its_author_reads(
    client, engine, db_session
):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.base import utcnow
    from app.features.trend import snapshot

    pc = await machine(db_session, "PC", location="A", hw_model='=HYPERLINK("x")')
    await _incidents(db_session, pc.id, 2)
    async with AsyncSession(engine) as session:
        await snapshot.record(session, utcnow())
        await session.commit()

    admin = await _headers(client, db_session, "all@test.local", ALL_PERMISSIONS)
    resp, book = await _workbook(client, admin, "months=3")
    assert 'filename="tendances-' in resp.headers["content-disposition"]
    assert book.sheetnames == [
        "Parc",
        "Indicateurs",
        "Pannes par modèle",
        "Pannes par salle",
    ]
    parc = book["Parc"]
    assert parc["A1"].value.startswith("Rapport Tia'i généré le")
    assert [c.value for c in parc[2]][:3] == ["Mois", "Dernier jour suivi", "Postes"]
    rows = list(parc.iter_rows(min_row=3, values_only=True))
    assert len(rows) == 3
    # The current month: photographed today, one poste.
    assert rows[-1][2] == 1
    # The months before: never photographed, left empty.
    assert rows[0][1] is None

    indicators = [
        r[0] for r in book["Indicateurs"].iter_rows(min_row=3, values_only=True)
    ]
    assert "Vérifications closes" in indicators
    assert "Déploiements en anneaux arrêtés" in indicators

    models = book["Pannes par modèle"]
    cell = models["A3"]
    assert cell.value == '=HYPERLINK("x")'
    assert cell.data_type == "s"
    assert models["B3"].value == 2


async def test_sheets_and_rows_follow_the_rights(client, db_session):
    fleet_only = await _headers(
        client, db_session, "f@test.local", {"machine:read", "intervention:read"}
    )
    _, book = await _workbook(client, fleet_only)
    assert book.sheetnames == ["Parc", "Pannes par modèle", "Pannes par salle"]

    no_checks = await _headers(
        client, db_session, "n@test.local", {"machine:read", "maintenance:read"}
    )
    _, book = await _workbook(client, no_checks)
    assert book.sheetnames == ["Parc", "Indicateurs"]
    labels = [r[0] for r in book["Indicateurs"].iter_rows(min_row=3, values_only=True)]
    assert labels == ["Maintenances faites", "Maintenances faites à l'heure"]

    nothing = await _headers(client, db_session, "x@test.local", {"check:read"})
    resp = await client.get("/api/v1/stats/report.xlsx", headers=nothing)
    assert resp.status_code == 403


async def test_the_report_in_english(client, db_session):
    admin = await _headers(client, db_session, "en@test.local", ALL_PERMISSIONS)
    resp, book = await _workbook(client, admin, "lang=en&months=1")
    assert 'filename="trends-' in resp.headers["content-disposition"]
    assert book.sheetnames == [
        "Fleet",
        "Indicators",
        "Failures by model",
        "Failures by room",
    ]
    assert book["Fleet"]["A1"].value.startswith("Tia'i report generated on")
    assert [c.value for c in book["Fleet"][2]][:3] == [
        "Month",
        "Last day tracked",
        "Computers",
    ]
    assert [c.value for c in book["Failures by model"][2]][0] == "Model"
    resp = await client.get("/api/v1/stats/report.xlsx?lang=de", headers=admin)
    assert resp.status_code == 422


def test_a_one_sheet_workbook_is_unchanged():
    """``xlsx_bytes`` is now one sheet of ``xlsx_workbook_bytes``: same
    header row, same frozen pane and filter as before."""
    from app.api.xlsx_export import xlsx_bytes

    book = load_workbook(
        io.BytesIO(xlsx_bytes(["A", "B"], [["x", 1]], sheet_title="S"))
    )
    assert book.sheetnames == ["S"]
    sheet = book["S"]
    assert [c.value for c in sheet[1]] == ["A", "B"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:B2"


async def test_a_site_limited_account_gets_its_site_only(client, engine, db_session):
    """Every reader of the workbook takes the caller's scope: the fleet
    counts, the indicators (the same as ``GET /stats/indicators``) and both
    failure sheets show site A only to an account confined to it (review
    docs-tests #2)."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.base import utcnow
    from app.features.check.models import MachineCheck
    from app.features.machine.models import Machine
    from app.features.room.models import Room
    from app.features.trend import snapshot
    from tests.scope_helpers import SITE_A, SITE_B, two_sites

    sites = await two_sites(client, db_session)
    room_a = Room(name="Salle A", location=SITE_A)
    room_b = Room(name="Salle B", location=SITE_B)
    db_session.add_all([room_a, room_b])
    await db_session.flush()
    for poste, room, model in (
        (sites.a, room_a, "Model A"),
        (sites.b, room_b, "Model B"),
    ):
        row = await db_session.get(Machine, poste.id)
        assert row is not None
        row.room_id = room.id
        row.hw_model = model
        db_session.add(
            MachineCheck(
                machine_id=poste.id,
                requested_by="t@test.local",
                closed_at=utcnow(),
            )
        )
    await db_session.commit()
    for poste in (sites.a, sites.b):
        await _incidents(db_session, poste.id, 2)
    async with AsyncSession(engine) as session:
        await snapshot.record(session, utcnow())
        await session.commit()

    def postes(book):
        return list(book["Parc"].iter_rows(min_row=3, values_only=True))[-1][2]

    def column_a(book, sheet):
        return [r[0] for r in book[sheet].iter_rows(min_row=3, values_only=True)]

    _, everything = await _workbook(client, sites.admin, "months=1")
    assert postes(everything) == 2
    assert sorted(column_a(everything, "Pannes par salle")) == ["Salle A", "Salle B"]

    _, book = await _workbook(client, sites.scoped, "months=1")
    assert postes(book) == 1
    assert column_a(book, "Pannes par modèle") == ["Model A"]
    assert column_a(book, "Pannes par salle") == ["Salle A"]
    models = list(book["Pannes par modèle"].iter_rows(min_row=3, values_only=True))
    assert models[0][1:4] == (2, 1, 1)  # incidents, postes, parc

    resp = await client.get("/api/v1/stats/indicators?months=1", headers=sites.scoped)
    assert resp.status_code == 200, resp.text
    checks = resp.json()["checks"]
    assert [m["closed"] for m in checks] == [1]
    rows = {
        r[0]: list(r[1:])
        for r in book["Indicateurs"].iter_rows(min_row=3, values_only=True)
    }
    assert rows["Vérifications closes"] == [m["closed"] for m in checks]
    assert rows["Délai de clôture médian (h)"] == [m["median_hours"] for m in checks]
    assert rows["Maintenances faites"] == [
        m["done"] for m in resp.json()["maintenance"]
    ]

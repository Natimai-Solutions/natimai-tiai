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

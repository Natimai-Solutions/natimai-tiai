"""Excel responses for the console's export buttons.

The CSV export exists because Excel opens it; this one exists because Excel
opens it *well*: a real date is sortable and filterable, a real number sums,
and a header that is bold, frozen and carrying an auto-filter is what a
spreadsheet handed to a meeting looks like. The column set is the caller's
business — this module only knows how to lay a header and rows out.
"""

import asyncio
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from fastapi import Response
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Widest a column is allowed to grow when sized to its content: a 300-character
# CPU string or install path would otherwise push every other column off the
# screen. Narrowest, so a header of two letters still reads.
MIN_WIDTH = 8
MAX_WIDTH = 60

DATETIME_FORMAT = "yyyy-mm-dd hh:mm"
DATE_FORMAT = "yyyy-mm-dd"


# What XML 1.0 cannot carry and openpyxl's own pattern lets through: the two
# non-characters U+FFFE and U+FFFF, and lone surrogates. Written, they make a
# workbook that openpyxl itself — and Excel — cannot open again (audit S11).
_XML_ILLEGAL_RE = re.compile("[\ud800-\udfff\ufffe\uffff]")


def _cell(value: object) -> object:
    """``None`` as an empty cell; a string without the characters XML 1.0
    cannot carry, which openpyxl refuses or writes into a broken file — one
    character reported by an agent would otherwise fail the whole export
    (audit S11)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _XML_ILLEGAL_RE.sub("", ILLEGAL_CHARACTERS_RE.sub("", value))
    return value


async def xlsx_response(
    filename: str,
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    sheet_title: str = "Export",
) -> Response:
    """Render rows as a downloadable ``.xlsx`` workbook with one sheet.

    Built in a worker thread: a fleet-wide workbook takes seconds of CPU, and
    the API is one process whose event loop also answers every heartbeat —
    built in place, an export froze the postes and every console user. The
    rows must therefore be plain values already read, not lazy ORM objects.
    """
    content = await asyncio.to_thread(
        xlsx_bytes, header, list(rows), sheet_title=sheet_title
    )
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@dataclass(frozen=True)
class Sheet:
    """One sheet of a workbook: its title, its header and its rows, and an
    optional caption written above the header (a report's « généré le … »)."""

    title: str
    header: Sequence[str]
    rows: Sequence[Sequence[object]]
    caption: str | None = None


async def xlsx_workbook_response(filename: str, sheets: Sequence[Sheet]) -> Response:
    """``xlsx_response`` for a workbook of several sheets, built in a thread
    for the same reason."""
    content = await asyncio.to_thread(xlsx_workbook_bytes, list(sheets))
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def xlsx_bytes(
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    sheet_title: str = "Export",
) -> bytes:
    """The workbook of ``xlsx_response``, as bytes: one sheet.

    ``None`` becomes an empty cell, as in the CSV: a spreadsheet has no notion
    of "never reported". Dates and datetimes are written as Excel dates with a
    display format rather than as text, which is the whole reason to prefer
    this format over CSV. Aware datetimes must be made naive by the caller —
    Excel has no timezone, and openpyxl refuses an aware value.

    openpyxl stores any string starting with ``=`` as a formula; the values here
    come from the agents (a poste can name itself ``=HYPERLINK(...)``), so every
    string cell is forced to text.
    """
    return xlsx_workbook_bytes([Sheet(sheet_title, header, list(rows))])


def xlsx_workbook_bytes(sheets: Sequence[Sheet]) -> bytes:
    """A workbook of ``sheets``, in order, under the rules of ``xlsx_bytes``
    — text forced, illegal characters dropped, native dates, bounded widths."""
    workbook = Workbook()
    # New sheets rather than the default one: ``active`` is typed as possibly
    # absent, and the default sheet is dropped so the workbook opens on ours.
    created = [
        _fill(workbook.create_sheet(title=sheet.title, index=i), sheet)
        for i, sheet in enumerate(sheets)
    ]
    for other in list(workbook.worksheets):
        if other not in created:
            workbook.remove(other)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _fill(sheet: Worksheet, spec: Sheet) -> Worksheet:
    header = spec.header
    first = 1
    if spec.caption is not None:
        sheet.append([_cell(spec.caption)])
        sheet.cell(row=1, column=1).data_type = "s"
        sheet.cell(row=1, column=1).font = Font(italic=True)
        first = 2
    sheet.append(list(header))
    for cell in sheet[first]:
        cell.font = Font(bold=True)

    widths = [len(h) for h in header]
    # The row number is counted here, never read back from the sheet:
    # ``sheet.max_row`` walks every cell written so far, and reading it once
    # per cell made the export quadratic — 10 s for 1,500 postes, minutes for
    # all columns.
    last = first
    for row in spec.rows:
        values = [_cell(v) for v in row]
        sheet.append(values)
        last += 1
        for i, value in enumerate(values):
            if isinstance(value, str):
                sheet.cell(row=last, column=i + 1).data_type = "s"
                length = len(value)
            elif isinstance(value, datetime):
                sheet.cell(row=last, column=i + 1).number_format = DATETIME_FORMAT
                length = len(DATETIME_FORMAT)
            elif isinstance(value, date):
                sheet.cell(row=last, column=i + 1).number_format = DATE_FORMAT
                length = len(DATE_FORMAT)
            else:
                length = len(str(value))
            if i < len(widths) and length > widths[i]:
                widths[i] = length

    for i, width in enumerate(widths):
        sheet.column_dimensions[get_column_letter(i + 1)].width = min(
            MAX_WIDTH, max(MIN_WIDTH, width + 2)
        )
    # The header stays put while the rows scroll, and every column gets the
    # dropdown Excel users reach for first.
    sheet.freeze_panes = f"A{first + 1}"
    if header:
        sheet.auto_filter.ref = f"A{first}:{get_column_letter(len(header))}{last}"
    return sheet

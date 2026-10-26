"""CSV responses for the console's export buttons.

One helper rather than two hand-rolled writers: the two exports differ only in
their rows, and the parts that are easy to get wrong — the separator, the BOM,
the filename — are the parts they share.
"""

import csv
import io
from collections.abc import Iterable, Sequence

from fastapi import Response

# Excel on a French Windows reads a comma-separated file as one column: it
# expects the list separator of the locale, which is a semicolon. This export
# exists to be opened in Excel, so semicolon it is — the API's JSON is what a
# script should be reading anyway.
DELIMITER = ";"

# Excel guesses the encoding of a file it has no BOM for, and guesses the ANSI
# codepage — which turns every accented hostname and program name into mojibake.
# The BOM is three bytes that make it read UTF-8. The same lesson the maintenance
# commands learned from four different encodings, applied on the way out.
BOM = "﻿"


# A cell starting with one of these is read by Excel as a formula. Hostnames,
# session names and program names come from the agents — a poste can name itself
# `=HYPERLINK(...)` — so such a cell is prefixed with an apostrophe, which Excel
# and LibreOffice both take as "this is text" (OWASP, CSV injection).
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize(value: object) -> object:
    """Return ``value`` safe to land in a spreadsheet cell; ``None`` → ``""``."""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(FORMULA_TRIGGERS):
        return "'" + value
    return value


def csv_response(
    filename: str, header: Sequence[str], rows: Iterable[Sequence[object]]
) -> Response:
    """Render rows as a downloadable CSV.

    Values are written through ``str`` except ``None``, which becomes an empty
    cell — a spreadsheet has no notion of "never reported", and "None" printed
    in a column of serial numbers reads as a serial number. Text that Excel would
    run as a formula is neutralized (``neutralize``).
    """
    buffer = io.StringIO()
    buffer.write(BOM)
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([neutralize(value) for value in row])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

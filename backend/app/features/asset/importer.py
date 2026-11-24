"""Reading an asset import: a CSV or an Excel workbook, one poste per row,
matched on its serial number.

Nobody types three hundred purchase dates by hand: they come out of the
supplier's delivery note or the accounting system, as a sheet. Each row is
matched against the postes' chassis serial (``machines.hw_serial``) — the
sticker an asset tag copies — and the import first says what it *would*
write, row by row, before writing it (``dry_run``).

Headers are recognised in French or in English, accents, case and spaces
aside; unknown columns are ignored. A row's fields are each optional except
the serial: an empty cell leaves the stored value alone.
"""

import csv
import io
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import chain, islice
from typing import Any

from app.features.asset.models import AssetStatus

MAX_ROWS = 5000
# Rows read at most, empty ones included: a sheet formatted down to its
# millionth row is refused before it is read whole — as such, not as a
# sheet of too many postes. Far above what a template formatted a few
# thousand rows down holds.
MAX_RAW_ROWS = 20 * MAX_ROWS
# Rows looked at for the header, below a title or a blank line or two.
HEADER_ROWS = 10
# The CSV delimiters tried, in the order a tie is settled: the French Excel's
# first.
DELIMITERS = ";,\t"

# Normalised header → field. Normalised: lower case, no accent, letters and
# digits only (« N° de série » → « ndeserie »).
HEADERS: dict[str, str] = {}
for _field, _names in {
    "serial": [
        "serial",
        "serialnumber",
        "numeroserie",
        "numerodeserie",
        "ndeserie",
        "nserie",
        "serie",
        "sn",
    ],
    "inventory_number": [
        "inventorynumber",
        "inventory",
        "assettag",
        "numeroinventaire",
        "numerodinventaire",
        "ninventaire",
        "ndinventaire",
        "noinventaire",
        "inventaire",
        # The export's own headers (``machine_export``), read back.
        "inventoryno",
    ],
    "status": ["status", "statut", "etat", "statutdelactif", "assetstatus"],
    "purchase_date": ["purchasedate", "dateachat", "datedachat", "achat"],
    "supplier": ["supplier", "vendor", "fournisseur"],
    "order_reference": [
        "orderreference",
        "order",
        "referencecommande",
        "refcommande",
        "commande",
        "bondecommande",
    ],
    "warranty_end": [
        "warrantyend",
        "warranty",
        "fingarantie",
        "findegarantie",
        "garantie",
    ],
    "purchase_price": ["purchaseprice", "price", "prix", "prixachat", "prixdachat"],
    "notes": ["notes", "note", "comment", "comments", "commentaire", "remarques"],
}.items():
    for _name in _names:
        HEADERS[_name] = _field

# Statuses in either language, normalised like the headers.
STATUSES: dict[str, str] = {
    "instock": AssetStatus.IN_STOCK,
    "stock": AssetStatus.IN_STOCK,
    "enstock": AssetStatus.IN_STOCK,
    "inservice": AssetStatus.IN_SERVICE,
    "service": AssetStatus.IN_SERVICE,
    "enservice": AssetStatus.IN_SERVICE,
    "inrepair": AssetStatus.IN_REPAIR,
    "repair": AssetStatus.IN_REPAIR,
    "enreparation": AssetStatus.IN_REPAIR,
    "reparation": AssetStatus.IN_REPAIR,
    "onloan": AssetStatus.ON_LOAN,
    "loan": AssetStatus.ON_LOAN,
    "prete": AssetStatus.ON_LOAN,
    "pret": AssetStatus.ON_LOAN,
    "retired": AssetStatus.RETIRED,
    "reforme": AssetStatus.RETIRED,
}
for _status in AssetStatus:
    STATUSES[_status.value.replace("_", "")] = _status


def normalise(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.lower())


class UnreadableFile(ValueError):
    """Neither a CSV nor a workbook this importer can read, or no serial
    column in it. ``args[0]`` is the cause's code."""


class TooManyRows(ValueError):
    """Over a limit: more than ``MAX_ROWS`` postes (« too_many_rows »: to be
    split), or more than ``MAX_RAW_ROWS`` rows, most of them empty
    (« too_many_blank_rows »: the empty rows below the data to delete).
    ``args[0]`` is the cause, ``limit`` the number."""

    def __init__(self, cause: str = "too_many_rows", limit: int = MAX_ROWS) -> None:
        super().__init__(cause)
        self.cause = cause
        self.limit = limit


def _too_many_blank_rows() -> TooManyRows:
    return TooManyRows("too_many_blank_rows", MAX_RAW_ROWS)


@dataclass
class ImportRow:
    line: int
    serial: str
    values: dict[str, Any] = field(default_factory=dict)
    # Codes of the cells that could not be read: « purchase_date », …
    errors: list[str] = field(default_factory=list)


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnreadableFile("encoding")


def _dialect(delimiter: str) -> Any:
    class Dialect(csv.excel):
        pass

    Dialect.delimiter = delimiter
    return Dialect


def _header_of(rows: Iterable[list[Any]]) -> tuple[int, dict[int, str]] | None:
    """Where the header is in the first rows — the first naming a serial
    column — and the field of each column it names."""
    for index, header_row in enumerate(islice(rows, HEADER_ROWS)):
        found = {
            i: HEADERS[normalise(str(cell))]
            for i, cell in enumerate(header_row)
            if cell is not None and normalise(str(cell)) in HEADERS
        }
        if "serial" in found.values():
            return index, found
    return None


def _rows_of_csv(content: bytes) -> Iterator[list[Any]]:
    text = _decode(content)
    # The delimiter is the one that splits a header out of the first rows —
    # below a title line too, which names no column. Not ``csv.Sniffer``: an
    # apostrophe in a header (« N° d'inventaire ») makes it take « ' » for
    # the quote character and swallow whole rows. On a tie, the delimiter
    # that cuts the header line into the most cells (« N° de série; » is one
    # cell to « , » and to a tab, two to « ; »), then « ; », « , », tab.
    best: tuple[int, int, int, int, str] | None = None
    for order, delimiter in enumerate(DELIMITERS):
        try:
            rows = csv.reader(io.StringIO(text), _dialect(delimiter))
            head = list(islice(rows, HEADER_ROWS))
        except csv.Error:
            # A quote this delimiter opens and never closes: not this one.
            continue
        header = _header_of(head)
        if header is None:
            continue
        index, columns = header
        rank = (index, -len(columns), -len(head[index]), order, delimiter)
        if best is None or rank < best:
            best = rank
    delimiter = best[4] if best is not None else DELIMITERS[0]
    return _guarded(csv.reader(io.StringIO(text), _dialect(delimiter)))


def _guarded(rows: Iterator[list[Any]]) -> Iterator[list[Any]]:
    """The rows, a CSV the reader cannot follow (a quote never closed over
    128 KB) refused as unreadable rather than failing the request."""
    try:
        yield from rows
    except csv.Error as exc:
        raise UnreadableFile("csv") from exc


def _rows_of_xlsx(content: bytes) -> Iterator[list[Any]]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # zip, XML: whatever the file is, it is not one
        raise UnreadableFile("xlsx") from exc
    sheet = workbook.worksheets[0]
    if sheet.max_row is not None and sheet.max_row > MAX_RAW_ROWS + HEADER_ROWS:
        raise _too_many_blank_rows()
    return (list(r) for r in sheet.iter_rows(values_only=True))


def _date(value: Any) -> date | None:
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(text)


def _blank(value: Any) -> bool:
    """An empty cell — a stray space too: it leaves the stored value alone."""
    return value is None or (isinstance(value, str) and value.strip() == "")


_THOUSANDS_OR_DECIMALS = re.compile(r"\d{1,3}[.,]\d{3}")


def _price(value: Any) -> Decimal | None:
    if _blank(value):
        return None
    if isinstance(value, (int, float, Decimal)):
        amount = Decimal(str(value))
    else:
        text = re.sub(r"[\s€$  ]", "", str(value))
        # « 1 234,56 » and « 1,234.56 » alike.
        if "," in text and "." in text:
            text = (
                text.replace(",", "")
                if text.rfind(".") > text.rfind(",")
                else (text.replace(".", "").replace(",", "."))
            )
        else:
            text = text.replace(",", ".")
        amount = Decimal(text)
    if amount < 0 or amount >= Decimal("1e10"):
        raise InvalidOperation(str(value))
    # Written with more than two decimals is a thousands separator read as
    # a decimal point (« 1,299 », « 125.000 »): refused, never rounded to
    # 1.30. A number cell of a workbook is a number, and is rounded.
    if isinstance(value, str):
        # « 1,299 », « 125.000 »: three digits after a single separator is a
        # thousands group as much as decimals — refused, never read as 1.30.
        if _THOUSANDS_OR_DECIMALS.fullmatch(re.sub(r"[\s€$  ]", "", value)):
            raise InvalidOperation(str(value))
        # More than two decimals that count (« 749.9000 » is 749.90).
        exponent = amount.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise InvalidOperation(str(value))
    return amount.quantize(Decimal("0.01"))


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def parse(filename: str, content: bytes) -> list[ImportRow]:
    """The rows of an import file, read and typed, not yet matched. CPU work:
    the route runs it off the event loop."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        table = _rows_of_xlsx(content)
    else:
        table = _rows_of_csv(content)
    try:
        head = list(islice(table, HEADER_ROWS))
    except csv.Error as exc:
        raise UnreadableFile("csv") from exc
    header = _header_of(head)
    if header is None:
        raise UnreadableFile("no_serial_column")
    header_index, columns = header

    rows: list[ImportRow] = []
    lines = chain(head[header_index + 1 :], table)
    for offset, raw in enumerate(lines, start=header_index + 2):
        if offset > MAX_RAW_ROWS + header_index + 1:
            raise _too_many_blank_rows()
        cells = {name: raw[i] if i < len(raw) else None for i, name in columns.items()}
        serial = _text(cells.get("serial"), 200)
        if serial is None:
            if any(not _blank(v) for v in cells.values()):
                rows.append(ImportRow(offset, "", errors=["serial"]))
            continue
        row = ImportRow(offset, serial)
        for name, value in cells.items():
            if name == "serial" or _blank(value):
                continue
            try:
                if name in ("purchase_date", "warranty_end"):
                    row.values[name] = _date(value)
                elif name == "purchase_price":
                    row.values[name] = _price(value)
                elif name == "status":
                    status = STATUSES.get(normalise(str(value)))
                    if status is None:
                        raise ValueError(value)
                    row.values[name] = str(status)
                elif name == "inventory_number":
                    row.values[name] = _text(value, 100)
                elif name == "notes":
                    row.values[name] = _text(value, 5000)
                else:
                    row.values[name] = _text(value, 200)
            except (ValueError, InvalidOperation):
                row.errors.append(name)
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise TooManyRows()
    return rows

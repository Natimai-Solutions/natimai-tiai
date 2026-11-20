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
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.features.asset.models import AssetStatus

MAX_ROWS = 5000

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
    ],
    "status": ["status", "statut", "etat"],
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
    column in it."""


@dataclass
class ImportRow:
    line: int
    serial: str
    values: dict[str, Any] = field(default_factory=dict)
    # Codes of the cells that could not be read: « purchase_date », …
    errors: list[str] = field(default_factory=list)


def _rows_of_csv(content: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UnreadableFile("encoding")
    # The delimiter is the one the header line uses most. Not
    # ``csv.Sniffer``: an apostrophe in a header (« N° d'inventaire ») makes
    # it take « ' » for the quote character and swallow whole rows.
    first_line = text.split("\n", 1)[0]
    delimiter = max(";,\t", key=first_line.count)

    class Dialect(csv.excel):
        pass

    Dialect.delimiter = delimiter
    dialect: Any = Dialect
    return [list(r) for r in csv.reader(io.StringIO(text), dialect)]


def _rows_of_xlsx(content: bytes) -> list[list[Any]]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # zip, XML: whatever the file is, it is not one
        raise UnreadableFile("xlsx") from exc
    sheet = workbook.worksheets[0]
    return [list(r) for r in sheet.iter_rows(values_only=True)]


def _date(value: Any) -> date | None:
    if value is None or value == "":
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


def _price(value: Any) -> Decimal | None:
    if value is None or value == "":
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
    return amount.quantize(Decimal("0.01"))


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def parse(filename: str, content: bytes) -> list[ImportRow]:
    """The rows of an import file, read and typed, not yet matched."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        table = _rows_of_xlsx(content)
    else:
        table = _rows_of_csv(content)
    # The header is the first row naming a serial column.
    header_index = None
    columns: dict[int, str] = {}
    for index, header_row in enumerate(table[:10]):
        found = {
            i: HEADERS[normalise(str(cell))]
            for i, cell in enumerate(header_row)
            if cell is not None and normalise(str(cell)) in HEADERS
        }
        if "serial" in found.values():
            header_index, columns = index, found
            break
    if header_index is None:
        raise UnreadableFile("no_serial_column")

    rows: list[ImportRow] = []
    for offset, raw in enumerate(table[header_index + 1 :], start=header_index + 2):
        cells = {name: raw[i] if i < len(raw) else None for i, name in columns.items()}
        serial = _text(cells.get("serial"), 200)
        if serial is None:
            if any(v not in (None, "") for v in cells.values()):
                rows.append(ImportRow(offset, "", errors=["serial"]))
            continue
        row = ImportRow(offset, serial)
        for name, value in cells.items():
            if name == "serial" or value is None or value == "":
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
            raise UnreadableFile("too_many_rows")
    return rows

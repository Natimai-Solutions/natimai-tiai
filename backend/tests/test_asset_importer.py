"""The asset import's reader, alone (pure): encodings, the delimiter below a
title line, the export's own headers read back, prices, blank cells, statuses
and the limits."""

from datetime import date
from decimal import Decimal

import pytest

from app.features.asset import importer


def _row(rows, line):
    return next(r for r in rows if r.line == line)


def test_french_excel_csv_in_cp1252():
    content = (
        "N° de série;Statut;Fournisseur;Référence commande;Notes;Prix\n"
        "SN-1;prêté;Société;BC-12;À rendre;1,234.50\n"
    ).encode("cp1252")
    [row] = importer.parse("parc.csv", content)
    assert row.serial == "SN-1"
    assert row.errors == []
    assert row.values == {
        "status": "on_loan",
        "supplier": "Société",
        "order_reference": "BC-12",
        "notes": "À rendre",
        "purchase_price": Decimal("1234.50"),
    }


@pytest.mark.parametrize(
    ("cell", "price"),
    [
        ("1 234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("749,90 €", Decimal("749.90")),
        ("749,9", Decimal("749.90")),
        ("125000", Decimal("125000.00")),
    ],
)
def test_prices_that_read(cell, price):
    [row] = importer.parse("p.csv", f"Serial;Prix\nSN-1;{cell}\n".encode())
    assert row.errors == []
    assert row.values["purchase_price"] == price


@pytest.mark.parametrize(
    "cell",
    [
        # A thousands separator read as a decimal point: refused, not 1.30.
        "1,299",
        "125.000",
        "-5",
        "1e11",
        "beaucoup",
    ],
)
def test_prices_that_do_not(cell):
    [row] = importer.parse("p.csv", f"Serial;Prix\nSN-1;{cell}\n".encode())
    assert row.errors == ["purchase_price"]
    assert "purchase_price" not in row.values


def test_a_blank_cell_leaves_the_value_alone():
    content = b"Serial;Inventaire;Fournisseur;Notes;Prix\nSN-1; ;  ;\t; \n"
    [row] = importer.parse("p.csv", content)
    assert row.errors == []
    assert row.values == {}
    # A row of blanks only, serial included, is no row at all.
    assert importer.parse("p.csv", b"Serial;Notes\n ; \n") == []


def test_unknown_status_is_an_error_of_its_cell():
    [row] = importer.parse("p.csv", b"Serial;Statut\nSN-1;perdu\n")
    assert row.errors == ["status"]


@pytest.mark.parametrize(
    "content",
    [
        # A title line naming no column, above a comma-separated sheet.
        b"Livraison du 12/03/2024\nSerial number,Purchase date\nSN-1,2024-03-12\n",
        # A title with a comma, above a semicolon-separated one.
        b"Export, mars 2024\n\nN\xc2\xb0 de s\xc3\xa9rie;Date d'achat\nSN-1;12/03/2024\n",
        b"Serial\tPurchase date\nSN-1\t2024-03-12\n",
    ],
)
def test_the_delimiter_is_the_header_lines(content):
    [row] = importer.parse("p.csv", content)
    assert row.serial == "SN-1"
    assert row.values == {"purchase_date": date(2024, 3, 12)}


@pytest.mark.parametrize("language", ["fr", "en"])
def test_the_exports_own_headers_read_back(language):
    """An export of the parc, filled in and imported again."""
    from app.api.machine_export import EXPORT_TEXTS, column_label, resolve_columns
    from app.features.user.models import Language

    lang = Language(language)
    keys = [
        "hostname",
        "hw_serial",
        "asset_inventory_number",
        "asset_status",
        "asset_purchase_date",
        "asset_warranty_end",
        "asset_supplier",
    ]
    columns = resolve_columns(",".join(keys))
    header = ";".join(column_label(c, lang) for c in columns)
    statuses = EXPORT_TEXTS[lang].asset_status
    lines = [header]
    for i, label in enumerate(statuses.values()):
        lines.append(f"PC-{i};SN-{i};INV-{i};{label};2024-03-12;2027-03-12;Dell")
    rows = importer.parse("export.csv", "\n".join(lines).encode())
    assert len(rows) == len(statuses)
    for row, code in zip(rows, statuses, strict=True):
        assert row.errors == []
        assert row.values["status"] == code
        assert row.values["inventory_number"].startswith("INV-")
        assert row.values["purchase_date"] == date(2024, 3, 12)
        assert row.values["warranty_end"] == date(2027, 3, 12)
        assert row.values["supplier"] == "Dell"


def test_no_serial_column_is_unreadable():
    with pytest.raises(importer.UnreadableFile) as exc:
        importer.parse("p.csv", b"nom;prix\nPC;1\n")
    assert exc.value.args[0] == "no_serial_column"


def test_too_many_rows():
    rows = "\n".join(f"SN-{i};1" for i in range(importer.MAX_ROWS + 1))
    with pytest.raises(importer.TooManyRows):
        importer.parse("p.csv", f"Serial;Prix\n{rows}\n".encode())
    # Exactly the limit reads.
    rows = "\n".join(f"SN-{i};1" for i in range(importer.MAX_ROWS))
    assert len(importer.parse("p.csv", f"Serial;Prix\n{rows}\n".encode())) == (
        importer.MAX_ROWS
    )


def test_empty_rows_count_towards_a_limit_too():
    """A sheet formatted far down is refused before it is read whole."""
    blanks = ";\n" * (importer.MAX_RAW_ROWS + 1)
    with pytest.raises(importer.TooManyRows):
        importer.parse("p.csv", f"Serial;Prix\n{blanks}".encode())


def test_a_workbook_formatted_far_down_is_refused_on_its_size():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Serial number", "Price"])
    ws.cell(row=importer.MAX_RAW_ROWS + 50, column=1, value="SN-LAST")
    buffer = io.BytesIO()
    wb.save(buffer)
    with pytest.raises(importer.TooManyRows):
        importer.parse("parc.xlsx", buffer.getvalue())

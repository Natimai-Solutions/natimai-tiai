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
        # Accounting exports: zeros past the cents, not a thousands group.
        ("1299.9900", Decimal("1299.99")),
        ("749,9000", Decimal("749.90")),
        ("0.5000", Decimal("0.50")),
        ("1 299,00", Decimal("1299.00")),
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
        "0,500",
        # Three decimals that count.
        "1234.567",
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


def test_empty_rows_count_towards_a_limit_of_their_own():
    """A sheet formatted far down is refused before it is read whole — as
    such: its empty rows are to delete, not its postes to split."""
    blanks = ";\n" * (importer.MAX_RAW_ROWS + 1)
    with pytest.raises(importer.TooManyRows) as exc:
        importer.parse("p.csv", f"Serial;Prix\n{blanks}".encode())
    assert exc.value.cause == "too_many_blank_rows"
    assert exc.value.limit == importer.MAX_RAW_ROWS


def test_a_template_formatted_a_few_thousand_rows_down_still_reads():
    rows = "\n".join(f"SN-{i};1" for i in range(300))
    blanks = ";;;\n" * 11_700
    parsed = importer.parse("p.csv", f"Serial;Prix\n{rows}\n{blanks}".encode())
    assert len(parsed) == 300


def test_a_workbook_formatted_far_down_is_refused_on_its_size():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Serial number", "Price"])
    ws.cell(row=importer.MAX_RAW_ROWS + 50, column=1, value="SN-LAST")
    buffer = io.BytesIO()
    wb.save(buffer)
    with pytest.raises(importer.TooManyRows) as exc:
        importer.parse("parc.xlsx", buffer.getvalue())
    assert exc.value.cause == "too_many_blank_rows"


def test_a_cell_on_two_lines_does_not_trip_the_other_delimiters():
    """Excel writes a cell with a line break (Alt+Entrée) between quotes: read
    with « , », its closing quote opens a field that swallows the file —
    that delimiter is passed over, not the request failed."""
    # Over 128 KB after the quote: the size at which csv gives up.
    rows = "\n".join(
        f"SN-{i};Remarque sans guillemet, ligne {i:04d} du bon;Dell"
        for i in range(1, 4001)
    )
    content = f'Serial;Notes;Fournisseur\nSN-0;"Écran cassé\n";Dell\n{rows}\n'
    assert len(content) > 131_072
    parsed = importer.parse("p.csv", content.encode())
    assert len(parsed) == 4001
    assert parsed[0].values == {"notes": "Écran cassé", "supplier": "Dell"}


def test_a_quote_never_closed_is_unreadable_not_a_crash():
    content = 'Serial;Notes\nSN-0;"' + "x" * 140_000 + "\n"
    with pytest.raises(importer.UnreadableFile) as exc:
        importer.parse("p.csv", content.encode())
    assert exc.value.args[0] == "csv"


@pytest.mark.parametrize(
    "header",
    ["N° de série;", "Serial;;", "Serial;", "N° de série;Notes"],
)
def test_a_trailing_empty_column_keeps_the_semicolon(header):
    """« N° de série; » is one cell to « , » and to a tab: « ; » wins the tie,
    and the serial does not carry the delimiter."""
    [row] = importer.parse("p.csv", f"{header}\nSN-1;\n".encode())
    assert row.serial == "SN-1"

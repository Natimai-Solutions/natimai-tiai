"""Exports in the language the console asks for (plan
``dev/plan-console-bilingue.md``, I4): ``lang=fr|en`` on the fleet and
software exports and on the column catalogue.

French when absent, byte for byte the file it was before ``lang`` existed:
a script, or a console older than this server, gets what it always got. The
French headers and words are pinned here in full.

The route tests require TIAI_TEST_DATABASE_URL; the words of the values are
pure functions over an ``ExportRow``.
"""

import csv as _csv
import io
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook

from app.features.user.models import Language
from tests.test_api_inventory import (  # noqa: F401  (fixtures come from conftest)
    _enroll,
    _heartbeat,
    _inventory,
)
from tests.test_api_inventory_fleet import _admin_headers, _poste, _software

ALL_FR = (
    "Nom;Domaine;Emplacement;Bâtiment;Salle;Emplacement divergent;"
    "Vérification demandée;Vérification affectée à;Vérification : consignes;"
    "Maintenance;Maintenance due le;Responsable maintenance;Dernière maintenance;"
    "Adresse IP;Adresse MAC;OS;Architecture;UUID machine;Version agent;Session;"
    "Allumé;Heures allumées (7 j);À vérifier;Vu le;Premier contact;Antivirus;"
    "Antivirus à jour;Protection active;Protection temps réel (Defender);"
    "Mode Defender;Version signatures;Signatures mises à jour le;"
    "Âge signatures (j);Dernier scan rapide;Dernier scan complet;MAJ en attente;"
    "Redémarrage requis;Dernière recherche MAJ;Dernière installation MAJ;"
    "Constructeur;Modèle;N° de série;Châssis;Machine virtuelle;Hyperviseur;"
    "Carte mère (constructeur);Carte mère (modèle);BIOS (éditeur);BIOS;Date BIOS;"
    "Secure Boot;TPM;Processeur;Processeur (fabricant);Cœurs;Threads;"
    "Fréquence (MHz);Processeurs;RAM (Gio);RAM (Mio);Barrettes utilisées;"
    "Emplacements mémoire;Disque système (Mio);Libre (Mio);Libre (%);"
    "Windows installé le;Dernier démarrage;Inventaire du"
)
ALL_EN = (
    "Name;Domain;Location;Building;Room;Location mismatch;Check requested;"
    "Check assigned to;Check: instructions;Maintenance;Maintenance due on;"
    "Maintenance owner;Last maintenance;IP address;MAC address;OS;Architecture;"
    "Machine UUID;Agent version;Session;On;Hours on (7 d);Identity to confirm;"
    "Last seen;First contact;Antivirus;Antivirus up to date;Protection on;"
    "Real-time protection (Defender);Defender mode;Signature version;"
    "Signatures updated on;Signature age (days);Last quick scan;Last full scan;"
    "Updates pending;Restart required;Last update search;Last update install;"
    "Manufacturer;Model;Serial number;Chassis;Virtual machine;Hypervisor;"
    "Motherboard (manufacturer);Motherboard (model);BIOS (vendor);BIOS;BIOS date;"
    "Secure Boot;TPM;Processor;Processor (manufacturer);Cores;Threads;"
    "Frequency (MHz);Processors;RAM (GiB);RAM (MiB);Memory sticks used;"
    "Memory slots;System disk (MiB);Free (MiB);Free (%);Windows installed on;"
    "Last boot;Inventory date"
)


def _all_columns() -> str:
    from app.api.machine_export import COLUMNS

    return ",".join(c.key for c in COLUMNS)


# --- The catalogue ------------------------------------------------------------------


def test_every_column_has_its_english_label():
    from app.api.machine_export import COLUMN_LABELS_EN, COLUMNS, EXPORT_TEXTS

    assert set(COLUMN_LABELS_EN) == {c.key for c in COLUMNS}
    groups = {c.group for c in COLUMNS}
    for texts in EXPORT_TEXTS.values():
        assert set(texts.groups) == groups
    fr, en = EXPORT_TEXTS[Language.FR], EXPORT_TEXTS[Language.EN]
    assert set(en.chassis) == set(fr.chassis)
    assert set(en.maintenance) == set(fr.maintenance)


async def test_the_catalogue_is_listed_in_the_language_asked(client, db_session):
    headers = await _admin_headers(client, db_session)
    url = "/api/v1/machines/export-columns"
    default = (await client.get(url, headers=headers)).json()
    french = (await client.get(f"{url}?lang=fr", headers=headers)).json()
    english = (await client.get(f"{url}?lang=en", headers=headers)).json()

    assert french == default
    fr_by_key = {c["key"]: c for c in french}
    en_by_key = {c["key"]: c for c in english}
    assert fr_by_key["cpu_model"]["label"] == "Processeur"
    assert fr_by_key["cpu_model"]["group_label"] == "Matériel"
    assert en_by_key["cpu_model"]["label"] == "Processor"
    assert en_by_key["cpu_model"]["group_label"] == "Hardware"
    # Only the words change: keys, groups, kinds and defaults are the same.
    strip = [
        {k: v for k, v in c.items() if k not in ("label", "group_label")}
        for c in english
    ]
    assert strip == [
        {k: v for k, v in c.items() if k not in ("label", "group_label")}
        for c in french
    ]


# --- The fleet export -----------------------------------------------------------


async def test_the_french_file_is_the_one_it_always_was(client, db_session):
    """No ``lang`` and ``lang=fr``: the same bytes, with today's headers."""
    headers = await _admin_headers(client, db_session)
    await _poste(client, "lang-fr", hostname="PC-FR")
    url = f"/api/v1/machines/export.csv?columns={_all_columns()}"

    default = await client.get(url, headers=headers)
    french = await client.get(f"{url}&lang=fr", headers=headers)
    assert default.status_code == 200, default.text
    assert french.content == default.content
    assert 'filename="parc.csv"' in default.headers["content-disposition"]
    assert default.text.lstrip("﻿").splitlines()[0] == ALL_FR


async def test_the_english_file(client, db_session):
    headers = await _admin_headers(client, db_session)
    await _poste(client, "lang-en", hostname="PC-EN")

    csv = await client.get(
        f"/api/v1/machines/export.csv?columns={_all_columns()}&lang=en",
        headers=headers,
    )
    assert csv.status_code == 200, csv.text
    assert 'filename="fleet.csv"' in csv.headers["content-disposition"]
    rows = list(_csv.reader(io.StringIO(csv.text.lstrip("﻿")), delimiter=","))
    # Comma-separated, as an English Excel reads it; the BOM is kept.
    assert rows[0] == ALL_EN.split(";")
    assert csv.text.startswith("﻿")
    assert csv.text.lstrip("﻿").startswith("Name,Domain,Location,")

    xlsx = await client.get(
        "/api/v1/machines/export.xlsx?columns=hostname,ram_total_gb,secure_boot&lang=en",
        headers=headers,
    )
    assert xlsx.status_code == 200, xlsx.text
    assert 'filename="fleet.xlsx"' in xlsx.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(xlsx.content))
    assert workbook.sheetnames == ["Fleet"]
    sheet = workbook["Fleet"]
    assert [c.value for c in sheet[1]] == ["Name", "RAM (GiB)", "Secure Boot"]
    assert [c.value for c in sheet[2]] == ["PC-EN", 32, "Yes"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/machines/export.csv",
        "/api/v1/machines/export.xlsx",
        "/api/v1/machines/export-columns",
        "/api/v1/software/export.csv",
        "/api/v1/software/export.xlsx",
    ],
)
async def test_an_unknown_language_is_refused(client, db_session, path):
    """A 422 rather than a French file that was not asked for."""
    headers = await _admin_headers(client, db_session)
    for lang in ("de", "EN", ""):
        resp = await client.get(f"{path}?lang={lang}", headers=headers)
        assert resp.status_code == 422, (lang, resp.text)
        assert resp.json()["error"]["code"] == "request.validation_error"


# --- The words of the values --------------------------------------------------------


def _row(language: Language, **machine):
    from app.api.machine_export import ExportRow
    from app.features.machine.models import Machine
    from app.features.maintenance.policy import MaintenanceState, Resolved

    return ExportRow(
        machine=Machine(machine_uuid="u-1", **machine),
        maintenance=Resolved(
            cycle_days=365,
            cycle_origin="fleet",
            owner_id=None,
            owner_origin="fleet",
            due_at=None,
            state=MaintenanceState.OVERDUE,
        ),
        language=language,
    )


def _cells(language: Language, keys: str, **machine) -> list[object]:
    from app.api.machine_export import csv_value, resolve_columns

    row = _row(language, **machine)
    utc = ZoneInfo("UTC")
    return [csv_value(c, c.read(row), utc, language) for c in resolve_columns(keys)]


def test_a_decimal_is_written_as_the_files_language_writes_it():
    """« 4,9 » in the semicolon-separated French file, « 4.9 » in the English
    one: each as the Excel of that language reads a number."""
    from app.api.machine_export import csv_value, resolve_columns

    (column,) = resolve_columns("usage_hours")
    utc = ZoneInfo("UTC")
    assert csv_value(column, 4.9, utc, Language.FR) == "4,9"
    assert csv_value(column, 4.9, utc, Language.EN) == "4.9"


KEYS = "hw_chassis_type,session,av_product_name,maintenance_state,hw_is_virtual"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (Language.FR, ["Portable", "Aucun utilisateur", "Aucun", "En retard", "Oui"]),
        (Language.EN, ["Laptop", "No user", "None", "Overdue", "Yes"]),
    ],
)
def test_the_values_are_worded_in_the_files_language(language, expected):
    assert (
        _cells(
            language,
            KEYS,
            hw_chassis_type="laptop",
            session_user_present=False,
            av_product_name="",
            hw_is_virtual=True,
        )
        == expected
    )


def test_the_french_words_are_the_ones_they_always_were():
    from app.api.machine_export import EXPORT_TEXTS
    from app.features.maintenance.policy import MaintenanceState

    fr = EXPORT_TEXTS[Language.FR]
    assert fr.yes_no == {True: "Oui", False: "Non"}
    assert fr.chassis == {
        "desktop": "Poste fixe",
        "laptop": "Portable",
        "tablet": "Tablette",
        "all-in-one": "Tout-en-un",
        "server": "Serveur",
    }
    assert fr.maintenance == {
        MaintenanceState.EXCLUDED: "Exclu",
        MaintenanceState.OVERDUE: "En retard",
        MaintenanceState.DUE_SOON: "À échéance",
        MaintenanceState.OK: "À jour",
    }
    assert fr.groups == {
        "identity": "Identité",
        "antivirus": "Antivirus",
        "windows_update": "Windows Update",
        "hardware": "Matériel",
    }
    assert (fr.no_user, fr.user_present, fr.no_antivirus) == (
        "Aucun utilisateur",
        "Utilisateur connecté",
        "Aucun",
    )
    assert (fr.sheet_title, fr.file_stem) == ("Parc", "parc")


def test_a_logged_on_session_and_a_value_kept_as_reported():
    """A user's name and an unknown chassis kind are data, never translated."""
    assert _cells(
        Language.EN,
        "session,hw_chassis_type",
        session_user_present=True,
        hw_chassis_type="rack",
    ) == ["User logged on", "rack"]
    assert _cells(
        Language.EN, "session", session_user_present=True, session_username="eleve"
    ) == ["eleve"]


def test_the_workbook_writes_booleans_in_the_files_language():
    from app.api.machine_export import resolve_columns, xlsx_value

    (column,) = resolve_columns("secure_boot")
    utc = ZoneInfo("UTC")
    assert xlsx_value(column, False, utc) == "Non"
    assert xlsx_value(column, False, utc, Language.EN) == "No"
    when = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)
    (seen,) = resolve_columns("last_seen")
    assert xlsx_value(seen, when, utc, Language.EN) == xlsx_value(seen, when, utc)


# --- The software export -----------------------------------------------------------


async def test_the_software_export_in_both_languages(client, db_session):
    headers = await _admin_headers(client, db_session)
    await _poste(client, "lang-soft", software=[_software("Café Tool", "1.0")])

    default = await client.get("/api/v1/software/export.csv", headers=headers)
    french = await client.get("/api/v1/software/export.csv?lang=fr", headers=headers)
    assert french.content == default.content
    assert 'filename="logiciels.csv"' in default.headers["content-disposition"]
    assert default.text.lstrip("﻿").splitlines()[0] == (
        "Nom;Version;Éditeur;Postes;Vu pour la première fois"
    )

    english = await client.get("/api/v1/software/export.csv?lang=en", headers=headers)
    assert 'filename="software.csv"' in english.headers["content-disposition"]
    lines = english.text.lstrip("﻿").splitlines()
    assert lines[0] == "Name,Version,Publisher,Computers,First seen"
    assert lines[1].startswith("Café Tool,1.0,Acme,1,")

    xlsx = await client.get("/api/v1/software/export.xlsx?lang=en", headers=headers)
    assert 'filename="software.xlsx"' in xlsx.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(xlsx.content))
    assert workbook.sheetnames == ["Software"]
    assert [c.value for c in workbook["Software"][1]] == [
        "Name",
        "Version",
        "Publisher",
        "Computers",
        "First seen",
    ]

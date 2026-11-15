"""Software deployment, third verification pass of the 2026-11 audit: what the
server accepted and every poste then refused (T23), what a retirement left
behind (T08), what a signer could not see (T38), and what two requests at
once, or a store that lost a file, did to a package.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import asyncio
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlmodel import col, select

from tests.test_api_packages import (
    _admin,
    _cert,
    _command,
    _deploy,
    _enroll,
    _pronote,
    _signature_document,
    _uninstall,
    signed_pe,
)

PRODUCT_CODE = "{6C2A1A7B-0D5E-4F1C-9E4B-3B1C2D3E4F50}"
GIB = 1024**3


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PACKAGES_DIR", str(tmp_path / "packages"))
    return tmp_path / "packages"


async def _upload(client, admin, package_id, *files):
    return await client.post(
        f"/api/v1/packages/{package_id}/files",
        headers=admin,
        files=[("files", f) for f in files],
    )


async def _get(client, admin, package_id):
    resp = await client.get(f"/api/v1/packages/{package_id}", headers=admin)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _manifest(client, admin, package_id):
    resp = await client.get(f"/api/v1/packages/{package_id}/manifest", headers=admin)
    assert resp.status_code == 200, resp.text
    return resp.content


async def _sign(client, admin, package_id):
    key = ec.generate_private_key(ec.SECP256R1())
    document = _signature_document(
        await _manifest(client, admin, package_id), key, _cert(key, "Tiai")
    )
    return await client.put(
        f"/api/v1/packages/{package_id}/signature", headers=admin, json=document
    )


async def _heartbeat(client, agent):
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    assert hb.status_code == 200, hb.text
    return hb.json()["commands"]


async def _set_sizes(db_session, package_id, sizes: dict[str, int]):
    """Give files a size no test could upload: the store is not asked."""
    from app.features.package.models import PackageFile

    rows = await db_session.exec(
        select(PackageFile).where(col(PackageFile.package_id) == package_id)
    )
    for row in rows.all():
        if row.name in sizes:
            row.size = sizes[row.name]
            db_session.add(row)
    await db_session.commit()


# --- 1. names differing only by case (T23) -----------------------------------------


async def test_a_name_differing_only_by_case_replaces_the_file(
    client, db_session, store
):
    """One file on Windows, and a manifest the agent refuses whole
    (deploy.ParseManifest): ``A.INI`` takes the place of ``a.ini``."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    first = await _upload(client, admin, package["id"], ("a.ini", b"[one]\n"))
    assert first.status_code == 200, first.text
    old_sha = hashlib.sha256(b"[one]\n").hexdigest()
    assert (store / old_sha).exists()

    second = await _upload(client, admin, package["id"], ("A.INI", b"[two]\n"))
    assert second.status_code == 200, second.text
    body = second.json()
    names = [f["name"] for f in body["files"]]
    assert "A.INI" in names
    assert "a.ini" not in names
    assert body["problems"] == []
    # The replaced file left the store, as one replaced under its exact name.
    assert not (store / old_sha).exists()
    manifest = json.loads(await _manifest(client, admin, package["id"]))
    lowered = [f["name"].lower() for f in manifest["files"]]
    assert len(lowered) == len(set(lowered))

    # What the agent would now accept goes out.
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    (command,) = await _heartbeat(client, agent)
    delivered = json.loads(base64.b64decode(command["package"]["manifest"]))
    assert [f["name"] for f in delivered["files"] if f["name"].lower() == "a.ini"] == [
        "A.INI"
    ]


async def test_the_step_follows_its_file_to_a_new_spelling(client, db_session, store):
    """Replacing the installer under another case must not leave the package
    naming a file it no longer has."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    up = await _upload(
        client,
        admin,
        package["id"],
        ("INSTALL_PRNCLIENT.EXE", signed_pe("INDEX EDUCATION SAS")),
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["install_run"] == "INSTALL_PRNCLIENT.EXE"
    assert body["problems"] == []
    assert body["publisher_name"] == "INDEX EDUCATION SAS"
    manifest = json.loads(await _manifest(client, admin, package["id"]))
    assert manifest["install"]["run"] == "INSTALL_PRNCLIENT.EXE"


async def test_two_spellings_of_one_name_in_a_request_are_refused(
    client, db_session, store
):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    before = {p.name for p in store.iterdir()}
    resp = await _upload(
        client, admin, package["id"], ("a.ini", b"[one]\n"), ("A.INI", b"[two]\n")
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "package.file.name_invalid"
    # Neither is kept, in the package or in the store.
    assert {p.name for p in store.iterdir()} == before
    names = {f["name"] for f in (await _get(client, admin, package["id"]))["files"]}
    assert names == {"Install_PRNclient.exe", "ClientPRONOTE.iss"}

    # One spelling given twice is not two names: the last one is kept, as ever.
    twice = await _upload(
        client, admin, package["id"], ("b.ini", b"[one]\n"), ("b.ini", b"[two]\n")
    )
    assert twice.status_code == 200, twice.text
    (kept,) = [f for f in twice.json()["files"] if f["name"] == "b.ini"]
    assert kept["sha256"] == hashlib.sha256(b"[two]\n").hexdigest()


async def test_a_package_holding_a_case_pair_is_not_deployable(
    client, db_session, store
):
    """Rows written before uploads replaced by case: reported, refused for a
    deployment, and repaired by the next upload of either spelling."""
    from app.features.package.models import PackageFile

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    for name, content in (("a.ini", b"[one]\n"), ("A.INI", b"[two]\n")):
        sha = hashlib.sha256(content).hexdigest()
        (store / sha).write_bytes(content)
        db_session.add(
            PackageFile(
                package_id=package["id"], name=name, sha256=sha, size=len(content)
            )
        )
    await db_session.commit()

    body = await _get(client, admin, package["id"])
    (problem,) = body["problems"]
    assert problem["code"] == "duplicate_names"
    assert "« A.INI », « a.ini »" in problem["message"]
    assert problem["blocks_uninstall"] is True

    machine_id, _ = await _enroll(client, "poste-1")
    refused = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "package.not_ready"
    # Nor signed: every poste would refuse the manifest.
    assert (await _sign(client, admin, package["id"])).status_code == 409

    fixed = await _upload(client, admin, package["id"], ("a.ini", b"[three]\n"))
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["problems"] == []
    assert [
        f["name"] for f in fixed.json()["files"] if f["name"].lower() == "a.ini"
    ] == ["a.ini"]


# --- 2. method A: the total-size cap ---------------------------------------------


async def test_method_a_is_capped_in_total_size(client, db_session, store, monkeypatch):
    """The agent refuses an unsigned manifest announcing more than
    DeployMethodAMaxGB in all (deploy.MethodAFiles): said here, before every
    poste fails. Signed, the package is not capped."""
    from app.core.config import settings

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")
    install = {
        "type": "package_install",
        "machine_ids": [machine_id],
        "package_id": package["id"],
    }
    body = await _get(client, admin, package["id"])
    assert body["method_a_too_large"] is False
    assert body["method_a_max_bytes"] == 8 * GIB

    # Exactly the cap: the agent refuses "more than", not "as much as".
    await _set_sizes(
        db_session,
        package["id"],
        {"Install_PRNclient.exe": 8 * GIB - 10, "ClientPRONOTE.iss": 10},
    )
    assert (await _get(client, admin, package["id"]))["method_a_too_large"] is False

    # One byte more, in total: each file alone is under the cap.
    await _set_sizes(db_session, package["id"], {"ClientPRONOTE.iss": 11})
    body = await _get(client, admin, package["id"])
    assert body["method_a_too_large"] is True
    # Not a "problem": the way out is to sign, which problems forbid.
    assert body["problems"] == []
    refused = await client.post("/api/v1/commands", headers=admin, json=install)
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "package.not_ready"
    assert "Plus de 8 Gio" in error["details"]["problems"][0]
    assert "Signez le paquet" in error["details"]["problems"][0]

    # A fleet whose GPO raised DeployMethodAMaxGB: the server follows.
    monkeypatch.setattr(settings, "PACKAGE_METHOD_A_MAX_GB", 16)
    body = await _get(client, admin, package["id"])
    assert body["method_a_too_large"] is False
    assert body["method_a_max_bytes"] == 16 * GIB
    monkeypatch.setattr(settings, "PACKAGE_METHOD_A_MAX_GB", 8)

    # Signed (method B): the sizes are the administrator's word.
    assert (await _sign(client, admin, package["id"])).status_code == 200
    accepted = await client.post("/api/v1/commands", headers=admin, json=install)
    assert accepted.status_code == 200, accepted.text


async def test_the_cap_spares_an_uninstall_by_product_code(client, db_session, store):
    """msiexec /x {code} downloads nothing: the agent does not weigh the
    files for it. An uninstaller .exe of the package is downloaded, and is."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")
    url = f"/api/v1/packages/{package['id']}"
    await _set_sizes(db_session, package["id"], {"Install_PRNclient.exe": 9 * GIB})

    await client.patch(
        url,
        headers=admin,
        json={"uninstall_run": "Install_PRNclient.exe", "uninstall_args": ["/u"]},
    )
    refused = await _uninstall(client, admin, package["id"], machine_id)
    assert refused.status_code == 409, refused.text
    assert "Plus de 8 Gio" in refused.json()["error"]["details"]["problems"][0]

    await client.patch(
        url,
        headers=admin,
        json={"uninstall_run": "msiexec", "uninstall_args": ["/x", PRODUCT_CODE]},
    )
    accepted = await _uninstall(client, admin, package["id"], machine_id)
    assert accepted.status_code == 200, accepted.text


def test_the_method_a_cap_is_bounded():
    from pydantic import ValidationError

    from app.core.config import Settings

    assert Settings.model_fields["PACKAGE_METHOD_A_MAX_GB"].default == 8
    for good in (1, 1024):
        assert Settings(PACKAGE_METHOD_A_MAX_GB=good).PACKAGE_METHOD_A_MAX_GB == good
    for bad in (0, 1025):
        with pytest.raises(ValidationError, match="PACKAGE_METHOD_A_MAX_GB"):
            Settings(PACKAGE_METHOD_A_MAX_GB=bad)


# --- 3. an uninstall: refused for what the agent would refuse, no more -------------


async def test_an_uninstall_does_not_wait_for_an_install_step(
    client, db_session, store
):
    """The agent runs the uninstall step of a manifest without an install
    step; it refuses, whatever the step, a manifest without files or naming
    a file the package does not have (deploy.ParseManifest)."""
    admin = await _admin(client, db_session)
    machine_id, _ = await _enroll(client, "poste-1")
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={
            "kind": "files",
            "name": "Ancien logiciel",
            "uninstall_run": "msiexec",
            "uninstall_args": ["/x", PRODUCT_CODE, "/qn"],
        },
    )
    assert created.status_code == 201, created.text
    package = created.json()
    assert {p["code"]: p["blocks_uninstall"] for p in package["problems"]} == {
        "no_files": True,
        "no_install": False,
    }
    # No file at all: "manifeste sans fichier" on every poste.
    refused = await _uninstall(client, admin, package["id"], machine_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"]["problems"] == ["Aucun fichier déposé"]

    up = await _upload(client, admin, package["id"], ("lisezmoi.txt", b"x"))
    assert {p["code"]: p["blocks_uninstall"] for p in up.json()["problems"]} == {
        "no_install": False
    }
    accepted = await _uninstall(client, admin, package["id"], machine_id)
    assert accepted.status_code == 200, accepted.text
    # The installation is still refused: there is nothing to run.
    install = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert install.status_code == 409, install.text

    # An install step naming a file that is not there: the agent refuses the
    # manifest before it looks at which step was asked.
    patched = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_run": "setup.exe"},
    )
    assert {p["code"]: p["blocks_uninstall"] for p in patched.json()["problems"]} == {
        "install_missing": True
    }
    machine_2, _ = await _enroll(client, "poste-2")
    refused = await _uninstall(client, admin, package["id"], machine_2)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "package.not_ready"


# --- 4. retirement cancels what waits (T08) -----------------------------------------


async def test_retiring_cancels_the_installs_still_pending(client, db_session, store):
    """Retire, restore, heartbeat: nothing is installed. The installation a
    poste already received runs to its end; uninstallations are untouched."""
    from app.features.audit.models import AuditEntry

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    url = f"/api/v1/packages/{package['id']}"
    patched = await client.patch(
        url,
        headers=admin,
        json={"uninstall_run": "Install_PRNclient.exe", "uninstall_args": ["/u"]},
    )
    assert patched.status_code == 200, patched.text
    waiting, waiting_agent = await _enroll(client, "poste-waiting")
    other, _ = await _enroll(client, "poste-other")
    running, running_agent = await _enroll(client, "poste-running")
    removing, removing_agent = await _enroll(client, "poste-removing")
    for machine_id in (waiting, other, running):
        await _deploy(client, admin, package["id"], machine_id)
    assert (await _uninstall(client, admin, package["id"], removing)).status_code == 200
    (delivered,) = await _heartbeat(client, running_agent)

    retired = await client.post(f"{url}/retire", headers=admin)
    assert retired.status_code == 200, retired.text
    for machine_id in (waiting, other):
        cmd = await _command(client, admin, machine_id)
        assert cmd["status"] == "failed"
        assert cmd["error"] == "Paquet retiré : installation annulée"
        assert cmd["finished_at"] is not None
    assert (await _command(client, admin, running))["status"] == "delivered"
    assert (await _command(client, admin, removing))["status"] == "pending"
    entries = await db_session.exec(
        select(AuditEntry).where(col(AuditEntry.action) == "package.retire")
    )
    (entry,) = entries.all()
    assert entry.details["cancelled_installs"] == 2

    restored = await client.post(f"{url}/restore", headers=admin)
    assert restored.status_code == 200, restored.text
    # Back in the catalogue before the poste asked: the old install is gone.
    assert await _heartbeat(client, waiting_agent) == []
    assert (await _command(client, admin, waiting))["status"] == "failed"
    # The uninstall goes out, and the install already delivered still
    # downloads its files and reports.
    assert [c["type"] for c in await _heartbeat(client, removing_agent)] == [
        "package_uninstall"
    ]
    sha = delivered["package"]["files"][0]["sha256"]
    got = await client.get(
        f"/api/v1/agent/packages/{package['id']}/files/{sha}", headers=running_agent
    )
    assert got.status_code == 200, got.text
    done = await client.post(
        f"/api/v1/agent/commands/{delivered['id']}/result",
        headers=running_agent,
        json={"status": "succeeded"},
    )
    assert done.status_code == 200, done.text
    # And a new install can be queued on the poste whose old one was cancelled.
    await _deploy(client, admin, package["id"], waiting)
    assert [c["type"] for c in await _heartbeat(client, waiting_agent)] == [
        "package_install"
    ]


async def test_a_cancelled_install_releases_the_files_it_held(
    client, db_session, store
):
    """A pending installation keeps the files it was queued with on disk
    (audit T09); cancelled by the retirement, it holds them no more."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    old_sha = hashlib.sha256(b"[InstallShield Silent]\n").hexdigest()
    replaced = await _upload(client, admin, package["id"], ("ClientPRONOTE.iss", b"v2"))
    assert replaced.status_code == 200, replaced.text
    assert (store / old_sha).exists()

    retired = await client.post(
        f"/api/v1/packages/{package['id']}/retire", headers=admin
    )
    assert retired.status_code == 200, retired.text
    assert not (store / old_sha).exists()
    for f in retired.json()["files"]:
        assert (store / f["sha256"]).exists()


async def test_delivery_still_refuses_an_install_of_a_retired_package(
    client, db_session, store
):
    """The second line: an installation that reaches a heartbeat while its
    package is retired — queued in the instant of the retirement, or retired
    by other means than the route — is refused there."""
    from app.features.base import utcnow
    from app.features.package.models import Package

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    row = (
        await db_session.exec(
            select(Package).where(col(Package.name) == "Client PRONOTE")
        )
    ).one()
    row.retired_at = utcnow()
    db_session.add(row)
    await db_session.commit()

    assert await _heartbeat(client, agent) == []
    cmd = await _command(client, admin, machine_id)
    assert cmd["status"] == "failed"
    assert cmd["error"] == "Paquet retiré après la mise en file : installation annulée"


# --- 5. what a signer cannot see (T38) -------------------------------------------

# Everything refused in a name, a version, a file to run or an argument, as
# (first, last) code points. The script that signs refuses the same.
REFUSED_RANGES = [
    (0x00, 0x1F),
    (0x7F, 0x9F),
    (0x00AD, 0x00AD),
    (0x061C, 0x061C),
    (0x200B, 0x200F),
    (0x2028, 0x202E),
    (0x2060, 0x206F),
    (0xFEFF, 0xFEFF),
    (0xE0000, 0xE007F),
]


def _refused_code_points() -> list[int]:
    return [cp for first, last in REFUSED_RANGES for cp in range(first, last + 1)]


def test_the_refused_characters_are_exactly_the_listed_ones():
    from app.api.routes import packages

    refused = set(_refused_code_points())
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        assert bool(packages._CONTROL.search(chr(cp))) == (cp in refused), hex(cp)


async def test_invisible_and_reordering_characters_are_refused(client, db_session):
    """Audit T38: zero-width, soft hyphen, marks, isolates, BOM, tags — in
    every field the signer reads. Right-to-left letters are a script, not a
    trick: allowed."""
    admin = await _admin(client, db_session)
    samples = ["​", "‎", "‏", "؜", "­", "⁠", "⁤"]
    samples += ["⁯", "﻿", "\U000e0001", "\U000e007f", "⁦", "‮"]
    for ch in samples:
        for body in (
            {"kind": "files", "name": f"App{ch}"},
            {"kind": "files", "name": "App", "version": f"1{ch}0"},
            {"kind": "files", "name": "App", "detect_name": f"{ch}App"},
            {"kind": "files", "name": "App", "install_run": f"set{ch}up.exe"},
            {"kind": "files", "name": "App", "uninstall_run": f"un{ch}.exe"},
            {"kind": "files", "name": "App", "install_args": ["-s", f"a{ch}b"]},
            {"kind": "files", "name": "App", "uninstall_args": [ch]},
        ):
            resp = await client.post("/api/v1/packages", headers=admin, json=body)
            assert resp.status_code == 422, (hex(ord(ch)), body, resp.text)

    for name in ("مكتبة المدرسة", "ספריית בית הספר", "Pronote — édition 2026"):
        ok = await client.post(
            "/api/v1/packages",
            headers=admin,
            json={"kind": "files", "name": name, "install_args": ["/lang", "عربي"]},
        )
        assert ok.status_code == 201, (name, ok.text)
        assert ok.json()["name"] == name


def test_the_signing_script_refuses_the_same_characters():
    """Sign-TiaiPackage.ps1 displays the manifest before signing it: what the
    server refuses, the script refuses too — the file it is given may not
    come from the server. Read as the .NET regular expression it is, over
    UTF-16 code units; the script itself is not run here."""
    script = (
        Path(__file__).resolve().parents[2]
        / "deploy"
        / "packages"
        / "Sign-TiaiPackage.ps1"
    )
    if not script.exists():
        pytest.skip("deploy/ not in this checkout")
    raw = script.read_bytes()
    # Windows PowerShell 5.1 reads a script without a BOM in the ANSI code
    # page: anything but ASCII would be another character there.
    assert raw.isascii()
    source = raw.decode("ascii")
    found = re.search(r"^\$ForbiddenCharacters = '([^']+)'$", source, re.M)
    assert found, "$ForbiddenCharacters not found in Sign-TiaiPackage.ps1"
    assert "-match $ForbiddenCharacters" in source
    # \xHH and \uXXXX read the same in Python; PowerShell's -match ignores case.
    pattern = re.compile(found.group(1), re.IGNORECASE)

    def utf16(cp: int) -> str:
        """The character as .NET holds it: one code unit, or a surrogate pair."""
        if cp < 0x10000:
            return chr(cp)
        cp -= 0x10000
        return chr(0xD800 + (cp >> 10)) + chr(0xDC00 + (cp & 0x3FF))

    refused = set(_refused_code_points())
    for cp in refused:
        assert pattern.search("setup" + utf16(cp) + ".exe"), hex(cp)
    # And nothing else of what a manifest ordinarily holds: Latin, accents,
    # right-to-left letters, the neighbours of each refused range, an emoji.
    neighbours = {first - 1 for first, _ in REFUSED_RANGES if first} | {
        last + 1 for _, last in REFUSED_RANGES
    }
    allowed = (neighbours - refused) | set(map(ord, " aZ09é—«»{}\\\"'مש€")) | {0x1F600}
    for cp in allowed:
        assert not pattern.search(utf16(cp)), hex(cp)


def test_a_reserved_device_name_is_refused_whatever_follows_it():
    """Audit T38: Windows opens ``nul .cab`` as NUL — spaces before the first
    dot do not make it a file. The same names as the agent's own test
    (deploy_test.go, TestValidFileNameRefusesAReservedDeviceStem): one rule."""
    from app.features.package import manifest

    refused = [
        *"con CON prn aux nul com1 COM9 lpt1 LPT9 com0 lpt0".split(),
        *"con.txt NUL.cab nul.tar.gz Aux.h com1.exe lpt1.txt".split(),
        # A space, or several, before the extension.
        "nul .cab",
        "con .txt",
        "NUL  .cab",
        "Prn .txt",
        "aux .tar.gz",
        "com1 .exe",
        "LPT9 .txt",
        # Dots and spaces mixed after the stem.
        "nul..cab",
        "nul. .cab",
        "nul . .cab",
        "con ..txt",
        "con .a b.txt",
        # Superscript digits, which Windows takes after COM and LPT: outside
        # what a file name may hold at all.
        "com¹",
        "COM².txt",
        "lpt³ .txt",
        # Never a trailing dot or space, device or not.
        "nul ",
        "nul.",
        "setup.exe ",
        "setup.exe.",
    ]
    for name in refused:
        assert not manifest.valid_file_name(name), name
    accepted = [
        "console.exe",
        "con1.txt",
        "nul-device.txt",
        "nulle part.txt",
        "con txt.cab",
        "auxiliary.dll",
        "com10.txt",
        "lpt.txt",
        "com.exe",
        "setup con.exe",
        "a.nul",
        "x.con .txt",
        "data .cab",
        "Install_PRNclient.exe",
        "ClientPRONOTE.iss",
        "prn(1).txt",
    ]
    for name in accepted:
        assert manifest.valid_file_name(name), name


async def test_an_upload_named_after_a_device_is_refused(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    resp = await _upload(client, admin, package["id"], ("nul .cab", b"x"))
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "package.file.name_invalid"
    patched = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_run": "AUX .exe"},
    )
    assert patched.status_code == 422, patched.text


async def test_a_blank_name_is_not_a_name(client, db_session):
    """Stripped before it is measured: spaces, or U+00A0, used to be stored
    as an empty name."""
    admin = await _admin(client, db_session)
    for blank in (" ", " ", "  \t "):
        created = await client.post(
            "/api/v1/packages",
            headers=admin,
            json={"kind": "winget", "name": blank, "winget_id": "Mozilla.Firefox"},
        )
        assert created.status_code == 422, (repr(blank), created.text)
    ok = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "  Firefox ", "winget_id": "Mozilla.Firefox"},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["name"] == "Firefox"
    for blank in (" ", " "):
        patched = await client.patch(
            f"/api/v1/packages/{ok.json()['id']}", headers=admin, json={"name": blank}
        )
        assert patched.status_code == 422, (repr(blank), patched.text)
    assert (await _get(client, admin, ok.json()["id"]))["name"] == "Firefox"


# --- 6. two requests at once, and a sha that is not one -----------------------------


def _meet_in_save(monkeypatch, parties: int = 2, patience: float = 0.5):
    """Make the uploads meet in ``storage.save``: each waits there for the
    others, so that — unserialised — all have read the package before any
    writes to it. Serialised, the others never arrive while one is inside:
    it gives up waiting and goes on."""
    from app.features.package import storage

    original = storage.save
    everyone = asyncio.Event()
    arrived = 0

    async def save(upload, max_bytes):
        nonlocal arrived
        arrived += 1
        if arrived >= parties:
            everyone.set()
        try:
            await asyncio.wait_for(everyone.wait(), patience)
        except TimeoutError:
            pass
        return await original(upload, max_bytes)

    monkeypatch.setattr(storage, "save", save)


async def test_overlapping_uploads_both_reach_the_manifest(
    client, db_session, store, monkeypatch
):
    """Each used to rebuild the manifest from the files it saw — not the
    other's — and the last commit won: a file in the table, absent from what
    the postes are told to download."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    _meet_in_save(monkeypatch)
    one, two = await asyncio.gather(
        _upload(client, admin, package["id"], ("one.ini", b"[one]\n")),
        _upload(client, admin, package["id"], ("two.ini", b"[two]\n")),
    )
    assert one.status_code == 200, one.text
    assert two.status_code == 200, two.text

    body = await _get(client, admin, package["id"])
    in_table = {f["name"]: f["sha256"] for f in body["files"]}
    assert {"one.ini", "two.ini"} <= set(in_table)
    manifest = json.loads(await _manifest(client, admin, package["id"]))
    assert {f["name"]: f["sha256"] for f in manifest["files"]} == in_table
    for sha in in_table.values():
        assert (store / sha).exists()


async def test_overlapping_uploads_of_one_name_keep_one_file(
    client, db_session, store, monkeypatch
):
    """Two uploads of the same name used to collide on the primary key: an
    unhandled IntegrityError. One replaces the other, as in sequence."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    _meet_in_save(monkeypatch)
    contents = {b"[first]\n", b"[second]\n"}
    answers = await asyncio.gather(
        *(
            _upload(client, admin, package["id"], ("same.ini", content))
            for content in sorted(contents)
        )
    )
    assert [a.status_code for a in answers] == [200, 200], [a.text for a in answers]

    body = await _get(client, admin, package["id"])
    (kept,) = [f for f in body["files"] if f["name"] == "same.ini"]
    shas = {hashlib.sha256(c).hexdigest() for c in contents}
    assert kept["sha256"] in shas
    manifest = json.loads(await _manifest(client, admin, package["id"]))
    (named,) = [f for f in manifest["files"] if f["name"] == "same.ini"]
    assert named["sha256"] == kept["sha256"]
    # The one that lost its place left the store; the one kept is there.
    assert (store / kept["sha256"]).exists()
    (lost,) = shas - {kept["sha256"]}
    assert not (store / lost).exists()


async def test_an_upload_and_a_change_of_definition_do_not_lose_each_other(
    client, db_session, store, monkeypatch
):
    """The same lost update, between an upload and a PATCH that rebuilds the
    manifest: the upload, which read the package first, used to write a
    manifest with the command line it had read."""
    from app.features.package import storage

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    original = storage.save
    in_save = asyncio.Event()
    patch_answered = asyncio.Event()

    async def save(upload, max_bytes):
        # The upload has read the package; it lets the PATCH go first if the
        # PATCH can — behind the lock it cannot, and the wait runs out.
        in_save.set()
        try:
            await asyncio.wait_for(patch_answered.wait(), 0.5)
        except TimeoutError:
            pass
        return await original(upload, max_bytes)

    monkeypatch.setattr(storage, "save", save)
    uploading = asyncio.create_task(
        _upload(client, admin, package["id"], ("extra.ini", b"[x]\n"))
    )
    await in_save.wait()
    patched = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_args": ["/quiet"]},
    )
    patch_answered.set()
    up = await uploading
    assert up.status_code == 200, up.text
    assert patched.status_code == 200, patched.text
    manifest = json.loads(await _manifest(client, admin, package["id"]))
    assert "extra.ini" in {f["name"] for f in manifest["files"]}
    assert manifest["install"]["args"] == ["/quiet"]
    # What the PATCH answered is the package as it stands, upload included.
    assert "extra.ini" in {f["name"] for f in patched.json()["files"]}


async def test_a_download_named_by_something_else_than_a_sha_is_not_found(
    client, db_session, store
):
    """A NUL in the path used to reach PostgreSQL, which refuses it: 500."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    (command,) = await _heartbeat(client, agent)
    real = command["package"]["files"][0]["sha256"]
    base = f"/api/v1/agent/packages/{package['id']}/files"
    assert (await client.get(f"{base}/{real}", headers=agent)).status_code == 200
    for bad in (
        "%00",
        real[:-1] + "%00",
        real + "%00",
        "a" * 63 + "g",
        real.upper(),
        "nul",
    ):
        got = await client.get(f"{base}/{bad}", headers=agent)
        assert got.status_code == 404, (bad, got.text)
        assert got.json()["error"]["code"] == "package.not_found"


# --- 7. a file the store lost --------------------------------------------------


async def test_a_file_missing_from_the_store_is_reported(client, db_session, store):
    """What the sweep of v1.2.0 could leave: a row whose file is gone. Said
    in the package, refused for a deployment, repaired by uploading again."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")
    assert package["problems"] == []
    content = b"[InstallShield Silent]\n"
    (store / hashlib.sha256(content).hexdigest()).unlink()

    body = await _get(client, admin, package["id"])
    (problem,) = body["problems"]
    assert problem["code"] == "file_missing_in_store"
    assert "« ClientPRONOTE.iss »" in problem["message"]
    assert "Install_PRNclient.exe" not in problem["message"]
    assert problem["blocks_uninstall"] is True
    listed = await client.get("/api/v1/packages", headers=admin)
    assert [p["code"] for p in listed.json()[0]["problems"]] == [
        "file_missing_in_store"
    ]

    refused = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "package.not_ready"
    assert "ClientPRONOTE.iss" in error["details"]["problems"][0]
    assert (await _sign(client, admin, package["id"])).status_code == 409

    # msiexec /x {code}, unsigned: method A downloads no file for it.
    patched = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"uninstall_run": "msiexec", "uninstall_args": ["/x", PRODUCT_CODE]},
    )
    (problem,) = patched.json()["problems"]
    assert problem["blocks_uninstall"] is False
    accepted = await _uninstall(client, admin, package["id"], machine_id)
    assert accepted.status_code == 200, accepted.text

    again = await _upload(client, admin, package["id"], ("ClientPRONOTE.iss", content))
    assert again.status_code == 200, again.text
    assert again.json()["problems"] == []
    assert (store / hashlib.sha256(content).hexdigest()).exists()


# --- 8. the size an upload accepts -----------------------------------------------


async def test_the_package_says_how_large_a_file_may_be(
    client, db_session, store, monkeypatch
):
    """PACKAGE_MAX_BYTES is the deployment's to set: the console reads it
    from the package rather than carrying the default."""
    from app.core.config import settings

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    assert package["file_max_bytes"] == settings.PACKAGE_MAX_BYTES
    monkeypatch.setattr(settings, "PACKAGE_MAX_BYTES", 6 * GIB)
    assert (await _get(client, admin, package["id"]))["file_max_bytes"] == 6 * GIB
    listed = await client.get("/api/v1/packages", headers=admin)
    assert listed.json()[0]["file_max_bytes"] == 6 * GIB

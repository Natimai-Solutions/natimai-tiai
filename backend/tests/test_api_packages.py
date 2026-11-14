"""Software deployment: packages, their signature, and how they reach a poste.

DB-backed: requires TIAI_TEST_DATABASE_URL.
"""

import base64
import datetime as dt
import json
import struct

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tests.scope_helpers import account, login

# --- fixtures -----------------------------------------------------------------


def _cert(key, cn: str) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False
        )
        .sign(key, hashes.SHA256())
    )


def _signature_document(manifest: bytes, key, cert, *, p1363: bool = True) -> dict:
    """What Sign-TiaiPackage.ps1 produces — .NET's ECDSA output is r‖s."""
    if isinstance(key, rsa.RSAPrivateKey):
        sig = key.sign(manifest, padding.PKCS1v15(), hashes.SHA256())
        algorithm = "rsa-pkcs1-sha256"
    else:
        der = key.sign(manifest, ec.ECDSA(hashes.SHA256()))
        if p1363:
            r, s = decode_dss_signature(der)
            size = (key.curve.key_size + 7) // 8
            sig = r.to_bytes(size, "big") + s.to_bytes(size, "big")
        else:
            sig = der
        algorithm = "ecdsa-sha256"
    return {
        "format": "tiai-signature-1",
        "algorithm": algorithm,
        "signature": base64.b64encode(sig).decode(),
        "certificate": base64.b64encode(
            cert.public_bytes(serialization.Encoding.DER)
        ).decode(),
    }


def signed_pe(publisher: str) -> bytes:
    """A minimal PE32+ carrying an Authenticode-shaped certificate table: enough
    for the server to read who signed it (it never verifies)."""
    key = ec.generate_private_key(ec.SECP256R1())
    cert = _cert(key, publisher)
    blob = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(b"x")
        .add_signer(cert, key, hashes.SHA256())
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
    )
    pe_offset = 0x40
    optional = pe_offset + 24
    directories = optional + 112
    cert_offset = directories + 16 * 8
    win_cert = struct.pack("<IHH", 8 + len(blob), 0x0200, 0x0002) + blob
    head = bytearray(cert_offset)
    head[0:2] = b"MZ"
    head[0x3C:0x40] = struct.pack("<I", pe_offset)
    head[pe_offset : pe_offset + 4] = b"PE\0\0"
    head[optional : optional + 2] = struct.pack("<H", 0x20B)
    entry = directories + 8 * 4
    head[entry : entry + 8] = struct.pack("<II", cert_offset, len(win_cert))
    return bytes(head) + win_cert


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "PACKAGES_DIR", str(tmp_path / "packages"))
    return tmp_path / "packages"


async def _admin(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    return await account(client, db_session, "admin@test.local", [BuiltinGroup.ADMIN])


async def _enroll(client, uuid_: str):
    from app.core.config import settings

    enroll = await client.post(
        "/api/v1/agent/enroll",
        headers={"X-Enrollment-Secret": settings.ENROLLMENT_SECRET},
        json={"machine_uuid": uuid_},
    )
    assert enroll.status_code == 200, enroll.text
    body = enroll.json()
    return body["machine_id"], {"Authorization": f"Bearer {body['token']}"}


async def _pronote(client, headers):
    """A files package with an installer and its response file, ready."""
    resp = await client.post(
        "/api/v1/packages",
        headers=headers,
        json={
            "kind": "files",
            "name": "Client PRONOTE",
            "version": "2026.2.8",
            "install_run": "Install_PRNclient.exe",
            "install_args": ["-s", "-f1{dir}\\ClientPRONOTE.iss"],
            "detect_name": "PRONOTE",
        },
    )
    assert resp.status_code == 201, resp.text
    package = resp.json()
    resp = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=headers,
        files=[
            ("files", ("Install_PRNclient.exe", signed_pe("INDEX EDUCATION SAS"))),
            ("files", ("ClientPRONOTE.iss", b"[InstallShield Silent]\n")),
        ],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- catalogue ------------------------------------------------------------------


async def test_a_winget_package_names_its_identifier(client, db_session):
    admin = await _admin(client, db_session)
    ok = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "Firefox", "winget_id": "Mozilla.Firefox"},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["detect_name"] == "Firefox"
    assert ok.json()["problems"] == []
    for bad in ("--source msstore", "Mozilla Firefox", "-h", ""):
        r = await client.post(
            "/api/v1/packages",
            headers=admin,
            json={"kind": "winget", "name": "X", "winget_id": bad},
        )
        assert r.status_code == 422, bad


async def test_a_files_package_reads_its_publisher(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    assert package["problems"] == []
    assert package["publisher_name"] == "INDEX EDUCATION SAS"
    by_name = {f["name"]: f for f in package["files"]}
    assert by_name["ClientPRONOTE.iss"]["publisher_name"] is None
    # Content-addressed store: one file per hash.
    assert sorted(p.name for p in store.iterdir()) == sorted(
        f["sha256"] for f in package["files"]
    )


async def test_file_names_cannot_be_paths(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    resp = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[("files", ("con.txt", b"x"))],
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "package.file.name_invalid"


async def test_readonly_cannot_compose(client, db_session):
    from app.features.user.permissions import BuiltinGroup

    ro = await account(client, db_session, "ro@test.local", [BuiltinGroup.READONLY])
    resp = await client.post(
        "/api/v1/packages",
        headers=ro,
        json={"kind": "winget", "name": "x", "winget_id": "a.b"},
    )
    assert resp.status_code == 403


# --- method B -------------------------------------------------------------------


@pytest.mark.parametrize("curve", [None, ec.SECP256R1(), ec.SECP384R1()])
async def test_a_signature_verifies_over_the_manifest(client, db_session, store, curve):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    manifest = await client.get(
        f"/api/v1/packages/{package['id']}/manifest", headers=admin
    )
    assert manifest.status_code == 200
    document = json.loads(manifest.content)
    assert document["format"] == "tiai-package-1"
    assert document["install"]["args"] == ["-s", "-f1{dir}\\ClientPRONOTE.iss"]

    key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if curve is None
        else ec.generate_private_key(curve)
    )
    cert = _cert(key, "Tiai Signature")
    resp = await client.put(
        f"/api/v1/packages/{package['id']}/signature",
        headers=admin,
        json=_signature_document(manifest.content, key, cert),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["signed"] is True
    assert body["signer_subject"] == "CN=Tiai Signature"
    assert len(body["signer_thumbprint"]) == 64


async def test_a_change_voids_the_signature(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    manifest = (
        await client.get(f"/api/v1/packages/{package['id']}/manifest", headers=admin)
    ).content
    key = ec.generate_private_key(ec.SECP256R1())
    document = _signature_document(manifest, key, _cert(key, "Tiai"))
    r = await client.put(
        f"/api/v1/packages/{package['id']}/signature", headers=admin, json=document
    )
    assert r.json()["signed"] is True

    changed = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_args": ["-s", "-f1C:\\autre.iss"]},
    )
    assert changed.json()["signed"] is False
    # And the old signature does not fit the new manifest.
    again = await client.put(
        f"/api/v1/packages/{package['id']}/signature", headers=admin, json=document
    )
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "package.signature.invalid"


async def test_garbage_is_not_a_signature(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    r = await client.put(
        f"/api/v1/packages/{package['id']}/signature",
        headers=admin,
        json={
            "format": "tiai-signature-1",
            "algorithm": "md5",
            "signature": "",
            "certificate": "",
        },
    )
    assert r.status_code == 422


# --- commands, delivery, download --------------------------------------------------


async def test_a_deployment_reaches_the_poste_whole(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, agent = await _enroll(client, "poste-1")

    missing = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={"type": "package_install", "machine_ids": [machine_id]},
    )
    assert missing.status_code == 422
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1

    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    (command,) = hb.json()["commands"]
    assert command["type"] == "package_install"
    delivered = command["package"]
    assert delivered["kind"] == "files"
    manifest = json.loads(base64.b64decode(delivered["manifest"]))
    assert manifest["package_id"] == package["id"]
    assert {f["name"] for f in delivered["files"]} == {
        "Install_PRNclient.exe",
        "ClientPRONOTE.iss",
    }

    iss = next(f for f in delivered["files"] if f["name"] == "ClientPRONOTE.iss")
    url = f"/api/v1/agent/packages/{package['id']}/files/{iss['sha256']}"
    got = await client.get(url, headers=agent)
    assert got.status_code == 200
    assert got.content == b"[InstallShield Silent]\n"
    # Resumable.
    part = await client.get(url, headers={**agent, "Range": "bytes=1-5"})
    assert part.status_code == 206
    assert part.content == b"Insta"

    # Another poste, with no deployment open, cannot fetch it.
    _, other = await _enroll(client, "poste-2")
    assert (await client.get(url, headers=other)).status_code == 404


async def test_two_packages_do_not_exclude_each_other(client, db_session, store):
    admin = await _admin(client, db_session)
    first = await _pronote(client, admin)
    second = (
        await client.post(
            "/api/v1/packages",
            headers=admin,
            json={"kind": "winget", "name": "7-Zip", "winget_id": "7zip.7zip"},
        )
    ).json()
    machine_id, _ = await _enroll(client, "poste-1")
    for package in (first, second, first):
        await client.post(
            "/api/v1/commands",
            headers=admin,
            json={
                "type": "package_install",
                "machine_ids": [machine_id],
                "package_id": package["id"],
            },
        )
    listed = await client.get("/api/v1/commands", headers=admin)
    assert listed.json()["total"] == 2


async def test_retired_and_incomplete_packages_are_refused(client, db_session, store):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")

    no_uninstall = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_uninstall",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert no_uninstall.status_code == 409
    assert no_uninstall.json()["error"]["code"] == "package.not_ready"

    await client.post(f"/api/v1/packages/{package['id']}/retire", headers=admin)
    retired = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert retired.status_code == 409
    assert retired.json()["error"]["code"] == "package.retired"


async def test_deploying_takes_the_risky_permission(client, db_session, store):
    from app.features.user.permissions import BuiltinGroup
    from tests.scope_helpers import group

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")
    g = await group(
        db_session, "Courant", {"command:execute", "package:read", "machine:read"}, None
    )
    everyday = await account(client, db_session, "op@test.local", [g.id])
    resp = await client.post(
        "/api/v1/commands",
        headers=everyday,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert resp.status_code == 403
    _ = BuiltinGroup, login


async def test_installed_count_reads_the_inventory(client, db_session, store):
    from app.features.inventory.models import MachineSoftware, Software
    from app.features.machine.models import Machine

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    m = Machine(machine_uuid="m-1", hostname="PC-1")
    s = Software(name="Client PRONOTE 2026", version="2026.2.8", publisher="Index")
    db_session.add_all([m, s])
    await db_session.flush()
    db_session.add(MachineSoftware(machine_id=m.id, software_id=s.id))
    await db_session.commit()
    got = await client.get(f"/api/v1/packages/{package['id']}", headers=admin)
    assert got.json()["installed_count"] == 1


async def test_an_msi_is_installed_through_msiexec(client, db_session, store):
    admin = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "App", "install_run": "msiexec"},
    )
    # msiexec alone would do nothing: it needs the package's MSI.
    assert created.status_code == 422
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={
            "kind": "files",
            "name": "App",
            "install_run": "msiexec",
            "install_args": ["/i", "{dir}\\app.msi", "/qn", "/norestart"],
        },
    )
    assert created.status_code == 201, created.text
    package = created.json()
    up = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[("files", ("app.msi", b"\xd0\xcf\x11\xe0 not really an msi"))],
    )
    body = up.json()
    assert body["problems"] == []
    # Not a signed executable: only method B can carry it.
    assert body["publisher_name"] is None

    # And until it is signed, no poste would run it: refused up front rather
    # than queued for every poste to fail (audit B30).
    machine_id, _ = await _enroll(client, "poste-msi")
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
    assert "Signez le paquet" in refused.json()["error"]["details"]["problems"][0]


async def test_method_a_refuses_a_loadable_file_beside_the_installer(
    client, db_session, store
):
    """The agent would refuse it (audit S02): the server says so first."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-dll")
    up = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[("files", ("version.dll", b"MZ"))],
    )
    assert up.status_code == 200, up.text
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


# --- audit T08, T09 ---------------------------------------------------------------


async def _deploy(client, admin, package_id, machine_id):
    resp = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_install",
            "machine_ids": [machine_id],
            "package_id": package_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp


async def _command(client, admin, machine_id):
    resp = await client.get(
        "/api/v1/commands", headers=admin, params={"machine_id": machine_id}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"][0]


async def test_a_package_changed_after_queueing_is_not_delivered(
    client, db_session, store
):
    """Audit S08: what was approved is what runs, or nothing."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)

    # Someone holding package:write changes the command line afterwards.
    changed = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"install_args": ["/evil"]},
    )
    assert changed.status_code == 200, changed.text

    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    assert hb.json()["commands"] == []
    cmd = await _command(client, admin, machine_id)
    assert cmd["status"] == "failed"
    assert "modifié après la mise en file" in cmd["error"]

    # Queued again, the new version goes out.
    await _deploy(client, admin, package["id"], machine_id)
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    (command,) = hb.json()["commands"]
    manifest = json.loads(base64.b64decode(command["package"]["manifest"]))
    assert manifest["install"]["args"] == ["/evil"]


async def test_a_replaced_file_stays_for_the_deployment_that_has_it(
    client, db_session, store
):
    """Audit B13 and S09: the file a delivered deployment names is served and
    kept on disk until that deployment is over, then removed."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    (command,) = hb.json()["commands"]
    old = next(
        f for f in command["package"]["files"] if f["name"] == "ClientPRONOTE.iss"
    )

    replaced = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[("files", ("ClientPRONOTE.iss", b"[InstallShield Silent]\nv2\n"))],
    )
    assert replaced.status_code == 200, replaced.text
    assert (store / old["sha256"]).exists()

    url = f"/api/v1/agent/packages/{package['id']}/files/{old['sha256']}"
    got = await client.get(url, headers=agent)
    assert got.status_code == 200, got.text
    assert got.content == b"[InstallShield Silent]\n"

    done = await client.post(
        f"/api/v1/agent/commands/{command['id']}/result",
        headers=agent,
        json={"status": "succeeded", "output": "ok"},
    )
    assert done.status_code == 200, done.text
    # Over: the replaced file is no longer wanted, and goes.
    assert not (store / old["sha256"]).exists()
    # The current files stay.
    current = await client.get(f"/api/v1/packages/{package['id']}", headers=admin)
    for f in current.json()["files"]:
        assert (store / f["sha256"]).exists()


async def test_a_removed_file_and_a_failed_upload_leave_nothing_behind(
    client, db_session, store
):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    iss = next(f for f in package["files"] if f["name"] == "ClientPRONOTE.iss")
    removed = await client.delete(
        f"/api/v1/packages/{package['id']}/files/ClientPRONOTE.iss", headers=admin
    )
    assert removed.status_code == 200, removed.text
    assert not (store / iss["sha256"]).exists()

    # Two files, the second refused by name: the first one stored goes too.
    before = {p.name for p in store.iterdir()}
    failed = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[
            ("files", ("ok.ini", b"stored first, then orphaned")),
            ("files", ("con.txt", b"x")),
        ],
    )
    assert failed.status_code == 422, failed.text
    assert {p.name for p in store.iterdir()} == before


async def test_removing_a_file_already_gone_names_the_file(client, db_session, store):
    """Audit B36: the package exists — it is the file that is missing."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    url = f"/api/v1/packages/{package['id']}/files/ClientPRONOTE.iss"
    assert (await client.delete(url, headers=admin)).status_code == 200
    again = await client.delete(url, headers=admin)
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "package.file.not_found"


async def test_the_summary_counts_each_postes_latest_deployment(
    client, db_session, store
):
    """Audit B14: the tally reads every poste, not the first page of rows."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    agents = []
    for i in range(3):
        machine_id, agent = await _enroll(client, f"poste-{i}")
        agents.append(agent)
        await _deploy(client, admin, package["id"], machine_id)
    # Poste 0 answers: succeeded. The others are still waiting.
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agents[0], json={"agent_version": "t"}
    )
    (command,) = hb.json()["commands"]
    await client.post(
        f"/api/v1/agent/commands/{command['id']}/result",
        headers=agents[0],
        json={"status": "succeeded"},
    )
    summary = await client.get(
        "/api/v1/commands/package-summary",
        headers=admin,
        params={"package_id": package["id"]},
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["postes"] == 3
    assert body["by_status"] == {"succeeded": 1, "pending": 2}
    assert body["by_action"] == {"package_install": 3}


async def test_control_characters_are_refused(client, db_session):
    """Audit S25: nothing that could rewrite what the signer reads."""
    admin = await _admin(client, db_session)
    for body in (
        {"kind": "files", "name": "App\x1b[1A\x1b[2KPronote"},
        {"kind": "files", "name": "App", "version": "1\r2"},
        {"kind": "files", "name": "App", "install_args": ["-s", "\x1b[2Kevil"]},
        {"kind": "files", "name": "App", "install_args": ["\x9b2K"]},
    ):
        resp = await client.post("/api/v1/packages", headers=admin, json=body)
        assert resp.status_code == 422, (body, resp.text)


# --- audit 2026-11 verification: T08, T09, T38, T23, T02 ---------------------------


async def test_a_package_retired_after_queueing_is_not_installed(
    client, db_session, store
):
    """Audit T08: retiring says "install this nowhere any more" — an install
    queued before is cancelled at delivery; an uninstall still goes out."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    patched = await client.patch(
        f"/api/v1/packages/{package['id']}",
        headers=admin,
        json={"uninstall_run": "Install_PRNclient.exe", "uninstall_args": ["/u"]},
    )
    assert patched.status_code == 200, patched.text
    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    queued = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_uninstall",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert queued.status_code == 200, queued.text

    retired = await client.post(
        f"/api/v1/packages/{package['id']}/retire", headers=admin
    )
    assert retired.status_code == 200, retired.text

    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    assert [c["type"] for c in hb.json()["commands"]] == ["package_uninstall"]
    listed = await client.get(
        "/api/v1/commands", headers=admin, params={"machine_id": machine_id}
    )
    install = next(c for c in listed.json()["items"] if c["type"] == "package_install")
    assert install["status"] == "failed"
    assert install["error"] == (
        "Paquet retiré après la mise en file : installation annulée"
    )

    # Queued after the retirement, an uninstall is still delivered.
    (delivered,) = hb.json()["commands"]
    await client.post(
        f"/api/v1/agent/commands/{delivered['id']}/result",
        headers=agent,
        json={"status": "succeeded"},
    )
    again = await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_uninstall",
            "machine_ids": [machine_id],
            "package_id": package["id"],
        },
    )
    assert again.status_code == 200, again.text
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    assert [c["type"] for c in hb.json()["commands"]] == ["package_uninstall"]


def test_a_pinned_file_is_seen_by_a_sweep_that_started_before():
    """Audit T09: an upload that pinned, committed and unpinned while a sweep
    was asking the database still shows to that sweep."""
    from app.features.package import storage

    sha = "ab" * 32
    mark = storage.pin_mark()
    assert not storage.pinned_since(sha, mark)
    storage.pin(sha)
    storage.pin(sha)
    storage.unpin(sha)
    assert storage.pinned_since(sha, mark)
    storage.unpin(sha)
    # Released since the mark: a sweep that looked before must not delete.
    assert storage.pinned_since(sha, mark)
    # A sweep starting now sees nothing held.
    assert not storage.pinned_since(sha, storage.pin_mark())


async def test_the_sweep_keeps_a_pinned_file(client, db_session, store):
    """Audit T09, forced interleaving: pinned, the orphan stays; released, it
    goes."""
    from app.features.package import crud, storage

    admin = await _admin(client, db_session)
    await _pronote(client, admin)
    sha = "cd" * 32
    (store / sha).write_bytes(b"stored, not committed yet")
    storage.pin(sha)
    try:
        assert await crud.sweep_store(db_session) == 0
        assert (store / sha).exists()
    finally:
        storage.unpin(sha)
    assert await crud.sweep_store(db_session) == 1
    assert not (store / sha).exists()


def _sweep_before_commit(monkeypatch, engine):
    """Run a sweep from another session between the upload's save and its
    commit — what an agent's verdict or another admin's upload would do."""
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.features.package import crud

    original = crud.refresh_manifest
    swept: list[int] = []

    async def racing(session, package):
        async with AsyncSession(engine) as other:
            swept.append(await crud.sweep_store(other))
        return await original(session, package)

    monkeypatch.setattr(crud, "refresh_manifest", racing)
    return swept


async def test_a_sweep_during_an_upload_keeps_the_file(
    client, db_session, store, engine, monkeypatch
):
    """Audit T09: the upload answers 200 and the file it named is there to
    download — new content, and content whose blob was already in the store
    unreferenced."""
    import hashlib

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    orphan = b"[Setup]\nleft by a removed package file\n"
    orphan_sha = hashlib.sha256(orphan).hexdigest()
    (store / orphan_sha).write_bytes(orphan)

    from app.features.package import crud

    original = crud.refresh_manifest
    swept = _sweep_before_commit(monkeypatch, engine)
    up = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[
            ("files", ("new.ini", b"[Options]\nfresh\n")),
            ("files", ("reused.ini", orphan)),
        ],
    )
    assert up.status_code == 200, up.text
    assert swept == [0]
    monkeypatch.setattr(crud, "refresh_manifest", original)

    machine_id, agent = await _enroll(client, "poste-1")
    await _deploy(client, admin, package["id"], machine_id)
    hb = await client.post(
        "/api/v1/agent/heartbeat", headers=agent, json={"agent_version": "test"}
    )
    (command,) = hb.json()["commands"]
    files = {f["name"]: f["sha256"] for f in command["package"]["files"]}
    for name, content in (("new.ini", b"[Options]\nfresh\n"), ("reused.ini", orphan)):
        got = await client.get(
            f"/api/v1/agent/packages/{package['id']}/files/{files[name]}",
            headers=agent,
        )
        assert got.status_code == 200, (name, got.text)
        assert got.content == content


async def test_a_database_error_in_the_sweep_does_not_fail_the_upload(
    client, db_session, store, monkeypatch
):
    """The sweep runs after the upload committed: a database error there is
    logged, not answered 500 for a stored file."""
    from sqlalchemy.exc import OperationalError

    from app.features.package import crud

    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)

    async def broken(session, sha256):
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr(crud, "sha_in_use", broken)
    up = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers=admin,
        files=[("files", ("extra.ini", b"[x]\n"))],
    )
    assert up.status_code == 200, up.text
    assert "extra.ini" in {f["name"] for f in up.json()["files"]}


async def test_the_sweep_deletes_nothing_beside_an_empty_catalogue(
    db_session, store, caplog
):
    """Packages are retired, never deleted: files in the store and no package
    at all means the wrong database, not orphans."""
    import logging

    from app.features.package import crud

    store.mkdir(parents=True, exist_ok=True)
    sha = "ef" * 32
    (store / sha).write_bytes(b"an installer")
    with caplog.at_level(logging.WARNING, logger="app.features.package.crud"):
        assert await crud.sweep_store(db_session) == 0
    assert (store / sha).exists()
    assert "no package in the database" in caplog.text


def test_a_file_name_cannot_end_with_a_newline():
    """Audit T38: "$" after re.match accepts one trailing LF."""
    from app.features.package import manifest

    assert manifest.valid_file_name("setup.exe")
    for name in ("setup.exe\n", "con\n", "setup\n.exe", "\nsetup.exe"):
        assert not manifest.valid_file_name(name), repr(name)
    # The store's own names, from the download URL, likewise.
    from app.features.package import storage

    with pytest.raises(ValueError):
        storage.path_for("a" * 64 + "\n")


async def test_an_uploaded_file_name_with_a_newline_is_refused(
    client, db_session, store
):
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    # A bare LF inside the quoted file name: the multipart parser keeps it.
    boundary = "tiai-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="files"; filename="evil.txt\n"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
        "x\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    resp = await client.post(
        f"/api/v1/packages/{package['id']}/files",
        headers={**admin, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        content=body,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "package.file.name_invalid"


async def test_winget_identifiers_cannot_end_with_a_newline(client, db_session):
    from app.api.routes import packages

    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "Firefox", "winget_id": "Mozilla.Firefox\n"},
    )
    assert resp.status_code == 422, resp.text
    # The version is stripped before it is checked; the pattern holds anyway.
    assert packages.WINGET_VERSION.fullmatch("128.0")
    assert not packages.WINGET_VERSION.fullmatch("128.0\n")


async def test_bidi_controls_and_separators_are_refused(client, db_session):
    """Audit T38: they reorder or break what the signer reads, as control
    characters do."""
    admin = await _admin(client, db_session)
    for body in (
        {"kind": "files", "name": "App‮gnp.exe"},
        {"kind": "files", "name": "App", "version": "1.0⁦"},
        {"kind": "files", "name": "App", "detect_name": "App⁩"},
        {"kind": "files", "name": "App", "install_run": "setup‪.exe"},
        {"kind": "files", "name": "App", "uninstall_run": "un‭.exe"},
        {"kind": "files", "name": "App", "install_args": ["-s", "a b"]},
        {"kind": "files", "name": "App", "uninstall_args": [" "]},
    ):
        resp = await client.post("/api/v1/packages", headers=admin, json=body)
        assert resp.status_code == 422, (body, resp.text)


async def _uninstall(client, admin, package_id, machine_id):
    return await client.post(
        "/api/v1/commands",
        headers=admin,
        json={
            "type": "package_uninstall",
            "machine_ids": [machine_id],
            "package_id": package_id,
        },
    )


async def test_an_uninstall_no_poste_would_run_is_refused(client, db_session, store):
    """Audit T23 (U04, B30): the agent's rule — signed (B), an .exe of an
    approved publisher alone of its kind (A), or msiexec with a product code
    (A, rebuilt as /x {code}) — is applied before queueing."""
    admin = await _admin(client, db_session)
    package = await _pronote(client, admin)
    machine_id, _ = await _enroll(client, "poste-1")
    url = f"/api/v1/packages/{package['id']}"

    # msiexec with an MSI path: method A takes only a product code.
    await client.patch(
        url,
        headers=admin,
        json={"uninstall_run": "msiexec", "uninstall_args": ["/x", "{dir}\\a.msi"]},
    )
    refused = await _uninstall(client, admin, package["id"], machine_id)
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "package.not_ready"
    assert "aucun poste ne l'exécutera" in error["details"]["problems"][0]

    # A data file of the package, not an executable.
    await client.patch(
        url,
        headers=admin,
        json={"uninstall_run": "ClientPRONOTE.iss", "uninstall_args": []},
    )
    refused = await _uninstall(client, admin, package["id"], machine_id)
    assert refused.status_code == 409, refused.text

    # msiexec /x {product code}: method A runs it.
    await client.patch(
        url,
        headers=admin,
        json={
            "uninstall_run": "msiexec",
            "uninstall_args": ["/x", "{6C2A1A7B-0D5E-4F1C-9E4B-3B1C2D3E4F50}", "/qn"],
        },
    )
    accepted = await _uninstall(client, admin, package["id"], machine_id)
    assert accepted.status_code == 200, accepted.text


def test_the_loadable_extensions_match_the_agent_and_the_console():
    """Audit T02: one list in three languages — the agent's (what it refuses),
    the server's and the console's (what they predict it refuses)."""
    import re
    from pathlib import Path

    from app.features.package import manifest

    repo = Path(__file__).resolve().parents[2]
    agent_go = repo / "agent" / "internal" / "deploy" / "deploy.go"
    console_ts = repo / "frontend" / "src" / "services" / "packages.ts"
    if not agent_go.exists() or not console_ts.exists():
        pytest.skip("agent or frontend sources not in this checkout")

    go = agent_go.read_text(encoding="utf-8")
    block = re.search(r"var loadableExt = map\[string\]bool\{(.*?)\n\}", go, re.S)
    assert block, "loadableExt not found in deploy.go"
    agent = set(re.findall(r'"(\.[a-z0-9]+)":\s*true', block.group(1)))

    ts = console_ts.read_text(encoding="utf-8")
    block = re.search(r"const LOADABLE_EXTENSIONS = new Set\((.*?)\);", ts, re.S)
    assert block, "LOADABLE_EXTENSIONS not found in packages.ts"
    console = set(" ".join(re.findall(r"'([^']*)'", block.group(1))).split())

    assert set(manifest.LOADABLE_EXTENSIONS) == console
    assert set(manifest.LOADABLE_EXTENSIONS) == agent, sorted(
        agent ^ set(manifest.LOADABLE_EXTENSIONS)
    )

"""Package diagnostics as codes and parameters (plan console bilingue, I2).

The console words a package's problems, a refused name, a refused signature
and a refused field in its reader's language, from a ``code`` and its
``params``. The French ``message`` stays, unchanged, for an older console and
for other clients: every test here checks the new fields beside it.
"""

import json
import uuid

import pytest

from app.features.package import manifest, signature
from app.features.package.models import Package, PackageFile, PackageKind
from tests.test_api_packages import _admin

# --- file names --------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code,params",
    [
        ("", "empty", {}),
        ("a\x01b é.txt", "forbidden_characters", {"characters": ["U+0001", "é"]}),
        ("a»b.txt", "forbidden_characters", {"characters": ["»"]}),
        ("x" * 300, "too_long", {"max": 255}),
        ("_config.ini", "bad_first_character", {}),
        ("nul.txt", "reserved", {}),
        ("setup.", "bad_ending", {}),
    ],
)
def test_a_refused_name_says_why_as_a_code(name, code, params):
    refusal = manifest.file_name_refusal(name)
    assert refusal is not None
    assert (refusal.code, refusal.params) == (code, params)
    # The French sentence is the one the API always gave.
    assert manifest.file_name_problem(name) == refusal.message


def test_an_accepted_name_has_no_refusal():
    assert manifest.file_name_refusal("setup (x64).exe") is None
    assert manifest.file_name_problem("setup (x64).exe") is None


# --- signatures --------------------------------------------------------------


@pytest.mark.parametrize(
    "document,code,params",
    [
        (b"not json", "not_json", {}),
        (b"[1]", "not_object", {}),
        (b'{"format": "x"}', "unknown_format", {"expected": signature.FORMAT}),
        (
            json.dumps({"format": signature.FORMAT, "algorithm": "md5"}).encode(),
            "unsupported_algorithm",
            {"accepted": list(signature.ALGORITHMS)},
        ),
        (
            json.dumps(
                {"format": signature.FORMAT, "algorithm": "ecdsa-sha256"}
            ).encode(),
            "missing_field",
            {"field": "signature"},
        ),
        (
            json.dumps(
                {
                    "format": signature.FORMAT,
                    "algorithm": "ecdsa-sha256",
                    "signature": "!!",
                }
            ).encode(),
            "bad_base64",
            {"field": "signature"},
        ),
        (
            json.dumps(
                {
                    "format": signature.FORMAT,
                    "algorithm": "ecdsa-sha256",
                    "signature": "AAAA",
                    "certificate": "AAAA",
                }
            ).encode(),
            "unreadable_certificate",
            {},
        ),
    ],
)
def test_a_refused_signature_says_why_as_a_code(document, code, params):
    with pytest.raises(signature.SignatureError) as caught:
        signature.verify(b"manifest", document)
    assert (caught.value.code, caught.value.params) == (code, params)
    assert str(caught.value)  # the French sentence, as before


# --- problems ----------------------------------------------------------------


def _package(**fields) -> Package:
    return Package(id=uuid.uuid4(), kind=PackageKind.FILES, name="Outil", **fields)


def _file(name: str, publisher: str | None = None) -> PackageFile:
    return PackageFile(
        package_id=uuid.uuid4(),
        name=name,
        sha256="0" * 64,
        size=1,
        publisher_name=publisher,
    )


def test_each_problem_carries_what_its_sentence_names():
    package = _package(install_run="setup.exe", uninstall_run="remove.exe")
    found = {
        p.code: p.params
        for p in manifest.problems(package, [_file("A.ini"), _file("a.ini")])
    }
    assert found["install_missing"] == {"file": "setup.exe"}
    assert found["uninstall_missing"] == {"file": "remove.exe"}
    assert found["duplicate_names"] == {"groups": [["A.ini", "a.ini"]]}
    # Neither file was stored: both are named.
    assert found["file_missing_in_store"] == {"files": ["A.ini", "a.ini"]}


@pytest.mark.parametrize(
    "run,files,action,reason,extra",
    [
        ("msiexec", [], "uninstall", "msiexec_uninstall", {}),
        ("msiexec", [], "install", "msiexec_install", {}),
        ("tool.msi", ["tool.msi"], "install", "not_exe", {}),
        ("setup.exe", ["setup.exe"], "install", "no_publisher", {}),
        (
            "setup.exe",
            ["setup.exe", "b.dll", "A.dll"],
            "install",
            "loadable",
            {"files": ["A.dll", "b.dll"]},
        ),
    ],
)
def test_an_untrusted_step_says_why_method_a_refuses_it(
    run, files, action, reason, extra
):
    fields = {"uninstall_run": run} if action == "uninstall" else {"install_run": run}
    package = _package(**fields)
    rows = [
        _file(n, "Éditeur" if n == "setup.exe" and reason == "loadable" else None)
        for n in files
    ]
    problem = manifest._untrusted(package, rows, action)
    assert problem.code == "untrusted"
    assert problem.params == {"file": run, "reason": reason, **extra}


# --- the API -----------------------------------------------------------------


async def test_a_refused_field_gives_its_cause(client, db_session):
    admin = await _admin(client, db_session)
    resp = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "winget", "name": "Firefox", "winget_id": "pas un id !"},
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "package.invalid"
    assert error["message"] == "Identifiant winget invalide (ex. Mozilla.Firefox)"
    assert error["details"]["cause"] == {"code": "winget_id_invalid", "params": {}}

    resp = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "Outil", "install_run": "nul.exe"},
    )
    error = resp.json()["error"]
    assert error["details"]["cause"] == {
        "code": "run_file_refused",
        "params": {"file": "nul.exe", "refusal": {"code": "reserved", "params": {}}},
    }
    # What an older console read is still there.
    assert error["details"]["reason"].startswith("nom réservé par Windows")


async def test_a_refused_upload_name_gives_its_cause(client, db_session):
    admin = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/packages", headers=admin, json={"kind": "files", "name": "Outil"}
    )
    package_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/packages/{package_id}/files",
        headers=admin,
        files=[("files", ("_config.ini", b"x"))],
    )
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "package.file.name_invalid"
    assert error["details"]["cause"] == {"code": "bad_first_character", "params": {}}
    assert error["details"]["reason"] == manifest.file_name_problem("_config.ini")


async def test_the_package_lists_its_problems_and_blockers_with_their_params(
    client, db_session
):
    admin = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "Outil", "install_run": "setup.exe"},
    )
    body = created.json()
    assert {"code": "no_files", "params": {}} in [
        {"code": p["code"], "params": p["params"]} for p in body["problems"]
    ]
    missing = next(p for p in body["problems"] if p["code"] == "install_missing")
    assert missing["params"] == {"file": "setup.exe"}
    assert missing["message"] == "« setup.exe » n'est pas dans le paquet"
    assert [p["message"] for p in body["install_blocker_problems"]] == body[
        "install_blockers"
    ]


async def test_a_refused_deployment_gives_the_causes(client, db_session):
    admin = await _admin(client, db_session)
    created = await client.post(
        "/api/v1/packages",
        headers=admin,
        json={"kind": "files", "name": "Outil", "install_run": "setup.exe"},
    )
    package_id = created.json()["id"]
    resp = await client.put(
        f"/api/v1/packages/{package_id}/signature", headers=admin, json={}
    )
    assert resp.status_code == 409
    details = resp.json()["error"]["details"]
    assert len(details["causes"]) == len(details["problems"])
    assert {"code": "install_missing", "params": {"file": "setup.exe"}} in details[
        "causes"
    ]

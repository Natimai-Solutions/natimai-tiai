"""The French sentences of the package diagnostics, shared with the console.

Since the bilingual console (plan ``dev/plan-console-bilingue.md``, I2), the
console words a package problem, a refused field, a refused file name and a
refused signature itself, from the ``code`` and ``params`` the server sends.
Its French must stay the sentence the server writes in ``message``: an
installation updated to this version reads the same as before.

``tests/data/package_texts_fr.json`` holds the cases: this test checks the
server still writes them, ``frontend/src/utils/packageText.spec.ts`` that the
console writes the same from the codes. Regenerate it after a deliberate
change of wording with ``python -m tests.test_package_texts`` (run from
``backend/``, with ENVIRONMENT=local), and change the console's catalogue to
match.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "data" / "package_texts_fr.json"


def _package(**fields: Any):
    from app.features.package.models import Package, PackageKind

    return Package(id=uuid.uuid4(), kind=PackageKind.FILES, name="Outil", **fields)


def _file(name: str, publisher: str | None = None):
    from app.features.package.models import PackageFile

    return PackageFile(
        package_id=uuid.uuid4(),
        name=name,
        sha256="0" * 64,
        size=1,
        publisher_name=publisher,
    )


def _problems() -> list[dict[str, Any]]:
    from app.features.package import manifest

    found = []
    found += manifest.problems(_package(), [])
    found += manifest.problems(
        _package(install_run="setup.exe", uninstall_run="remove.exe"),
        [_file("A.ini"), _file("a.ini"), _file("B.txt"), _file("b.TXT")],
    )
    found += manifest.problems(
        _package(install_run="msiexec", install_args=["/x", "{X}"]), [_file("x")]
    )
    found += manifest.step_blockers(_package(install_run="setup.exe"), [], "uninstall")
    unsigned = [
        (_package(uninstall_run="msiexec"), [], "uninstall"),
        (_package(install_run="msiexec"), [], "install"),
        (_package(install_run="tool.msi"), [_file("tool.msi")], "install"),
        (_package(install_run="setup.exe"), [_file("setup.exe")], "install"),
        (
            _package(install_run="setup.exe"),
            [_file("setup.exe", "Éditeur"), _file("a.dll")],
            "install",
        ),
        (
            _package(install_run="setup.exe"),
            [_file("setup.exe", "Éditeur"), _file("b.dll"), _file("A.ocx")],
            "install",
        ),
    ]
    found += [manifest._untrusted(p, f, a) for p, f, a in unsigned]
    return [
        {"kind": "problem", "code": p.code, "params": p.params, "message": p.message}
        for p in found
    ]


def _too_large() -> list[dict[str, Any]]:
    """Method A's cap, read from the settings: 8 GiB by default."""
    from app.features.package import manifest

    package = _package(install_run="setup.exe")
    files = [_file("setup.exe", "Éditeur")]
    original = manifest.runnable_somewhere
    manifest.runnable_somewhere = lambda *a, **k: True  # type: ignore[assignment]
    try:
        problem = manifest._untrusted(package, files, "install")
    finally:
        manifest.runnable_somewhere = original  # type: ignore[assignment]
    return [
        {
            "kind": "problem",
            "code": problem.code,
            "params": problem.params,
            "message": problem.message,
        }
    ]


def _file_names() -> list[dict[str, Any]]:
    from app.features.package import manifest

    out = []
    for name in ["", "a\x01b é.txt", "a»b.txt", "x" * 300, "_a.ini", "nul.txt", "a."]:
        refusal = manifest.file_name_refusal(name)
        assert refusal is not None
        out.append(
            {
                "kind": "file_name",
                "name": name,
                "cause": {"code": refusal.code, "params": refusal.params},
                "message": f"« {name} » refusé : {refusal.message}",
            }
        )
    return out


def _invalid() -> list[dict[str, Any]]:
    from app.api.routes.packages import _apply
    from app.core.errors import AppError
    from app.features.package.models import PackageKind

    attempts = [
        (PackageKind.WINGET, {"winget_id": "pas un id"}),
        (PackageKind.WINGET, {"winget_id": "A.B", "winget_version": "1 2"}),
        (PackageKind.WINGET, {"winget_id": "A.B", "install_run": "x.exe"}),
        (PackageKind.FILES, {"winget_id": "A.B"}),
        (PackageKind.FILES, {"install_run": "nul.exe"}),
        (PackageKind.FILES, {"install_run": "_a.exe"}),
        (PackageKind.FILES, {"uninstall_run": "msiexec", "uninstall_args": []}),
        (PackageKind.FILES, {"install_run": "msiexec", "install_args": []}),
        (PackageKind.FILES, {"install_run": "msiexec", "install_args": ["/x", "{X}"]}),
    ]
    out = []
    for kind, fields in attempts:
        package = _package()
        package.kind = kind
        with pytest.raises(AppError) as caught:
            _apply(package, dict(fields))
        details = caught.value.details or {}
        out.append(
            {
                "kind": "invalid",
                "cause": details["cause"],
                "message": caught.value.message,
            }
        )
    return out


def _signatures() -> list[dict[str, Any]]:
    from app.features.package import signature

    documents = [
        b"pas du json",
        b"[1]",
        b'{"format": "x"}',
        json.dumps({"format": signature.FORMAT, "algorithm": "md5"}).encode(),
        json.dumps({"format": signature.FORMAT, "algorithm": "ecdsa-sha256"}).encode(),
        json.dumps(
            {"format": signature.FORMAT, "algorithm": "ecdsa-sha256", "signature": "!"}
        ).encode(),
        json.dumps(
            {
                "format": signature.FORMAT,
                "algorithm": "ecdsa-sha256",
                "signature": "AAAA",
            }
        ).encode(),
        json.dumps(
            {
                "format": signature.FORMAT,
                "algorithm": "ecdsa-sha256",
                "signature": "AAAA",
                "certificate": "!",
            }
        ).encode(),
        json.dumps(
            {
                "format": signature.FORMAT,
                "algorithm": "ecdsa-sha256",
                "signature": "AAAA",
                "certificate": "AAAA",
            }
        ).encode(),
    ]
    out = []
    for document in documents:
        with pytest.raises(signature.SignatureError) as caught:
            signature.verify(b"manifest", document)
        error = caught.value
        out.append(
            {
                "kind": "signature",
                "cause": {"code": error.code, "params": error.params},
                "message": str(error),
            }
        )
    # The refusals that need a real certificate: a self-signed one per key.
    rsa_key, rsa_doc = _signed_by("rsa")
    ec_key, ec_doc = _signed_by("ecdsa")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    other_bytes = rsa_key.sign(b"other", padding.PKCS1v15(), hashes.SHA256())
    for document in [
        rsa_doc("ecdsa-sha256", b"\0" * 64),  # algorithm and key disagree
        rsa_doc("rsa-pkcs1-sha256", other_bytes),  # this key, other bytes
        rsa_doc("rsa-pkcs1-sha256", b"\0" * 256),  # another key
        ec_doc("ecdsa-sha256", b"\0" * 64),  # ECDSA cannot tell which
    ]:
        with pytest.raises(signature.SignatureError) as caught:
            signature.verify(b"manifest", document)
        error = caught.value
        out.append(
            {
                "kind": "signature",
                "cause": {"code": error.code, "params": error.params},
                "message": str(error),
            }
        )
    return out


def _signed_by(kind: str):
    """A key, and a maker of signature documents with its self-signed
    certificate and a given algorithm and signature."""
    import base64
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.x509.oid import NameOID

    from app.features.package import signature

    key = (
        rsa.generate_private_key(65537, 2048)
        if kind == "rsa"
        else ec.generate_private_key(ec.SECP256R1())
    )
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)

    def document(algorithm: str, sig: bytes) -> bytes:
        return json.dumps(
            {
                "format": signature.FORMAT,
                "algorithm": algorithm,
                "signature": base64.b64encode(sig).decode(),
                "certificate": base64.b64encode(der).decode(),
            }
        ).encode()

    return key, document


def cases() -> list[dict[str, Any]]:
    return _problems() + _too_large() + _file_names() + _invalid() + _signatures()


def test_the_server_still_writes_the_shared_sentences():
    assert cases() == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_every_code_is_covered():
    """Each problem, refusal and cause the server can give has a case, so the
    console's French is checked for all of them."""
    covered = {(c["kind"], c.get("code") or c["cause"]["code"]) for c in cases()}
    reasons = {
        c["params"].get("reason") for c in cases() if c.get("code") == "untrusted"
    }
    problem_codes = {code for kind, code in covered if kind == "problem"}
    assert problem_codes >= {
        "no_files",
        "no_install",
        "install_missing",
        "install_removes",
        "uninstall_missing",
        "duplicate_names",
        "file_missing_in_store",
        "method_a_too_large",
        "no_uninstall",
        "untrusted",
    }
    assert reasons >= {
        "msiexec_uninstall",
        "msiexec_install",
        "not_exe",
        "no_publisher",
        "loadable",
    }


if __name__ == "__main__":
    FIXTURE.write_text(
        json.dumps(cases(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{len(cases())} cases written to {FIXTURE}")

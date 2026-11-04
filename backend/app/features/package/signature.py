"""Method B: the administrator's signature over a package manifest.

Produced off the server by ``deploy/packages/Sign-TiaiPackage.ps1`` as a small
JSON document::

    {"format": "tiai-signature-1", "algorithm": "rsa-pkcs1-sha256" | "ecdsa-sha256",
     "signature": "<base64>", "certificate": "<base64 DER>"}

The server checks it so that the console can say "signé par …" and refuse a
signature made over another manifest; the poste checks it again against the
certificates its GPO trusts, and that second check is the one that matters.
"""

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

FORMAT = "tiai-signature-1"
ALGORITHMS = ("rsa-pkcs1-sha256", "ecdsa-sha256")


class SignatureError(ValueError):
    """The signature document is malformed, or does not verify."""


@dataclass(frozen=True)
class Verified:
    algorithm: str
    signature: bytes
    certificate: bytes
    thumbprint: str  # SHA-256 of the DER certificate, upper-case hex
    subject: str


def thumbprint(certificate_der: bytes) -> str:
    return hashlib.sha256(certificate_der).hexdigest().upper()


def _ecdsa_der(signature: bytes, key: ec.EllipticCurvePublicKey) -> bytes:
    """.NET's ``ECDsa.SignData`` returns r‖s (IEEE P1363); OpenSSL wants DER.
    Accept both: a P1363 signature is exactly twice the field size."""
    size = (key.curve.key_size + 7) // 8
    if len(signature) == 2 * size:
        r = int.from_bytes(signature[:size], "big")
        s = int.from_bytes(signature[size:], "big")
        return encode_dss_signature(r, s)
    return signature


def verify(manifest: bytes, document: bytes) -> Verified:
    """Parse the signature document and verify it over ``manifest``."""
    try:
        data = json.loads(document)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SignatureError("Le fichier de signature n'est pas du JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise SignatureError("Format de signature inconnu")
    algorithm = data.get("algorithm")
    if algorithm not in ALGORITHMS:
        raise SignatureError("Algorithme de signature non pris en charge")
    try:
        signature = base64.b64decode(str(data.get("signature", "")), validate=True)
        cert_der = base64.b64decode(str(data.get("certificate", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("Signature ou certificat mal encodés") from exc
    try:
        cert = x509.load_der_x509_certificate(cert_der)
    except ValueError as exc:
        raise SignatureError("Certificat illisible") from exc

    key = cert.public_key()
    try:
        if algorithm == "rsa-pkcs1-sha256" and isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, manifest, padding.PKCS1v15(), hashes.SHA256())
        elif algorithm == "ecdsa-sha256" and isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(_ecdsa_der(signature, key), manifest, ec.ECDSA(hashes.SHA256()))
        else:
            raise SignatureError(
                "L'algorithme ne correspond pas à la clé du certificat"
            )
    except InvalidSignature as exc:
        raise SignatureError(
            "La signature ne correspond pas à ce manifeste — a-t-il changé depuis ?"
        ) from exc
    return Verified(
        algorithm=algorithm,
        signature=signature,
        certificate=cert_der,
        thumbprint=thumbprint(cert_der),
        subject=cert.subject.rfc4514_string(),
    )

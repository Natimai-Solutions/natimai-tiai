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


def _base64(value: object, what: str) -> bytes:
    """A base64 field of the document, refused by name when it is not one."""
    if not isinstance(value, str) or not value:
        raise SignatureError(f"{what} est absent du fichier de signature.")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(
            f"{what} n'est pas encodé en base64 valide : le fichier a-t-il été "
            "modifié après sa production ?"
        ) from exc


def _key_kind(key: object) -> str:
    if isinstance(key, rsa.RSAPublicKey):
        return "clé RSA"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return "clé ECDSA"
    return "clé d'un type non pris en charge"


def _mismatch(key: object, signature: bytes) -> str:
    """Why a well-formed signature does not verify, as far as one can tell.

    RSA gives the digest it signed back (PKCS#1 v1.5): a digest that comes
    out, but of other bytes, is this certificate's signature over another
    manifest — the package changed since it was downloaded; nothing coming
    out means another key made it. ECDSA cannot tell the two apart."""
    stale = (
        "La signature ne correspond pas au manifeste actuel : le paquet a changé "
        "depuis le téléchargement du manifeste signé. Téléchargez de nouveau le "
        "manifeste et signez-le."
    )
    if isinstance(key, rsa.RSAPublicKey):
        try:
            key.recover_data_from_signature(
                signature, padding.PKCS1v15(), hashes.SHA256()
            )
        except (InvalidSignature, ValueError):
            return (
                "La signature n'a pas été faite avec la clé du certificat joint : "
                "signée avec un autre certificat que celui du fichier."
            )
        return stale
    return (
        "La signature ne correspond pas : soit le manifeste a changé depuis qu'il "
        "a été signé (téléchargez-le de nouveau et signez-le), soit elle a été "
        "faite avec un autre certificat que celui du fichier."
    )


def verify(manifest: bytes, document: bytes) -> Verified:
    """Parse the signature document and verify it over ``manifest``."""
    try:
        data = json.loads(document)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SignatureError("Le fichier de signature n'est pas du JSON.") from exc
    if not isinstance(data, dict):
        raise SignatureError(
            "Le fichier de signature n'est pas un objet JSON ({ … }) : déposez le "
            "fichier .sig.json produit par Sign-TiaiPackage.ps1."
        )
    if data.get("format") != FORMAT:
        raise SignatureError(
            f"Format de signature inconnu (« {FORMAT} » attendu) : ce fichier n'a "
            "pas été produit par Sign-TiaiPackage.ps1."
        )
    algorithm = data.get("algorithm")
    if algorithm not in ALGORITHMS:
        raise SignatureError(
            "Algorithme de signature non pris en charge : seuls "
            "« rsa-pkcs1-sha256 » et « ecdsa-sha256 » sont acceptés."
        )
    signature = _base64(data.get("signature"), "La signature")
    cert_der = _base64(data.get("certificate"), "Le certificat")
    try:
        cert = x509.load_der_x509_certificate(cert_der)
    except ValueError as exc:
        raise SignatureError(
            "Certificat illisible : le champ « certificate » ne contient pas un "
            "certificat X.509 (DER encodé en base64)."
        ) from exc

    key = cert.public_key()
    try:
        if algorithm == "rsa-pkcs1-sha256" and isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, manifest, padding.PKCS1v15(), hashes.SHA256())
        elif algorithm == "ecdsa-sha256" and isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(_ecdsa_der(signature, key), manifest, ec.ECDSA(hashes.SHA256()))
        else:
            raise SignatureError(
                f"L'algorithme annoncé (« {algorithm} ») ne correspond pas à la "
                f"clé du certificat ({_key_kind(key)}) : la signature a été "
                "produite pour un autre certificat ou modifiée à la main."
            )
    except InvalidSignature as exc:
        raise SignatureError(_mismatch(key, signature)) from exc
    return Verified(
        algorithm=algorithm,
        signature=signature,
        certificate=cert_der,
        thumbprint=thumbprint(cert_der),
        subject=cert.subject.rfc4514_string(),
    )

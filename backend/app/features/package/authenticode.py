"""Who signed a Windows executable — for the console to *display*.

Reads the Authenticode signature embedded in a PE file (the certificate table
of the optional header) and returns the signer's name as Windows shows it in
the "Signatures numériques" tab: the common name of the signing certificate.

Nothing is *verified* here: the server runs on Linux, and the decision belongs
to the poste anyway (``WinVerifyTrust``, then the publishers its GPO
approves). What this gives the console is the line "signé par INDEX
EDUCATION SAS" next to the file, so that the administrator knows which name
to put in the GPO — or that the file is not signed at all.
"""

import struct
from typing import BinaryIO

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_SECURITY_DIRECTORY = 4
_WIN_CERT_TYPE_PKCS_SIGNED_DATA = 0x0002


def _read_at(f: BinaryIO, offset: int, size: int) -> bytes:
    f.seek(offset)
    data = f.read(size)
    if len(data) != size:
        raise ValueError("truncated")
    return data


def _pkcs7_blob(f: BinaryIO) -> bytes | None:
    """The PKCS#7 SignedData of the first WIN_CERTIFICATE, or None."""
    if _read_at(f, 0, 2) != b"MZ":
        return None
    (pe_offset,) = struct.unpack("<I", _read_at(f, 0x3C, 4))
    if _read_at(f, pe_offset, 4) != b"PE\0\0":
        return None
    optional = pe_offset + 24
    (magic,) = struct.unpack("<H", _read_at(f, optional, 2))
    if magic == 0x10B:  # PE32
        directories = optional + 96
    elif magic == 0x20B:  # PE32+
        directories = optional + 112
    else:
        return None
    address, size = struct.unpack(
        "<II", _read_at(f, directories + 8 * _SECURITY_DIRECTORY, 8)
    )
    # For this one directory the "address" is a file offset, not an RVA.
    if address == 0 or size < 8:
        return None
    length, _revision, cert_type = struct.unpack("<IHH", _read_at(f, address, 8))
    if cert_type != _WIN_CERT_TYPE_PKCS_SIGNED_DATA or length <= 8:
        return None
    return _read_at(f, address + 8, min(length, size) - 8)


def _signer(certs: list[x509.Certificate]) -> x509.Certificate | None:
    """The leaf: a certificate no other one in the set was issued by, with
    the code-signing usage when it says."""
    issuers = {c.issuer for c in certs}
    leaves = [c for c in certs if c.subject not in issuers or c.subject == c.issuer]
    for cert in leaves:
        try:
            usage = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        except x509.ExtensionNotFound:
            continue
        if ExtendedKeyUsageOID.CODE_SIGNING in usage.value:
            return cert
    return leaves[0] if leaves else None


def signer_name(f: BinaryIO) -> str | None:
    """The common name of the Authenticode signer, or None when the file is
    not a signed PE (or not a PE at all — an ``.iss``, an MSI)."""
    try:
        blob = _pkcs7_blob(f)
        if blob is None:
            return None
        cert = _signer(pkcs7.load_der_pkcs7_certificates(blob))
    except (ValueError, struct.error):
        return None
    if cert is None:
        return None
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    value = names[0].value if names else cert.subject.rfc4514_string()
    return value if isinstance(value, str) else value.decode("utf-8", "replace")

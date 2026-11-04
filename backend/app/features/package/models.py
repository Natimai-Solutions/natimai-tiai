"""Software packages the console can deploy (``dev/plan-deploiement-logiciel.md``).

Two kinds:

* ``winget`` — an identifier of the community repository; winget downloads the
  installer and checks the hash its manifest publishes;
* ``files`` — one or more files uploaded to the console and a command line,
  described by a *manifest*. The poste runs it only if the manifest is signed
  by a certificate its GPO trusts (method B), or failing that if the file it
  runs is signed by a publisher its GPO approves (method A).

The trust decision is the poste's, never the server's: what is stored here
about signatures is for the console to display.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, ForeignKey, Index, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class PackageKind(enum.StrEnum):
    WINGET = "winget"
    FILES = "files"


# What a Windows installer commonly returns on success: 0, and the two codes
# that mean "done, a restart will finish the job" (ERROR_SUCCESS_REBOOT_REQUIRED
# and ERROR_SUCCESS_REBOOT_INITIATED). The restart itself is never the agent's.
DEFAULT_SUCCESS_CODES = [0, 3010, 1641]


class Package(SQLModel, table=True):
    __tablename__ = "packages"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: str = Field(max_length=20)
    name: str = Field(max_length=200)
    version: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    # winget
    winget_id: str | None = Field(default=None, max_length=128)
    winget_version: str | None = Field(default=None, max_length=64)

    # files: what to run, as a file of the package (or "msiexec" for an
    # uninstall by product code), and its arguments as a list — never a
    # command line a shell would split.
    install_run: str | None = Field(default=None, max_length=255)
    install_args: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    uninstall_run: str | None = Field(default=None, max_length=255)
    uninstall_args: list[str] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, default=list)
    )
    success_codes: list[int] = Field(
        default_factory=lambda: list(DEFAULT_SUCCESS_CODES),
        sa_column=Column(JSONB, nullable=False, default=list),
    )

    # How the program shows in the inventory ("Applications et
    # fonctionnalités"), as a case-insensitive substring: what the console
    # counts as "installé".
    detect_name: str | None = Field(default=None, max_length=200)

    # files: the exact bytes of the manifest — what method B signs. Rebuilt on
    # every change, which voids the signature below.
    manifest: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    signature: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    signature_algorithm: str | None = Field(default=None, max_length=40)
    signer_certificate: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    # SHA-256 of the certificate (hex, upper case): what the GPO lists.
    signer_thumbprint: str | None = Field(default=None, max_length=64)
    signer_subject: str | None = Field(default=None, max_length=500)
    signed_at: datetime | None = utc_field(default=None, nullable=True)
    signed_by: str | None = None

    # Method A: the signer of the file ``install_run`` names, read at upload.
    # Information only — the poste verifies the signature itself.
    publisher_name: str | None = Field(default=None, max_length=300)

    created_by: str | None = None
    created_at: datetime = utc_field(default_factory=utcnow)
    updated_at: datetime = utc_field(default_factory=utcnow)
    retired_at: datetime | None = utc_field(default=None, nullable=True)


class PackageFile(SQLModel, table=True):
    """One file of a ``files`` package. The bytes live on the packages volume
    under their SHA-256 (``storage``), so two packages carrying the same
    installer share it."""

    __tablename__ = "package_files"
    __table_args__ = (Index("ix_package_files_sha256", "sha256"),)

    package_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True
        )
    )
    name: str = Field(primary_key=True, max_length=255)
    sha256: str = Field(max_length=64)
    size: int = Field(sa_column=Column(BigInteger, nullable=False))
    # Signer of this file when it carries an Authenticode signature (a PE).
    publisher_name: str | None = Field(default=None, max_length=300)
    created_at: datetime = utc_field(default_factory=utcnow)


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []

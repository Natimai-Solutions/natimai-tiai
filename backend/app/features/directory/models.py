"""What the directory says, read by designated postes (dev/plan-lecture-annuaire.md).

``directory_domains``: one row per domain a reader has read, identified by
its SID — two schools may both be « ecole.local ». ``directory_records``: one
row per computer object, per reader that read it, so that two readers of a
domain can be compared.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.features.base import utc_field, utcnow


class DirectoryDomain(SQLModel, table=True):
    __tablename__ = "directory_domains"
    __table_args__ = (
        # One domain per NetBIOS name: the agents declare their domain by
        # that name alone, so two domains bearing it could not be told apart
        # — and a reader inventing a second SID for a name must not be able
        # to unsettle the postes of the first.
        Index(
            "uq_directory_domains_netbios",
            text("lower(netbios_name)"),
            unique=True,
        ),
    )

    sid: str = Field(primary_key=True, max_length=100)
    # Its DNS name, as the reader reports it: for display.
    name: str = Field(max_length=255)
    # Its NetBIOS name: what the agents declare as their domain, hence what
    # a poste is matched to its domain by.
    netbios_name: str = Field(max_length=64)
    # Subnets and the AD site each belongs to, [{"subnet", "site"}]: kept for
    # the verified wake relays (plan §4.2), read with the computers.
    subnets: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    last_read_at: datetime | None = utc_field(default=None, nullable=True)
    last_reader_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(ForeignKey("machines.id", ondelete="SET NULL"), nullable=True),
    )
    objects_read: int = Field(default=0)
    # Set when two readers disagree on an object: nothing moves until they
    # agree again (plan §3.2).
    disagreement_at: datetime | None = utc_field(default=None, nullable=True)
    disagreement: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    # A reading that would move more than DIRECTORY_CONFIRM_MOVES postes:
    # held here, [{"machine_id", "from", "to"}], until confirmed or discarded.
    pending_moves: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    pending_since: datetime | None = utc_field(default=None, nullable=True)
    # How many moves are held (the list above is cut at 200).
    pending_count: int = Field(default=0)
    created_at: datetime = utc_field(default_factory=utcnow)


class DirectoryRecord(SQLModel, table=True):
    """One computer object as one reader read it."""

    __tablename__ = "directory_records"
    __table_args__ = (
        UniqueConstraint(
            "source", "object_guid", name="uq_directory_records_source_guid"
        ),
        Index("ix_directory_records_domain_sam", "domain_sid", "sam_account_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    object_guid: str = Field(max_length=64)
    domain_sid: str = Field(
        sa_column=Column(
            ForeignKey("directory_domains.sid", ondelete="CASCADE"), nullable=False
        )
    )
    sam_account_name: str = Field(max_length=256)
    dns_host_name: str | None = Field(default=None, max_length=255)
    distinguished_name: str | None = None
    ou: str | None = None
    ou_dn: str | None = None
    location: str | None = None
    disabled: bool = Field(default=False)
    # « relay:<machine id> »: which reader read it (« ldap » later).
    source: str = Field(max_length=64)
    read_at: datetime = utc_field(default_factory=utcnow)

"""Identity fingerprint diffing.

The machine is looked up by its stable identity (machine_uuid / token). The
fingerprint *components* are stored separately so we can apply per-attribute
rules rather than a binary hash:

- hostname / domain / machine_guid drift  -> benign (rename, OS re-image), update silently
- smbios_uuid or tpm_ek_hash drift         -> suspicious (hardware swap, clone, token theft)

A suspicious delta sets ``needs_verification`` (sticky until an admin clears it).
"""

from app.features.machine.models import Machine

# SMBIOS UUIDs that identify nothing: the null and all-F placeholders, and the
# constant whitebox and small-OEM firmwares ship unchanged on every unit they
# build. The agent already refuses them as an identity
# (``agent/internal/identity/identity.go``) and falls back to a UUID of its own —
# but it still *reports* the value, and the server stores it. So the server has
# to know them too: taken at face value, one constant shared by forty postes
# makes each of them look like a duplicate of the other thirty-nine, which is
# how a merge could delete a machine that was never a duplicate at all.
#
# Kept in step with the agent's own denylist.
INVALID_SMBIOS_UUIDS = frozenset(
    {
        "00000000-0000-0000-0000-000000000000",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
        "03000200-0400-0500-0006-000700080009",
    }
)


def trustworthy_smbios_uuid(smbios_uuid: str | None) -> str | None:
    """The SMBIOS UUID if it identifies one machine, else None.

    None means "this poste has no usable hardware anchor" — never "the values
    are equal", which is the reading that turns a shared constant into a fleet
    of mutual duplicates.
    """
    if not smbios_uuid:
        return None
    normalized = smbios_uuid.strip().lower()
    if not normalized or normalized in INVALID_SMBIOS_UUIDS:
        return None
    return normalized


def is_suspicious_change(
    machine: Machine, *, smbios_uuid: str | None, tpm_ek_hash: str | None
) -> bool:
    """Whether the reported anchor differs from what was recorded.

    An untrustworthy SMBIOS value counts as no anchor on either side: a poste
    whose firmware constant gave way to a real UUID (a BIOS update, a newer
    agent) has not changed hardware, and flagging it would send an administrator
    looking for a clone that does not exist.
    """
    stored_smbios = trustworthy_smbios_uuid(machine.smbios_uuid)
    reported_smbios = trustworthy_smbios_uuid(smbios_uuid)
    if stored_smbios and reported_smbios and stored_smbios != reported_smbios:
        return True
    if machine.tpm_ek_hash and tpm_ek_hash and machine.tpm_ek_hash != tpm_ek_hash:
        return True
    return False


def store_fingerprint(
    machine: Machine,
    *,
    machine_guid: str | None,
    smbios_uuid: str | None,
    tpm_ek_hash: str | None,
) -> None:
    """Update the stored fingerprint components with the latest reported values."""
    if machine_guid is not None:
        machine.machine_guid = machine_guid
    if smbios_uuid is not None:
        machine.smbios_uuid = smbios_uuid
    if tpm_ek_hash is not None:
        machine.tpm_ek_hash = tpm_ek_hash

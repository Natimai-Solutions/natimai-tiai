from app.features.machine.fingerprint import is_suspicious_change, store_fingerprint
from app.features.machine.models import Machine


def _machine(**kwargs) -> Machine:
    return Machine(machine_uuid="machine-1", **kwargs)


def test_first_fingerprint_is_not_suspicious():
    """A machine with no stored anchor accepts its first fingerprint."""
    m = _machine()
    assert not is_suspicious_change(m, smbios_uuid="smbios-a", tpm_ek_hash=None)


def test_identical_anchor_is_not_suspicious():
    m = _machine(smbios_uuid="smbios-a", tpm_ek_hash="tpm-a")
    assert not is_suspicious_change(m, smbios_uuid="smbios-a", tpm_ek_hash="tpm-a")


def test_smbios_change_is_suspicious():
    """A changed SMBIOS anchor signals a hardware swap / clone."""
    m = _machine(smbios_uuid="smbios-a")
    assert is_suspicious_change(m, smbios_uuid="smbios-b", tpm_ek_hash=None)


def test_tpm_change_is_suspicious():
    m = _machine(tpm_ek_hash="tpm-a")
    assert is_suspicious_change(m, smbios_uuid=None, tpm_ek_hash="tpm-b")


def test_store_updates_only_provided_components():
    """store_fingerprint leaves unprovided (None) components untouched."""
    m = _machine(machine_guid="guid-1", smbios_uuid="smbios-1")
    store_fingerprint(m, machine_guid=None, smbios_uuid="smbios-2", tpm_ek_hash="tpm-1")
    assert m.machine_guid == "guid-1"  # not overwritten by None
    assert m.smbios_uuid == "smbios-2"
    assert m.tpm_ek_hash == "tpm-1"


def test_store_sets_all_provided_components():
    m = _machine()
    store_fingerprint(
        m, machine_guid="guid-9", smbios_uuid="smbios-9", tpm_ek_hash="tpm-9"
    )
    assert m.machine_guid == "guid-9"
    assert m.smbios_uuid == "smbios-9"
    assert m.tpm_ek_hash == "tpm-9"


def test_firmware_constants_are_not_an_anchor():
    """A UUID every unit of a batch reports identifies none of them.

    The agent already refuses these as an identity, but it still reports them
    and the server stores them — so the server has to refuse them too, or forty
    whiteboxes would each look like a duplicate of the other thirty-nine.
    """
    from app.features.machine.fingerprint import trustworthy_smbios_uuid

    assert trustworthy_smbios_uuid("00000000-0000-0000-0000-000000000000") is None
    assert trustworthy_smbios_uuid("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF") is None
    assert trustworthy_smbios_uuid("03000200-0400-0500-0006-000700080009") is None
    assert trustworthy_smbios_uuid(None) is None
    assert trustworthy_smbios_uuid("  ") is None


def test_a_real_anchor_is_normalised_not_rejected():
    from app.features.machine.fingerprint import trustworthy_smbios_uuid

    assert trustworthy_smbios_uuid("  4C4C4544-0031-XXXX  ") == "4c4c4544-0031-xxxx"


def test_a_constant_giving_way_to_a_real_uuid_is_not_a_hardware_swap():
    """A BIOS update or a newer agent is not a clone.

    Both directions: the stored value and the reported one are each read as
    "no anchor" when untrustworthy, so neither transition raises the flag that
    puts an « à vérifier » banner on a poste that is perfectly fine.
    """
    m = _machine(smbios_uuid="03000200-0400-0500-0006-000700080009")
    assert not is_suspicious_change(m, smbios_uuid="real-uuid", tpm_ek_hash=None)

    m = _machine(smbios_uuid="real-uuid")
    assert not is_suspicious_change(
        m, smbios_uuid="00000000-0000-0000-0000-000000000000", tpm_ek_hash=None
    )

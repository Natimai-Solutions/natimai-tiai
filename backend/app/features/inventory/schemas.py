"""Wire schemas for the heartbeat's ``inventory`` block.

Same trade-off as ``WUStateReport`` and ``AVProduct``: every field is bounded or
defaulted rather than validated strictly. These strings come from vendor firmware
and from the registry — a motherboard model is whatever the OEM flashed into
SMBIOS — and a 422 on one malformed entry would cost the Defender state, the
threats and the command pickup riding along in the same heartbeat.

The three-state discipline of the rest of the protocol applies to every list
here, and it is load-bearing: ``null`` means *not read* (an agent too old, a WMI
namespace that is absent on this SKU) and leaves the stored set alone, while
``[]`` means *read and empty* and clears it. A virtual machine genuinely has no
memory modules, and a machine whose software collection is switched off by GPO
genuinely reports no software — both are findings, not gaps.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator

# Bounds on what one reported string can write to the database and pour into the
# console. Generous: a GPU name ("NVIDIA GeForce RTX 4060 Laptop GPU") and a
# program name from the registry are the long ones, and neither is queried.
TEXT_MAX = 200
# An install location is a path, which is longer than a label.
PATH_MAX = 400
# SHA-256, hex.
HASH_MAX = 64
# A distinguished name: a deep OU tree runs to a few hundred characters.
DN_MAX = 500

# Caps per list. Above these the report has stopped describing a workstation —
# a broken agent, or a hostile one — and the excess is dropped rather than
# stored. Applied to the *list*, so the machine's other sections still land.
MAX_MEMORY_MODULES = 64
MAX_DISKS = 32
MAX_VOLUMES = 64
MAX_NICS = 64
MAX_GPUS = 8
# A well-stocked workstation reports 200 to 400 entries; a developer's machine
# reaches four figures. Two thousand leaves headroom over anything real.
MAX_SOFTWARE = 2000

# Above these an integer has stopped being a measurement of a poste. They exist
# so a firmware that reports 0xFFFFFFFF for "unknown" — several do — lands as
# NULL instead of as a 4-petabyte disk on the dashboard.
MAX_MB = 1024 * 1024 * 64  # 64 TiB, in mebibytes
MAX_COUNT = 4096  # cores, threads, sockets, slots
MAX_MHZ = 100_000
MAX_MBPS = 10_000_000  # 10 Tb/s

NIC_TYPE_WIFI = "wifi"
NIC_TYPE_ETHERNET = "ethernet"
NIC_TYPE_OTHER = "other"


def _bounded(value: str | None, limit: int = TEXT_MAX) -> str | None:
    """Trim and cap a reported string; empty becomes NULL.

    "" and NULL are the same thing for every field in this module — unlike
    ``av_product_name``, where an empty name is the finding "no antivirus at
    all". Here a blank motherboard serial is simply a serial the OEM did not
    flash, and storing "" would only make the console print an empty cell where
    it means to print a dash.
    """
    if value is None:
        return None
    return value.strip()[:limit] or None


def _bounded_int(value: int | None, limit: int) -> int | None:
    """Keep a plausible non-negative count, drop anything else."""
    if value is None or value < 0 or value > limit:
        return None
    return value


class MemoryModuleReport(BaseModel):
    """One physical memory stick."""

    model_config = ConfigDict(extra="ignore")

    # The dedup key. An entry without one is dropped by the crud layer.
    slot: str = ""
    capacity_mb: int | None = None
    type: str | None = None
    speed_mhz: int | None = None
    manufacturer: str | None = None
    serial: str | None = None
    form_factor: str | None = None

    @field_validator("slot")
    @classmethod
    def _bound_slot(cls, value: str) -> str:
        return value.strip()[:TEXT_MAX]

    @field_validator("type", "manufacturer", "serial", "form_factor")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("capacity_mb")
    @classmethod
    def _bound_capacity(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MB)

    @field_validator("speed_mhz")
    @classmethod
    def _bound_speed(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MHZ)


class DiskReport(BaseModel):
    """One physical drive."""

    model_config = ConfigDict(extra="ignore")

    # The dedup key: Windows' own device id. Not the serial — see the model.
    device_id: str = ""
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    media_type: str | None = None
    bus_type: str | None = None
    size_mb: int | None = None
    health_status: str | None = None
    is_removable: bool = False

    @field_validator("device_id")
    @classmethod
    def _bound_device_id(cls, value: str) -> str:
        return value.strip()[:TEXT_MAX]

    @field_validator("model", "serial", "firmware", "media_type", "bus_type")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("health_status")
    @classmethod
    def _bound_health(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("size_mb")
    @classmethod
    def _bound_size(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MB)


class VolumeReport(BaseModel):
    """One fixed logical volume."""

    model_config = ConfigDict(extra="ignore")

    # The dedup key.
    letter: str = ""
    label: str | None = None
    filesystem: str | None = None
    total_mb: int | None = None
    free_mb: int | None = None
    is_system: bool = False
    encryption_status: str | None = None

    @field_validator("letter")
    @classmethod
    def _bound_letter(cls, value: str) -> str:
        # "C:" — capped short, and upper-cased so one poste's "c:" and another's
        # "C:" are the same volume to a fleet-wide query.
        return value.strip().upper()[:8]

    @field_validator("label", "filesystem", "encryption_status")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("total_mb", "free_mb")
    @classmethod
    def _bound_size(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MB)


class NicReport(BaseModel):
    """One network adapter."""

    model_config = ConfigDict(extra="ignore")

    # The dedup key: the MAC when there is one, else the adapter name. Composed
    # by the agent, which is the only side that knows whether the address it
    # read is a real one.
    key: str = ""
    name: str | None = None
    mac: str | None = None
    type: str = NIC_TYPE_OTHER
    speed_mbps: int | None = None
    is_up: bool = False
    is_virtual: bool = False
    ip_address: str | None = None
    ip_prefix_length: int | None = None
    is_dhcp: bool | None = None
    gateway: str | None = None
    driver_version: str | None = None

    @field_validator("key")
    @classmethod
    def _bound_key(cls, value: str) -> str:
        return value.strip()[:TEXT_MAX]

    @field_validator("name", "mac", "ip_address", "gateway", "driver_version")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in (NIC_TYPE_WIFI, NIC_TYPE_ETHERNET):
            return normalized
        return NIC_TYPE_OTHER

    @field_validator("speed_mbps")
    @classmethod
    def _bound_speed(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MBPS)

    @field_validator("ip_prefix_length")
    @classmethod
    def _bound_prefix(cls, value: int | None) -> int | None:
        # 1 to 128, as on the heartbeat's own prefix: 0 is what Windows leaves
        # when it did not fill the field in.
        if value is None or not 1 <= value <= 128:
            return None
        return value


class GpuReport(BaseModel):
    """One display adapter."""

    model_config = ConfigDict(extra="ignore")

    # The dedup key: the adapter name. A GPU has no serial and no stable index.
    name: str = ""
    chipset: str | None = None
    memory_mb: int | None = None
    driver_version: str | None = None
    driver_date: date | None = None
    resolution: str | None = None

    @field_validator("name")
    @classmethod
    def _bound_name(cls, value: str) -> str:
        return value.strip()[:TEXT_MAX]

    @field_validator("chipset", "driver_version", "resolution")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("memory_mb")
    @classmethod
    def _bound_memory(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MB)


class SoftwareReport(BaseModel):
    """One installed program, as the registry's Uninstall key describes it.

    Read from the registry and never from ``Win32_Product``: enumerating that
    class makes the Windows Installer re-verify every installed package, which
    takes minutes and writes an event into the Application log of every poste in
    the parc, every day (plan §4.1).
    """

    model_config = ConfigDict(extra="ignore")

    # The dedup key, with version and publisher. An entry without a name is
    # dropped by the crud layer — the registry has plenty, and so does
    # "Applications et fonctionnalités", which hides them for the same reason.
    name: str = ""
    version: str = ""
    publisher: str = ""
    install_date: date | None = None
    arch: str | None = None
    source: str | None = None
    install_location: str | None = None

    @field_validator("name", "version", "publisher")
    @classmethod
    def _bound_identity(cls, value: str) -> str:
        # Empty, never NULL: these three are the catalogue's unique key, and
        # Postgres considers NULLs distinct — a nullable publisher would let one
        # unpublished program accumulate a catalogue row per machine.
        return value.strip()[:TEXT_MAX]

    @field_validator("arch", "source")
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("install_location")
    @classmethod
    def _bound_path(cls, value: str | None) -> str | None:
        return _bounded(value, PATH_MAX)


class DirectoryReport(BaseModel):
    """What Active Directory says about the computer, read by the agent.

    Bounded like everything else in the block: a DN is a few hundred
    characters at most, and the strings are stored as keys and labels, never
    parsed server-side beyond a trim.
    """

    model_config = ConfigDict(extra="ignore")

    distinguished_name: str | None = None
    ou: str | None = None
    ou_dn: str | None = None
    ad_location: str | None = None

    @field_validator("distinguished_name", "ou_dn", mode="before")
    @classmethod
    def _bound_dn(cls, value: object) -> str | None:
        return _bounded(value if isinstance(value, str) else None, DN_MAX)

    @field_validator("ou", "ad_location", mode="before")
    @classmethod
    def _bound_label(cls, value: object) -> str | None:
        return _bounded(value if isinstance(value, str) else None, TEXT_MAX)


class InventoryReport(BaseModel):
    """Hardware and software inventory, reported on the agent's own daily cycle.

    Optional on the heartbeat exactly like the ``windows_update`` block, and
    attached even less often: the agent hashes what it collected and sends
    nothing at all while the hash is unchanged, so a stable poste reports once
    and then stays quiet.
    """

    model_config = ConfigDict(extra="ignore")

    # SHA-256 of the inventory the agent serialised, its own idea of "has
    # anything changed". Stored, and compared before writing: an agent that
    # restarted forgets having sent this and re-sends it, and matching the stored
    # hash lets the server skip seven set replacements for a machine it already
    # describes correctly.
    hash: str = ""

    # What the domain says about the poste. Not hardware, but read on the same
    # daily cycle and part of the same hash, so an OU move is reported the day
    # it happens. None = not read (a workgroup poste, an older agent) and
    # leaves the stored values alone.
    directory: DirectoryReport | None = None

    # --- System, motherboard, BIOS: cardinality one, hence columns.
    hw_manufacturer: str | None = None
    hw_model: str | None = None
    hw_serial: str | None = None
    hw_chassis_type: str | None = None
    hw_is_virtual: bool = False
    hw_hypervisor: str | None = None
    mb_manufacturer: str | None = None
    mb_model: str | None = None
    mb_serial: str | None = None
    bios_vendor: str | None = None
    bios_version: str | None = None
    bios_date: date | None = None
    secure_boot: bool | None = None
    tpm_version: str | None = None

    # --- CPU. Columns and not a table, unlike GLPI: a workstation is
    # single-socket, and the rare dual-socket one carries two identical
    # processors by construction — Windows refuses to boot otherwise. So: the
    # model of the first, and the number in ``cpu_count``.
    cpu_model: str | None = None
    cpu_manufacturer: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    cpu_speed_mhz: int | None = None
    cpu_count: int | None = None

    # --- Memory totals. The sticks are in their own table; these are what the
    # machine list shows without joining to it.
    ram_total_mb: int | None = None
    ram_slots_total: int | None = None
    ram_slots_used: int | None = None

    # --- OS facts the existing ``os_version`` does not carry.
    os_architecture: str | None = None
    os_install_date: datetime | None = None
    last_boot_time: datetime | None = None

    # --- The sets. None = not read (leave the stored set alone); [] = read and
    # empty (clear it). See the module docstring.
    memory_modules: list[MemoryModuleReport] | None = None
    disks: list[DiskReport] | None = None
    volumes: list[VolumeReport] | None = None
    nics: list[NicReport] | None = None
    gpus: list[GpuReport] | None = None
    # Absent when the agent is configured not to collect software
    # (``report_software=false``, pushed by GPO) — no, ``[]``: the switch is a
    # privacy guarantee, and it has to *clear* what an earlier cycle stored
    # rather than leave it lying in the database. ``None`` is reserved for "the
    # registry could not be read", which must not wipe a good list.
    software: list[SoftwareReport] | None = None

    @field_validator("hash")
    @classmethod
    def _bound_hash(cls, value: str) -> str:
        return value.strip()[:HASH_MAX]

    @field_validator(
        "hw_manufacturer",
        "hw_model",
        "hw_serial",
        "hw_chassis_type",
        "hw_hypervisor",
        "mb_manufacturer",
        "mb_model",
        "mb_serial",
        "bios_vendor",
        "bios_version",
        "tpm_version",
        "cpu_model",
        "cpu_manufacturer",
        "os_architecture",
    )
    @classmethod
    def _bound_text(cls, value: str | None) -> str | None:
        return _bounded(value)

    @field_validator("cpu_cores", "cpu_threads", "cpu_count")
    @classmethod
    def _bound_count(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_COUNT)

    @field_validator("ram_slots_total", "ram_slots_used")
    @classmethod
    def _bound_slots(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_COUNT)

    @field_validator("cpu_speed_mhz")
    @classmethod
    def _bound_mhz(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MHZ)

    @field_validator("ram_total_mb")
    @classmethod
    def _bound_mb(cls, value: int | None) -> int | None:
        return _bounded_int(value, MAX_MB)

    @field_validator("memory_modules")
    @classmethod
    def _cap_memory(
        cls, value: list[MemoryModuleReport] | None
    ) -> list[MemoryModuleReport] | None:
        return None if value is None else value[:MAX_MEMORY_MODULES]

    @field_validator("disks")
    @classmethod
    def _cap_disks(cls, value: list[DiskReport] | None) -> list[DiskReport] | None:
        return None if value is None else value[:MAX_DISKS]

    @field_validator("volumes")
    @classmethod
    def _cap_volumes(
        cls, value: list[VolumeReport] | None
    ) -> list[VolumeReport] | None:
        return None if value is None else value[:MAX_VOLUMES]

    @field_validator("nics")
    @classmethod
    def _cap_nics(cls, value: list[NicReport] | None) -> list[NicReport] | None:
        return None if value is None else value[:MAX_NICS]

    @field_validator("gpus")
    @classmethod
    def _cap_gpus(cls, value: list[GpuReport] | None) -> list[GpuReport] | None:
        return None if value is None else value[:MAX_GPUS]

    @field_validator("software")
    @classmethod
    def _cap_software(
        cls, value: list[SoftwareReport] | None
    ) -> list[SoftwareReport] | None:
        return None if value is None else value[:MAX_SOFTWARE]

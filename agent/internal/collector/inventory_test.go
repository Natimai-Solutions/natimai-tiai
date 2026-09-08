package collector

import (
	"testing"
	"time"

	"tiai/agent/internal/models"
)

func TestChassisTypeFoldsTheCodesThatMatter(t *testing.T) {
	cases := []struct {
		name  string
		codes []int32
		want  string
	}{
		{"tower", []int32{7}, "desktop"},
		{"notebook", []int32{10}, "laptop"},
		{"convertible", []int32{31}, "tablet"},
		{"all in one", []int32{13}, "all-in-one"},
		// A firmware that says "other" and "unknown" is saying it does not know,
		// which is not information worth carrying.
		{"no information", []int32{1, 2}, ""},
		{"nothing at all", nil, ""},
		// An unrecognised code is kept: a question someone can answer beats an
		// empty cell.
		{"unfolded", []int32{25}, "chassis-25"},
		// A machine reporting several picks the first one we fold, not the first
		// one reported: SMBIOS lists them in no useful order.
		{"several", []int32{1, 9}, "laptop"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := chassisType(c.codes); got != c.want {
				t.Errorf("chassisType(%v) = %q, want %q", c.codes, got, c.want)
			}
		})
	}
}

func TestHypervisorNamesGuests(t *testing.T) {
	cases := []struct{ manufacturer, model, want string }{
		{"Microsoft Corporation", "Virtual Machine", "Hyper-V"},
		{"VMware, Inc.", "VMware Virtual Platform", "VMware"},
		{"innotek GmbH", "VirtualBox", "VirtualBox"},
		{"QEMU", "Standard PC (Q35 + ICH9, 2009)", "QEMU"},
		// A model nobody listed but that says so itself.
		{"Acme", "Acme Virtual Server 9", "unknown"},
		// Real hardware, which is the case that must never be flagged: a poste
		// wrongly marked virtual would be skipped by every hardware alert.
		{"Dell Inc.", "OptiPlex 7010", ""},
		{"LENOVO", "20XW00E2FR", ""},
	}
	for _, c := range cases {
		if got := hypervisor(c.manufacturer, c.model); got != c.want {
			t.Errorf("hypervisor(%q, %q) = %q, want %q",
				c.manufacturer, c.model, got, c.want)
		}
	}
}

func TestMegabytesRoundsUpAndNeverShowsZero(t *testing.T) {
	// The Phase 2 lesson, applied on the way in: a driver of a few kilobytes
	// rendering as "0 Mio" next to a download icon is a bug that shipped once.
	if got := megabytes(4096); got == nil || *got != 1 {
		t.Errorf("a few kilobytes must round up to 1 Mio, got %v", got)
	}
	if got := megabytes(16 * 1024 * 1024 * 1024); got == nil || *got != 16384 {
		t.Errorf("16 GiB must be 16384 Mio, got %v", got)
	}
	// Zero is WMI's "unknown", not "empty".
	if got := megabytes(0); got != nil {
		t.Errorf("zero bytes must be reported as unknown, got %v", got)
	}
}

func TestParseCIMDateTime(t *testing.T) {
	// The offset is in *minutes*, a unit no Go layout expresses — which is why
	// this parser is hand-written.
	got, ok := parseCIMDateTime("20240115103000.000000+060")
	if !ok {
		t.Fatal("a well-formed CIM_DATETIME must parse")
	}
	want := time.Date(2024, 1, 15, 9, 30, 0, 0, time.UTC)
	if !got.Equal(want) {
		t.Errorf("got %s, want %s", got, want)
	}

	if _, ok := parseCIMDateTime("20240115103000.000000-300"); !ok {
		t.Error("a negative offset must parse")
	}
	// What WMI returns for a value it does not have.
	if _, ok := parseCIMDateTime("****************"); ok {
		t.Error("WMI's placeholder must not parse as a date")
	}
	if _, ok := parseCIMDateTime(""); ok {
		t.Error("an empty value must not parse")
	}
	if got := cimDate("20240115000000.000000+000"); got != "2024-01-15" {
		t.Errorf("cimDate = %q, want 2024-01-15", got)
	}
	if got := cimDate("nonsense"); got != "" {
		t.Errorf("an unparseable date must be dropped, got %q", got)
	}
}

func TestBuildMemoryModulesNeedsASlot(t *testing.T) {
	got := buildMemoryModules([]rawMemory{
		{DeviceLocator: "DIMM A1", Capacity: 16 * 1024 * 1024 * 1024,
			SMBIOSMemoryType: 34, Speed: 4800, FormFactor: 8},
		// No DeviceLocator, but a bank label: usable as a key.
		{BankLabel: "BANK 1", Capacity: 8 * 1024 * 1024 * 1024},
		// Neither: nothing to upsert on, so it is dropped rather than collapsed
		// onto its neighbours.
		{Capacity: 8 * 1024 * 1024 * 1024},
	})
	if len(got) != 2 {
		t.Fatalf("expected 2 modules, got %d", len(got))
	}
	if got[0].Type != "DDR5" || got[0].FormFactor != "DIMM" {
		t.Errorf("DDR5 DIMM expected, got %q / %q", got[0].Type, got[0].FormFactor)
	}
	if got[0].CapacityMB == nil || *got[0].CapacityMB != 16384 {
		t.Errorf("16 GiB expected, got %v", got[0].CapacityMB)
	}
	if got[1].Slot != "BANK 1" {
		t.Errorf("bank label must serve as the slot, got %q", got[1].Slot)
	}
}

func TestBuildDisksEnrichesFromTheStorageNamespace(t *testing.T) {
	drives := []rawDiskDrive{
		{DeviceID: `\\.\PHYSICALDRIVE0`, Model: "SAMSUNG MZVL2512",
			Size: 512 * 1000 * 1000 * 1000, InterfaceType: "SCSI",
			MediaType: "Fixed hard disk media"},
		{DeviceID: `\\.\PHYSICALDRIVE1`, Model: "WDC WD10EZEX",
			Size: 1000 * 1000 * 1000 * 1000, InterfaceType: "IDE",
			MediaType: "Fixed hard disk media"},
	}
	physical := []rawPhysicalDisk{
		{DeviceId: "0", MediaType: 4, BusType: 17, HealthStatus: 0, SerialNumber: "S64A"},
	}
	got := buildDisks(drives, physical)
	if len(got) != 2 {
		t.Fatalf("expected 2 disks, got %d", len(got))
	}
	// Enriched: Win32_DiskDrive calls both "Fixed hard disk media".
	if got[0].MediaType != "SSD" || got[0].BusType != "NVMe" {
		t.Errorf("drive 0 should be an NVMe SSD, got %q on %q",
			got[0].MediaType, got[0].BusType)
	}
	if got[0].HealthStatus != "Healthy" {
		t.Errorf("health should come from the storage namespace, got %q",
			got[0].HealthStatus)
	}
	if got[0].Serial != "S64A" {
		t.Errorf("a serial only the storage namespace has must be picked up, got %q",
			got[0].Serial)
	}
	// Not enriched, and still reported: a host without the storage namespace
	// keeps its disks and loses only their media type.
	if got[1].MediaType != "unknown" {
		t.Errorf("an unmatched drive must read unknown, got %q", got[1].MediaType)
	}
	if got[1].BusType != "IDE" {
		t.Errorf("the fallback bus type must survive, got %q", got[1].BusType)
	}
}

func TestBuildDisksWithoutTheStorageNamespace(t *testing.T) {
	got := buildDisks([]rawDiskDrive{{DeviceID: `\\.\PHYSICALDRIVE0`, Size: 1024}}, nil)
	if len(got) != 1 || got[0].MediaType != "unknown" {
		t.Fatalf("disks must survive a missing storage namespace, got %+v", got)
	}
}

func TestPhysicalDriveNumber(t *testing.T) {
	if got := physicalDriveNumber(`\\.\PHYSICALDRIVE12`); got != "12" {
		t.Errorf("got %q, want 12", got)
	}
	if got := physicalDriveNumber("something else"); got != "" {
		t.Errorf("an unparseable device id must simply fail to join, got %q", got)
	}
}

func TestBuildVolumesFlagsTheSystemDrive(t *testing.T) {
	got := buildVolumes(
		[]rawLogicalDisk{
			{DeviceID: "C:", VolumeName: "Windows", FileSystem: "NTFS",
				Size: 500 * 1024 * 1024 * 1024, FreeSpace: 40 * 1024 * 1024 * 1024},
			{DeviceID: "D:", FileSystem: "NTFS", Size: 1024 * 1024 * 1024},
		},
		"C:",
		map[string]string{"C:": "FullyEncrypted"},
	)
	if len(got) != 2 {
		t.Fatalf("expected 2 volumes, got %d", len(got))
	}
	if !got[0].IsSystem || got[1].IsSystem {
		t.Error("only the drive Windows booted from is the system one")
	}
	if got[0].EncryptionStatus != "FullyEncrypted" {
		t.Errorf("encryption must be joined on the letter, got %q", got[0].EncryptionStatus)
	}
	// Not read is not "not encrypted": the server must be able to tell them apart.
	if got[1].EncryptionStatus != "" {
		t.Errorf("an unread status must stay empty, got %q", got[1].EncryptionStatus)
	}
}

func TestBuildGpus(t *testing.T) {
	got := buildGpus([]rawVideo{
		{Name: "Intel(R) UHD Graphics 770", VideoProcessor: "Intel UHD",
			AdapterRAM: 1024 * 1024 * 1024, DriverVersion: "31.0.101.5186",
			DriverDate:                  "20240502000000.000000-000",
			CurrentHorizontalResolution: 1920, CurrentVerticalResolution: 1080},
		// No name: nothing to key on server-side.
		{VideoProcessor: "ghost"},
	})
	if len(got) != 1 {
		t.Fatalf("expected 1 gpu, got %d", len(got))
	}
	if got[0].Resolution != "1920x1080" {
		t.Errorf("resolution %q", got[0].Resolution)
	}
	if got[0].DriverDate != "2024-05-02" {
		t.Errorf("driver date %q", got[0].DriverDate)
	}
}

// The hash is what keeps a stable parc quiet, so it has to be stable itself:
// WMI hands its rows back in whatever order the provider enumerated them.
func TestInventoryHashIgnoresRowOrder(t *testing.T) {
	a := &models.InventoryState{
		HWModel: "OptiPlex 7010",
		Disks: []models.Disk{
			{DeviceID: `\\.\PHYSICALDRIVE0`}, {DeviceID: `\\.\PHYSICALDRIVE1`},
		},
		Software: []models.Software{
			{Name: "7-Zip", Version: "24.09"}, {Name: "Firefox", Version: "142.0"},
		},
	}
	b := &models.InventoryState{
		HWModel: "OptiPlex 7010",
		Disks: []models.Disk{
			{DeviceID: `\\.\PHYSICALDRIVE1`}, {DeviceID: `\\.\PHYSICALDRIVE0`},
		},
		Software: []models.Software{
			{Name: "Firefox", Version: "142.0"}, {Name: "7-Zip", Version: "24.09"},
		},
	}
	InventoryHash(a)
	InventoryHash(b)
	if a.Hash == "" {
		t.Fatal("a hash must be produced")
	}
	if a.Hash != b.Hash {
		t.Error("re-ordered rows must not look like a changed inventory")
	}
}

func TestInventoryHashChangesWithTheContent(t *testing.T) {
	before := &models.InventoryState{HWModel: "OptiPlex 7010"}
	after := &models.InventoryState{HWModel: "OptiPlex 7020"}
	InventoryHash(before)
	InventoryHash(after)
	if before.Hash == after.Hash {
		t.Error("a changed inventory must produce a different hash")
	}

	// And an uninstalled program is a change, which is the everyday case.
	full := &models.InventoryState{Software: []models.Software{{Name: "A"}, {Name: "B"}}}
	fewer := &models.InventoryState{Software: []models.Software{{Name: "A"}}}
	InventoryHash(full)
	InventoryHash(fewer)
	if full.Hash == fewer.Hash {
		t.Error("removing a program must change the hash")
	}
}

// An empty list and an absent one are different reports, and the hash has to
// tell them apart: one clears the server's set, the other leaves it alone.
func TestInventoryHashDistinguishesEmptyFromAbsent(t *testing.T) {
	empty := &models.InventoryState{Software: []models.Software{}}
	absent := &models.InventoryState{Software: nil}
	InventoryHash(empty)
	InventoryHash(absent)
	if empty.Hash == absent.Hash {
		t.Error(`"no software" and "software not read" must not hash alike`)
	}
}

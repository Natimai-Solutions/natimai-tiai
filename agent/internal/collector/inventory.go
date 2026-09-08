package collector

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"tiai/agent/internal/models"
)

// Hardware inventory: what the machine *is*, as opposed to what it is doing.
//
// Everything in this file is pure — tables, parsers, conversions, the hash —
// so it is testable off Windows. The WMI queries that feed it live in
// inventory_windows.go, and the stub in inventory_other.go, following the shape
// of the Defender and Security Center collectors.
//
// The classes are the ones GLPI's agent has been reading for twenty years; the
// one class deliberately *not* read is Win32_Product (see software.go).

// --- Raw rows, as WMI hands them over ---------------------------------------
//
// Declared here rather than in the //go:build windows file so every mapping
// below stays compilable, and unit-testable, off Windows.

type rawSystem struct {
	Manufacturer        string
	Model               string
	TotalPhysicalMemory uint64
	NumberOfProcessors  uint32
}

type rawEnclosure struct {
	SerialNumber string
	// []int32 and not []uint16, although CIM declares the property uint16[]:
	// WMI hands a uint16 array over COM as a SafeArray of VT_I4, so the
	// elements arrive as int32 — and the WMI library, asked to fill a []uint16
	// from them, calls reflect.Value.Uint on an int32 and *panics* rather than
	// erring. That panic was the death of every agent of the parc four minutes
	// after start, on its first inventory (v0.0.8 field logs). The only array
	// property the inventory reads, and it is read into what actually arrives.
	ChassisTypes []int32
}

type rawBaseBoard struct {
	Manufacturer string
	Product      string
	SerialNumber string
}

type rawBIOS struct {
	Manufacturer      string
	SMBIOSBIOSVersion string
	ReleaseDate       string // CIM_DATETIME
}

type rawProcessor struct {
	Name                      string
	Manufacturer              string
	NumberOfCores             uint32
	NumberOfLogicalProcessors uint32
	MaxClockSpeed             uint32
}

type rawMemory struct {
	DeviceLocator    string
	BankLabel        string
	Capacity         uint64
	SMBIOSMemoryType uint16
	Speed            uint32
	Manufacturer     string
	SerialNumber     string
	FormFactor       uint16
}

type rawMemoryArray struct {
	MemoryDevices uint32
}

type rawVideo struct {
	Name                        string
	VideoProcessor              string
	AdapterRAM                  uint32
	DriverVersion               string
	DriverDate                  string // CIM_DATETIME
	CurrentHorizontalResolution uint32
	CurrentVerticalResolution   uint32
}

type rawDiskDrive struct {
	DeviceID         string
	Model            string
	SerialNumber     string
	FirmwareRevision string
	InterfaceType    string
	Size             uint64
	MediaType        string
}

// rawPhysicalDisk is MSFT_PhysicalDisk, from root\Microsoft\Windows\Storage —
// the only class that knows SSD from HDD, and the only one that reports health.
type rawPhysicalDisk struct {
	DeviceId     string
	MediaType    uint16
	BusType      uint16
	HealthStatus uint16
	SerialNumber string
}

type rawLogicalDisk struct {
	DeviceID   string
	VolumeName string
	FileSystem string
	Size       uint64
	FreeSpace  uint64
}

type rawOS struct {
	OSArchitecture string
	InstallDate    string // CIM_DATETIME
	LastBootUpTime string // CIM_DATETIME
	SystemDrive    string
}

// --- Chassis --------------------------------------------------------------

// chassisNames folds Win32_SystemEnclosure's thirty-odd codes into the handful
// of words the console shows and filters on. The distinction that matters is
// desktop / laptop / tablet: it is what says whether a poste has a battery, can
// leave the building, and should be woken rather than left on.
var chassisNames = map[uint16]string{
	3: "desktop", 4: "desktop", 5: "desktop", 6: "desktop", 7: "desktop",
	15: "desktop", 16: "desktop", 24: "desktop",
	8: "laptop", 9: "laptop", 10: "laptop", 14: "laptop",
	11: "tablet", 30: "tablet", 31: "tablet", 32: "tablet",
	13: "all-in-one",
	17: "server", 23: "server",
}

// chassisType names the enclosure, or reports the raw code when it is not one
// we fold. An unrecognised code is kept rather than dropped: "chassis-25" in the
// console is a question someone can answer, where an empty cell is not.
func chassisType(codes []int32) string {
	for _, code := range codes {
		if name, ok := chassisNames[uint16(code)]; ok {
			return name
		}
	}
	for _, code := range codes {
		// 1 = Other, 2 = Unknown: the firmware saying it does not know, which is
		// not information worth carrying.
		if code > 2 {
			return fmt.Sprintf("chassis-%d", code)
		}
	}
	return ""
}

// virtualModels are the system models a hypervisor reports for its guests.
// Matched on the model rather than on a WMI "is virtual" property, because
// there is none: this is what every inventory tool does, and the strings are
// stable — they are part of the guest ABI these hypervisors expose.
var virtualModels = map[string]string{
	"virtual machine":            "Hyper-V",
	"vmware virtual platform":    "VMware",
	"vmware20,1":                 "VMware",
	"virtualbox":                 "VirtualBox",
	"kvm":                        "KVM",
	"qemu":                       "QEMU",
	"bochs":                      "QEMU",
	"openstack nova":             "OpenStack",
	"parallels virtual platform": "Parallels",
}

// hypervisor names the hypervisor behind a guest, or "" on real hardware.
//
// It is not cosmetic: a virtual machine has no battery, no SMART, no BIOS to
// flash and no TPM chip, so half of what the console would otherwise flag on it
// is noise. Better to say so once here than to special-case it everywhere.
func hypervisor(manufacturer, model string) string {
	m := strings.ToLower(strings.TrimSpace(model))
	if name, ok := virtualModels[m]; ok {
		return name
	}
	switch {
	case strings.Contains(m, "virtual"):
		// A model nobody listed above but that says so itself. Reported as
		// unknown-but-virtual rather than guessed at.
		return "unknown"
	case strings.Contains(strings.ToLower(manufacturer), "qemu"):
		return "QEMU"
	}
	return ""
}

// --- Conversions -----------------------------------------------------------

// megabytes converts a byte count to mebibytes, or nil when there is nothing to
// report.
//
// Rounded *up*, and floored at 1: a figure of a few hundred kilobytes rendering
// as "0 Mio" next to a real object is the bug Phase 2 shipped once already with
// driver sizes. Zero itself stays nil — WMI reports 0 for "unknown", not for
// "empty".
func megabytes(b uint64) *int {
	if b == 0 {
		return nil
	}
	const mib = 1024 * 1024
	mb := int((b + mib - 1) / mib)
	if mb < 1 {
		mb = 1
	}
	return &mb
}

// intPtr returns a pointer to n, or nil when n is zero.
//
// Zero is "not reported" for every count in this inventory — cores, slots,
// megahertz — because WMI fills a property it could not read with zero rather
// than leaving it out. A machine with zero cores does not exist; a machine whose
// core count could not be read does.
func intPtr(n int) *int {
	if n == 0 {
		return nil
	}
	return &n
}

// --- CIM_DATETIME ----------------------------------------------------------

// cimDateTimeLayout is the fixed-width form WMI uses for every date it returns:
// yyyymmddHHMMSS.ffffff±UUU, where UUU is the offset from UTC *in minutes*.
const cimDateTimeMinLen = 14

// parseCIMDateTime reads a WMI timestamp.
//
// Written by hand rather than with time.Parse because of the offset: WMI counts
// it in minutes ("+060", "-300"), a unit no Go layout expresses. Anything that
// does not parse — including the "****************" WMI returns for a value it
// does not have — comes back false, which the callers turn into an omitted
// field rather than into an error: a machine whose BIOS date is unreadable
// still has a motherboard worth reporting.
func parseCIMDateTime(s string) (time.Time, bool) {
	s = strings.TrimSpace(s)
	if len(s) < cimDateTimeMinLen {
		return time.Time{}, false
	}
	base, err := time.Parse("20060102150405", s[:cimDateTimeMinLen])
	if err != nil {
		return time.Time{}, false
	}
	offset := 0
	if i := strings.LastIndexAny(s, "+-"); i > 0 && i+1 < len(s) {
		if minutes, err := strconv.Atoi(s[i+1:]); err == nil {
			offset = minutes * 60
			if s[i] == '-' {
				offset = -offset
			}
		}
	}
	return base.Add(-time.Duration(offset) * time.Second).UTC(), true
}

// cimDate renders a WMI timestamp as the "2006-01-02" string the server's DATE
// columns take, or "" when it does not parse.
func cimDate(s string) string {
	t, ok := parseCIMDateTime(s)
	if !ok {
		return ""
	}
	return t.Format("2006-01-02")
}

// cimTime renders a WMI timestamp as an instant, or nil when it does not parse.
func cimTime(s string) *time.Time {
	t, ok := parseCIMDateTime(s)
	if !ok {
		return nil
	}
	return &t
}

// --- Memory ----------------------------------------------------------------

// memoryTypes decodes SMBIOSMemoryType. Only the generations a parc actually
// holds are named; anything else is left empty rather than guessed at, on the
// same principle as productState in avproduct.go.
var memoryTypes = map[uint16]string{
	20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5",
	25: "FBD2", 27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 35: "LPDDR5",
}

// formFactors decodes Win32_PhysicalMemory.FormFactor — the two values that
// distinguish a desktop stick from a laptop one, which is what an ordering
// decision turns on.
var formFactors = map[uint16]string{8: "DIMM", 12: "SODIMM", 13: "SRIMM", 9: "SODIMM"}

// buildMemoryModules maps the physical memory rows, dropping the ones with no
// slot label — the key the server upserts on.
func buildMemoryModules(rows []rawMemory) []models.MemoryModule {
	out := make([]models.MemoryModule, 0, len(rows))
	for _, r := range rows {
		slot := strings.TrimSpace(r.DeviceLocator)
		if slot == "" {
			slot = strings.TrimSpace(r.BankLabel)
		}
		if slot == "" {
			continue
		}
		out = append(out, models.MemoryModule{
			Slot:         slot,
			CapacityMB:   megabytes(r.Capacity),
			Type:         memoryTypes[r.SMBIOSMemoryType],
			SpeedMHz:     intPtr(int(r.Speed)),
			Manufacturer: strings.TrimSpace(r.Manufacturer),
			Serial:       strings.TrimSpace(r.SerialNumber),
			FormFactor:   formFactors[r.FormFactor],
		})
	}
	return out
}

// --- Disks -----------------------------------------------------------------

// mediaTypes decodes MSFT_PhysicalDisk.MediaType. 0 and 1 are "unspecified" and
// "unknown", which the caller reports as "unknown" rather than as nothing: on a
// disk, not knowing whether it spins is itself worth showing.
var mediaTypes = map[uint16]string{3: "HDD", 4: "SSD", 5: "SCM"}

// busTypes decodes MSFT_PhysicalDisk.BusType, restricted to what a workstation
// carries.
var busTypes = map[uint16]string{
	1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel",
	7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC",
	17: "NVMe", 18: "SCM", 19: "UFS",
}

// healthStatuses decodes MSFT_PhysicalDisk.HealthStatus.
var healthStatuses = map[uint16]string{0: "Healthy", 1: "Warning", 2: "Unhealthy"}

// buildDisks merges the two views of a drive.
//
// Win32_DiskDrive is the one that always answers, and it is the one that cannot
// say SSD from HDD — the property it exposes under that name reports "Fixed hard
// disk media" for both. MSFT_PhysicalDisk knows, and reports health besides, but
// its namespace is missing on older or trimmed-down hosts. So: the first is the
// spine, the second enriches it where present, and a host with only the first
// still reports its disks with an unknown media type.
//
// Joined on the disk *number*, which both classes carry — Win32_DiskDrive as the
// tail of "\\.\PHYSICALDRIVE2", MSFT_PhysicalDisk as its DeviceId. Matching on
// serials would fail on exactly the machines that report none.
func buildDisks(drives []rawDiskDrive, physical []rawPhysicalDisk) []models.Disk {
	byNumber := make(map[string]rawPhysicalDisk, len(physical))
	for _, p := range physical {
		byNumber[strings.TrimSpace(p.DeviceId)] = p
	}
	out := make([]models.Disk, 0, len(drives))
	for _, d := range drives {
		deviceID := strings.TrimSpace(d.DeviceID)
		if deviceID == "" {
			continue
		}
		disk := models.Disk{
			DeviceID:    deviceID,
			Model:       strings.TrimSpace(d.Model),
			Serial:      strings.TrimSpace(d.SerialNumber),
			Firmware:    strings.TrimSpace(d.FirmwareRevision),
			BusType:     strings.TrimSpace(d.InterfaceType),
			SizeMB:      megabytes(d.Size),
			MediaType:   "unknown",
			IsRemovable: strings.Contains(strings.ToLower(d.MediaType), "removable"),
		}
		if p, ok := byNumber[physicalDriveNumber(deviceID)]; ok {
			if name, known := mediaTypes[p.MediaType]; known {
				disk.MediaType = name
			}
			if bus, known := busTypes[p.BusType]; known {
				disk.BusType = bus
			}
			disk.HealthStatus = healthStatuses[p.HealthStatus]
			if disk.Serial == "" {
				disk.Serial = strings.TrimSpace(p.SerialNumber)
			}
		}
		out = append(out, disk)
	}
	return out
}

// physicalDriveNumber extracts the trailing number of "\\.\PHYSICALDRIVE2".
// Returns "" for anything else, which simply fails to join.
func physicalDriveNumber(deviceID string) string {
	i := strings.LastIndexAny(deviceID, "\\/")
	tail := deviceID[i+1:]
	digits := strings.TrimLeftFunc(tail, func(r rune) bool { return r < '0' || r > '9' })
	if _, err := strconv.Atoi(digits); err != nil {
		return ""
	}
	return digits
}

// --- Volumes ---------------------------------------------------------------

// buildVolumes maps the fixed logical disks, flagging the one Windows booted
// from. Encryption is filled in separately (it lives in another namespace and
// often fails), hence the second argument keyed by drive letter.
func buildVolumes(rows []rawLogicalDisk, systemDrive string, encryption map[string]string) []models.Volume {
	system := strings.ToUpper(strings.TrimSpace(systemDrive))
	out := make([]models.Volume, 0, len(rows))
	for _, r := range rows {
		letter := strings.ToUpper(strings.TrimSpace(r.DeviceID))
		if letter == "" {
			continue
		}
		out = append(out, models.Volume{
			Letter:           letter,
			Label:            strings.TrimSpace(r.VolumeName),
			Filesystem:       strings.TrimSpace(r.FileSystem),
			TotalMB:          megabytes(r.Size),
			FreeMB:           megabytes(r.FreeSpace),
			IsSystem:         letter == system,
			EncryptionStatus: encryption[letter],
		})
	}
	return out
}

// --- GPUs ------------------------------------------------------------------

func buildGpus(rows []rawVideo) []models.Gpu {
	out := make([]models.Gpu, 0, len(rows))
	for _, r := range rows {
		name := strings.TrimSpace(r.Name)
		if name == "" {
			continue
		}
		gpu := models.Gpu{
			Name:          name,
			Chipset:       strings.TrimSpace(r.VideoProcessor),
			DriverVersion: strings.TrimSpace(r.DriverVersion),
			DriverDate:    cimDate(r.DriverDate),
			// AdapterRAM is a uint32, so it saturates at 4 GiB and reports
			// nonsense on a modern card. Kept anyway — it is right on the
			// integrated adapters that make up most of a parc — but never
			// presented as authoritative, which is why the console shows it
			// beside the name rather than as a figure of its own.
			MemoryMB: megabytes(uint64(r.AdapterRAM)),
		}
		if r.CurrentHorizontalResolution > 0 && r.CurrentVerticalResolution > 0 {
			gpu.Resolution = fmt.Sprintf("%dx%d",
				r.CurrentHorizontalResolution, r.CurrentVerticalResolution)
		}
		out = append(out, gpu)
	}
	return out
}

// --- Hash ------------------------------------------------------------------

// sortInventory puts every list in a deterministic order, keyed the same way the
// server keys its rows.
//
// Without this the hash would change every day for nothing: WMI hands its rows
// back in whatever order the provider enumerated them, which is stable in
// practice and not guaranteed, and a reordering would send the whole inventory
// again and rewrite every row server-side.
func sortInventory(inv *models.InventoryState) {
	sort.Slice(inv.MemoryModules, func(i, j int) bool {
		return inv.MemoryModules[i].Slot < inv.MemoryModules[j].Slot
	})
	sort.Slice(inv.Disks, func(i, j int) bool {
		return inv.Disks[i].DeviceID < inv.Disks[j].DeviceID
	})
	sort.Slice(inv.Volumes, func(i, j int) bool {
		return inv.Volumes[i].Letter < inv.Volumes[j].Letter
	})
	sort.Slice(inv.Nics, func(i, j int) bool { return inv.Nics[i].Key < inv.Nics[j].Key })
	sort.Slice(inv.Gpus, func(i, j int) bool { return inv.Gpus[i].Name < inv.Gpus[j].Name })
	sort.Slice(inv.Software, func(i, j int) bool {
		a, b := inv.Software[i], inv.Software[j]
		if a.Name != b.Name {
			return a.Name < b.Name
		}
		if a.Version != b.Version {
			return a.Version < b.Version
		}
		return a.Publisher < b.Publisher
	})
}

// InventoryHash sorts the inventory and stamps it with a hash of its contents.
//
// This is what keeps a stable poste quiet: the daily cycle collects, hashes, and
// the heartbeat attaches the block only when the hash differs from the last one
// the server acknowledged. A parc of a thousand machines then writes on the days
// something actually changed, and not otherwise.
//
// The hash covers the fields as JSON, the Hash field itself excluded — Go
// marshals struct fields in declaration order, so the encoding is stable for a
// given build. It is deliberately *not* a promise across versions: adding a
// field changes every machine's hash, which costs one extra inventory each and
// is exactly the right outcome, since there is now a field the server lacks.
func InventoryHash(inv *models.InventoryState) {
	if inv == nil {
		return
	}
	sortInventory(inv)
	inv.Hash = ""
	encoded, err := json.Marshal(inv)
	if err != nil {
		// Cannot happen with these types; and if it ever did, an empty hash is
		// the safe answer — the server never short-circuits on one.
		return
	}
	sum := sha256.Sum256(encoded)
	inv.Hash = hex.EncodeToString(sum[:])
}

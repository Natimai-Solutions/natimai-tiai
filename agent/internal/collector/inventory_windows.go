package collector

import (
	"context"
	"fmt"
	"strings"

	"tiai/agent/internal/models"

	"tiai/agent/internal/logging"
)

const (
	cimv2Namespace      = `root\CIMV2`
	storageNamespace    = `root\Microsoft\Windows\Storage`
	encryptionNamespace = `root\CIMV2\Security\MicrosoftVolumeEncryption`
	tpmNamespace        = `root\CIMV2\Security\MicrosoftTpm`
)

// rawEncryptableVolume is Win32_EncryptableVolume — BitLocker. Its namespace is
// absent on some SKUs and the class needs elevation, so every read of it is
// best-effort.
type rawEncryptableVolume struct {
	DriveLetter      string
	ProtectionStatus uint32
	ConversionStatus uint32
}

// rawTpm is Win32_Tpm. Absent on a machine without one, which is most of a
// parc bought before 2018.
type rawTpm struct {
	SpecVersion            string
	IsEnabled_InitialValue bool
}

// ReadInventory collects everything the machine *is*: chassis, motherboard,
// BIOS, CPU, memory, disks, volumes, adapters, GPUs and installed software.
//
// Best-effort throughout, and that is the design rather than a concession. A
// poste of 2015 has no TPM, no Secure Boot and no Storage namespace; a Windows
// Server has no Security Center; a machine mid-BitLocker refuses the encryption
// class. None of those is an error worth failing an inventory over — the field
// is simply absent, which the server reads as "not reported" and the console
// renders as a dash.
//
// The only hard failure is the first query: if Win32_ComputerSystem cannot be
// read, WMI itself is broken and nothing below would answer either.
func ReadInventory(ctx context.Context, includeSoftware bool) (*models.InventoryState, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	var systems []rawSystem
	if err := queryNamespace("SELECT * FROM Win32_ComputerSystem", &systems, cimv2Namespace); err != nil {
		return nil, fmt.Errorf("query Win32_ComputerSystem: %w", err)
	}
	inv := &models.InventoryState{}
	if len(systems) > 0 {
		s := systems[0]
		inv.HWManufacturer = strings.TrimSpace(s.Manufacturer)
		inv.HWModel = strings.TrimSpace(s.Model)
		inv.RAMTotalMB = megabytes(s.TotalPhysicalMemory)
		inv.CPUCount = intPtr(int(s.NumberOfProcessors))
		if hv := hypervisor(s.Manufacturer, s.Model); hv != "" {
			inv.HWIsVirtual = true
			inv.HWHypervisor = hv
		}
	}

	readInto(ctx, "Win32_SystemEnclosure", cimv2Namespace, func(rows []rawEnclosure) {
		if len(rows) == 0 {
			return
		}
		inv.HWSerial = strings.TrimSpace(rows[0].SerialNumber)
		inv.HWChassisType = chassisType(rows[0].ChassisTypes)
	})

	readInto(ctx, "Win32_BaseBoard", cimv2Namespace, func(rows []rawBaseBoard) {
		if len(rows) == 0 {
			return
		}
		inv.MBManufacturer = strings.TrimSpace(rows[0].Manufacturer)
		inv.MBModel = strings.TrimSpace(rows[0].Product)
		inv.MBSerial = strings.TrimSpace(rows[0].SerialNumber)
	})

	readInto(ctx, "Win32_BIOS", cimv2Namespace, func(rows []rawBIOS) {
		if len(rows) == 0 {
			return
		}
		inv.BIOSVendor = strings.TrimSpace(rows[0].Manufacturer)
		inv.BIOSVersion = strings.TrimSpace(rows[0].SMBIOSBIOSVersion)
		inv.BIOSDate = cimDate(rows[0].ReleaseDate)
	})

	readInto(ctx, "Win32_Processor", cimv2Namespace, func(rows []rawProcessor) {
		if len(rows) == 0 {
			return
		}
		// The first socket's model, and the *sum* of the cores: on the rare
		// dual-socket workstation the two processors are identical by
		// construction, so one model describes both, while "how many cores does
		// this machine have" must not answer with half of them.
		p := rows[0]
		inv.CPUModel = strings.TrimSpace(p.Name)
		inv.CPUManufacturer = strings.TrimSpace(p.Manufacturer)
		inv.CPUSpeedMHz = intPtr(int(p.MaxClockSpeed))
		var cores, threads int
		for _, r := range rows {
			cores += int(r.NumberOfCores)
			threads += int(r.NumberOfLogicalProcessors)
		}
		inv.CPUCores = intPtr(cores)
		inv.CPUThreads = intPtr(threads)
		// Win32_ComputerSystem.NumberOfProcessors is what a virtualised host
		// reports oddly; the row count here is the socket count as SMBIOS sees
		// it, and it wins when both are present.
		inv.CPUCount = intPtr(len(rows))
	})

	readInto(ctx, "Win32_PhysicalMemory", cimv2Namespace, func(rows []rawMemory) {
		inv.MemoryModules = buildMemoryModules(rows)
		inv.RAMSlotsUsed = intPtr(len(inv.MemoryModules))
	})
	readInto(ctx, "Win32_PhysicalMemoryArray", cimv2Namespace, func(rows []rawMemoryArray) {
		total := 0
		for _, r := range rows {
			total += int(r.MemoryDevices)
		}
		inv.RAMSlotsTotal = intPtr(total)
	})

	readInto(ctx, "Win32_VideoController", cimv2Namespace, func(rows []rawVideo) {
		inv.Gpus = buildGpus(rows)
	})

	// Disks: the always-answering class first, the one that knows SSD from HDD
	// second. A host without the Storage namespace keeps its disks and loses
	// only their media type and health.
	var drives []rawDiskDrive
	if err := queryNamespace(
		"SELECT * FROM Win32_DiskDrive", &drives, cimv2Namespace); err != nil {
		logging.Debugf("agent: inventory: Win32_DiskDrive: %v", err)
	} else {
		var physical []rawPhysicalDisk
		if err := queryNamespace(
			"SELECT * FROM MSFT_PhysicalDisk", &physical, storageNamespace); err != nil {
			logging.Debugf("agent: inventory: MSFT_PhysicalDisk: %v", err)
		}
		inv.Disks = buildDisks(drives, physical)
	}

	// Volumes. DriveType = 3 is a fixed disk: a USB key and a mapped network
	// share are not this machine's storage, and counting either would make the
	// "plus de place" card fire on a full memory stick.
	var systemDrive string
	readInto(ctx, "Win32_OperatingSystem", cimv2Namespace, func(rows []rawOS) {
		if len(rows) == 0 {
			return
		}
		inv.OSArchitecture = strings.TrimSpace(rows[0].OSArchitecture)
		inv.OSInstallDate = cimTime(rows[0].InstallDate)
		inv.LastBootTime = cimTime(rows[0].LastBootUpTime)
		systemDrive = rows[0].SystemDrive
	})
	var logical []rawLogicalDisk
	if err := queryNamespace(
		"SELECT * FROM Win32_LogicalDisk WHERE DriveType = 3", &logical, cimv2Namespace); err != nil {
		logging.Debugf("agent: inventory: Win32_LogicalDisk: %v", err)
	} else {
		inv.Volumes = buildVolumes(logical, systemDrive, readEncryption())
	}

	readInto(ctx, "Win32_Tpm", tpmNamespace, func(rows []rawTpm) {
		if len(rows) == 0 {
			return
		}
		// SpecVersion is "2.0, 0, 1.16" — a version, a level and a revision. Only
		// the first is the answer to "does this machine have a TPM 2.0", which is
		// the question BitLocker and Windows 11 both turn on.
		inv.TPMVersion = strings.TrimSpace(strings.Split(rows[0].SpecVersion, ",")[0])
	})

	if secure, ok := readSecureBoot(); ok {
		inv.SecureBoot = &secure
	}

	nics, err := enumerateAdapters()
	if err != nil {
		logging.Debugf("agent: inventory: adapters: %v", err)
	} else {
		inv.Nics = buildNics(nics, readPhysicalAdapterMACs())
	}

	if includeSoftware {
		inv.Software = readInstalledSoftware()
	} else {
		// Empty and not nil, which is the whole point of the switch: nil tells
		// the server "not read" and leaves whatever an earlier cycle stored
		// sitting in the database, where the guarantee this setting makes is
		// that the list *disappears*. See the contract on models.InventoryState.
		inv.Software = []models.Software{}
	}

	InventoryHash(inv)
	return inv, nil
}

// readInto runs one best-effort WMI query and hands its rows to fn.
//
// A failure is logged at debug and skipped: this is called for a dozen classes,
// several of which are legitimately absent on a given host, and an inventory
// that gave up on the first missing namespace would return nothing on exactly
// the machines worth inventorying.
func readInto[T any](ctx context.Context, class, namespace string, fn func([]T)) {
	if ctx.Err() != nil {
		return
	}
	var rows []T
	if err := queryNamespace("SELECT * FROM "+class, &rows, namespace); err != nil {
		logging.Debugf("agent: inventory: %s: %v", class, err)
		return
	}
	fn(rows)
}

// conversionStatuses decodes Win32_EncryptableVolume.ConversionStatus. The
// console shows the word, and the dashboard counts anything that is not
// "FullyEncrypted" as a volume that is not protected right now.
var conversionStatuses = map[uint32]string{
	0: "FullyDecrypted",
	1: "FullyEncrypted",
	2: "EncryptionInProgress",
	3: "DecryptionInProgress",
	4: "EncryptionPaused",
	5: "DecryptionPaused",
}

// readEncryption returns the BitLocker status of each volume, keyed by letter.
//
// Empty on failure, and failure is common: the namespace does not exist on some
// SKUs and the class refuses a non-elevated caller. An empty map leaves every
// volume's status unset, which the server stores as NULL — "not read", which it
// deliberately does not count as "not encrypted".
func readEncryption() map[string]string {
	var rows []rawEncryptableVolume
	if err := queryNamespace(
		"SELECT * FROM Win32_EncryptableVolume", &rows, encryptionNamespace); err != nil {
		logging.Debugf("agent: inventory: Win32_EncryptableVolume: %v", err)
		return nil
	}
	out := make(map[string]string, len(rows))
	for _, r := range rows {
		letter := strings.ToUpper(strings.TrimSpace(r.DriveLetter))
		if letter == "" {
			continue
		}
		if status, ok := conversionStatuses[r.ConversionStatus]; ok {
			out[letter] = status
		}
	}
	return out
}

// rawNetworkAdapter is Win32_NetworkAdapter, read for one property:
// PhysicalAdapter. GetAdaptersAddresses has no equivalent — Windows exposes no
// "is virtual" bit there — and this is the answer that does not depend on
// matching adapter names against a list of hypervisor products.
type rawNetworkAdapter struct {
	MACAddress      string
	PhysicalAdapter bool
}

// readPhysicalAdapterMACs returns the MACs of the adapters Windows considers
// physical. Empty on failure, which makes every adapter read as physical — the
// safe direction: showing a Hyper-V switch as a real card is a cosmetic error,
// hiding a real card is not.
func readPhysicalAdapterMACs() map[string]bool {
	var rows []rawNetworkAdapter
	if err := queryNamespace(
		"SELECT MACAddress, PhysicalAdapter FROM Win32_NetworkAdapter",
		&rows, cimv2Namespace); err != nil {
		logging.Debugf("agent: inventory: Win32_NetworkAdapter: %v", err)
		return nil
	}
	out := make(map[string]bool, len(rows))
	for _, r := range rows {
		mac := strings.ToUpper(strings.TrimSpace(r.MACAddress))
		if mac == "" {
			continue
		}
		out[mac] = r.PhysicalAdapter
	}
	return out
}

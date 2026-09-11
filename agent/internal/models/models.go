// Package models holds the wire types shared between the agent and the server.
package models

import "time"

// Fingerprint carries the identity components used for clone/tamper detection.
// Stored separately server-side (never hashed) so a benign rename can be told
// apart from a hardware swap. See plan §2.3.
type Fingerprint struct {
	MachineGUID string `json:"machine_guid,omitempty"` // HKLM Cryptography MachineGuid
	SMBIOSUUID  string `json:"smbios_uuid,omitempty"`  // Win32_ComputerSystemProduct.UUID (anchor)
	TPMEKHash   string `json:"tpm_ek_hash,omitempty"`  // hash of TPM 2.0 EK public, when present
}

// EnrollRequest is the first-contact payload (auth: X-Enrollment-Secret header).
type EnrollRequest struct {
	MachineUUID string `json:"machine_uuid"`
	Hostname    string `json:"hostname,omitempty"`
	Domain      string `json:"domain,omitempty"`
	// Location is the configured site name, "" when none is configured. Sent
	// without omitempty, on enroll and on every heartbeat alike: an empty value
	// is what *clears* a site the server stored earlier, and omitting it would
	// pin a poste on the location its config no longer names. A server older
	// than the field ignores it.
	Location     string       `json:"location"`
	OSVersion    string       `json:"os_version,omitempty"`
	AgentVersion string       `json:"agent_version,omitempty"`
	Fingerprint  *Fingerprint `json:"fingerprint,omitempty"`
}

// EnrollResponse carries the per-machine token (returned exactly once).
type EnrollResponse struct {
	MachineID string `json:"machine_id"`
	Token     string `json:"token"`
}

// DefenderState mirrors MSFT_MpComputerStatus fields we report.
type DefenderState struct {
	RTPEnabled           *bool      `json:"rtp_enabled,omitempty"`
	AVEnabled            *bool      `json:"av_enabled,omitempty"`
	SignatureVersion     string     `json:"signature_version,omitempty"`
	SignatureLastUpdated *time.Time `json:"signature_last_updated,omitempty"`
	SignatureAgeDays     *int       `json:"signature_age_days,omitempty"`
	LastQuickScan        *time.Time `json:"last_quick_scan,omitempty"`
	LastFullScan         *time.Time `json:"last_full_scan,omitempty"`
	// AMRunningMode: Normal / Passive / SxS Passive Mode / EDR Block Mode. This
	// is what explains an "antivirus off" reading on a machine that is in fact
	// protected — a third-party antivirus pushed Defender aside. Empty on
	// Windows 10 before 1903, where the property does not exist.
	RunningMode string `json:"running_mode,omitempty"`
}

// AVProductState reports the antivirus registered with the Windows Security
// Center, which is the only place a third-party product is visible (see
// collector/avproduct.go). Read-only by design: the Security Center exposes no
// signature version and no way to trigger an update.
//
// No omitempty on Name: an empty name means "no antivirus registered at all",
// which the server must be able to tell from an absent block — the latter means
// the agent could not look, and leaves the last known value alone.
type AVProductState struct {
	Name               string `json:"name"`
	Enabled            *bool  `json:"enabled,omitempty"`
	SignaturesUpToDate *bool  `json:"signatures_up_to_date,omitempty"`
	// Whether the product above is Defender itself. Decided here rather than
	// server-side: the evidence (instanceGuid, registered URI) is local, and
	// matching product names in the backend would be brittle.
	IsDefender bool `json:"is_defender"`
}

// SessionState reports whether a user is logged on to the workstation. The
// username is present only when the agent is configured to report it
// (report_session_username, default true) — the presence always is.
//
// No omitempty on the bools: an omitted "user_present": false would be
// indistinguishable server-side from "the agent never reported a session",
// which is a third, meaningful state.
type SessionState struct {
	UserPresent bool   `json:"user_present"`
	Username    string `json:"username,omitempty"`
	State       string `json:"state,omitempty"` // active / disconnected
	IsRemote    bool   `json:"is_remote"`
}

// PendingUpdate is one update WUA reports as applicable and not yet installed
// (search criteria "IsInstalled=0 and IsHidden=0").
//
// UpdateID carries WUA's UpdateID *and* its revision: Microsoft revises an
// update in place, and the revised one is a different thing to install, so the
// revision belongs in the key the server deduplicates on.
type PendingUpdate struct {
	UpdateID string `json:"update_id"`
	KB       string `json:"kb,omitempty"` // "KB5063878"; empty on the many that have none
	Title    string `json:"title,omitempty"`
	Severity string `json:"severity,omitempty"` // MSRC rating; empty when unrated
	Type     string `json:"type"`               // software / driver
	// The WUA category names ("Security Updates", "Drivers"). Sent as a list
	// and joined server-side: the console displays them and never queries them.
	Categories   []string `json:"categories,omitempty"`
	IsDownloaded bool     `json:"is_downloaded"`
	SizeMB       *float64 `json:"size_mb,omitempty"` // nil when WUA reports no size
}

// WUState is the heartbeat's Windows Update block, produced by the agent's own
// slow cycle rather than by the 60 s poll: a WU search takes minutes.
//
// No omitempty on Pending, and never nil: an empty list is the meaningful
// report of a fully patched machine, and the server *replaces* its stored set
// with what arrives here. Omitting the field would instead leave the previous
// set in place, which is what an absent block (a nil *WUState) means.
type WUState struct {
	RebootRequired  bool            `json:"reboot_required"`
	LastSearchTime  *time.Time      `json:"last_search_time,omitempty"`
	LastInstallTime *time.Time      `json:"last_install_time,omitempty"`
	Pending         []PendingUpdate `json:"pending"`
}

// --- Inventory --------------------------------------------------------------
//
// Dates that are dates and not instants (a BIOS date, an install date) travel
// as "2006-01-02" strings: the server stores them in a DATE column, and a
// midnight-UTC timestamp would shift across the date line for no reason.
//
// Every list below is nil-able and carries **no** omitempty, which is the whole
// contract: nil marshals to `null` and means "not read" — the server leaves its
// stored set alone — while an empty non-nil slice marshals to `[]` and means
// "read, and empty", which clears it. A virtual machine genuinely has no memory
// modules; a poste whose software collection is switched off genuinely reports
// no software, and that has to erase what an earlier cycle stored.

// MemoryModule is one physical stick, from Win32_PhysicalMemory.
type MemoryModule struct {
	// The bank/slot label ("DIMM A1"). The key the server upserts on: it is the
	// only field that stays put across reboots — a serial is blank on cheap
	// modules, and the enumeration order is not stable.
	Slot         string `json:"slot"`
	CapacityMB   *int   `json:"capacity_mb,omitempty"`
	Type         string `json:"type,omitempty"` // DDR4, DDR5…
	SpeedMHz     *int   `json:"speed_mhz,omitempty"`
	Manufacturer string `json:"manufacturer,omitempty"`
	Serial       string `json:"serial,omitempty"`
	FormFactor   string `json:"form_factor,omitempty"`
}

// Disk is one physical drive.
type Disk struct {
	// Windows' own device id (\\.\PHYSICALDRIVE0) and not the serial: a serial
	// is the better key right up to the machines that report none, and a blank
	// key is not a key.
	DeviceID string `json:"device_id"`
	Model    string `json:"model,omitempty"`
	Serial   string `json:"serial,omitempty"`
	Firmware string `json:"firmware,omitempty"`
	// SSD / HDD / NVMe / unknown. "unknown" is a real answer: Win32_DiskDrive
	// cannot tell the two apart, and a host without the Storage WMI namespace
	// falls back to it.
	MediaType    string `json:"media_type,omitempty"`
	BusType      string `json:"bus_type,omitempty"`
	SizeMB       *int   `json:"size_mb,omitempty"`
	HealthStatus string `json:"health_status,omitempty"`
	IsRemovable  bool   `json:"is_removable"`
}

// Volume is one fixed logical volume. No "used" field: the server subtracts, so
// two figures can never contradict each other about one number.
type Volume struct {
	Letter     string `json:"letter"` // "C:"
	Label      string `json:"label,omitempty"`
	Filesystem string `json:"filesystem,omitempty"`
	TotalMB    *int   `json:"total_mb,omitempty"`
	FreeMB     *int   `json:"free_mb,omitempty"`
	IsSystem   bool   `json:"is_system"`
	// BitLocker. Empty means not read — the namespace is absent on some SKUs and
	// the class needs elevation — which the server must not read as "not
	// encrypted": an alarm on a machine that may well be encrypted is how a
	// dashboard gets ignored.
	EncryptionStatus string `json:"encryption_status,omitempty"`
}

// Nic is one network adapter, from the same GetAdaptersAddresses walk that
// elects IPAddress above — but a different pass over it, with a different
// filter: the election wants candidates (up, non-tunnel), the inventory wants
// every adapter the machine has, disconnected ones included.
type Nic struct {
	// The MAC when the adapter has one, else its name. Composed here because
	// this is the only side that knows whether the address it read is a real
	// one — a PPP or tunnel pseudo-adapter has none.
	Key            string `json:"key"`
	Name           string `json:"name,omitempty"` // Windows' description = the model
	MAC            string `json:"mac,omitempty"`
	Type           string `json:"type,omitempty"` // ethernet / wifi / other
	SpeedMbps      *int   `json:"speed_mbps,omitempty"`
	IsUp           bool   `json:"is_up"`
	IsVirtual      bool   `json:"is_virtual"`
	IPAddress      string `json:"ip_address,omitempty"`
	IPPrefixLength int    `json:"ip_prefix_length,omitempty"`
	IsDHCP         *bool  `json:"is_dhcp,omitempty"`
	Gateway        string `json:"gateway,omitempty"`
}

// Gpu is one display adapter. Two is the common case: an iGPU and a card.
type Gpu struct {
	Name          string `json:"name"`
	Chipset       string `json:"chipset,omitempty"`
	MemoryMB      *int   `json:"memory_mb,omitempty"`
	DriverVersion string `json:"driver_version,omitempty"`
	DriverDate    string `json:"driver_date,omitempty"` // "2006-01-02"
	Resolution    string `json:"resolution,omitempty"`  // "1920x1080"
}

// Software is one installed program, read from the registry's Uninstall keys
// and never from Win32_Product — enumerating that class makes the Windows
// Installer re-verify every installed package, which takes minutes and writes
// an event into the Application log of every poste in the parc, every day.
type Software struct {
	// Name, version and publisher together are the catalogue's key server-side.
	// Plain strings and not pointers: the server's UNIQUE constraint treats
	// NULLs as distinct, so an absent publisher has to travel as "".
	Name            string `json:"name"`
	Version         string `json:"version"`
	Publisher       string `json:"publisher"`
	InstallDate     string `json:"install_date,omitempty"` // "2006-01-02"
	Arch            string `json:"arch,omitempty"`         // x86 / x64
	Source          string `json:"source,omitempty"`       // which Uninstall hive
	InstallLocation string `json:"install_location,omitempty"`
}

// InventoryState is the heartbeat's inventory block, produced by the agent's own
// daily cycle — and attached only when its Hash differs from the last one the
// server acknowledged, so a stable poste reports once and then stays quiet.
type InventoryState struct {
	// SHA-256 of everything below, this field excluded. The server stores it and
	// compares before writing: an agent that restarted has forgotten sending
	// this and re-sends it, and a match lets seven set replacements be skipped.
	Hash string `json:"hash,omitempty"`

	HWManufacturer string `json:"hw_manufacturer,omitempty"`
	HWModel        string `json:"hw_model,omitempty"`
	HWSerial       string `json:"hw_serial,omitempty"`
	HWChassisType  string `json:"hw_chassis_type,omitempty"`
	HWIsVirtual    bool   `json:"hw_is_virtual"`
	HWHypervisor   string `json:"hw_hypervisor,omitempty"`

	MBManufacturer string `json:"mb_manufacturer,omitempty"`
	MBModel        string `json:"mb_model,omitempty"`
	MBSerial       string `json:"mb_serial,omitempty"`

	BIOSVendor  string `json:"bios_vendor,omitempty"`
	BIOSVersion string `json:"bios_version,omitempty"`
	BIOSDate    string `json:"bios_date,omitempty"` // "2006-01-02"
	SecureBoot  *bool  `json:"secure_boot,omitempty"`
	TPMVersion  string `json:"tpm_version,omitempty"`

	// One CPU, in fields rather than a list: a workstation is single-socket, and
	// the rare dual-socket one carries two identical processors by construction.
	// CPUCount says how many.
	CPUModel        string `json:"cpu_model,omitempty"`
	CPUManufacturer string `json:"cpu_manufacturer,omitempty"`
	CPUCores        *int   `json:"cpu_cores,omitempty"`
	CPUThreads      *int   `json:"cpu_threads,omitempty"`
	CPUSpeedMHz     *int   `json:"cpu_speed_mhz,omitempty"`
	CPUCount        *int   `json:"cpu_count,omitempty"`

	RAMTotalMB    *int `json:"ram_total_mb,omitempty"`
	RAMSlotsTotal *int `json:"ram_slots_total,omitempty"`
	RAMSlotsUsed  *int `json:"ram_slots_used,omitempty"`

	OSArchitecture string     `json:"os_architecture,omitempty"`
	OSInstallDate  *time.Time `json:"os_install_date,omitempty"`
	LastBootTime   *time.Time `json:"last_boot_time,omitempty"`

	MemoryModules []MemoryModule `json:"memory_modules"`
	Disks         []Disk         `json:"disks"`
	Volumes       []Volume       `json:"volumes"`
	Nics          []Nic          `json:"nics"`
	Gpus          []Gpu          `json:"gpus"`
	Software      []Software     `json:"software"`

	// Directory is what the domain says about this computer — not hardware,
	// but read on the same daily cycle and shipped in the same block, because
	// it changes as rarely and the server files the poste by it
	// (ROOM_SOURCE). nil on a poste that is not domain-joined, or whose
	// directory could not be read; the server then keeps what it had.
	Directory *DirectoryState `json:"directory,omitempty"`
}

// DirectoryState is the computer object as Active Directory holds it, the two
// readings a console can file a poste by: the OU it sits in, and the
// free-text "location" an administrator typed on the object.
type DirectoryState struct {
	// The computer object's distinguished name, as Group Policy processing
	// cached it: "CN=PC-B12-03,OU=Salle B12,OU=Postes,DC=lycee,DC=local".
	DistinguishedName string `json:"distinguished_name,omitempty"`
	// The name of the OU directly containing the computer — the second RDN
	// above, "Salle B12" — and its DN, which is what the server keys a room
	// by: an OU renamed is a new room, an OU moved is not.
	OU   string `json:"ou,omitempty"`
	OUDN string `json:"ou_dn,omitempty"`
	// The object's "location" attribute (the Emplacement field of ADUC),
	// read through ADSI. Empty when unset, or when the directory could not
	// be reached — the two are not told apart, and the server treats empty
	// as "no opinion".
	ADLocation string `json:"ad_location,omitempty"`
}

// Threat mirrors the backend ThreatReport: one Defender detection. detection_id
// is the dedup key (UNIQUE (machine_id, detection_id) server-side, plan §2.7).
type Threat struct {
	DetectionID string     `json:"detection_id,omitempty"`
	ThreatName  string     `json:"threat_name,omitempty"`
	Severity    string     `json:"severity,omitempty"`
	Category    string     `json:"category,omitempty"`
	Status      string     `json:"status,omitempty"`
	ActionTaken string     `json:"action_taken,omitempty"`
	DetectedAt  *time.Time `json:"detected_at,omitempty"`
}

// HeartbeatRequest is sent on each poll (auth: Bearer token).
//
// IPAddress and MACAddress are plain attributes like the hostname, not a block:
// one elected adapter, re-read on every poll. omitempty is load-bearing — an
// agent that could not determine an address omits the field, and the server
// keeps the last known one rather than blanking it on no evidence.
//
// The MAC is what the server needs to wake this machine once it is off, and it
// is deliberately the MAC of the adapter holding IPAddress: the magic packet is
// broadcast on the subnet of that address, so a MAC belonging to another
// adapter would have the server shouting on the wrong network. IPPrefixLength
// is that subnet — reported rather than assumed server-side, because only the
// poste knows whether it lives in a /16 or a /24.
type HeartbeatRequest struct {
	Hostname string `json:"hostname,omitempty"`
	Domain   string `json:"domain,omitempty"`
	// See EnrollRequest.Location: always sent, "" clears.
	Location   string `json:"location"`
	IPAddress  string `json:"ip_address,omitempty"`
	MACAddress string `json:"mac_address,omitempty"`
	// omitempty on an int omits zero, which is precisely "not reported": the
	// server then keeps whatever mask it had, exactly as for the two above.
	IPPrefixLength int             `json:"ip_prefix_length,omitempty"`
	OSVersion      string          `json:"os_version,omitempty"`
	AgentVersion   string          `json:"agent_version,omitempty"`
	Defender       *DefenderState  `json:"defender,omitempty"`
	AVProduct      *AVProductState `json:"av_product,omitempty"`
	Session        *SessionState   `json:"session,omitempty"`
	// Attached only on the heartbeats that follow a Windows Update collection —
	// every few hours, not every minute. Absent (nil) leaves the server's stored
	// state alone, exactly like an absent Defender block.
	WindowsUpdate *WUState `json:"windows_update,omitempty"`
	// Rarer still than the block above: collected once a day, attached only when
	// its hash changed. A stable poste sends it once and then never again.
	Inventory   *InventoryState `json:"inventory,omitempty"`
	Fingerprint *Fingerprint    `json:"fingerprint,omitempty"`
	Threats     []Threat        `json:"threats,omitempty"`
}

// Command is a unit of work handed back by the server on heartbeat.
type Command struct {
	ID   string `json:"id"`
	Type string `json:"type"` // one of the server's CommandType values
	// TargetMAC is the one argument the protocol carries, and only for one
	// type: a wake_on_lan handed to this poste as a *relay* names the hardware
	// address of the poste to wake. Everything else in the catalogue still
	// travels as a bare type name. The agent validates it as an EUI-48 and
	// emits on its own subnets only — see collector.RelayWake for what that
	// bounds.
	TargetMAC string `json:"target_mac,omitempty"`
}

// HeartbeatResponse carries the pending commands for this machine.
type HeartbeatResponse struct {
	Commands []Command `json:"commands"`
}

// CommandResult is posted back after executing a command.
type CommandResult struct {
	Status string `json:"status"` // succeeded / failed
	Output string `json:"output,omitempty"`
	Error  string `json:"error,omitempty"`
}

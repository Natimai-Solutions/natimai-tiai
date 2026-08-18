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
	MachineUUID  string       `json:"machine_uuid"`
	Hostname     string       `json:"hostname,omitempty"`
	Domain       string       `json:"domain,omitempty"`
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
// IPAddress is a plain attribute like the hostname, not a block: one elected
// address, re-read on every poll. omitempty is load-bearing — an agent that
// could not determine an address omits the field, and the server keeps the last
// known one rather than blanking it on no evidence.
type HeartbeatRequest struct {
	Hostname     string          `json:"hostname,omitempty"`
	Domain       string          `json:"domain,omitempty"`
	IPAddress    string          `json:"ip_address,omitempty"`
	OSVersion    string          `json:"os_version,omitempty"`
	AgentVersion string          `json:"agent_version,omitempty"`
	Defender     *DefenderState  `json:"defender,omitempty"`
	AVProduct    *AVProductState `json:"av_product,omitempty"`
	Session      *SessionState   `json:"session,omitempty"`
	// Attached only on the heartbeats that follow a Windows Update collection —
	// every few hours, not every minute. Absent (nil) leaves the server's stored
	// state alone, exactly like an absent Defender block.
	WindowsUpdate *WUState     `json:"windows_update,omitempty"`
	Fingerprint   *Fingerprint `json:"fingerprint,omitempty"`
	Threats       []Threat     `json:"threats,omitempty"`
}

// Command is a unit of work handed back by the server on heartbeat.
type Command struct {
	ID   string `json:"id"`
	Type string `json:"type"` // one of the server's CommandType values
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

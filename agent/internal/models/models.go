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
	Hostname     string         `json:"hostname,omitempty"`
	Domain       string         `json:"domain,omitempty"`
	IPAddress    string         `json:"ip_address,omitempty"`
	OSVersion    string         `json:"os_version,omitempty"`
	AgentVersion string         `json:"agent_version,omitempty"`
	Defender     *DefenderState `json:"defender,omitempty"`
	Session      *SessionState  `json:"session,omitempty"`
	Fingerprint  *Fingerprint   `json:"fingerprint,omitempty"`
	Threats      []Threat       `json:"threats,omitempty"`
}

// Command is a unit of work handed back by the server on heartbeat.
type Command struct {
	ID   string `json:"id"`
	Type string `json:"type"` // quick_scan / full_scan / update_signatures
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

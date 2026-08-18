// Package collector reads the per-poll state of a workstation — Microsoft
// Defender status and threats, and the logged-on session — and drives Defender
// scans / signature updates.
//
// Per plan §2.6, Defender status and threats are read via WMI (namespace
// ROOT\Microsoft\Windows\Defender) — cheap, no process spawn — while the
// actions not cleanly exposed as WMI methods (scans, signature update) fall
// back to PowerShell cmdlets. The session is read through the WTS API, which
// works from session 0 where the agent runs (see session.go).
//
// Mapping and election helpers in the build-tag-free files are pure and
// platform-independent so they can be unit-tested anywhere.
package collector

import "time"

// mapSeverity maps MSFT_MpThreat.SeverityID to a label.
func mapSeverity(id uint32) string {
	switch id {
	case 1:
		return "low"
	case 2:
		return "medium"
	case 4:
		return "high"
	case 5:
		return "severe"
	default:
		return "unknown"
	}
}

// mapThreatStatus maps MSFT_MpThreatDetection.ThreatStatusID to a label.
func mapThreatStatus(id uint32) string {
	switch id {
	case 0:
		return "unknown"
	case 1:
		return "active"
	case 2:
		return "cleaned"
	case 3:
		return "quarantined"
	case 4:
		return "removed"
	case 5:
		return "allowed"
	case 6:
		return "blocked"
	case 102:
		return "quarantine_failed"
	case 103:
		return "remove_failed"
	case 104:
		return "allow_failed"
	case 105:
		return "abandoned"
	case 107:
		return "block_failed"
	default:
		// "unknown", never "active": a status id Defender adds later is a status
		// we cannot read, not a live infection. Guessing "active" would show the
		// console an untreated threat that Defender has in fact dealt with, and
		// there is no way back from a false alarm of that kind.
		return "unknown"
	}
}

// mapCategory maps the most common MSFT_MpThreat.CategoryID values. The threat
// name already encodes the category, so unknown ids are reported empty rather
// than as noise.
func mapCategory(id uint32) string {
	switch id {
	case 1:
		return "adware"
	case 2:
		return "spyware"
	case 3:
		return "password_stealer"
	case 4:
		return "trojan_downloader"
	case 5:
		return "worm"
	case 6:
		return "backdoor"
	case 7:
		return "remote_access_trojan"
	case 8:
		return "trojan"
	case 10:
		return "keylogger"
	case 22:
		return "tool"
	case 25:
		return "remote_control_software"
	case 27:
		return "potentially_unwanted_software"
	case 30:
		return "exploit"
	case 34:
		return "tool"
	case 37:
		return "trojan_dropper"
	case 41:
		return "virus"
	case 42:
		return "known_bad"
	case 46:
		return "vulnerability"
	default:
		return ""
	}
}

// signatureAgeDays returns whole days between the signature timestamp and now,
// or nil when no timestamp is available.
func signatureAgeDays(lastUpdated *time.Time, now time.Time) *int {
	if lastUpdated == nil || lastUpdated.IsZero() {
		return nil
	}
	d := int(now.Sub(*lastUpdated).Hours() / 24)
	if d < 0 {
		d = 0
	}
	return &d
}

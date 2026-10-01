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

import (
	"errors"
	"fmt"
	"time"
)

// ErrWMIUnavailable is returned, without waiting, by every WMI read while a
// previous query has not come back (see queryNamespace in the Windows file).
// The heartbeat carries on without the blocks it could not read — the server
// keeps their last known values — and, crucially, keeps carrying the machine's
// presence and picking up its commands: a poste in this state is one an
// administrator wants to be able to restart from the console.
//
// Declared off the build tag so the agent can recognise it on any platform.
var ErrWMIUnavailable = errors.New(
	"wmi: a previous query has not returned yet, reads are skipped until it does")

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

// --- Actions: budgets and failure messages ----------------------------------

// Budgets for the Defender actions. Like the maintenance timeout classes, they
// exist because the command worker is sequential: a scan that never returns —
// a Defender engine wedged on a broken definition update, a PowerShell host
// stuck on a WMI provider — would otherwise pin the worker for the life of the
// service, and every command queued behind it, a reboot included, would wait
// forever with "transmise" on the console.
//
// They are hang detectors, not estimates. The full scan's budget is not here:
// it is the one an administrator legitimately needs to raise, so it is a
// setting (config.DefaultDefenderFullScanTimeout), passed to RunFullScan the
// same way the Windows Update install budget is passed to RunWUInstall.
const (
	// quickScanTimeout: a quick scan covers memory, startup locations and the
	// system folders, and finishes in minutes even on a tired machine. An hour
	// is an order of magnitude above that — beyond it the scan is stuck, not
	// slow.
	quickScanTimeout = 1 * time.Hour
	// signatureUpdateTimeout: a definition update is a download of at most a
	// few hundred megabytes (a full package when the delta chain is broken),
	// from WSUS, Windows Update or a share. Same budget as a Windows Update
	// search, for the same kind of work over the same kind of link.
	signatureUpdateTimeout = 30 * time.Minute
)

// powerShellWaitDelay bounds how long a killed PowerShell may keep its output
// pipes open. Without it, a budget is only as good as the last process holding
// a copy of those handles: exec kills powershell.exe at the deadline, but Wait
// still blocks until every inheritor of stdout has exited — and a child that
// never does would pin the worker exactly as if there had been no budget.
const powerShellWaitDelay = 10 * time.Second

// defenderAction is one of the three Defender commands: the script PowerShell
// runs, and how to talk about it when it does not finish.
type defenderAction struct {
	script string
	// label names the action inside a French sentence ("l'analyse rapide
	// Defender"), so every message about it reads the same.
	label string
	// advice is what an administrator should do after a timeout — the part
	// that makes the message actionable rather than a bare "délai dépassé".
	advice string
}

var (
	defenderQuickScan = defenderAction{
		script: "Start-MpScan -ScanType QuickScan",
		label:  "l'analyse rapide Defender",
		advice: "L'analyse peut se poursuivre sur le poste : vérifier la date de " +
			"dernière analyse rapide avant de la relancer. Un dépassement répété " +
			"signale un moteur Defender bloqué (redémarrer le poste).",
	}
	defenderFullScan = defenderAction{
		script: "Start-MpScan -ScanType FullScan",
		label:  "l'analyse complète Defender",
		advice: "L'analyse peut se poursuivre sur le poste : vérifier la date de " +
			"dernière analyse complète avant de la relancer. Si les analyses " +
			"complètes de ce parc sont légitimement plus longues (gros disques " +
			"mécaniques), augmenter defender_full_scan_timeout_seconds " +
			"(registre : DefenderFullScanTimeoutSeconds).",
	}
	defenderSignatureUpdate = defenderAction{
		script: "Update-MpSignature",
		label:  "la mise à jour des signatures Defender",
		advice: "Vérifier que le poste joint sa source de signatures (WSUS, " +
			"Windows Update ou partage de définitions configuré par stratégie).",
	}
)

// timeoutError is the verdict for an action that outlived its budget. The
// budget is named in the message: "délai dépassé" alone does not say whether
// the scan was given ten minutes or ten hours, and that is the first thing to
// know before raising it.
func (a defenderAction) timeoutError(budget time.Duration) error {
	return fmt.Errorf("délai dépassé : %s ne s'est pas terminée en %s. %s",
		a.label, frDuration(budget), a.advice)
}

// interruptedError is the verdict for an action cut short by the service
// stopping — not a Defender problem, and nothing for anyone to fix.
func (a defenderAction) interruptedError() error {
	return fmt.Errorf("%s a été interrompue (arrêt de l'agent) : à relancer", a.label)
}

// frDuration renders a budget for a French console message: "8 h", "1 h 30 min",
// "30 min". Not time.Duration.String(), whose "8h0m0s" reads as a log line in
// the middle of a sentence.
func frDuration(d time.Duration) string {
	h := int(d / time.Hour)
	m := int(d % time.Hour / time.Minute)
	switch {
	case h > 0 && m > 0:
		return fmt.Sprintf("%d h %d min", h, m)
	case h > 0:
		return fmt.Sprintf("%d h", h)
	case m > 0:
		return fmt.Sprintf("%d min", m)
	default:
		return fmt.Sprintf("%d s", int(d/time.Second))
	}
}

package collector

import (
	"strings"
	"testing"
	"time"
)

func TestMapSeverity(t *testing.T) {
	cases := map[uint32]string{1: "low", 2: "medium", 4: "high", 5: "severe", 0: "unknown", 99: "unknown"}
	for id, want := range cases {
		if got := mapSeverity(id); got != want {
			t.Errorf("mapSeverity(%d) = %q, want %q", id, got, want)
		}
	}
}

func TestMapThreatStatus(t *testing.T) {
	// 999: an id we cannot read is reported "unknown", not "active" — the console
	// must not show a live infection on a status Defender never claimed.
	cases := map[uint32]string{
		1: "active", 2: "cleaned", 3: "quarantined", 4: "removed", 5: "allowed",
		6: "blocked", 0: "unknown", 999: "unknown",
	}
	for id, want := range cases {
		if got := mapThreatStatus(id); got != want {
			t.Errorf("mapThreatStatus(%d) = %q, want %q", id, got, want)
		}
	}
}

func TestSignatureAgeDays(t *testing.T) {
	now := time.Date(2026, 6, 26, 12, 0, 0, 0, time.UTC)

	if got := signatureAgeDays(nil, now); got != nil {
		t.Errorf("nil timestamp should yield nil, got %v", *got)
	}

	zero := time.Time{}
	if got := signatureAgeDays(&zero, now); got != nil {
		t.Errorf("zero timestamp should yield nil, got %v", *got)
	}

	threeDaysAgo := now.Add(-72 * time.Hour)
	if got := signatureAgeDays(&threeDaysAgo, now); got == nil || *got != 3 {
		t.Errorf("expected 3 days, got %v", got)
	}

	future := now.Add(24 * time.Hour)
	if got := signatureAgeDays(&future, now); got == nil || *got != 0 {
		t.Errorf("future timestamp should clamp to 0, got %v", got)
	}
}

// A timed-out scan is reported to an administrator who has to decide what to do
// next, so the message must name the action, the budget it was given, and the
// way out — for the full scan, the setting that raises that budget.
func TestDefenderTimeoutMessagesAreActionable(t *testing.T) {
	cases := []struct {
		name   string
		action defenderAction
		budget time.Duration
		want   []string
	}{
		{"quick", defenderQuickScan, quickScanTimeout,
			[]string{"délai dépassé", "analyse rapide", "1 h", "dernière analyse rapide"}},
		{"full", defenderFullScan, 8 * time.Hour,
			[]string{"délai dépassé", "analyse complète", "8 h",
				"defender_full_scan_timeout_seconds", "DefenderFullScanTimeoutSeconds"}},
		{"signatures", defenderSignatureUpdate, signatureUpdateTimeout,
			[]string{"délai dépassé", "signatures", "30 min", "WSUS"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			msg := c.action.timeoutError(c.budget).Error()
			for _, w := range c.want {
				if !strings.Contains(msg, w) {
					t.Errorf("message %q does not mention %q", msg, w)
				}
			}
		})
	}
}

// The service stopping is not a Defender failure: the message must say what
// happened instead of looking like a timeout.
func TestDefenderInterruptionIsNotATimeout(t *testing.T) {
	msg := defenderFullScan.interruptedError().Error()
	if strings.Contains(msg, "délai") {
		t.Errorf("an interruption must not read as a timeout: %q", msg)
	}
	if !strings.Contains(msg, "arrêt de l'agent") {
		t.Errorf("an interruption must say the agent stopped: %q", msg)
	}
}

// Each action runs the cmdlet it is named after — a swapped script would scan
// quickly when asked for a full scan, and report success.
func TestDefenderActionsRunTheirOwnCmdlet(t *testing.T) {
	if !strings.Contains(defenderQuickScan.script, "QuickScan") {
		t.Errorf("quick scan runs %q", defenderQuickScan.script)
	}
	if !strings.Contains(defenderFullScan.script, "FullScan") {
		t.Errorf("full scan runs %q", defenderFullScan.script)
	}
	if !strings.Contains(defenderSignatureUpdate.script, "Update-MpSignature") {
		t.Errorf("signature update runs %q", defenderSignatureUpdate.script)
	}
}

// The fixed budgets are hang detectors: far above a normal run, far below
// "never". A quick scan allowed as long as a full scan would make the
// distinction between the two meaningless.
func TestDefenderFixedBudgets(t *testing.T) {
	if quickScanTimeout < 15*time.Minute || quickScanTimeout > 2*time.Hour {
		t.Errorf("quick scan budget %s is not a hang detector", quickScanTimeout)
	}
	if signatureUpdateTimeout < 10*time.Minute || signatureUpdateTimeout > time.Hour {
		t.Errorf("signature update budget %s is not a hang detector", signatureUpdateTimeout)
	}
	if powerShellWaitDelay <= 0 || powerShellWaitDelay > time.Minute {
		t.Errorf("wait delay %s must be short and positive", powerShellWaitDelay)
	}
}

func TestFrDuration(t *testing.T) {
	cases := map[time.Duration]string{
		8 * time.Hour:                    "8 h",
		90 * time.Minute:                 "1 h 30 min",
		30 * time.Minute:                 "30 min",
		45 * time.Second:                 "45 s",
		time.Hour + 30*time.Second:       "1 h",
		2*time.Hour + 59*time.Minute + 1: "2 h 59 min",
	}
	for d, want := range cases {
		if got := frDuration(d); got != want {
			t.Errorf("frDuration(%s) = %q, want %q", d, got, want)
		}
	}
}

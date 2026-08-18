package collector

import (
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

package agent

import (
	"fmt"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/config"
)

func TestNextBackoffDoublesAndCaps(t *testing.T) {
	base := 60 * time.Second
	max := 300 * time.Second

	got := nextBackoff(base, max)
	if got != 120*time.Second {
		t.Errorf("first backoff = %s, want 2m", got)
	}
	got = nextBackoff(got, max)
	if got != 240*time.Second {
		t.Errorf("second backoff = %s, want 4m", got)
	}
	// 240 * 2 = 480 > 300 → capped.
	got = nextBackoff(got, max)
	if got != max {
		t.Errorf("third backoff = %s, want cap %s", got, max)
	}
	// Stays capped.
	if got = nextBackoff(got, max); got != max {
		t.Errorf("backoff should stay at cap, got %s", got)
	}
}

// The 401 detection is what turns a revocation into a re-enrollment instead of
// an endless 401 loop, so it must see the status through the client's wrapping
// — and must NOT fire on anything else (a 403 is "stay away", not "retry").
func TestIsUnauthorized(t *testing.T) {
	wrapped := fmt.Errorf("POST /api/v1/agent/heartbeat: %w",
		&api.StatusError{StatusCode: 401, Body: "revoked"})
	if !isUnauthorized(wrapped) {
		t.Error("wrapped 401 not detected")
	}
	forbidden := fmt.Errorf("POST /api/v1/agent/enroll: %w",
		&api.StatusError{StatusCode: 403, Body: "machine.enrollment.revoked"})
	if isUnauthorized(forbidden) {
		t.Error("403 must not count as unauthorized")
	}
	if isUnauthorized(fmt.Errorf("dial tcp: connection refused")) {
		t.Error("transport error must not count as unauthorized")
	}
	if isUnauthorized(nil) {
		t.Error("nil error must not count as unauthorized")
	}
}

// The heartbeat carrying an inventory gets a budget of its own: timing it out
// at the poll timeout never loses just that heartbeat, it loses the inventory
// on every retry after it, for as long as the poste keeps trying.
func TestHeavyTimeoutOutlastsThePollTimeout(t *testing.T) {
	a := &Agent{cfg: &config.Config{RequestTimeoutSeconds: config.DefaultRequestTimeout}}
	if got := a.heavyTimeout(); got != heavyHeartbeatTimeout {
		t.Errorf("expected the heavy budget %s, got %s", heavyHeartbeatTimeout, got)
	}
	// A parc that widened the request timeout meant it for this request above
	// all — the wider value wins.
	wide := int(heavyHeartbeatTimeout.Seconds()) * 2
	a = &Agent{cfg: &config.Config{RequestTimeoutSeconds: wide}}
	if got := a.heavyTimeout(); got != time.Duration(wide)*time.Second {
		t.Errorf("a configured timeout above the default must win, got %s", got)
	}
}

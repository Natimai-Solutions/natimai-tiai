package agent

import (
	"context"
	"fmt"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/collector"
	"tiai/agent/internal/config"
	"tiai/agent/internal/models"
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

// The jittered delay stays inside [step/2, step]: never sooner than half the
// step — a fleet hammering a server that is down is what back-off prevents —
// and never past the step, so the configured cap remains a ceiling.
func TestJitterBackoffStaysWithinHalfToFullStep(t *testing.T) {
	for _, step := range []time.Duration{
		120 * time.Second, 240 * time.Second, 300 * time.Second, 3, 2,
	} {
		for range 500 {
			got := jitterBackoff(step)
			if got < step-step/2 || got > step {
				t.Fatalf("jitterBackoff(%s) = %s, want within [%s, %s]",
					step, got, step-step/2, step)
			}
		}
	}
}

// The point of the jitter is that two agents failing together do not retry
// together: the draws must actually spread, and reach both ends of the range.
func TestJitterBackoffSpreads(t *testing.T) {
	const step = 4 * time.Nanosecond // range {2,3,4}: small enough to hit both ends
	seen := map[time.Duration]bool{}
	for range 1000 {
		seen[jitterBackoff(step)] = true
	}
	for _, want := range []time.Duration{2, 3, 4} {
		if !seen[want] {
			t.Errorf("jitterBackoff(%d) never returned %d (seen %v)", step, want, seen)
		}
	}

	big := map[time.Duration]bool{}
	for range 200 {
		big[jitterBackoff(300*time.Second)] = true
	}
	if len(big) < 2 {
		t.Error("a fixed retry delay would bring the whole parc back at the same second")
	}
}

// Degenerate steps never panic (rand.N rejects a non-positive bound) and are
// returned as they are.
func TestJitterBackoffDegenerateSteps(t *testing.T) {
	for _, step := range []time.Duration{0, 1, -time.Second} {
		if got := jitterBackoff(step); got != step {
			t.Errorf("jitterBackoff(%s) = %s, want it unchanged", step, got)
		}
	}
}

// A full scan is bounded by the configured budget — the sequential worker
// would otherwise be held for good by a scan that never returns — and is
// announced with `running`, since it lasts tens of minutes at the very least.
func TestFullScanRunsUnderTheConfiguredBudget(t *testing.T) {
	var got time.Duration
	orig := runFullScan
	t.Cleanup(func() { runFullScan = orig })
	runFullScan = func(_ context.Context, timeout time.Duration) (string, error) {
		got = timeout
		return "", nil
	}

	for _, c := range []struct {
		name    string
		seconds int
		want    time.Duration
	}{
		{"configured", 12 * 3600, 12 * time.Hour},
		{"default", config.DefaultConfig().DefenderFullScanTimeoutSeconds,
			config.DefaultDefenderFullScanTimeout * time.Second},
		// A Config built by hand, without Load: the bound must not vanish.
		{"unset", 0, config.DefaultDefenderFullScanTimeout * time.Second},
	} {
		t.Run(c.name, func(t *testing.T) {
			got = 0
			a := &Agent{cfg: &config.Config{DefenderFullScanTimeoutSeconds: c.seconds}}
			run, long, ok := a.resolve(models.Command{ID: "c1", Type: "full_scan"})
			if !ok {
				t.Fatal("full_scan must be a known command")
			}
			if !long {
				t.Error("full_scan must post an intermediate `running`")
			}
			if _, err := run(context.Background()); err != nil {
				t.Fatalf("run: %v", err)
			}
			if got != c.want {
				t.Errorf("full scan budget = %s, want %s", got, c.want)
			}
		})
	}
}

// The quick scan and the signature update stay short commands: a `running`
// for something that ends in minutes is noise on the console.
func TestShortDefenderCommandsAreNotAnnounced(t *testing.T) {
	a := &Agent{cfg: config.DefaultConfig()}
	for _, typ := range []string{"quick_scan", "update_signatures"} {
		_, long, ok := a.resolve(models.Command{Type: typ})
		if !ok {
			t.Errorf("%s must be a known command", typ)
		}
		if long {
			t.Errorf("%s must not post `running`", typ)
		}
	}
}

// resolve keeps what execute used to decide inline: the maintenance catalogue
// still carries its own `long` flag, and an unknown type is refused rather
// than run.
func TestResolveMaintenanceAndUnknownTypes(t *testing.T) {
	a := &Agent{cfg: config.DefaultConfig()}
	info, found := collector.LookupMaintenance("sfc_scan")
	if !found {
		t.Fatal("sfc_scan must be in the maintenance catalogue")
	}
	if _, long, ok := a.resolve(models.Command{Type: "sfc_scan"}); !ok || long != info.Long {
		t.Errorf("sfc_scan: ok=%v long=%v, want ok and long=%v", ok, long, info.Long)
	}
	if _, _, ok := a.resolve(models.Command{Type: "format_c"}); ok {
		t.Error("a type outside every catalogue must not resolve")
	}
}

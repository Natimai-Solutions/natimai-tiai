package agent

import (
	"errors"
	"strings"
	"testing"
	"time"
)

// upSince builds a guard whose machine booted d ago.
func upSince(d time.Duration) *rebootGuard {
	return &rebootGuard{uptime: func() (time.Duration, error) { return d, nil }}
}

func TestRebootAllowedOnALongRunningMachine(t *testing.T) {
	g := upSince(3 * time.Hour)
	if err := g.allow(time.Now()); err != nil {
		t.Errorf("allow = %v, want nil on a machine up for hours", err)
	}
}

// The case the whole guard exists for: a queue that keeps re-offering a restart
// would otherwise loop the poste, each boot wiping the evidence of the last —
// the agent's own memory goes down with the machine.
func TestRebootRefusedOnAFreshlyBootedMachine(t *testing.T) {
	g := upSince(3 * time.Minute)
	err := g.allow(time.Now())
	if err == nil {
		t.Fatal("a machine booted three minutes ago must not restart again")
	}
	if !errors.Is(err, errRebootTooSoon) {
		t.Errorf("err = %v, want it to wrap errRebootTooSoon", err)
	}
	// The message is read in the console by whoever asked: it has to say how
	// long, not quote a rule.
	if !strings.Contains(err.Error(), "3 min") {
		t.Errorf("message should name the age: %v", err)
	}
}

func TestRebootRefusedTwiceInAWindow(t *testing.T) {
	// Uptime is long: only the process-local memory can refuse here.
	g := upSince(3 * time.Hour)
	now := time.Now()
	if err := g.allow(now); err != nil {
		t.Fatalf("first restart refused: %v", err)
	}
	g.markScheduled(now)

	err := g.allow(now.Add(2 * time.Minute))
	if err == nil {
		t.Fatal("a second restart inside the window must be refused")
	}
	if !strings.Contains(err.Error(), "déjà été programmé") {
		t.Errorf("message should name the earlier restart: %v", err)
	}

	// Past the window it is allowed again — this is rationing, not a one-shot.
	if err := g.allow(now.Add(minRebootInterval + time.Second)); err != nil {
		t.Errorf("allow after the window = %v, want nil", err)
	}
}

// A rationing rule, not a security boundary. Refusing every restart on a
// machine whose uptime call misbehaves would break the feature to enforce a
// courtesy — the process-local check still stands.
func TestRebootSurvivesAnUnreadableUptime(t *testing.T) {
	g := &rebootGuard{uptime: func() (time.Duration, error) {
		return 0, errors.New("kernel32 unavailable")
	}}
	now := time.Now()
	if err := g.allow(now); err != nil {
		t.Fatalf("allow = %v, want nil when uptime cannot be read", err)
	}
	g.markScheduled(now)
	if err := g.allow(now.Add(time.Minute)); err == nil {
		t.Error("the process-local guard must still refuse a second restart")
	}
}

// --- Holding the rest of the catalogue back --------------------------------

// Ordering protects one direction only: a long command queued *after* a restart
// cannot start before it, but a restart queued *before* one returns in
// milliseconds and the machine then goes down sixty seconds into a dism.
func TestPendingRestartBlocksOtherCommands(t *testing.T) {
	g := upSince(3 * time.Hour)
	now := time.Now()

	if g.restartPending(now) {
		t.Error("nothing is pending before a restart is scheduled")
	}
	g.markScheduled(now)
	if !g.restartPending(now.Add(30 * time.Second)) {
		t.Error("a restart scheduled 30 s ago must hold commands back")
	}
}

// A restart can be called off — `shutdown /a` from a local administrator. An
// agent that waited for a machine which is never going down would refuse every
// command for the rest of its life.
func TestPendingRestartExpires(t *testing.T) {
	g := upSince(3 * time.Hour)
	now := time.Now()
	g.markScheduled(now)

	if !g.restartPending(now.Add(rebootPendingWindow - time.Second)) {
		t.Error("still pending just inside the window")
	}
	if g.restartPending(now.Add(rebootPendingWindow + time.Second)) {
		t.Error("past the window the agent must assume the restart was cancelled")
	}
}

// The window that blocks other commands has to clear well before the one that
// rations restarts, or a poste whose restart was called off would sit refusing
// everything until it could be restarted again.
func TestPendingWindowIsShorterThanTheRationingInterval(t *testing.T) {
	if rebootPendingWindow >= minRebootInterval {
		t.Errorf("rebootPendingWindow (%s) must be shorter than minRebootInterval (%s)",
			rebootPendingWindow, minRebootInterval)
	}
	// And long enough to cover the scheduled delay itself, or the guard would
	// lift while the machine is still counting down.
	if rebootPendingWindow <= 2*time.Minute {
		t.Errorf("rebootPendingWindow (%s) barely covers the 60 s restart delay",
			rebootPendingWindow)
	}
}

// These strings land in the command history of a French console, beside the
// maintenance verdicts — not in a log.
func TestHumanAge(t *testing.T) {
	cases := map[time.Duration]string{
		42 * time.Second:                              "42 s",
		3*time.Minute + 12*time.Second:                "3 min",
		2*time.Hour + 31*time.Minute + 40*time.Second: "2 h",
		// Truncated, not rounded: 9 min 50 s must not read as "10 min" next to
		// a minimum of 10 min it has not reached.
		9*time.Minute + 50*time.Second: "9 min",
	}
	for in, want := range cases {
		if got := humanAge(in); got != want {
			t.Errorf("humanAge(%s) = %q, want %q", in, got, want)
		}
	}
}

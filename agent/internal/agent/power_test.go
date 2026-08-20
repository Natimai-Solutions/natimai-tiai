package agent

import (
	"errors"
	"strings"
	"testing"
	"time"
)

// upSince builds a guard whose machine booted d ago.
func upSince(d time.Duration) *powerGuard {
	return &powerGuard{uptime: func() (time.Duration, error) { return d, nil }}
}

func TestPowerActionAllowedOnALongRunningMachine(t *testing.T) {
	g := upSince(3 * time.Hour)
	if err := g.allow(time.Now()); err != nil {
		t.Errorf("allow = %v, want nil on a machine up for hours", err)
	}
}

// The case the whole guard exists for: a queue that keeps re-offering a restart
// would otherwise loop the poste, each boot wiping the evidence of the last —
// the agent's own memory goes down with the machine.
func TestPowerActionRefusedOnAFreshlyBootedMachine(t *testing.T) {
	g := upSince(3 * time.Minute)
	err := g.allow(time.Now())
	if err == nil {
		t.Fatal("a machine booted three minutes ago must not go down again")
	}
	if !errors.Is(err, errPowerActionTooSoon) {
		t.Errorf("err = %v, want it to wrap errPowerActionTooSoon", err)
	}
	// The message is read in the console by whoever asked: it has to say how
	// long, not quote a rule.
	if !strings.Contains(err.Error(), "3 min") {
		t.Errorf("message should name the age: %v", err)
	}
}

func TestPowerActionRefusedTwiceInAWindow(t *testing.T) {
	// Uptime is long: only the process-local memory can refuse here.
	g := upSince(3 * time.Hour)
	now := time.Now()
	if err := g.allow(now); err != nil {
		t.Fatalf("first restart refused: %v", err)
	}
	g.markScheduled(now, actionReboot)

	err := g.allow(now.Add(2 * time.Minute))
	if err == nil {
		t.Fatal("a second power action inside the window must be refused")
	}
	if !strings.Contains(err.Error(), "déjà été programmé") {
		t.Errorf("message should name the earlier operation: %v", err)
	}

	// Past the window it is allowed again — this is rationing, not a one-shot.
	if err := g.allow(now.Add(minPowerActionInterval + time.Second)); err != nil {
		t.Errorf("allow after the window = %v, want nil", err)
	}
}

// One guard for both operations: what is rationed is the machine going down.
// A shutdown queued behind a restart would meet a poste that is already on its
// way out — and, with the server able to wake it again, a stale shutdown is how
// a poste ends up switching itself off the moment it comes back.
func TestAShutdownIsRefusedAfterARestart(t *testing.T) {
	g := upSince(3 * time.Hour)
	now := time.Now()
	g.markScheduled(now, actionReboot)

	err := g.allow(now.Add(time.Minute))
	if err == nil {
		t.Fatal("a shutdown must be refused while a restart is still fresh")
	}
	// And it says which operation stands in the way, in the words the console
	// uses: an administrator reading "arrêt" here would go looking for the
	// wrong thing.
	if !strings.Contains(err.Error(), actionReboot) {
		t.Errorf("message should name the pending restart: %v", err)
	}
}

// A rationing rule, not a security boundary. Refusing every restart on a
// machine whose uptime call misbehaves would break the feature to enforce a
// courtesy — the process-local check still stands.
func TestPowerActionSurvivesAnUnreadableUptime(t *testing.T) {
	g := &powerGuard{uptime: func() (time.Duration, error) {
		return 0, errors.New("kernel32 unavailable")
	}}
	now := time.Now()
	if err := g.allow(now); err != nil {
		t.Fatalf("allow = %v, want nil when uptime cannot be read", err)
	}
	g.markScheduled(now, actionShutdown)
	if err := g.allow(now.Add(time.Minute)); err == nil {
		t.Error("the process-local guard must still refuse a second power action")
	}
}

// --- Holding the rest of the catalogue back --------------------------------

// Ordering protects one direction only: a long command queued *after* a restart
// cannot start before it, but a restart queued *before* one returns in
// milliseconds and the machine then goes down sixty seconds into a dism.
func TestAPendingPowerActionBlocksOtherCommands(t *testing.T) {
	g := upSince(3 * time.Hour)
	now := time.Now()

	if kind := g.pending(now); kind != "" {
		t.Errorf("pending = %q, want nothing before anything is scheduled", kind)
	}
	g.markScheduled(now, actionShutdown)
	if kind := g.pending(now.Add(30 * time.Second)); kind != actionShutdown {
		t.Errorf("pending = %q, want %q 30 s after it was scheduled", kind, actionShutdown)
	}
}

// A power action can be called off — `shutdown /a` from a local administrator.
// An agent that waited for a machine which is never going down would refuse
// every command for the rest of its life.
func TestAPendingPowerActionExpires(t *testing.T) {
	g := upSince(3 * time.Hour)
	now := time.Now()
	g.markScheduled(now, actionReboot)

	if g.pending(now.Add(powerActionPendingWindow-time.Second)) == "" {
		t.Error("still pending just inside the window")
	}
	if kind := g.pending(now.Add(powerActionPendingWindow + time.Second)); kind != "" {
		t.Errorf("pending = %q past the window; the agent must assume it was cancelled", kind)
	}
}

// The window that blocks other commands has to clear well before the one that
// rations power actions, or a poste whose restart was called off would sit
// refusing everything until it could be restarted again.
func TestPendingWindowIsShorterThanTheRationingInterval(t *testing.T) {
	if powerActionPendingWindow >= minPowerActionInterval {
		t.Errorf("powerActionPendingWindow (%s) must be shorter than minPowerActionInterval (%s)",
			powerActionPendingWindow, minPowerActionInterval)
	}
	// And long enough to cover the scheduled delay itself, or the guard would
	// lift while the machine is still counting down.
	if powerActionPendingWindow <= 2*time.Minute {
		t.Errorf("powerActionPendingWindow (%s) barely covers the 60 s delay",
			powerActionPendingWindow)
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

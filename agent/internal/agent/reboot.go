package agent

import (
	"errors"
	"fmt"
	"sync"
	"time"

	"tiai/agent/internal/collector"
	"tiai/agent/internal/logging"
)

// Rationing the restart — the one command in the catalogue whose effect
// outlives the agent process that ran it, and the only one that can cost a user
// their work.
//
// The console already asks for a confirmation, and the server refuses to queue
// a second restart while one is still open. Neither of those runs on the
// machine being restarted, which is why this exists as well: the guard that
// matters is the one inside the signed binary, where a mistake in the console,
// a duplicated queue or a compromised server cannot reach it. It is the same
// reasoning as the closed command catalogue — the agent decides what it will
// actually do.

const (
	// minRebootInterval is the floor between two restarts of the same machine.
	//
	// It is measured against the machine's *uptime* as much as against this
	// process's memory, and that is the point: an agent that only remembered
	// its own restarts would forget every one of them at the moment it matters
	// most, since the restart takes the process with it. A queue that kept
	// re-offering a restart would then loop the poste indefinitely, each boot
	// wiping the evidence of the last.
	minRebootInterval = 10 * time.Minute

	// rebootPendingWindow is how long a scheduled restart blocks the rest of
	// the catalogue (see restartPending).
	//
	// Bounded rather than permanent because a restart can be called off:
	// `shutdown /a` from a local administrator cancels it, and an agent that
	// waited for a machine that is never going down would refuse every command
	// for the rest of its life. Comfortably past the 60 s delay plus the time
	// Windows takes to actually begin shutting down, and self-healing after.
	rebootPendingWindow = 5 * time.Minute
)

// errRebootTooSoon is returned to the console instead of restarting. A failure
// and not a silent success: an administrator who asked for a restart must be
// told it did not happen, and why.
var errRebootTooSoon = errors.New("redémarrage refusé")

// rebootGuard holds what the agent knows about restarts of this machine.
type rebootGuard struct {
	mu sync.Mutex
	// scheduled is when this process last got a restart accepted by Windows.
	// Zero means none since the agent started — which, after a restart, is the
	// normal state and exactly why uptime is consulted too.
	scheduled time.Time
	// uptime is injected so the rules can be tested without owning a machine.
	// nil means the real one.
	uptime func() (time.Duration, error)
}

func (g *rebootGuard) readUptime() (time.Duration, error) {
	if g.uptime != nil {
		return g.uptime()
	}
	return collector.Uptime()
}

// allow reports whether a restart may be scheduled now, and says why not
// otherwise. The message is read by an administrator in the console, so it
// names the delay rather than the rule.
func (g *rebootGuard) allow(now time.Time) error {
	g.mu.Lock()
	defer g.mu.Unlock()

	if !g.scheduled.IsZero() {
		if since := now.Sub(g.scheduled); since < minRebootInterval {
			return fmt.Errorf(
				"%w : un redémarrage a déjà été programmé sur ce poste il y a %s "+
					"(délai minimum %s)",
				errRebootTooSoon, humanAge(since), humanAge(minRebootInterval))
		}
	}

	// A read failure is *not* a refusal. This is a rationing rule, not a
	// security boundary: refusing every restart on a machine whose kernel32
	// call misbehaves would break the feature to enforce a courtesy. The
	// process-local check above still stands.
	up, err := g.readUptime()
	if err != nil {
		logging.Debugf("agent: uptime unavailable, reboot rationing falls back to process memory: %v", err)
		return nil
	}
	if up < minRebootInterval {
		return fmt.Errorf(
			"%w : ce poste a démarré il y a %s (délai minimum %s entre deux redémarrages)",
			errRebootTooSoon, humanAge(up), humanAge(minRebootInterval))
	}
	return nil
}

// markScheduled records that Windows accepted a restart.
func (g *rebootGuard) markScheduled(now time.Time) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.scheduled = now
}

// restartPending reports whether a restart is due imminently.
//
// The reason the guard is consulted by *every* command and not only by the
// restart: the worker runs commands one at a time, so a long command queued
// after a restart cannot start before it — but a restart queued *before* one
// returns in milliseconds, and the machine then goes down sixty seconds into a
// dism that is rewriting the component store. Ordering protects one direction
// only; this protects the other.
func (g *rebootGuard) restartPending(now time.Time) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.scheduled.IsZero() {
		return false
	}
	return now.Sub(g.scheduled) < rebootPendingWindow
}

// humanAge renders a duration the way the console message needs it.
//
// Not time.Duration.String(): "il y a 3 min" is what an administrator reads,
// "il y a 3m12.418s" is what a log reads — and these messages land in the
// command history of a French console, beside the maintenance verdicts.
// Truncated rather than rounded, so an age never reads as longer than it is
// next to a minimum it has not actually reached.
func humanAge(d time.Duration) string {
	switch {
	case d < time.Minute:
		return fmt.Sprintf("%d s", int(d.Seconds()))
	case d < time.Hour:
		return fmt.Sprintf("%d min", int(d.Minutes()))
	default:
		return fmt.Sprintf("%d h", int(d.Hours()))
	}
}

package agent

import (
	"errors"
	"fmt"
	"sync"
	"time"

	"tiai/agent/internal/collector"
	"tiai/agent/internal/logging"
)

// Rationing the power actions — the two commands in the catalogue whose effect
// outlives the agent process that ran them, and the only ones that can cost a
// user their work.
//
// The console already asks for a confirmation, and the server refuses to queue
// a second restart while one is still open. Neither of those runs on the
// machine being taken down, which is why this exists as well: the guard that
// matters is the one inside the signed binary, where a mistake in the console,
// a duplicated queue or a compromised server cannot reach it. It is the same
// reasoning as the closed command catalogue — the agent decides what it will
// actually do.
//
// One guard for both, not one each: what is being rationed is the machine going
// down, and a poste that has just restarted must no more be stopped than
// restarted again. The shutdown makes that argument sharper than the restart
// ever did — the server can now wake a poste with a magic packet, so a stale
// `shutdown` still sitting in the queue would meet the machine it just woke and
// switch it straight back off, on a loop nobody is watching.

const (
	// minPowerActionInterval is the floor between two power actions on the same
	// machine.
	//
	// It is measured against the machine's *uptime* as much as against this
	// process's memory, and that is the point: an agent that only remembered
	// its own restarts would forget every one of them at the moment it matters
	// most, since the restart takes the process with it. A queue that kept
	// re-offering a restart would then loop the poste indefinitely, each boot
	// wiping the evidence of the last.
	minPowerActionInterval = 10 * time.Minute

	// powerActionPendingWindow is how long a scheduled restart or shutdown
	// blocks the rest of the catalogue (see pending).
	//
	// Bounded rather than permanent because either can be called off:
	// `shutdown /a` from a local administrator cancels it, and an agent that
	// waited for a machine that is never going down would refuse every command
	// for the rest of its life. Comfortably past the 60 s delay plus the time
	// Windows takes to actually begin shutting down, and self-healing after.
	powerActionPendingWindow = 5 * time.Minute
)

// The two operations, named as the console names them. These strings are read
// by an administrator in the command history, so a refusal says "un arrêt" or
// "un redémarrage" rather than quoting a command type.
const (
	actionReboot   = "redémarrage"
	actionShutdown = "arrêt"
)

// errPowerActionTooSoon is returned to the console instead of taking the
// machine down. A failure and not a silent success: an administrator who asked
// for a restart must be told it did not happen, and why.
var errPowerActionTooSoon = errors.New("opération refusée")

// powerGuard holds what the agent knows about this machine going down.
type powerGuard struct {
	mu sync.Mutex
	// scheduled is when this process last got a power action accepted by
	// Windows, and kind is which one. Zero means none since the agent started —
	// which, after a restart, is the normal state and exactly why uptime is
	// consulted too.
	scheduled time.Time
	kind      string
	// uptime is injected so the rules can be tested without owning a machine.
	// nil means the real one.
	uptime func() (time.Duration, error)
}

func (g *powerGuard) readUptime() (time.Duration, error) {
	if g.uptime != nil {
		return g.uptime()
	}
	return collector.Uptime()
}

// allow reports whether a power action may be scheduled now, and says why not
// otherwise. The message is read by an administrator in the console, so it
// names the delay rather than the rule.
func (g *powerGuard) allow(now time.Time) error {
	g.mu.Lock()
	defer g.mu.Unlock()

	if !g.scheduled.IsZero() {
		if since := now.Sub(g.scheduled); since < minPowerActionInterval {
			return fmt.Errorf(
				"%w : un %s a déjà été programmé sur ce poste il y a %s "+
					"(délai minimum %s)",
				errPowerActionTooSoon, g.kind, humanAge(since),
				humanAge(minPowerActionInterval))
		}
	}

	// A read failure is *not* a refusal. This is a rationing rule, not a
	// security boundary: refusing every restart on a machine whose kernel32
	// call misbehaves would break the feature to enforce a courtesy. The
	// process-local check above still stands.
	up, err := g.readUptime()
	if err != nil {
		logging.Debugf("agent: uptime unavailable, power rationing falls back to process memory: %v", err)
		return nil
	}
	if up < minPowerActionInterval {
		return fmt.Errorf(
			"%w : ce poste a démarré il y a %s (délai minimum %s avant de l'arrêter "+
				"ou de le redémarrer à nouveau)",
			errPowerActionTooSoon, humanAge(up), humanAge(minPowerActionInterval))
	}
	return nil
}

// markScheduled records that Windows accepted a power action, and which one.
func (g *powerGuard) markScheduled(now time.Time, kind string) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.scheduled = now
	g.kind = kind
}

// pending reports whether the machine is due to go down imminently, and as
// what. The empty string means nothing is pending.
//
// The reason the guard is consulted by *every* command and not only by the two
// power ones: the worker runs commands one at a time, so a long command queued
// after a restart cannot start before it — but a restart queued *before* one
// returns in milliseconds, and the machine then goes down sixty seconds into a
// dism that is rewriting the component store. Ordering protects one direction
// only; this protects the other.
func (g *powerGuard) pending(now time.Time) string {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.scheduled.IsZero() {
		return ""
	}
	if now.Sub(g.scheduled) >= powerActionPendingWindow {
		return ""
	}
	return g.kind
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

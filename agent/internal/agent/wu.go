package agent

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"tiai/agent/internal/collector"
	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
)

// wuFirstCollectDelay keeps the first search off the boot path: a machine
// starting up has better things to do than evaluate a thousand applicability
// rules while a user waits for their session. Short enough that a poste enrolled
// today still appears in the console with its updates the same morning.
const wuFirstCollectDelay = 2 * time.Minute

// wuCache holds the last Windows Update reading between the slow cycle that
// produces it and the heartbeat that ships it.
//
// The block is attached to a heartbeat only when it holds something the server
// has not acknowledged yet: a WU state is a few dozen updates with their titles,
// and re-sending an unchanged one every 60 seconds would multiply the parc's
// heartbeat payload for no new information — while re-writing the same rows
// server-side on every poll.
//
// "Acknowledged" is tracked with a generation counter rather than a boolean,
// and that is the whole point of the type. A collection finishing *between* the
// moment a heartbeat picks up its payload and the moment that heartbeat
// succeeds must not be marked as sent: with a flag it would be, and the fresh
// reading would then sit in the cache until the next cycle six hours later.
type wuCache struct {
	mu    sync.Mutex
	state *models.WUState
	// gen increments on every store; sentGen is the last generation the server
	// acknowledged. Equal means there is nothing new to send.
	gen     uint64
	sentGen uint64
}

// store records a fresh reading, making it pending again.
func (c *wuCache) store(state *models.WUState) {
	if state == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state = state
	c.gen++
}

// pending returns the state to attach to the next heartbeat and the generation
// to acknowledge afterwards, or (nil, 0) when the server is already up to date.
func (c *wuCache) pending() (*models.WUState, uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state == nil || c.gen == c.sentGen {
		return nil, 0
	}
	return c.state, c.gen
}

// markSent acknowledges a generation after a successful heartbeat. A newer
// reading stored in the meantime keeps the cache pending, which is exactly the
// race the counter exists for.
func (c *wuCache) markSent(gen uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if gen > c.sentGen {
		c.sentGen = gen
	}
}

// wuLoop collects the Windows Update state on its own slow cycle.
//
// A goroutine of its own rather than a branch of the poll loop: one search takes
// minutes, and pollOnce must stay short enough to keep the 60 s heartbeat — the
// same reason commands execute on the worker.
func (a *Agent) wuLoop(ctx context.Context) {
	defer a.wg.Done()

	interval := time.Duration(a.cfg.WUCollectIntervalSeconds) * time.Second
	timer := time.NewTimer(wuFirstCollectDelay)
	defer timer.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-timer.C:
		}
		a.collectWU(ctx)
		timer.Reset(interval)
	}
}

// collectWU refreshes the cache, serialised against every other WUA operation.
//
// A failure is logged and nothing else: the block is simply not attached to the
// next heartbeat, the server keeps what it had, and the cycle tries again. A
// machine whose Windows Update service is broken must still report its Defender
// state, its session and its address — and still pick up its commands.
func (a *Agent) collectWU(ctx context.Context) {
	a.wuOp.Lock()
	defer a.wuOp.Unlock()
	if ctx.Err() != nil {
		return
	}

	start := time.Now()
	state, err := collector.ReadWUState(ctx)
	if err != nil {
		log.Printf("agent: windows update state: %v", err)
		return
	}
	a.wu.store(state)
	logging.Debugf("agent: windows update: %d pending update(s) in %s",
		len(state.Pending), time.Since(start).Round(time.Second))
}

// runWUScan forces a collection and reports what it found.
//
// Its whole value is immediacy: an administrator who has just approved a KB on
// the WSUS server does not want to wait out the six-hour cycle to see the parc
// react. The refreshed cache rides the next heartbeat, seconds later.
func (a *Agent) runWUScan(ctx context.Context) (string, error) {
	a.wuOp.Lock()
	defer a.wuOp.Unlock()

	state, err := collector.ReadWUState(ctx)
	if err != nil {
		return "", err
	}
	a.wu.store(state)
	return fmt.Sprintf("%d mise(s) à jour en attente.", len(state.Pending)), nil
}

// runWUReset moves the Windows Update store aside — the repair for a poste
// whose updates no longer search, download or install.
//
// Under the same lock as everything else that touches Windows Update, and this
// is the operation the lock matters most for: renaming SoftwareDistribution
// while a search or an install is running is precisely how a machine ends up
// with a half-written update store, and the six-hourly collection *will*
// eventually land on top of a reset otherwise.
//
// The cache is deliberately left alone afterwards. What the reset discards is
// the store, not the truth: the updates this machine is missing are still
// missing, so the pending list the console shows stays correct. The two
// timestamps beside it come from the Automatic Updates results in the
// registry, which the reset does not touch either. The next cycle — or a
// wu_scan, which is what the command's own output tells the administrator to
// run — re-reads all of it.
func (a *Agent) runWUReset(ctx context.Context) (string, error) {
	a.wuOp.Lock()
	defer a.wuOp.Unlock()

	return collector.RunWUReset(ctx)
}

// runWUInstall installs the pending updates, drivers included or not.
//
// The state is re-read afterwards whatever the outcome, and that is deliberate:
// a partial install leaves the machine in a state neither the previous reading
// nor the install summary describes, and the console showing updates that are
// now installed would be worse than showing none. The refreshed reading — and
// with it "restart required", which only becomes true here — reaches the console
// on the next heartbeat, a minute later.
func (a *Agent) runWUInstall(ctx context.Context, includeDrivers bool) (string, error) {
	a.wuOp.Lock()
	defer a.wuOp.Unlock()

	timeout := time.Duration(a.cfg.WUInstallTimeoutSeconds) * time.Second
	output, err := collector.RunWUInstall(ctx, includeDrivers, timeout)

	if state, rerr := collector.ReadWUState(ctx); rerr == nil {
		a.wu.store(state)
	} else if ctx.Err() == nil {
		// Not fatal to the command: the install is what was asked for, and its
		// own verdict stands. The next cycle re-reads the state.
		log.Printf("agent: windows update state after install: %v", rerr)
	}
	return output, err
}

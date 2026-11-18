package agent

import (
	"context"
	"log"
	"time"

	"tiai/agent/internal/collector"
	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// wuFirstCollectDelay keeps the first search off the boot path: a machine
// starting up has better things to do than evaluate a thousand applicability
// rules while a user waits for their session. Short enough that a poste enrolled
// today still appears in the console with its updates the same morning.
const wuFirstCollectDelay = 2 * time.Minute

// wuCache is the Windows Update slow-cycle cache. The mechanism — and the
// generation counter that makes it correct — lives in cache.go, shared with the
// inventory cycle.
type wuCache = stateCache[models.WUState]

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
func (a *Agent) runWUScan(ctx context.Context) (msg.Message, error) {
	a.wuOp.Lock()
	defer a.wuOp.Unlock()

	state, err := collector.ReadWUState(ctx)
	if err != nil {
		return msg.Message{}, err
	}
	a.wu.store(state)
	return msg.New("wu.scan", msg.Params{"count": len(state.Pending)}), nil
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

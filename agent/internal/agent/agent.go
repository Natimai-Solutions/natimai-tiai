// Package agent runs the polling loop: enroll once, then heartbeat on an
// interval, executing any commands the server hands back. On transient server
// failures it backs off; command results that can't be delivered are queued
// locally and replayed (plan §2.9).
//
// Commands run on a separate worker goroutine, one at a time. A Defender full
// scan takes tens of minutes and executing it inline would freeze heartbeats
// for its whole duration, so the poll loop only ever hands work off.
package agent

import (
	"context"
	"fmt"
	"log"
	"path/filepath"
	"sync"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/collector"
	"tiai/agent/internal/config"
	"tiai/agent/internal/identity"
	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
	"tiai/agent/internal/queue"
	"tiai/agent/internal/sysinfo"
)

// Version is the agent version reported on enroll/heartbeat. A `var`, not a
// `const`: release builds overwrite it from the git tag via
// `-ldflags "-X tiai/agent/internal/agent.Version=..."` (cf. .github/workflows/release.yml).
// The literal below is only what a plain `go build` produces.
var Version = "0.1.0"

// maxPendingCommands bounds the in-memory backlog handed to the worker. Beyond
// it we simply stop accepting: the command stays pending server-side and comes
// back on a later heartbeat.
const maxPendingCommands = 16

// Agent owns the runtime state and the polling loop.
type Agent struct {
	cfg      *config.Config
	cfgPath  string
	client   *api.Client
	identity identity.Identity
	host     sysinfo.Info
	queue    *queue.Queue

	// Commands execute off the polling loop: a Defender full scan blocks for
	// tens of minutes, and running it inline would stall heartbeats long enough
	// for the server to mark the machine offline.
	commands chan models.Command
	mu       sync.Mutex
	running  map[string]struct{} // command ids queued or executing
	wg       sync.WaitGroup
}

// New creates an agent from config.
func New(cfg *config.Config, cfgPath string) *Agent {
	timeout := time.Duration(cfg.RequestTimeoutSeconds) * time.Second
	return &Agent{
		cfg:     cfg,
		cfgPath: cfgPath,
		client:  api.New(cfg.APIBaseURL, cfg.AuthToken, timeout),
	}
}

// Run blocks, polling until the context is cancelled.
func (a *Agent) Run(ctx context.Context) error {
	dir := filepath.Dir(a.cfgPath)

	id, err := identity.Resolve(dir, a.cfg.MachineUUID)
	if err != nil {
		return fmt.Errorf("resolve identity: %w", err)
	}
	a.identity = id
	a.host = sysinfo.Collect()
	log.Printf("agent: identity %s (hostname %s)", id.MachineUUID, a.host.Hostname)
	if !a.cfg.ReportsUsername() {
		// Traced once so the setting is auditable from the log. The name itself
		// is never logged, at any level.
		log.Printf("agent: logged-on username reporting disabled (presence only)")
	}

	q, err := queue.New(filepath.Join(dir, "queue"), a.cfg.QueueMaxItems)
	if err != nil {
		return fmt.Errorf("open local queue: %w", err)
	}
	a.queue = q

	// One worker, not a pool: Defender serialises scans itself, so running two
	// at once only yields "a scan is already in progress" failures.
	a.commands = make(chan models.Command, maxPendingCommands)
	a.running = make(map[string]struct{})
	a.wg.Add(1)
	go a.worker(ctx)
	defer a.wg.Wait()

	base := time.Duration(a.cfg.HeartbeatIntervalSeconds) * time.Second
	maxBackoff := time.Duration(a.cfg.BackoffMaxSeconds) * time.Second
	wait := base

	for {
		if err := a.tick(ctx); err != nil {
			wait = nextBackoff(wait, maxBackoff)
			log.Printf("agent: tick failed, retrying in %s: %v", wait, err)
		} else {
			wait = base
		}

		select {
		case <-ctx.Done():
			return nil
		case <-time.After(wait):
		}
	}
}

// tick enrolls if needed, then runs one heartbeat cycle. A returned error means
// the server was unreachable and the caller should back off.
func (a *Agent) tick(ctx context.Context) error {
	if err := a.ensureEnrolled(ctx); err != nil {
		return err
	}
	return a.pollOnce(ctx)
}

// ensureEnrolled performs trust-on-first-use enrollment if no token is stored.
func (a *Agent) ensureEnrolled(ctx context.Context) error {
	if a.cfg.AuthToken != "" {
		return nil
	}
	fp := a.identity.Fingerprint
	resp, err := a.client.Enroll(ctx, a.cfg.EnrollmentSecret, models.EnrollRequest{
		MachineUUID:  a.identity.MachineUUID,
		Hostname:     a.host.Hostname,
		Domain:       a.host.Domain,
		OSVersion:    a.host.OSVersion,
		AgentVersion: Version,
		Fingerprint:  &fp,
	})
	if err != nil {
		return err
	}
	a.cfg.AuthToken = resp.Token
	a.client.SetToken(resp.Token)
	if err := config.SaveToken(filepath.Dir(a.cfgPath), resp.Token); err != nil {
		return fmt.Errorf("persist token: %w", err)
	}
	log.Printf("agent: enrolled as machine %s", resp.MachineID)
	return nil
}

// pollOnce flushes queued results, sends a heartbeat, and executes returned
// commands. It returns an error only when the heartbeat itself fails.
func (a *Agent) pollOnce(ctx context.Context) error {
	a.flushQueue(ctx)

	state, err := collector.ReadDefenderState(ctx)
	if err != nil {
		log.Printf("agent: defender state: %v", err)
	}
	threats, err := collector.ReadThreats(ctx)
	if err != nil {
		log.Printf("agent: defender threats: %v", err)
	}
	// On failure sess stays nil, the block is omitted, and the server keeps the
	// last known session rather than being told "nobody" on no evidence.
	sess, err := collector.ReadSessionState(ctx, a.cfg.ReportsUsername())
	if err != nil {
		log.Printf("agent: session state: %v", err)
	}

	fp := a.identity.Fingerprint
	resp, err := a.client.Heartbeat(ctx, models.HeartbeatRequest{
		Hostname:     a.host.Hostname,
		Domain:       a.host.Domain,
		OSVersion:    a.host.OSVersion,
		AgentVersion: Version,
		Defender:     state,
		Session:      sess,
		Fingerprint:  &fp,
		Threats:      threats,
	})
	if err != nil {
		return err
	}
	if n := len(resp.Commands); n > 0 {
		log.Printf("agent: heartbeat ok, %d command(s) to run", n)
	} else {
		logging.Debugf("agent: heartbeat ok, no pending command")
	}
	for _, cmd := range resp.Commands {
		a.accept(cmd)
	}
	return nil
}

// accept hands a command to the worker without blocking the polling loop.
// Duplicates are dropped: the server keeps re-offering a command until it gets
// a result, which for a full scan spans many heartbeats.
func (a *Agent) accept(cmd models.Command) {
	a.mu.Lock()
	if _, dup := a.running[cmd.ID]; dup {
		a.mu.Unlock()
		logging.Debugf("agent: %s (id %s) already in flight, ignoring", cmd.Type, cmd.ID)
		return
	}
	a.running[cmd.ID] = struct{}{}
	a.mu.Unlock()

	select {
	case a.commands <- cmd:
	default:
		// Backlog full — forget it so a later heartbeat can re-offer it.
		a.release(cmd.ID)
		log.Printf("agent: backlog full (%d), deferring %s (id %s)",
			maxPendingCommands, cmd.Type, cmd.ID)
	}
}

func (a *Agent) release(id string) {
	a.mu.Lock()
	delete(a.running, id)
	a.mu.Unlock()
}

// worker executes accepted commands one at a time until the context is
// cancelled. On shutdown, commands still waiting are abandoned rather than run
// with a dead context — the server re-offers them at the next start.
func (a *Agent) worker(ctx context.Context) {
	defer a.wg.Done()
	for {
		select {
		case <-ctx.Done():
			return
		case cmd := <-a.commands:
			if ctx.Err() != nil {
				return
			}
			a.execute(ctx, cmd)
			a.release(cmd.ID)
		}
	}
}

// execute runs a command and reports its result, queuing the result locally if
// it can't be delivered right now.
func (a *Agent) execute(ctx context.Context, cmd models.Command) {
	var run func(context.Context) (string, error)
	switch cmd.Type {
	case "quick_scan":
		run = collector.RunQuickScan
	case "full_scan":
		run = collector.RunFullScan
	case "update_signatures":
		run = collector.UpdateSignatures
	default:
		log.Printf("agent: unknown command type %q (id %s), ignoring", cmd.Type, cmd.ID)
		return
	}

	log.Printf("agent: executing %s (id %s)", cmd.Type, cmd.ID)
	start := time.Now()
	output, err := run(ctx)

	res := models.CommandResult{Status: "succeeded", Output: output}
	if err != nil {
		res.Status = "failed"
		res.Error = err.Error()
		log.Printf("agent: %s (id %s) failed after %s: %v",
			cmd.Type, cmd.ID, time.Since(start).Round(time.Second), err)
	} else {
		log.Printf("agent: %s (id %s) succeeded in %s",
			cmd.Type, cmd.ID, time.Since(start).Round(time.Second))
	}
	if perr := a.client.PostResult(ctx, cmd.ID, res); perr != nil {
		log.Printf("agent: post result failed, queuing %s: %v", cmd.ID, perr)
		if qerr := a.queue.Enqueue(queue.Item{CommandID: cmd.ID, Result: res}); qerr != nil {
			log.Printf("agent: queue result %s: %v", cmd.ID, qerr)
		}
	}
}

// flushQueue replays queued command results oldest-first, stopping at the first
// delivery failure (the server is still down — retry next poll).
func (a *Agent) flushQueue(ctx context.Context) {
	for {
		item, path, err := a.queue.Peek()
		if err != nil {
			log.Printf("agent: queue peek: %v", err)
			return
		}
		if item == nil {
			return
		}
		if err := a.client.PostResult(ctx, item.CommandID, item.Result); err != nil {
			return
		}
		log.Printf("agent: delivered queued result for command %s", item.CommandID)
		if err := a.queue.Remove(path); err != nil {
			log.Printf("agent: queue remove: %v", err)
			return
		}
	}
}

// nextBackoff doubles the wait up to a cap.
func nextBackoff(cur, max time.Duration) time.Duration {
	n := cur * 2
	if n > max {
		return max
	}
	return n
}

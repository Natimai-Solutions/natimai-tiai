// Package agent runs the polling loop: enroll once, then heartbeat on an
// interval, executing any commands the server hands back. On transient server
// failures it backs off; command results that can't be delivered are queued
// locally and replayed (plan §2.9).
package agent

import (
	"context"
	"fmt"
	"log"
	"path/filepath"
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

// Version is the agent version reported on enroll/heartbeat.
const Version = "0.1.0"

// Agent owns the runtime state and the polling loop.
type Agent struct {
	cfg      *config.Config
	cfgPath  string
	client   *api.Client
	identity identity.Identity
	host     sysinfo.Info
	queue    *queue.Queue
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

	q, err := queue.New(filepath.Join(dir, "queue"), a.cfg.QueueMaxItems)
	if err != nil {
		return fmt.Errorf("open local queue: %w", err)
	}
	a.queue = q

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

	fp := a.identity.Fingerprint
	resp, err := a.client.Heartbeat(ctx, models.HeartbeatRequest{
		Hostname:     a.host.Hostname,
		Domain:       a.host.Domain,
		OSVersion:    a.host.OSVersion,
		AgentVersion: Version,
		Defender:     state,
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
		a.execute(ctx, cmd)
	}
	return nil
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

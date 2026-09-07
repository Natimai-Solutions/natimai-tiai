// Package service installs and runs the Tiai agent as a Windows service.
package service

import (
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"tiai/agent/internal/agent"
	"tiai/agent/internal/config"
	"tiai/agent/internal/logging"
)

const (
	ServiceName        = "TiaiAgent"
	ServiceDisplayName = "Tiai Agent"
	ServiceDescription = "Reports Microsoft Defender state to the Tiai server and executes its commands."

	// stopTimeout bounds the wait for the service to report Stopped. Shutdown
	// does wait for the command worker, but a Defender scan in flight dies with
	// its PowerShell process when the context is cancelled (exec.CommandContext),
	// so this is a safety net rather than the normal path.
	stopTimeout = 30 * time.Second

	// startRetryDelay and startRetryMax pace the retries of a service that
	// cannot start its agent yet.
	//
	// They exist because the alternative — the one this replaced — is a service
	// that stops for good. A poste whose ApiBaseURL has not been pushed yet (the
	// MSI installs and starts the service, the GPO writes the registry value at
	// the next boot), a token.dat truncated by a power cut, a WMI service not
	// up yet on a slow machine: each of those used to end the process, the SCM
	// spent its two recovery restarts inside the minute, and the poste was then
	// left with a service Stopped, its start type still saying Automatic, and
	// nothing anywhere to say why. Retrying from inside the service means the
	// same poste heals itself the moment the missing piece arrives.
	startRetryDelay = 1 * time.Minute
	startRetryMax   = 15 * time.Minute

	// stopProgressInterval and stopGraceTimeout govern what the SCM is told
	// while the agent unwinds.
	//
	// A stop is not instant: the poll loop, the command worker, the Windows
	// Update cycle and the inventory cycle are all waited for, and a WMI query
	// or a WUA search already in flight is not cancellable. A service that goes
	// silent during that is a service the SCM eventually declares hung — and the
	// GPO script, which stops the service to replace its binary, then fails and
	// leaves the poste with nothing running. So: a checkpoint every second with
	// a wait hint that covers it, and a bound past which we report Stopped and
	// let the process exit rather than hang the SCM.
	stopProgressInterval = 1 * time.Second
	stopGraceTimeout     = 90 * time.Second
)

type tiaiService struct {
	cfgPath string
}

// Execute is the SCM entry point: it runs the polling loop under a context
// cancelled on Stop/Shutdown.
func (s *tiaiService) Execute(_ []string, r <-chan svc.ChangeRequest, changes chan<- svc.Status) (bool, uint32) {
	const accepted = svc.AcceptStop | svc.AcceptShutdown
	changes <- svc.Status{State: svc.StartPending}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Running is reported before the configuration is even read, and that is
	// deliberate: runAgent keeps retrying a configuration it cannot use, so the
	// service is genuinely up — waiting on its settings, not failing to start.
	errCh := make(chan error, 1)
	go func() { errCh <- runAgent(ctx, s.cfgPath) }()

	changes <- svc.Status{State: svc.Running, Accepts: accepted}

	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Interrogate:
				changes <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				cancel()
				return waitForStop(errCh, changes)
			}
		case err := <-errCh:
			// runAgent only returns on a cancelled context, so this is the path
			// nothing takes. Logged rather than silently stopped: it is the one
			// case where the service ends and nobody asked it to.
			log.Printf("agent: polling loop ended on its own (%v), stopping the service", err)
			changes <- svc.Status{State: svc.StopPending}
			return false, 1
		}
	}
}

// runAgent loads the configuration and runs the agent, retrying until the
// context is cancelled.
//
// The loop covers both halves of a failed start: a configuration that is not
// usable *yet* (see startRetryDelay) and an agent that could not open what it
// needs — the WMI identity read, the local result queue. Neither is worth
// stopping a monitoring agent over, because a poste whose agent stopped is
// precisely a poste nobody is watching, and nothing on it will say so.
func runAgent(ctx context.Context, cfgPath string) error {
	wait := startRetryDelay
	for {
		cfg, err := config.Load(cfgPath)
		if err == nil {
			logging.SetLevel(cfg.LogLevel)
			log.Printf("agent: v%s starting under the SCM (log level %s)",
				agent.Version, cfg.LogLevel)
			err = agent.New(cfg, cfgPath).Run(ctx)
			if err == nil {
				return nil // clean stop: the context was cancelled
			}
			wait = startRetryDelay // it ran; the next failure starts over
		}
		if ctx.Err() != nil {
			return nil
		}
		log.Printf("agent: cannot run yet (%v); retrying in %s", err, wait)
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(wait):
		}
		if wait *= 2; wait > startRetryMax {
			wait = startRetryMax
		}
	}
}

// waitForStop keeps the SCM informed while the agent unwinds.
//
// Checkpoint and wait hint together are the protocol: each checkpoint says
// "still working", each hint says "give me this much longer". Without them the
// SCM applies its own patience to a stop that legitimately takes longer than a
// heartbeat interval, and kills the process — or, worse for the parc, reports
// the stop as failed to whoever asked for it.
func waitForStop(errCh <-chan error, changes chan<- svc.Status) (bool, uint32) {
	hint := uint32(stopGraceTimeout / time.Millisecond)
	checkpoint := uint32(1)
	changes <- svc.Status{State: svc.StopPending, CheckPoint: checkpoint, WaitHint: hint}

	ticker := time.NewTicker(stopProgressInterval)
	defer ticker.Stop()
	deadline := time.After(stopGraceTimeout)

	for {
		select {
		case <-errCh:
			return false, 0
		case <-ticker.C:
			checkpoint++
			changes <- svc.Status{State: svc.StopPending, CheckPoint: checkpoint, WaitHint: hint}
		case <-deadline:
			// Something that cannot be cancelled — a WMI query, a WUA search —
			// is still in flight. Reporting Stopped and letting the process go
			// beats holding the SCM (and a shutting-down machine) on it.
			log.Printf("agent: still unwinding after %s, reporting the service stopped", stopGraceTimeout)
			return false, 0
		}
	}
}

// IsWindowsService reports whether the process was launched by the SCM.
func IsWindowsService() (bool, error) { return svc.IsWindowsService() }

// Run hands control to the SCM (used when started as a service).
//
// It takes the config *path* and not a loaded config: the configuration is read
// inside the service, where a failure to read it can be retried instead of
// killing the process before its log file is even open.
func Run(cfgPath string) error {
	return svc.Run(ServiceName, &tiaiService{cfgPath: cfgPath})
}

// Install registers the service to auto-start and run `run --config <path>`.
func Install(cfgPath string) error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("executable path: %w", err)
	}
	if exePath, err = filepath.Abs(exePath); err != nil {
		return fmt.Errorf("abs path: %w", err)
	}
	if cfgPath, err = filepath.Abs(cfgPath); err != nil {
		return fmt.Errorf("abs config path: %w", err)
	}

	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect service manager: %w", err)
	}
	defer m.Disconnect()

	if s, err := m.OpenService(ServiceName); err == nil {
		s.Close()
		return fmt.Errorf("service %s already exists", ServiceName)
	}

	s, err := m.CreateService(ServiceName, exePath, mgr.Config{
		DisplayName:  ServiceDisplayName,
		Description:  ServiceDescription,
		StartType:    mgr.StartAutomatic,
		ErrorControl: mgr.ErrorNormal,
	}, "run", "--config", cfgPath)
	if err != nil {
		return fmt.Errorf("create service: %w", err)
	}
	defer s.Close()

	if err := setRecoveryActions(s); err != nil {
		fmt.Printf("warning: could not set recovery actions: %v\n", err)
	}
	fmt.Printf("Service %s installed.\n", ServiceName)
	return nil
}

// setRecoveryActions makes the SCM bring the service back after a crash.
//
// The third action is a restart and not NoAction, which is the whole point of
// the change: the SCM repeats the *last* action for every failure beyond the
// third, so "restart, restart, nothing" means a service that fails three times
// inside its reset period stays Stopped until a human notices — start type
// Automatic, no error dialog, nothing in the console but a poste that went
// quiet. Two minutes is the third delay: long enough to sit out whatever kept
// failing (a boot storm, a WMI service not up yet), short enough that nobody
// has to drive to the poste.
func setRecoveryActions(s *mgr.Service) error {
	return s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 15 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 30 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 2 * time.Minute},
	}, 86400)
}

// Repair re-applies to an already-installed service the settings a fresh
// install would give it: automatic start and the recovery actions above.
//
// It exists for the postes installed by an earlier version, which carry the old
// "restart, restart, nothing" and would otherwise keep it for the life of the
// machine — an upgrade replaces the binary, never the SCM's idea of what to do
// when it dies.
func Repair() error {
	return withService(func(s *mgr.Service) error {
		cfg, err := s.Config()
		if err != nil {
			return fmt.Errorf("read service config: %w", err)
		}
		if cfg.StartType != mgr.StartAutomatic {
			cfg.StartType = mgr.StartAutomatic
			if err := s.UpdateConfig(cfg); err != nil {
				return fmt.Errorf("set automatic start: %w", err)
			}
		}
		if err := setRecoveryActions(s); err != nil {
			return fmt.Errorf("set recovery actions: %w", err)
		}
		fmt.Printf("Service %s: automatic start and restart-on-failure re-applied.\n", ServiceName)
		return nil
	})
}

// Uninstall stops the service, then removes it.
//
// Stopping first is not a courtesy: deleting a running service only marks it
// for deletion, and it stays registered until it stops or the machine reboots —
// so a later install fails on a service that looks gone. Uninstall followed by
// install must work in one pass.
func Uninstall() error {
	return withService(func(s *mgr.Service) error {
		if err := stopAndWait(s); err != nil {
			return fmt.Errorf("stop before uninstall: %w", err)
		}
		if err := s.Delete(); err != nil {
			return fmt.Errorf("delete service: %w", err)
		}
		fmt.Printf("Service %s uninstalled.\n", ServiceName)
		return nil
	})
}

// Start starts the installed service.
func Start() error {
	return withService(func(s *mgr.Service) error {
		if err := s.Start(); err != nil {
			return fmt.Errorf("start service: %w", err)
		}
		fmt.Printf("Service %s started.\n", ServiceName)
		return nil
	})
}

// Stop stops the service and waits for it to terminate.
func Stop() error {
	return withService(func(s *mgr.Service) error {
		if err := stopAndWait(s); err != nil {
			return err
		}
		fmt.Printf("Service %s stopped.\n", ServiceName)
		return nil
	})
}

// stopAndWait stops the service and blocks until it reports Stopped. A service
// that is already stopped (or stopping) is not an error — Control(Stop) on a
// stopped service fails with ERROR_SERVICE_NOT_ACTIVE, which would make an
// otherwise fine `stop` or `uninstall` look broken.
func stopAndWait(s *mgr.Service) error {
	status, err := s.Query()
	if err != nil {
		return fmt.Errorf("query service: %w", err)
	}
	if status.State == svc.Stopped {
		return nil
	}
	if status.State != svc.StopPending {
		if status, err = s.Control(svc.Stop); err != nil {
			return fmt.Errorf("stop service: %w", err)
		}
	}

	deadline := time.Now().Add(stopTimeout)
	for status.State != svc.Stopped {
		if time.Now().After(deadline) {
			return fmt.Errorf("timeout waiting for service to stop")
		}
		time.Sleep(500 * time.Millisecond)
		if status, err = s.Query(); err != nil {
			return fmt.Errorf("query service: %w", err)
		}
	}
	return nil
}

// Status prints the current service state.
func Status() error {
	return withService(func(s *mgr.Service) error {
		st, err := s.Query()
		if err != nil {
			return fmt.Errorf("query service: %w", err)
		}
		fmt.Printf("Service %s: %s\n", ServiceName, stateString(st.State))
		return nil
	})
}

func withService(fn func(*mgr.Service) error) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect service manager: %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(ServiceName)
	if err != nil {
		return fmt.Errorf("open service %s (installed?): %w", ServiceName, err)
	}
	defer s.Close()
	return fn(s)
}

func stateString(state svc.State) string {
	switch state {
	case svc.Stopped:
		return "Stopped"
	case svc.StartPending:
		return "StartPending"
	case svc.StopPending:
		return "StopPending"
	case svc.Running:
		return "Running"
	case svc.ContinuePending:
		return "ContinuePending"
	case svc.PausePending:
		return "PausePending"
	case svc.Paused:
		return "Paused"
	default:
		return "Unknown"
	}
}

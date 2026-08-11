// Package service installs and runs the Tiai agent as a Windows service.
package service

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"

	"tiai/agent/internal/agent"
	"tiai/agent/internal/config"
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
)

type tiaiService struct {
	cfg     *config.Config
	cfgPath string
}

// Execute is the SCM entry point: it runs the polling loop under a context
// cancelled on Stop/Shutdown.
func (s *tiaiService) Execute(_ []string, r <-chan svc.ChangeRequest, changes chan<- svc.Status) (bool, uint32) {
	const accepted = svc.AcceptStop | svc.AcceptShutdown
	changes <- svc.Status{State: svc.StartPending}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	errCh := make(chan error, 1)
	a := agent.New(s.cfg, s.cfgPath)
	go func() { errCh <- a.Run(ctx) }()

	changes <- svc.Status{State: svc.Running, Accepts: accepted}

	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Interrogate:
				changes <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				changes <- svc.Status{State: svc.StopPending}
				cancel()
				<-errCh // wait for the loop to unwind
				return false, 0
			}
		case <-errCh:
			// Agent exited on its own (fatal error) → stop the service.
			changes <- svc.Status{State: svc.StopPending}
			return false, 1
		}
	}
}

// IsWindowsService reports whether the process was launched by the SCM.
func IsWindowsService() (bool, error) { return svc.IsWindowsService() }

// Run hands control to the SCM (used when started as a service).
func Run(cfg *config.Config, cfgPath string) error {
	return svc.Run(ServiceName, &tiaiService{cfg: cfg, cfgPath: cfgPath})
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

	// Restart on failure (15s, then 30s), reset the failure count after 24h.
	if err := s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 15 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 30 * time.Second},
		{Type: mgr.NoAction},
	}, 86400); err != nil {
		fmt.Printf("warning: could not set recovery actions: %v\n", err)
	}
	fmt.Printf("Service %s installed.\n", ServiceName)
	return nil
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

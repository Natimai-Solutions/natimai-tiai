// Command tiai-agent is the Windows endpoint agent: a polling service that
// reports Microsoft Defender state to the Tiai server and runs its commands.
//
// Commands: run / init-config / install / uninstall / start / stop / status /
// version. When started by the Windows Service Control Manager, `run` hands off
// to the service harness; otherwise it runs in the foreground.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"tiai/agent/internal/agent"
	"tiai/agent/internal/config"
	"tiai/agent/internal/logging"
	"tiai/agent/internal/service"
)

func main() {
	if len(os.Args) < 2 {
		printUsage()
		os.Exit(1)
	}

	switch os.Args[1] {
	case "run":
		doRun(os.Args[2:])
	case "init-config":
		doInitConfig(os.Args[2:])
	case "install":
		doInstall(os.Args[2:])
	case "repair":
		fatalIf(service.Repair())
	case "uninstall":
		fatalIf(service.Uninstall())
	case "start":
		fatalIf(service.Start())
	case "stop":
		fatalIf(service.Stop())
	case "status":
		fatalIf(service.Status())
	case "version":
		fmt.Printf("Tiai agent v%s\n", agent.Version)
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", os.Args[1])
		printUsage()
		os.Exit(1)
	}
}

func printUsage() {
	fmt.Println("Tiai agent v" + agent.Version)
	fmt.Println()
	fmt.Println("Usage: tiai-agent <command> [options]")
	fmt.Println()
	fmt.Println("Commands:")
	fmt.Println("  run            Run the polling loop (foreground, or under the SCM)")
	fmt.Println("  init-config    Generate a default config file (optional: registry alone is enough)")
	fmt.Println("  install        Install and register the Windows service")
	fmt.Println("  repair         Re-apply automatic start and restart-on-failure to an installed service")
	fmt.Println("  uninstall      Remove the Windows service")
	fmt.Println("  start          Start the installed service")
	fmt.Println("  stop           Stop the service")
	fmt.Println("  status         Show the service state")
	fmt.Println("  version        Show version")
}

func doRun(args []string) {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	cfgPath := fs.String("config", config.DefaultConfigPath(), "config file path")
	_ = fs.Parse(args)

	// The log file is opened *before* the configuration is read, and that order
	// is the fix for a whole class of silent deaths: under the SCM stderr goes
	// nowhere, so an agent that gave up on its configuration used to leave the
	// service stopped with not one line anywhere saying why. The level is not
	// known yet — it lives in that configuration — so INFO applies until it is,
	// which is exactly the level these messages are logged at.
	closeLog := logging.Setup(filepath.Dir(*cfgPath), "")
	defer closeLog()

	// The config file is optional (registry-only GPO deployments). Say which
	// case we are in: it is the first thing to check when a poste misbehaves.
	source := *cfgPath
	if _, err := os.Stat(*cfgPath); os.IsNotExist(err) {
		source = "registry + defaults, no " + *cfgPath
	}
	log.Printf("agent: v%s starting (config %s)", agent.Version, source)

	// Started by the Service Control Manager → run under the service harness,
	// which loads the configuration itself and keeps retrying one it cannot use
	// rather than ending the process (see service.runAgent).
	if isSvc, _ := service.IsWindowsService(); isSvc {
		if err := service.Run(*cfgPath); err != nil {
			log.Printf("agent: service error: %v", err)
			os.Exit(1)
		}
		return
	}

	// Foreground: a person is watching, so an unusable configuration is said
	// once and the command ends. Retrying belongs to the service alone.
	cfg, err := config.Load(*cfgPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error loading config: %v\n", err)
		os.Exit(1)
	}
	logging.SetLevel(cfg.LogLevel)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	a := agent.New(cfg, *cfgPath)
	fmt.Println("Agent running. Press Ctrl+C to stop.")
	if err := a.Run(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "Agent error: %v\n", err)
		os.Exit(1)
	}
}

func doInitConfig(args []string) {
	fs := flag.NewFlagSet("init-config", flag.ExitOnError)
	cfgPath := fs.String("config", config.DefaultConfigPath(), "config file path")
	apiURL := fs.String("api-url", "https://tiai.natimai.local", "API base URL")
	machineUUID := fs.String("machine-uuid", "", "optional identity override (else auto-resolved: SMBIOS UUID / agent UUID)")
	_ = fs.Parse(args)

	cfg := config.DefaultConfig()
	cfg.APIBaseURL = *apiURL
	cfg.MachineUUID = *machineUUID

	if err := cfg.Save(*cfgPath); err != nil {
		fmt.Fprintf(os.Stderr, "Error saving config: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("Config written to %s\n", *cfgPath)
	fmt.Println("Set enrollment_secret (config or HKLM\\SOFTWARE\\Tiai) and TLS as needed.")
	fmt.Println("Identity is auto-resolved at first run; the token is stored encrypted (DPAPI).")
}

func doInstall(args []string) {
	fs := flag.NewFlagSet("install", flag.ExitOnError)
	cfgPath := fs.String("config", config.DefaultConfigPath(), "config file path")
	_ = fs.Parse(args)
	fatalIf(service.Install(*cfgPath))
}

func fatalIf(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

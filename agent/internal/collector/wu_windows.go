package collector

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"tiai/agent/internal/models"
)

// ReadWUState searches Windows Update and returns what the machine is missing.
//
// Slow by nature — see wuSearchTimeout — which is why the caller runs it on its
// own cycle instead of on the 60 s heartbeat.
func ReadWUState(ctx context.Context) (*models.WUState, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, wuSearchTimeout)
	defer cancel()

	// includeDrivers: the collection always lists everything. Which of them get
	// installed is the console's decision (wu_install vs wu_install_full), and it
	// cannot be a decision at all if the drivers were never reported.
	out, err := runPowerShellJSON(ctx, buildWUScript(wuCollectScript, true))
	if err != nil {
		return nil, wrapWUError(err)
	}
	return parseWUState(out)
}

// RunWUInstall searches, downloads and installs, drivers included or not.
//
// The timeout is a parameter rather than a constant: it is the one WU budget an
// administrator legitimately needs to raise, on a parc behind a slow link where
// a cumulative update is a gigabyte away.
func RunWUInstall(ctx context.Context, includeDrivers bool, timeout time.Duration) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	out, err := runPowerShellJSON(ctx, buildWUScript(wuInstallScript, includeDrivers))
	if err != nil {
		return "", wrapWUError(err)
	}
	return summarizeInstall(out)
}

// runPowerShellJSON runs a script whose value is a single object, and returns it
// as JSON bytes.
//
// A separate wrapper from runPowerShell, for two reasons this collector cannot
// do without. First, the payload must survive intact: runPowerShell pipes
// through Out-String, whose formatter wraps at the host's width and would break
// a JSON document containing update titles longer than that. Here the serialised
// string is written straight to the standard output handle as UTF-8 bytes,
// bypassing the console encoder exactly as runPowerShell does (setting
// [Console]::OutputEncoding throws when no console is attached — the service
// case). Second, streams are kept apart: a warning WUA writes to stderr must not
// end up spliced into the object stdout is carrying.
//
// -Depth 5 covers the deepest shape we emit (object → updates → array of
// objects → array of strings) with room to spare; the default of 2 would
// silently render the nested arrays as type names.
func runPowerShellJSON(ctx context.Context, script string) ([]byte, error) {
	wrapped := "$ErrorActionPreference = 'Stop'; " +
		"$ProgressPreference = 'SilentlyContinue'; " +
		"try { " +
		"$value = & { " + script + " }; " +
		"$json = $value | ConvertTo-Json -Depth 5 -Compress; " +
		"$bytes = [Text.Encoding]::UTF8.GetBytes($json); " +
		"$stdout = [Console]::OpenStandardOutput(); " +
		"$stdout.Write($bytes, 0, $bytes.Length); $stdout.Flush(); " +
		"} catch { " +
		"$msg = [Text.Encoding]::UTF8.GetBytes(($_ | Out-String)); " +
		"$stderr = [Console]::OpenStandardError(); " +
		"$stderr.Write($msg, 0, $msg.Length); $stderr.Flush(); " +
		"exit 1 }"

	cmd := exec.CommandContext(ctx, "powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	if err != nil {
		// Ours (wuSearchTimeout / the configured install budget) versus the
		// service being stopped — two very different things to report.
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, errors.New("délai d'exécution dépassé pour l'opération Windows Update")
		}
		if errors.Is(ctx.Err(), context.Canceled) {
			return nil, errors.New("opération Windows Update interrompue (arrêt de l'agent)")
		}
		detail := strings.TrimSpace(stderr.String())
		if detail == "" {
			detail = strings.TrimSpace(stdout.String())
		}
		return nil, fmt.Errorf("powershell: %w (%s)", err, truncateOutput(detail, maxOutputBytes))
	}

	out := bytes.TrimSpace(stdout.Bytes())
	if len(out) == 0 {
		// A script that exits 0 with nothing to say is a bug in the script, not
		// a machine with no updates: the empty case is still a JSON object.
		return nil, errors.New("powershell: aucune sortie JSON")
	}
	return out, nil
}

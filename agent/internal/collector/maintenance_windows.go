package collector

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

// RunMaintenance executes one catalogue command and returns what the console
// should show. The command type is the *only* thing that came from the network;
// everything actually executed comes from maintenanceCatalogue.
//
// On failure the collected output is returned alongside the error rather than
// dropped: for these tools the output is usually the explanation, and the
// caller stores both (models.CommandResult carries an output and an error).
func RunMaintenance(ctx context.Context, cmdType string) (string, error) {
	spec, ok := maintenanceCatalogue[cmdType]
	if !ok {
		return "", fmt.Errorf("unknown maintenance command %q", cmdType)
	}

	ctx, cancel := context.WithTimeout(ctx, spec.timeout)
	defer cancel()

	if spec.native {
		return runNativeMaintenance(ctx, cmdType)
	}

	raw, code, err := runSystem32(ctx, spec.exe, spec.args...)
	output := truncateOutput(normalizeConsoleOutput(decodeToolOutput(raw, spec.enc)), maxOutputBytes)
	if err != nil {
		return output, err
	}
	return spec.verdict(code, output)
}

// runNativeMaintenance covers the catalogue entries that are not an .exe call.
func runNativeMaintenance(ctx context.Context, cmdType string) (string, error) {
	switch cmdType {
	case "spooler_reset":
		return runSpoolerReset(ctx)
	default:
		return "", fmt.Errorf("no native implementation for %q", cmdType)
	}
}

// --- Executing a System32 tool ---------------------------------------------

// runSystem32 runs a tool from %SystemRoot%\System32 and returns its combined
// output and exit code. A non-zero exit is *not* an error here — reading it is
// the verdict function's job; the error return is reserved for "could not run
// it at all" and for the timeout.
func runSystem32(ctx context.Context, exe string, args ...string) ([]byte, int, error) {
	path := system32Path(exe)
	cmd := exec.CommandContext(ctx, path, args...)
	// Pinned rather than inherited: chkdsk /scan takes no drive letter and acts
	// on the volume of the working directory, so the target has to be decided
	// here instead of depending on wherever the SCM happened to start us.
	cmd.Dir = systemDrive()

	out, err := cmd.CombinedOutput()
	if err == nil {
		return out, 0, nil
	}

	// The deadline is ours (spec.timeout); cancellation is the service stopping.
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return out, 0, fmt.Errorf("délai d'exécution dépassé pour %s", exe)
	}
	if errors.Is(ctx.Err(), context.Canceled) {
		return out, 0, fmt.Errorf("exécution de %s interrompue (arrêt de l'agent)", exe)
	}

	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return out, exitErr.ExitCode(), nil
	}
	return out, 0, fmt.Errorf("lancement de %s : %w", exe, err)
}

// system32Path resolves a catalogue executable to an absolute path.
//
// Absolute on purpose, never a PATH lookup: the agent runs as LocalSystem, so a
// directory that appears before System32 in PATH and is writable by a normal
// user would turn every one of these commands into SYSTEM code execution.
func system32Path(exe string) string {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return filepath.Join(root, "System32", exe)
}

// systemDrive is the volume Windows is installed on — "C:\" on all but the
// unusual machine, which is exactly why it is read rather than assumed.
func systemDrive() string {
	drive := os.Getenv("SystemDrive")
	if drive == "" {
		drive = "C:"
	}
	return drive + `\`
}

// Code pages for MultiByteToWideChar. CP_OEMCP (850 on a French Windows, 437 on
// a US one) and CP_ACP (1252 in Western Europe) are the "whatever this system is
// configured for" pseudo-values, which is what these tools actually use — never
// a hard-coded 850 or 1252, which would be wrong on the first non-Western parc.
const (
	cpOEM  = 1 // CP_OEMCP
	cpANSI = 0 // CP_ACP
)

// decodeToolOutput turns captured bytes into text, three ways.
//
// The order matters. UTF-16LE first, because NUL bytes are perfectly valid
// UTF-8 and sfc's output would otherwise sail through the next test with a NUL
// between every character. Then UTF-8, which identifies itself and so needs no
// per-tool declaration. Only then the declared code page, which is the one
// thing that cannot be detected from the bytes.
//
// The spec's UTF-16 claim is *checked* against the bytes rather than trusted: a
// build of sfc that stopped doing it would degrade to readable text instead of
// producing Chinese characters.
func decodeToolOutput(raw []byte, enc toolEncoding) string {
	if enc == encUTF16LE && looksUTF16LE(raw) {
		return decodeUTF16LE(raw)
	}
	if isProbablyUTF8(raw) {
		return string(raw)
	}
	cp := uint32(cpOEM)
	if enc == encANSI {
		cp = cpANSI
	}
	return codePageText(raw, cp)
}

// codePageText converts single-byte code-page bytes to a Go string, the same
// conversion Windows itself would apply. On failure the raw bytes are returned:
// mojibake beats an empty result dialog.
func codePageText(raw []byte, cp uint32) string {
	if len(raw) == 0 {
		return ""
	}
	n, err := windows.MultiByteToWideChar(cp, 0, &raw[0], int32(len(raw)), nil, 0)
	if err != nil || n <= 0 {
		return string(raw)
	}
	buf := make([]uint16, n)
	if _, err := windows.MultiByteToWideChar(cp, 0, &raw[0], int32(len(raw)), &buf[0], n); err != nil {
		return string(raw)
	}
	return windows.UTF16ToString(buf)
}

// --- Spooler reset ----------------------------------------------------------

const (
	spoolerService = "Spooler"
	// spoolQueueSubdir holds the queued jobs: a .spl (the data) and a .shd (the
	// descriptor) per job. Only those two extensions are ever deleted — the
	// directory is not wiped.
	spoolQueueSubdir = `System32\spool\PRINTERS`
	// serviceStateTimeout bounds each of the two state transitions. The spooler
	// normally stops in under a second; a stuck driver is what this catches.
	serviceStateTimeout = 60 * time.Second
	servicePollInterval = 300 * time.Millisecond
)

// runSpoolerReset stops the print spooler, empties its queue and starts it
// again — the standard fix for a queue nobody can clear from the UI.
//
// Driven through the service manager rather than `net stop spooler` in a shell:
// the API reports the actual service state instead of a localized sentence, it
// needs no shell, and stopAndWait can genuinely wait for Stopped rather than
// racing the deletion against a service that has not let go of the files yet.
func runSpoolerReset(ctx context.Context) (string, error) {
	m, err := mgr.Connect()
	if err != nil {
		return "", fmt.Errorf("connexion au gestionnaire de services : %w", err)
	}
	defer m.Disconnect()

	s, err := m.OpenService(spoolerService)
	if err != nil {
		return "", fmt.Errorf("ouverture du service %s : %w", spoolerService, err)
	}
	defer s.Close()

	var lines []string
	if err := setServiceState(ctx, s, svc.Stop, svc.Stopped); err != nil {
		return "", fmt.Errorf("arrêt du spouleur : %w", err)
	}
	lines = append(lines, "Spouleur d'impression arrêté.")

	removed, purgeErr := purgeSpoolQueue()
	if purgeErr != nil {
		lines = append(lines, fmt.Sprintf("Purge incomplète de la file : %v", purgeErr))
	} else {
		lines = append(lines, fmt.Sprintf("File d'impression purgée (%d fichier(s)).", removed))
	}

	// Attempted whatever happened above: a machine left with no print spooler at
	// all is a worse outcome than a queue that is still full.
	if err := setServiceState(ctx, s, svc.Cmd(0), svc.Running); err != nil {
		lines = append(lines, "Le spouleur n'a PAS pu être redémarré.")
		return strings.Join(lines, "\n"), fmt.Errorf("démarrage du spouleur : %w", err)
	}
	lines = append(lines, "Spouleur d'impression redémarré.")

	output := strings.Join(lines, "\n")
	if purgeErr != nil {
		return output, fmt.Errorf("purge de la file d'impression : %w", purgeErr)
	}
	return output, nil
}

// setServiceState drives the service to want, then waits for it to get there.
// A zero control code means "start" (there is no svc.Cmd for starting).
func setServiceState(ctx context.Context, s *mgr.Service, control svc.Cmd, want svc.State) error {
	status, err := s.Query()
	if err != nil {
		return fmt.Errorf("interrogation du service : %w", err)
	}
	if status.State == want {
		return nil
	}
	if control == 0 {
		if err := s.Start(); err != nil {
			return err
		}
	} else if status.State != svc.StopPending {
		// Control(Stop) on an already-stopping service fails; the query above
		// plus this guard keep a normal path from looking broken.
		if _, err := s.Control(control); err != nil {
			return err
		}
	}

	deadline := time.Now().Add(serviceStateTimeout)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(servicePollInterval):
		}
		if status, err = s.Query(); err != nil {
			return fmt.Errorf("interrogation du service : %w", err)
		}
		if status.State == want {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("le service n'a pas atteint l'état attendu en %s", serviceStateTimeout)
		}
	}
}

// purgeSpoolQueue deletes the queued print jobs, returning how many files went.
// Failures are counted but not fatal — one locked job must not stop the rest
// from being cleared, nor the spooler from restarting.
func purgeSpoolQueue() (int, error) {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	dir := filepath.Join(root, spoolQueueSubdir)

	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0, fmt.Errorf("lecture de %s : %w", dir, err)
	}

	removed, failed := 0, 0
	var firstErr error
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		switch strings.ToLower(filepath.Ext(e.Name())) {
		case ".spl", ".shd":
		default:
			continue
		}
		if err := os.Remove(filepath.Join(dir, e.Name())); err != nil {
			failed++
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		removed++
	}
	if firstErr != nil {
		return removed, fmt.Errorf("%d fichier(s) non supprimé(s), première erreur : %w", failed, firstErr)
	}
	return removed, nil
}

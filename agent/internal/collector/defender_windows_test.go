package collector

import (
	"context"
	"strings"
	"testing"
	"time"
)

// Accented characters must survive the PowerShell → Go round-trip: the legacy
// console code page (CP850/CP1252 on French systems) would otherwise turn them
// into U+FFFD once the bytes are treated as UTF-8.
func TestRunPowerShellKeepsAccents(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	out, err := runPowerShell(ctx, "Write-Output 'échec à répéter'")
	if err != nil {
		t.Fatalf("runPowerShell: %v", err)
	}
	if out != "échec à répéter" {
		t.Errorf("output = %q, want %q", out, "échec à répéter")
	}
}

func TestRunPowerShellFailureKeepsAccents(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	_, err := runPowerShell(ctx, "Write-Error 'mise à jour échouée'")
	if err == nil {
		t.Fatal("expected an error for Write-Error, got nil")
	}
	if !strings.Contains(err.Error(), "mise à jour échouée") {
		t.Errorf("error %q should contain the accented message", err)
	}
}

// A script with no pipeline output (Start-MpScan/Update-MpSignature on
// success) must not trip the UTF-8 re-encoding wrapper: Out-String yields an
// empty string, never $null.
func TestRunPowerShellEmptyOutput(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	out, err := runPowerShell(ctx, "$x = 1")
	if err != nil {
		t.Fatalf("runPowerShell: %v", err)
	}
	if out != "" {
		t.Errorf("output = %q, want empty", out)
	}
}

func TestRunPowerShellTerminatingError(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	_, err := runPowerShell(ctx, "throw 'arrêt brutal'")
	if err == nil {
		t.Fatal("expected an error for throw, got nil")
	}
	if !strings.Contains(err.Error(), "arrêt brutal") {
		t.Errorf("error %q should contain the accented message", err)
	}
}

package winpath

import (
	"path/filepath"
	"strings"
	"testing"
)

// Every program the agent starts hangs off %SystemRoot%: on the unusual machine
// installed elsewhere than C:\Windows, a hard-coded path would point at nothing
// — or at a directory someone else created.
func TestPathsFollowSystemRoot(t *testing.T) {
	t.Setenv("SystemRoot", `D:\WINNT`)

	if got, want := System32("ipconfig.exe"), filepath.Join(`D:\WINNT`, "System32", "ipconfig.exe"); got != want {
		t.Errorf("System32 = %q, want %q", got, want)
	}
	want := filepath.Join(`D:\WINNT`, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
	if got := PowerShell(); got != want {
		t.Errorf("PowerShell = %q, want %q", got, want)
	}
}

// A missing variable falls back to the default location rather than to a
// relative path, which exec would resolve against the working directory.
func TestPathsFallBackToTheDefaultWindowsDirectory(t *testing.T) {
	t.Setenv("SystemRoot", "")
	t.Setenv("SystemDrive", "")

	if got := SystemRoot(); got != `C:\Windows` {
		t.Errorf("SystemRoot = %q, want C:\\Windows", got)
	}
	if got := SystemDrive(); got != `C:\` {
		t.Errorf("SystemDrive = %q, want C:\\", got)
	}
	if got := PowerShell(); !strings.HasPrefix(got, `C:\Windows`) {
		t.Errorf("PowerShell = %q, must stay under the default Windows directory", got)
	}
}

// The in-box Windows PowerShell, never a bare name for PATH to resolve and
// never pwsh, which is not installed on a stock machine.
func TestPowerShellIsTheInBoxBinary(t *testing.T) {
	got := strings.ToLower(PowerShell())
	if !strings.HasSuffix(got, "powershell.exe") {
		t.Errorf("PowerShell = %q, want the powershell.exe binary", got)
	}
	if !strings.Contains(got, "windowspowershell") {
		t.Errorf("PowerShell = %q, want the in-box WindowsPowerShell directory", got)
	}
}

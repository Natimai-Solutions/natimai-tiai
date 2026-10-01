// Package winpath resolves the Windows system programs the agent launches to
// absolute paths.
//
// Absolute on purpose, never a PATH lookup: the agent runs as LocalSystem, so a
// directory that appears before System32 in PATH and is writable by a normal
// user would turn every program the agent starts — a catalogue tool, a
// Defender scan, a Windows Update search — into SYSTEM code execution. One
// package rather than a helper per collector, so that no new call site has a
// reason to type a bare "powershell" again.
//
// Pure string work with no build tag: the paths only mean something on
// Windows, but computing them does not need Windows, which keeps them testable
// anywhere.
package winpath

import (
	"os"
	"path/filepath"
)

// SystemRoot is the Windows directory — "C:\Windows" on all but the unusual
// machine, which is exactly why it is read rather than assumed.
//
// Read from the environment, which for a LocalSystem service is the system's
// own block: %SystemRoot% is set by Windows itself, not by anything a user can
// write to.
func SystemRoot() string {
	if root := os.Getenv("SystemRoot"); root != "" {
		return root
	}
	return `C:\Windows`
}

// SystemDrive is the volume Windows is installed on, with its trailing
// separator — "C:\" on all but the unusual machine.
func SystemDrive() string {
	drive := os.Getenv("SystemDrive")
	if drive == "" {
		drive = "C:"
	}
	return drive + `\`
}

// System32 resolves a program shipped in %SystemRoot%\System32.
func System32(exe string) string {
	return filepath.Join(SystemRoot(), "System32", exe)
}

// PowerShell is Windows PowerShell 5.1, the in-box one: present on every
// supported Windows, and the one whose Defender (Start-MpScan,
// Update-MpSignature) and WUA behaviour the agent's scripts were written and
// tested against. Never pwsh.exe, which is an optional install.
//
// The "v1.0" in the path is not a version — Microsoft kept the directory name
// when PowerShell 2.0 through 5.1 replaced the binary inside it.
func PowerShell() string {
	return filepath.Join(SystemRoot(), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
}

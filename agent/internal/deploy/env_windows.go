//go:build windows

package deploy

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Supported tells whether this platform can deploy at all.
const Supported = true

// VerifyAuthenticode implements Env with WinVerifyTrust: a valid signature,
// chaining to a root Windows trusts, revocation checked on the whole chain.
// A poste that cannot reach the revocation servers (a school network behind
// a proxy SYSTEM does not use) still accepts the file — the signature itself
// verified — and says so in the result; an actual revocation is a refusal.
func (e *SystemEnv) VerifyAuthenticode(path string) (string, error) {
	err := winVerifyTrust(path, windows.WTD_REVOKE_WHOLECHAIN)
	if err == nil {
		return "", nil
	}
	if errors.Is(err, syscall.Errno(windows.CERT_E_REVOCATION_FAILURE)) || errors.Is(err, syscall.Errno(windows.CRYPT_E_REVOCATION_OFFLINE)) {
		if err2 := winVerifyTrust(path, windows.WTD_REVOKE_NONE); err2 != nil {
			return "", err2
		}
		return "révocation non vérifiable hors ligne", nil
	}
	return "", err
}

func winVerifyTrust(path string, revocation uint32) error {
	p, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	data := &windows.WinTrustData{
		Size:             uint32(unsafe.Sizeof(windows.WinTrustData{})),
		UIChoice:         windows.WTD_UI_NONE,
		RevocationChecks: revocation,
		UnionChoice:      windows.WTD_CHOICE_FILE,
		StateAction:      windows.WTD_STATEACTION_VERIFY,
		FileOrCatalogOrBlobOrSgnrOrCert: unsafe.Pointer(&windows.WinTrustFileInfo{
			Size:     uint32(unsafe.Sizeof(windows.WinTrustFileInfo{})),
			FilePath: p,
		}),
	}
	verifyErr := windows.WinVerifyTrustEx(windows.InvalidHWND, &windows.WINTRUST_ACTION_GENERIC_VERIFY_V2, data)
	data.StateAction = windows.WTD_STATEACTION_CLOSE
	_ = windows.WinVerifyTrustEx(windows.InvalidHWND, &windows.WINTRUST_ACTION_GENERIC_VERIFY_V2, data)
	return verifyErr
}

// Run implements Env: the executable itself, no shell, no window. Its exit
// code is returned as Windows reports it (an unsigned 32-bit value).
func (e *SystemEnv) Run(ctx context.Context, exe string, args []string, dir string) (int64, error) {
	cmd := exec.CommandContext(ctx, exe, args...)
	cmd.Dir = dir
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	err := cmd.Run()
	if ctx.Err() != nil {
		return 0, fmt.Errorf("délai dépassé : %w", ctx.Err())
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return int64(uint32(exitErr.ExitCode())), nil
	}
	if err != nil {
		return 0, err
	}
	return 0, nil
}

// WingetPath implements Env. winget is an App Installer alias in the user's
// profile, so `winget` resolves for nobody running as SYSTEM: the executable
// is taken from the newest DesktopAppInstaller package under WindowsApps —
// a folder only TrustedInstaller writes, and whose suffix is Microsoft's
// publisher id.
func (e *SystemEnv) WingetPath() (string, error) {
	pf := os.Getenv("ProgramFiles")
	if pf == "" {
		pf = `C:\Program Files`
	}
	dirs, _ := filepath.Glob(filepath.Join(pf, "WindowsApps", "Microsoft.DesktopAppInstaller_*__8wekyb3d8bbwe"))
	var withWinget []string
	for _, d := range dirs {
		if _, err := os.Stat(filepath.Join(d, "winget.exe")); err == nil {
			withWinget = append(withWinget, d)
		}
	}
	best := LatestWingetDir(withWinget)
	if best == "" {
		return "", errors.New("winget absent de ce poste (App Installer non installé — fréquent sur LTSC et Windows Server) : utiliser un paquet de fichiers")
	}
	return filepath.Join(best, "winget.exe"), nil
}

// MsiExecPath implements Env.
func (e *SystemEnv) MsiExecPath() string {
	root := os.Getenv("SystemRoot")
	if root == "" {
		root = `C:\Windows`
	}
	return filepath.Join(root, "System32", "msiexec.exe")
}

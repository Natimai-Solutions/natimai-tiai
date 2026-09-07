package identity

import (
	"context"
	"log"
	"os/exec"
	"strings"
	"time"

	"github.com/yusufpapurcu/wmi"
	"golang.org/x/sys/windows/registry"
)

// tpmReadTimeout bounds the PowerShell call below. Generous — launching
// PowerShell on a poste that has just booted is not fast — but finite.
const tpmReadTimeout = 60 * time.Second

type win32ComputerSystemProduct struct {
	UUID string
}

// smbiosReadAttempts and smbiosRetryDelay retry the anchor read at start-up.
//
// The agent starts with the machine, and WMI does not: on a slow or loaded
// poste, Winmgmt is still coming up when the first query goes out and it fails
// with an RPC error. The cost of accepting that first answer is not a missing
// field — Resolve falls back to a UUID it generates and persists, so the poste
// enrolls as a *second* machine, the real one goes quiet in the console, and
// nobody can tell the ghost from a genuine new arrival. Three attempts over six
// seconds, once per process start, buy that back.
const (
	smbiosReadAttempts = 3
	smbiosRetryDelay   = 3 * time.Second
)

// readSMBIOSUUID returns Win32_ComputerSystemProduct.UUID via WMI — the SMBIOS
// system UUID, the primary identity anchor (plan §2.3).
func readSMBIOSUUID() string {
	for attempt := 1; ; attempt++ {
		// Explicit class name: wmi.CreateQuery would derive it from the Go type
		// name (win32ComputerSystemProduct), which doesn't match the WMI class.
		var dst []win32ComputerSystemProduct
		err := wmi.Query("SELECT UUID FROM Win32_ComputerSystemProduct", &dst)
		if err == nil && len(dst) > 0 {
			return strings.TrimSpace(dst[0].UUID)
		}
		if attempt >= smbiosReadAttempts {
			// Traced, because what follows it — a generated identity — is the
			// kind of thing somebody has to be able to explain later.
			log.Printf("identity: SMBIOS UUID unreadable after %d attempts (%v); "+
				"falling back to the persisted agent UUID", attempt, err)
			return ""
		}
		time.Sleep(smbiosRetryDelay)
	}
}

// readMachineGUID returns HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid.
// Reported as a fingerprint component only — it is duplicated across clones
// imaged without Sysprep, so it is never used as the identity.
func readMachineGUID() string {
	k, err := registry.OpenKey(
		registry.LOCAL_MACHINE,
		`SOFTWARE\Microsoft\Cryptography`,
		registry.QUERY_VALUE|registry.WOW64_64KEY,
	)
	if err != nil {
		return ""
	}
	defer k.Close()
	v, _, err := k.GetStringValue("MachineGuid")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(v)
}

// readTPMEKHash returns a hash of the TPM 2.0 Endorsement Key public, if a TPM
// is present. Best-effort and optional (plan §2.3: bonus fingerprint, never
// depended upon) — any failure yields "".
func readTPMEKHash() string {
	// Bounded, and the bound is the point: this runs before the first heartbeat,
	// so a PowerShell that never comes back — a TPM stack in a bad way, a
	// machine still thrashing through its boot — would leave the service
	// Running and the agent doing nothing at all, forever, with no failure
	// anybody could see. A fingerprint component the plan calls a bonus is not
	// worth that.
	ctx, cancel := context.WithTimeout(context.Background(), tpmReadTimeout)
	defer cancel()

	out, err := exec.CommandContext(ctx, "powershell", "-NoProfile", "-NonInteractive", "-Command",
		"(Get-TpmEndorsementKeyInfo -ErrorAction SilentlyContinue).PublicKeyHash",
	).Output()
	if err != nil {
		return ""
	}
	return strings.ToLower(strings.TrimSpace(string(out)))
}

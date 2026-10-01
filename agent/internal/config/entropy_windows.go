// Per-install DPAPI entropy for token.dat.
//
// Machine-scope DPAPI alone lets *any* local principal decrypt the token. The
// entropy is the second half of the secret: 32 random bytes generated at first
// use and stored under HKLM\SOFTWARE\Tiai (value TokenEntropy) — a key the
// installers (MSI, GPO script, `tiai-agent install`) restrict to SYSTEM and
// Administrators, and that the agent restricts itself before writing the
// entropy into it. A standard user can read
// token.dat under %ProgramData% but not the entropy, so the pair decrypts only
// for the service and for admins. Losing the entropy (key deleted, machine
// re-imaged) merely costs a re-enrollment: an undecryptable token is treated
// as no token at all (cf. LoadToken).
package config

import (
	"crypto/rand"
	"encoding/base64"
	"log"

	"golang.org/x/sys/windows/registry"

	"tiai/agent/internal/acl"
)

const entropyValueName = "TokenEntropy"

// readTokenEntropy returns the stored entropy, or nil when there is none (or
// it is unreadable/corrupt — decryption then fails and degrades to re-enroll).
func readTokenEntropy() []byte {
	k, err := registry.OpenKey(
		registry.LOCAL_MACHINE,
		`SOFTWARE\Tiai`,
		registry.QUERY_VALUE|registry.WOW64_64KEY,
	)
	if err != nil {
		return nil
	}
	defer k.Close()
	v, _, err := k.GetStringValue(entropyValueName)
	if err != nil || v == "" {
		return nil
	}
	raw, err := base64.StdEncoding.DecodeString(v)
	if err != nil {
		return nil
	}
	return raw
}

// ensureTokenEntropy returns the entropy, generating and persisting it on
// first use. nil when it can neither read nor create one (no rights on HKLM —
// a manual run as a non-admin): the token is then protected by machine DPAPI
// alone, exactly as before entropy existed.
func ensureTokenEntropy() []byte {
	if e := readTokenEntropy(); e != nil {
		return e
	}
	// Restricted *before* the value exists, never after: an entropy written
	// under the inherited ACL of HKLM\SOFTWARE is readable by every local user
	// for as long as it sits there, and a user who copied it once keeps it. The
	// installers restrict the key already; this covers the poste whose key was
	// created some other way — a GPO preference pushing ApiBaseURL, an agent run
	// by hand — before the first enrollment.
	//
	// A failure does not stop the entropy from being written: the token is then
	// protected exactly as it was before entropy existed (machine DPAPI alone),
	// and becomes properly protected the moment an installer restricts the key.
	_, hardenErr := acl.HardenRegistryKey()
	k, _, err := registry.CreateKey(
		registry.LOCAL_MACHINE,
		`SOFTWARE\Tiai`,
		registry.QUERY_VALUE|registry.SET_VALUE|registry.WOW64_64KEY,
	)
	if err != nil {
		return nil
	}
	defer k.Close()
	// Re-read under the writable handle: another process (service start racing
	// an install script) may have created it between the read above and here.
	if v, _, err := k.GetStringValue(entropyValueName); err == nil && v != "" {
		if raw, err := base64.StdEncoding.DecodeString(v); err == nil {
			return raw
		}
	}
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return nil
	}
	if err := k.SetStringValue(entropyValueName, base64.StdEncoding.EncodeToString(raw)); err != nil {
		return nil
	}
	if hardenErr != nil {
		// Said only once the entropy is actually there to be read: a run with
		// no rights on HKLM at all fails both, and stores nothing.
		log.Printf("config: token entropy stored, but HKLM\\%s could not be restricted to "+
			"SYSTEM + Administrators (%v): local users may be able to read it until an "+
			"installer (or `tiai-agent repair`) restricts the key", acl.RegistryKeyPath, hardenErr)
	}
	return raw
}

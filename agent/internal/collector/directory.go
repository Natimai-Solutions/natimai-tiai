package collector

import (
	"strings"

	"tiai/agent/internal/models"
)

// Directory: what Active Directory says about this computer, for the server
// to file the poste by (ROOM_SOURCE = ad_ou or ad_location).
//
// This file is pure — DN parsing — and testable off Windows. The two reads
// that feed it (the registry for the DN, ADSI for the location attribute)
// live in directory_windows.go, with the stub in directory_other.go.

// splitDN cuts a distinguished name into its RDNs, honouring the backslash
// escapes of RFC 4514: "CN=Dupont\, Jean,OU=Postes" is two components, not
// three. Each component is returned trimmed, escapes kept as written — the
// server stores the DN as a key and never displays the escaped form.
func splitDN(dn string) []string {
	var parts []string
	var current strings.Builder
	escaped := false
	for _, r := range dn {
		switch {
		case escaped:
			current.WriteRune(r)
			escaped = false
		case r == '\\':
			current.WriteRune(r)
			escaped = true
		case r == ',':
			parts = append(parts, strings.TrimSpace(current.String()))
			current.Reset()
		default:
			current.WriteRune(r)
		}
	}
	if current.Len() > 0 || len(parts) > 0 {
		parts = append(parts, strings.TrimSpace(current.String()))
	}
	return parts
}

// rdnValue returns the value of an "attr=value" component, unescaped for
// display: "Salle B12" from "OU=Salle B12", "Dupont, Jean" from
// "CN=Dupont\, Jean". Empty when the component is not of that shape.
func rdnValue(rdn string) string {
	_, value, ok := strings.Cut(rdn, "=")
	if !ok {
		return ""
	}
	var out strings.Builder
	escaped := false
	for _, r := range value {
		if escaped || r != '\\' {
			out.WriteRune(r)
			escaped = false
			continue
		}
		escaped = true
	}
	return strings.TrimSpace(out.String())
}

// parentOU returns the OU directly containing the object named by dn — its
// display name and its own DN. A computer sitting straight under a domain or
// a container ("CN=Computers,DC=…") is in no OU: both come back empty, and
// the server files nothing rather than filing by "Computers".
func parentOU(dn string) (name, ouDN string) {
	parts := splitDN(dn)
	if len(parts) < 2 {
		return "", ""
	}
	parent := parts[1]
	if !strings.EqualFold(strings.TrimSpace(strings.SplitN(parent, "=", 2)[0]), "OU") {
		return "", ""
	}
	return rdnValue(parent), strings.Join(parts[1:], ",")
}

// directoryState builds the block from the two raw readings. nil when there
// is no DN at all — a workgroup poste, or a domain-joined one that has never
// processed Group Policy — so the server keeps what it had rather than being
// told "no OU" on no evidence.
func directoryState(dn, adLocation string) *models.DirectoryState {
	dn = strings.TrimSpace(dn)
	if dn == "" {
		return nil
	}
	ou, ouDN := parentOU(dn)
	return &models.DirectoryState{
		DistinguishedName: dn,
		OU:                ou,
		OUDN:              ouDN,
		ADLocation:        strings.TrimSpace(adLocation),
	}
}

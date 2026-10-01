// Package acl restricts the agent's two sensitive locations to SYSTEM and
// Administrators: the registry key HKLM\SOFTWARE\Tiai and the data directory
// (%ProgramData%\Tiai).
//
// Both inherit readable ACLs by default. HKLM\SOFTWARE is readable by every
// authenticated user, and the key holds the enrollment secret and the
// TokenEntropy that is half of what decrypts token.dat; %ProgramData% lets
// users read the subfolders the system creates, and the directory holds
// token.dat itself. Either one left readable undoes the per-machine token
// protection (see config/entropy_windows.go).
//
// The MSI (deploy/msi/Package.wxs) and the GPO script
// (deploy/gpo/Install-TiaiAgent.ps1) already restrict both. This package gives
// `tiai-agent install` and `repair`, and the first creation of the entropy, the
// very same descriptors — so that how the agent was installed decides nothing
// about who can read its secrets.
//
// This file is pure: the descriptors, and the rule that decides whether a DACL
// read back from Windows already is the restricted one. Reading and writing
// security descriptors is Windows-only (acl_windows.go).
package acl

// The descriptors, in SDDL, byte for byte those of the MSI and the GPO script
// (a test reads both files to keep it that way).
//
//   - D:P — the DACL is protected: nothing is inherited from HKLM\SOFTWARE or
//     from %ProgramData%, which is the whole point.
//   - SY, BA — the well-known SIDs of LocalSystem (the service) and
//     BUILTIN\Administrators, never group *names*, which are localised
//     ("Administrateurs") and would not resolve on another language's Windows.
//   - KA / FA — full control of a key / of a file or directory.
//   - CI on the key: subkeys inherit, and there are no "objects" under a key,
//     so OI would be meaningless. OICI on the directory: token.dat, agent.log
//     and the queue/ subfolder all inherit the restriction when created.
const (
	RegistryKeySDDL = "D:P(A;CI;KA;;;SY)(A;CI;KA;;;BA)"
	DataDirSDDL     = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
)

// RegistryKeyPath is the agent's key under HKEY_LOCAL_MACHINE.
const RegistryKeyPath = `SOFTWARE\Tiai`

// The two principals a restricted DACL may name.
const (
	sidLocalSystem    = "S-1-5-18"
	sidAdministrators = "S-1-5-32-544"
)

// winnt.h values, spelled out so the rule below stays pure and testable off
// Windows. KA and FA are the literal masks those SDDL rights expand to.
const (
	keyAllAccess  uint32 = 0x000F003F // KEY_ALL_ACCESS (SDDL "KA")
	fileAllAccess uint32 = 0x001F01FF // FILE_ALL_ACCESS (SDDL "FA")

	aceTypeAccessAllowed uint8 = 0x0 // ACCESS_ALLOWED_ACE_TYPE
	aceObjectInherit     uint8 = 0x1 // OBJECT_INHERIT_ACE (SDDL "OI")
	aceContainerInherit  uint8 = 0x2 // CONTAINER_INHERIT_ACE (SDDL "CI")
)

// policy is one restricted descriptor and what its ACEs must carry.
type policy struct {
	sddl    string
	mask    uint32 // the full-control mask each of SY and BA must hold
	inherit uint8  // the inheritance flags each of their ACEs must carry
}

var (
	registryPolicy = policy{sddl: RegistryKeySDDL, mask: keyAllAccess, inherit: aceContainerInherit}
	dataDirPolicy  = policy{sddl: DataDirSDDL, mask: fileAllAccess, inherit: aceObjectInherit | aceContainerInherit}
)

// ace is what the rule needs to know of one access control entry.
type ace struct {
	typ   uint8
	flags uint8
	mask  uint32
	sid   string // in S-1-… form; empty for a type whose SID was not read
}

// restricted reports whether a DACL already is what the policy would write, so
// that install and repair leave an already restricted location alone — and say
// nothing about it.
//
// Compared on the principals and their rights, never on the SDDL string: Windows
// re-orders and re-flags a descriptor when it stores it (an "AI" appears, ACEs
// move), so a string comparison would rewrite a correct DACL on every run. The
// rule is the GPO script's (Test-TiaiAclTight), made stricter on one point: SY
// and BA must each actually hold full control, inherited down. A protected DACL
// that admitted only those two but with reduced rights would pass the script's
// test while locking the service out of its own key.
//
// Not restricted: an unprotected DACL (it inherits whatever its parent grants),
// an empty one (nobody, the service included), any ACE that is not an allow (a
// deny, an object ACE), any other principal. A NULL DACL — everyone, full
// control — never gets here: the Windows reader rejects it first.
func (p policy) restricted(protected bool, aces []ace) bool {
	if !protected {
		return false
	}
	var system, admins bool
	for _, a := range aces {
		if a.typ != aceTypeAccessAllowed {
			return false
		}
		if a.sid != sidLocalSystem && a.sid != sidAdministrators {
			return false
		}
		full := a.mask&p.mask == p.mask && a.flags&p.inherit == p.inherit
		switch {
		case !full:
			continue
		case a.sid == sidLocalSystem:
			system = true
		default:
			admins = true
		}
	}
	return system && admins
}

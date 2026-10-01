package acl

import (
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// HardenRegistryKey creates HKLM\SOFTWARE\Tiai if it does not exist yet and
// restricts its DACL to SYSTEM + Administrators. changed is false when the key
// already carried that DACL and nothing was written.
//
// Through a handle opened in the 64-bit view, like every other access the agent
// makes to the key (registry.WOW64_64KEY): the named-object API would resolve
// the path in the caller's own view, and a restriction applied to the wrong
// view protects nothing.
func HardenRegistryKey() (changed bool, err error) {
	return hardenKey(registry.LOCAL_MACHINE, RegistryKeyPath)
}

// hardenKey is HardenRegistryKey for any key — tests point it at a scratch key
// under HKCU rather than at the machine's real configuration.
func hardenKey(root registry.Key, path string) (bool, error) {
	k, _, err := registry.CreateKey(root, path,
		windows.READ_CONTROL|windows.WRITE_DAC|registry.WOW64_64KEY)
	if err != nil {
		return false, fmt.Errorf("open %s: %w", path, err)
	}
	defer k.Close()
	h := windows.Handle(k)

	if sd, err := windows.GetSecurityInfo(h, windows.SE_REGISTRY_KEY,
		windows.DACL_SECURITY_INFORMATION); err == nil && registryPolicy.matches(sd) {
		return false, nil
	}
	dacl, err := registryPolicy.dacl()
	if err != nil {
		return false, err
	}
	// PROTECTED_DACL is what cuts inheritance from HKLM\SOFTWARE: without it the
	// two ACEs would be added to the inherited ones, not substituted for them.
	// Inheritable ACEs propagate to existing subkeys, as with the MSI.
	if err := windows.SetSecurityInfo(h, windows.SE_REGISTRY_KEY,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION,
		nil, nil, dacl, nil); err != nil {
		return false, fmt.Errorf("restrict %s: %w", path, err)
	}
	return true, nil
}

// HardenDataDir restricts an existing directory's DACL to SYSTEM +
// Administrators, inherited by everything under it. changed is false when the
// directory already carried that DACL.
//
// By name, which is what makes Windows propagate the new inheritable ACEs to
// what the directory already holds — a token.dat written before the
// restriction must lose its readable ACEs too, not only the files created after.
func HardenDataDir(dir string) (changed bool, err error) {
	if ok, err := DataDirRestricted(dir); err == nil && ok {
		return false, nil
	}
	dacl, err := dataDirPolicy.dacl()
	if err != nil {
		return false, err
	}
	if err := windows.SetNamedSecurityInfo(dir, windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION,
		nil, nil, dacl, nil); err != nil {
		return false, fmt.Errorf("restrict %s: %w", dir, err)
	}
	return true, nil
}

// DataDirRestricted reports whether dir already carries the restricted DACL —
// what install checks before declining to touch a directory it does not own.
func DataDirRestricted(dir string) (bool, error) {
	sd, err := windows.GetNamedSecurityInfo(dir, windows.SE_FILE_OBJECT,
		windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return false, fmt.Errorf("read the ACL of %s: %w", dir, err)
	}
	return dataDirPolicy.matches(sd), nil
}

// dacl parses the policy's SDDL into the ACL handed to Set*SecurityInfo.
//
// The ACL points into sd's memory, which the Go heap owns (x/sys copies it out
// of LocalAlloc): it lives as long as the returned pointer is reachable.
func (p policy) dacl() (*windows.ACL, error) {
	sd, err := windows.SecurityDescriptorFromString(p.sddl)
	if err != nil {
		return nil, fmt.Errorf("parse %s: %w", p.sddl, err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		return nil, fmt.Errorf("DACL of %s: %w", p.sddl, err)
	}
	return dacl, nil
}

// matches reads a security descriptor back into the pure rule.
func (p policy) matches(sd *windows.SECURITY_DESCRIPTOR) bool {
	protected, aces, ok := summarize(sd)
	return ok && p.restricted(protected, aces)
}

// summarize extracts the DACL's protection bit and its ACEs. ok is false when
// there is no DACL to judge — absent, unreadable, or NULL (which grants
// everyone everything and is therefore the opposite of restricted).
func summarize(sd *windows.SECURITY_DESCRIPTOR) (protected bool, aces []ace, ok bool) {
	if sd == nil {
		// x/sys documents a nil descriptor with a nil error for an object that
		// has none at all.
		return false, nil, false
	}
	control, _, err := sd.Control()
	if err != nil {
		return false, nil, false
	}
	dacl, _, err := sd.DACL()
	if err != nil || dacl == nil {
		return false, nil, false
	}
	for i := uint32(0); i < uint32(dacl.AceCount); i++ {
		var a *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &a); err != nil {
			return false, nil, false
		}
		entry := ace{typ: a.Header.AceType, flags: a.Header.AceFlags, mask: uint32(a.Mask)}
		// The SID follows the mask only in the plain allow/deny layouts; for
		// any other type it is left empty, and the rule rejects the type anyway.
		if entry.typ == aceTypeAccessAllowed {
			entry.sid = (*windows.SID)(unsafe.Pointer(&a.SidStart)).String()
		}
		aces = append(aces, entry)
	}
	return control&windows.SE_DACL_PROTECTED != 0, aces, true
}

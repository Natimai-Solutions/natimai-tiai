package acl

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The descriptors must be those of the MSI and of the GPO script, byte for
// byte: a poste installed by `tiai-agent install` and one installed by the MSI
// are the same poste to whoever tries to read its secrets.
//
// Read from the deployment files themselves rather than restated here, so that
// a change to either side is a test failure and not a silent divergence.
func TestDescriptorsMatchTheInstallers(t *testing.T) {
	root := filepath.Join("..", "..", "..", "deploy")
	for _, f := range []string{
		filepath.Join(root, "msi", "Package.wxs"),
		filepath.Join(root, "gpo", "Install-TiaiAgent.ps1"),
	} {
		data, err := os.ReadFile(f)
		if os.IsNotExist(err) {
			// The agent module checked out on its own, without the rest of the
			// repository: there is nothing to compare against, which is not a
			// divergence.
			t.Skipf("%s not present (agent built outside the repository)", f)
		}
		if err != nil {
			t.Fatalf("read %s: %v", f, err)
		}
		for name, sddl := range map[string]string{
			"registry key": RegistryKeySDDL,
			"data dir":     DataDirSDDL,
		} {
			if !strings.Contains(string(data), sddl) {
				t.Errorf("%s: %s descriptor %q not found — the installers and the agent disagree",
					f, name, sddl)
			}
		}
	}
}

// The SDDL strings themselves: protected (no inheritance from HKLM\SOFTWARE or
// %ProgramData%), and the two well-known SIDs only — never a localised group
// name, which would not resolve on another language's Windows.
func TestDescriptorsAreProtectedAndNameOnlySYAndBA(t *testing.T) {
	for _, sddl := range []string{RegistryKeySDDL, DataDirSDDL} {
		if !strings.HasPrefix(sddl, "D:P(") {
			t.Errorf("%q: the DACL must be protected (D:P)", sddl)
		}
		if strings.Count(sddl, "(") != 2 || !strings.Contains(sddl, ";;;SY)") || !strings.Contains(sddl, ";;;BA)") {
			t.Errorf("%q: exactly two ACEs, SYSTEM and Administrators", sddl)
		}
	}
	if !strings.Contains(DataDirSDDL, "OICI") {
		t.Errorf("%q: files and subfolders must inherit the restriction", DataDirSDDL)
	}
}

func regACE(sid string) ace {
	return ace{typ: aceTypeAccessAllowed, flags: aceContainerInherit, mask: keyAllAccess, sid: sid}
}

func dirACE(sid string) ace {
	return ace{typ: aceTypeAccessAllowed, flags: aceObjectInherit | aceContainerInherit, mask: fileAllAccess, sid: sid}
}

// The rule that lets install and repair leave a restricted location alone —
// and that must never take a readable one for restricted.
func TestRestricted(t *testing.T) {
	sy, ba := sidLocalSystem, sidAdministrators
	const users = "S-1-5-32-545"

	cases := []struct {
		name      string
		p         policy
		protected bool
		aces      []ace
		want      bool
	}{
		{"registry, as written", registryPolicy, true, []ace{regACE(sy), regACE(ba)}, true},
		{"dir, as written", dataDirPolicy, true, []ace{dirACE(sy), dirACE(ba)}, true},
		{"order does not matter", dataDirPolicy, true, []ace{dirACE(ba), dirACE(sy)}, true},
		{"split ACEs still grant full control", registryPolicy, true,
			[]ace{regACE(sy), regACE(ba), {typ: aceTypeAccessAllowed, flags: aceContainerInherit, mask: 0x20019, sid: ba}}, true},

		{"unprotected: inherits from its parent", registryPolicy, false, []ace{regACE(sy), regACE(ba)}, false},
		{"users can read", dataDirPolicy, true,
			[]ace{dirACE(sy), dirACE(ba), {typ: aceTypeAccessAllowed, flags: 0x3, mask: 0x1200A9, sid: users}}, false},
		{"a deny ACE", registryPolicy, true,
			[]ace{regACE(sy), regACE(ba), {typ: 0x1, mask: keyAllAccess, sid: ""}}, false},
		{"SYSTEM missing: the service is locked out", registryPolicy, true, []ace{regACE(ba)}, false},
		{"Administrators missing", dataDirPolicy, true, []ace{dirACE(sy)}, false},
		{"reduced rights for the service", registryPolicy, true,
			[]ace{{typ: aceTypeAccessAllowed, flags: aceContainerInherit, mask: 0x20019, sid: sy}, regACE(ba)}, false},
		{"not inherited by files", dataDirPolicy, true,
			[]ace{{typ: aceTypeAccessAllowed, flags: aceContainerInherit, mask: fileAllAccess, sid: sy}, dirACE(ba)}, false},
		{"empty DACL: nobody", dataDirPolicy, true, nil, false},
		{"registry ACEs do not satisfy the dir policy", dataDirPolicy, true, []ace{regACE(sy), regACE(ba)}, false},
	}
	for _, c := range cases {
		if got := c.p.restricted(c.protected, c.aces); got != c.want {
			t.Errorf("%s: restricted = %v, want %v", c.name, got, c.want)
		}
	}
}

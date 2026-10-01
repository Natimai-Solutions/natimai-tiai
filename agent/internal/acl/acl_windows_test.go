package acl

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// The rule and the descriptors must agree once Windows has parsed them: a DACL
// written from RegistryKeySDDL that the rule did not recognise would be
// rewritten — and announced — on every install and every repair. No privilege
// needed: nothing is applied to anything.
func TestParsedDescriptorsSatisfyTheirOwnPolicy(t *testing.T) {
	for _, p := range []policy{registryPolicy, dataDirPolicy} {
		sd, err := windows.SecurityDescriptorFromString(p.sddl)
		if err != nil {
			t.Fatalf("parse %s: %v", p.sddl, err)
		}
		if !p.matches(sd) {
			protected, aces, ok := summarize(sd)
			t.Errorf("%s does not satisfy its own policy (protected=%v ok=%v aces=%+v)",
				p.sddl, protected, ok, aces)
		}
	}

	// And what an unhardened location looks like does not.
	for _, sddl := range []string{
		"D:AI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)", // %ProgramData% child
		"D:(A;CI;KA;;;SY)(A;CI;KA;;;BA)",                             // right ACEs, not protected
		"D:P(A;CI;KA;;;SY)(A;CI;KA;;;BA)(A;CI;KR;;;AU)",              // authenticated users read
	} {
		sd, err := windows.SecurityDescriptorFromString(sddl)
		if err != nil {
			t.Fatalf("parse %s: %v", sddl, err)
		}
		if registryPolicy.matches(sd) || dataDirPolicy.matches(sd) {
			t.Errorf("%s must not count as restricted", sddl)
		}
	}
}

// requireElevation skips a test that applies a restricted DACL. Restricting is
// what install does, and install runs elevated. It is also what makes cleanup
// trivial: an elevated administrator holds full control — DELETE included —
// through the BA entry the restriction itself grants, whereas an unelevated run
// would lock itself out of what it then has to remove.
func requireElevation(t *testing.T) {
	t.Helper()
	if !windows.GetCurrentProcessToken().IsElevated() {
		t.Skip("applying a SYSTEM + Administrators DACL needs an elevated administrator, as install does")
	}
}

// End to end on a scratch directory: restricted once, left alone the second
// time, and the file that was already there loses its readable ACEs — the
// token.dat written before the install is the case that matters.
func TestHardenDataDir(t *testing.T) {
	requireElevation(t)

	dir := filepath.Join(t.TempDir(), "Tiai")
	if err := os.MkdirAll(dir, 0o750); err != nil {
		t.Fatal(err)
	}
	token := filepath.Join(dir, "token.dat")
	if err := os.WriteFile(token, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	changed, err := HardenDataDir(dir)
	if err != nil {
		t.Fatalf("HardenDataDir: %v", err)
	}
	if !changed {
		t.Error("a directory inheriting from its parent must be rewritten")
	}
	if ok, err := DataDirRestricted(dir); err != nil || !ok {
		t.Fatalf("after hardening: restricted=%v err=%v", ok, err)
	}
	if changed, err := HardenDataDir(dir); err != nil || changed {
		t.Errorf("second run: changed=%v err=%v, want an untouched directory", changed, err)
	}

	sd, err := windows.GetNamedSecurityInfo(token, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read token ACL: %v", err)
	}
	_, aces, ok := summarize(sd)
	if !ok {
		t.Fatal("token.dat has no readable DACL")
	}
	for _, a := range aces {
		if a.sid != sidLocalSystem && a.sid != sidAdministrators {
			t.Errorf("token.dat still grants %s (mask %#x)", a.sid, a.mask)
		}
	}
}

// Same on a scratch key under HKCU — never on the machine's HKLM\SOFTWARE\Tiai,
// which belongs to whatever agent is installed on the machine running the suite.
func TestHardenKey(t *testing.T) {
	requireElevation(t)

	path := fmt.Sprintf(`Software\TiaiAclTest-%d-%d`, os.Getpid(), time.Now().UnixNano())
	t.Cleanup(func() {
		if err := registry.DeleteKey(registry.CURRENT_USER, path); err != nil {
			t.Errorf("delete scratch key: %v", err)
		}
	})

	changed, err := hardenKey(registry.CURRENT_USER, path)
	if err != nil {
		t.Fatalf("hardenKey: %v", err)
	}
	if !changed {
		t.Error("a freshly created key inherits from its parent and must be rewritten")
	}
	if changed, err := hardenKey(registry.CURRENT_USER, path); err != nil || changed {
		t.Errorf("second run: changed=%v err=%v, want an untouched key", changed, err)
	}

	k, err := registry.OpenKey(registry.CURRENT_USER, path, windows.READ_CONTROL|registry.WOW64_64KEY)
	if err != nil {
		t.Fatalf("reopen: %v", err)
	}
	defer k.Close()
	sd, err := windows.GetSecurityInfo(windows.Handle(k), windows.SE_REGISTRY_KEY, windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		t.Fatalf("read key ACL: %v", err)
	}
	if !registryPolicy.matches(sd) {
		t.Errorf("key DACL is %s, want %s", sd, RegistryKeySDDL)
	}
}

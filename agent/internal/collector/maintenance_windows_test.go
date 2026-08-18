package collector

import (
	"context"
	"strings"
	"testing"
	"time"
)

// Real runs against the real Windows of whoever runs the suite. Same intent as
// TestRunPowerShellKeepsAccents: the pure tests prove the decoding logic, these
// prove it was wired to the bytes the tools actually produce — which is where
// the first version of this collector got it wrong.
//
// One command per encoding branch, all three read-only and sub-second. The long
// and destructive entries are deliberately not exercised here.
func TestRunMaintenanceOutputIsReadable(t *testing.T) {
	cases := []struct {
		cmd string
		why string
	}{
		{"net_config", "ipconfig writes the OEM code page"},
		{"gpo_report", "gpresult writes UTF-8"},
		{"cert_pulse", "certutil writes ANSI"},
	}
	for _, c := range cases {
		t.Run(c.cmd, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
			defer cancel()

			// The error is not the subject: gpo_report and cert_pulse need
			// elevation and fail for an unprivileged test run. Their *output*
			// is still the tool's own localized text, which is what is checked.
			out, err := RunMaintenance(ctx, c.cmd)
			if strings.TrimSpace(out) == "" {
				t.Fatalf("no output (err = %v)", err)
			}
			// The failure this guards (%s): decoding through the wrong code
			// page turns every accented character into U+FFFD or into two
			// glyphs, and the console shows the result verbatim.
			if strings.ContainsRune(out, '\uFFFD') {
				t.Errorf("replacement characters in output — %s:\n%s", c.why, out)
			}
			if strings.ContainsRune(out, '\x00') {
				t.Errorf("NUL bytes in output:\n%s", out)
			}
		})
	}
}

func TestRunMaintenanceRejectsUnknownType(t *testing.T) {
	if _, err := RunMaintenance(context.Background(), "reboot"); err == nil {
		t.Error("a type outside the catalogue must not run")
	}
}

// The catalogue's executables must exist where the agent looks for them —
// System32 and nowhere else, since PATH is deliberately not consulted.
func TestCatalogueExecutablesResolveUnderSystem32(t *testing.T) {
	for name, spec := range maintenanceCatalogue {
		if spec.native {
			continue
		}
		path := system32Path(spec.exe)
		if !strings.HasSuffix(strings.ToLower(path), strings.ToLower(spec.exe)) {
			t.Errorf("%s: unexpected resolved path %q", name, path)
		}
		if !strings.Contains(strings.ToLower(path), `system32`) {
			t.Errorf("%s: %q is not under System32", name, path)
		}
	}
}

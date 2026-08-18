package collector

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Real runs against the real Windows of whoever runs the suite, in the same
// spirit as the maintenance ones: the pure tests prove the parsing, these prove
// it was wired to what PowerShell and WUA actually produce.

// The JSON wrapper is the piece the pure tests cannot reach, and it carries two
// traps at once: the console code page mangling accented titles, and Out-String
// wrapping a long line — an update title easily outruns the host's width, and a
// JSON document broken at column 120 is not a JSON document.
func TestRunPowerShellJSONSurvivesLongAccentedText(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	long := strings.Repeat("Mise à jour cumulative pour Windows 11 — ", 20)
	script := "@{ title = '" + long + "'; nested = @(@{ kb = @('5063878') }) }"

	out, err := runPowerShellJSON(ctx, script)
	if err != nil {
		t.Fatalf("runPowerShellJSON: %v", err)
	}

	var got struct {
		Title  string `json:"title"`
		Nested []struct {
			KB []string `json:"kb"`
		} `json:"nested"`
	}
	if err := json.Unmarshal(out, &got); err != nil {
		t.Fatalf("output is not valid JSON (%v):\n%s", err, out)
	}
	if got.Title != long {
		t.Errorf("title did not survive intact:\n got %q\nwant %q", got.Title, long)
	}
	// -Depth: the default of 2 would render this nested array as a type name.
	if len(got.Nested) != 1 || len(got.Nested[0].KB) != 1 || got.Nested[0].KB[0] != "5063878" {
		t.Errorf("nested arrays did not survive: %+v", got.Nested)
	}
}

// A failing script must fail the call rather than return half a document: the
// parser downstream would otherwise report a WUA outage as malformed JSON.
func TestRunPowerShellJSONReportsFailures(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	_, err := runPowerShellJSON(ctx, "throw 'Exception from HRESULT: 0x80070422'")
	if err == nil {
		t.Fatal("expected an error")
	}
	if !strings.Contains(err.Error(), "0x80070422") {
		t.Errorf("the failure detail was lost: %v", err)
	}
	// And the hint layer must read that code back out of it.
	if hint := wuErrorHint(err.Error()); hint == "" {
		t.Errorf("no hint derived from %v", err)
	}
}

// Both scripts are parsed by PowerShell itself, without being run.
//
// The install script's install branch cannot be exercised without actually
// patching the machine, so this is what stands between a typo in it and an
// administrator meeting that typo on a production poste: a syntax error would
// fail the command with a PowerShell parse message instead of a Windows Update
// one, minutes after it was triggered.
func TestWUScriptsAreValidPowerShell(t *testing.T) {
	scripts := map[string]string{
		"collect": wuCollectScript,
		"install": wuInstallScript,
	}
	for name, script := range scripts {
		for _, drivers := range []bool{false, true} {
			path := filepath.Join(t.TempDir(), "script.ps1")
			if err := os.WriteFile(path, []byte(buildWUScript(script, drivers)), 0o600); err != nil {
				t.Fatalf("write script: %v", err)
			}
			check := "$errors = $null; " +
				"[void][System.Management.Automation.Language.Parser]::ParseFile(" +
				"'" + path + "', [ref]$null, [ref]$errors); " +
				"if ($errors.Count) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"

			ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
			out, err := exec.CommandContext(ctx, "powershell", "-NoProfile",
				"-NonInteractive", "-Command", check).CombinedOutput()
			cancel()
			if err != nil {
				t.Errorf("%s script (drivers=%v) does not parse:\n%s", name, drivers, out)
			}
		}
	}
}

// The collection script against the machine's own WUA. Slow — a search runs to
// minutes on a poste that is behind — so it is opt-in via TIAI_WU_LIVE=1 rather
// than run on every `go test`.
func TestReadWUStateLive(t *testing.T) {
	if os.Getenv("TIAI_WU_LIVE") != "1" {
		t.Skip("set TIAI_WU_LIVE=1 to search Windows Update on this machine")
	}

	ctx, cancel := context.WithTimeout(context.Background(), wuSearchTimeout)
	defer cancel()

	state, err := ReadWUState(ctx)
	if err != nil {
		t.Fatalf("ReadWUState: %v", err)
	}
	if state.Pending == nil {
		t.Error("pending must be an empty slice, never nil")
	}
	t.Logf("reboot_required=%v last_search=%v pending=%d",
		state.RebootRequired, state.LastSearchTime, len(state.Pending))
	for _, u := range state.Pending {
		if u.UpdateID == "" {
			t.Error("an update reached the wire with no id")
		}
		if strings.ContainsRune(u.Title, '�') {
			t.Errorf("replacement characters in a title: %q", u.Title)
		}
		t.Logf("  %-14s %-9s %-10s %s", u.KB, u.Type, u.Severity, u.Title)
	}
}

package collector

import (
	"strings"
	"testing"
)

// --- Search criteria --------------------------------------------------------

// The criteria string is the only thing that differs between wu_install and
// wu_install_full, so it is the one place a mistake would silently install
// drivers on a parc that asked for software only.
func TestSearchCriteriaFiltersDrivers(t *testing.T) {
	software := wuSearchCriteria(false)
	if !strings.Contains(software, "Type='Software'") {
		t.Errorf("software-only criteria must exclude drivers, got %q", software)
	}
	full := wuSearchCriteria(true)
	if strings.Contains(full, "Type=") {
		t.Errorf("full criteria must not filter on type, got %q", full)
	}
	for _, c := range []string{software, full} {
		if !strings.Contains(c, "IsInstalled=0") || !strings.Contains(c, "IsHidden=0") {
			t.Errorf("criteria must ask for pending, non-hidden updates, got %q", c)
		}
	}
}

// The placeholder is substituted in Go, before PowerShell ever sees the script:
// one left behind would reach the shell as an undefined variable and search on
// an empty criteria string, which WUA rejects.
func TestBuildWUScriptSubstitutesTheCriteria(t *testing.T) {
	for _, script := range []string{wuCollectScript, wuInstallScript} {
		if !strings.Contains(script, "$CRITERIA") {
			t.Fatal("script no longer carries the criteria placeholder")
		}
		for _, drivers := range []bool{false, true} {
			built := buildWUScript(script, drivers)
			if strings.Contains(built, "$CRITERIA") {
				t.Error("placeholder survived substitution")
			}
			// Quotes doubled, PowerShell-style: the software-only criteria
			// contains its own (Type='Software'), and pasting it in raw closes
			// the literal mid-string — the script then does not parse at all.
			want := "'" + strings.ReplaceAll(wuSearchCriteria(drivers), "'", "''") + "'"
			if !strings.Contains(built, want) {
				t.Errorf("built script does not carry %s", want)
			}
		}
	}
}

// --- Parsing a collection ---------------------------------------------------

const collectFixture = `{
  "reboot_required": true,
  "last_search_time": "2026-08-13T04:00:00Z",
  "last_install_time": "2026-08-01T03:12:00Z",
  "updates": [
    {
      "update_id": "e6cf1350-c01b-414d-a61f-263d14d133b4",
      "revision": 201,
      "title": "  2026-08 Mise à jour cumulative pour Windows 11  ",
      "severity": "Critical",
      "type_id": 1,
      "categories": ["Security Updates", "Windows 11"],
      "kb_article_ids": ["5063878"],
      "is_downloaded": true,
      "size_bytes": 650854400
    },
    {
      "update_id": "8f1b1e4c-0000-4000-8000-000000000001",
      "revision": 1,
      "title": "Intel - Display - 31.0.101.5333",
      "severity": "",
      "type_id": 2,
      "categories": ["Drivers"],
      "kb_article_ids": [],
      "is_downloaded": false,
      "size_bytes": 0
    }
  ]
}`

func TestParseWUState(t *testing.T) {
	state, err := parseWUState([]byte(collectFixture))
	if err != nil {
		t.Fatalf("parseWUState: %v", err)
	}
	if !state.RebootRequired {
		t.Error("reboot_required lost")
	}
	if state.LastSearchTime == nil || state.LastSearchTime.Format("2006-01-02") != "2026-08-13" {
		t.Errorf("last search time = %v", state.LastSearchTime)
	}
	if state.LastInstallTime == nil {
		t.Error("last install time lost")
	}
	if len(state.Pending) != 2 {
		t.Fatalf("expected 2 pending updates, got %d", len(state.Pending))
	}

	cumulative := state.Pending[0]
	// The revision is part of the key: a revised update is a different thing to
	// install, and the server deduplicates on this string.
	if cumulative.UpdateID != "e6cf1350-c01b-414d-a61f-263d14d133b4.201" {
		t.Errorf("update id = %q", cumulative.UpdateID)
	}
	if cumulative.KB != "KB5063878" {
		t.Errorf("kb = %q, want the KB prefix added", cumulative.KB)
	}
	if cumulative.Title != "2026-08 Mise à jour cumulative pour Windows 11" {
		t.Errorf("title = %q, want it trimmed", cumulative.Title)
	}
	if cumulative.Severity != "critical" {
		t.Errorf("severity = %q, want it lowercased", cumulative.Severity)
	}
	if cumulative.Type != updateTypeSoftware {
		t.Errorf("type = %q", cumulative.Type)
	}
	if cumulative.SizeMB == nil || *cumulative.SizeMB != 620.7 {
		t.Errorf("size = %v MB, want 620.7", cumulative.SizeMB)
	}

	driver := state.Pending[1]
	if driver.Type != updateTypeDriver {
		t.Errorf("driver type = %q", driver.Type)
	}
	if driver.KB != "" {
		t.Errorf("kb = %q, want empty for a driver with no article", driver.KB)
	}
	if driver.Severity != "" {
		t.Errorf("severity = %q, want empty rather than an invented rating", driver.Severity)
	}
	// nil, not 0: WUA reporting no size is not a claim that the update is empty.
	if driver.SizeMB != nil {
		t.Errorf("size = %v, want nil when WUA reports none", *driver.SizeMB)
	}
}

// A machine with nothing pending is the normal, healthy case — and the report
// that clears the server's stored set, so the list must be present and empty
// rather than nil (which would marshal as JSON null).
func TestParseWUStateEmptyIsNotNil(t *testing.T) {
	state, err := parseWUState([]byte(`{"reboot_required":false,"updates":[]}`))
	if err != nil {
		t.Fatalf("parseWUState: %v", err)
	}
	if state.Pending == nil {
		t.Fatal("pending must be an empty slice, never nil")
	}
	if len(state.Pending) != 0 {
		t.Errorf("expected no pending updates, got %d", len(state.Pending))
	}
	if state.LastSearchTime != nil || state.LastInstallTime != nil {
		t.Error("absent dates must stay nil")
	}
}

// Fields the script could not fill must cost themselves and nothing else: a
// poste with an odd WUA build still reports the updates it did manage to read.
func TestParseWUStateToleratesMissingFields(t *testing.T) {
	const partial = `{
      "updates": [
        {"update_id": "only-an-id"},
        {"update_id": "  ", "title": "no id, dropped"},
        {"title": "no id at all, dropped"}
      ],
      "last_search_time": "not a date",
      "last_install_time": null
    }`
	state, err := parseWUState([]byte(partial))
	if err != nil {
		t.Fatalf("parseWUState: %v", err)
	}
	if len(state.Pending) != 1 {
		t.Fatalf("expected the one keyed update, got %d", len(state.Pending))
	}
	u := state.Pending[0]
	if u.UpdateID != "only-an-id" {
		t.Errorf("update id = %q", u.UpdateID)
	}
	// No revision reported: the bare id, not a misleading ".0".
	if u.Type != updateTypeSoftware {
		t.Errorf("type = %q, want the software default", u.Type)
	}
	if state.LastSearchTime != nil {
		t.Error("an unparseable date must degrade to nil, not to year one")
	}
}

func TestParseWUStateRejectsGarbage(t *testing.T) {
	if _, err := parseWUState([]byte("not json at all")); err == nil {
		t.Error("expected an error on unparseable output")
	}
}

// --- Mappings ---------------------------------------------------------------

func TestFormatKB(t *testing.T) {
	cases := []struct {
		name string
		ids  []string
		want string
	}{
		{"bare digits gain the prefix", []string{"5063878"}, "KB5063878"},
		{"an existing prefix is not doubled", []string{"KB5063878"}, "KB5063878"},
		{"lowercase is normalised", []string{"kb5063878"}, "KB5063878"},
		{"several are all kept", []string{"5063878", "5062660"}, "KB5063878, KB5062660"},
		{"none is empty, not KB", nil, ""},
		{"blanks are dropped", []string{"", "  "}, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := formatKB(c.ids); got != c.want {
				t.Errorf("formatKB(%v) = %q, want %q", c.ids, got, c.want)
			}
		})
	}
}

func TestMapUpdateType(t *testing.T) {
	if got := mapUpdateType(wuTypeIDDriver, nil); got != updateTypeDriver {
		t.Errorf("type id 2 = %q", got)
	}
	if got := mapUpdateType(wuTypeIDSoftware, []string{"Drivers"}); got != updateTypeSoftware {
		t.Errorf("the type id must win over the category, got %q", got)
	}
	// The fallback that matters: a WUA build that did not marshal the enum would
	// otherwise file every driver as software, and wu_install would install them.
	if got := mapUpdateType(0, []string{"Drivers"}); got != updateTypeDriver {
		t.Errorf("category fallback = %q, want driver", got)
	}
	if got := mapUpdateType(0, []string{"Security Updates"}); got != updateTypeSoftware {
		t.Errorf("default = %q, want software", got)
	}
}

func TestBytesToMB(t *testing.T) {
	if mb := bytesToMB(0); mb != nil {
		t.Errorf("zero must read as unknown, got %v", *mb)
	}
	if mb := bytesToMB(-1); mb != nil {
		t.Errorf("a negative size must read as unknown, got %v", *mb)
	}
	mb := bytesToMB(1024 * 1024)
	if mb == nil || *mb != 1 {
		t.Errorf("1 MiB = %v, want 1", mb)
	}
	mb = bytesToMB(1024 * 1024 * 3 / 2)
	if mb == nil || *mb != 1.5 {
		t.Errorf("1.5 MiB = %v, want 1.5", mb)
	}
	// A driver extension of a few kilobytes is a real download, and rendering it
	// as "0 Mio" next to a Télécharger icon reads as a bug.
	mb = bytesToMB(20 * 1024)
	if mb == nil || *mb != 0.1 {
		t.Errorf("20 KiB = %v, want the 0.1 floor", mb)
	}
}

func TestParseWUTimeRejectsTheNeverDate(t *testing.T) {
	if parseWUTime("") != nil {
		t.Error("an empty date must be nil")
	}
	if got := parseWUTime("2026-08-13T04:00:00Z"); got == nil || got.Year() != 2026 {
		t.Errorf("parseWUTime = %v", got)
	}
}

// --- Install summaries ------------------------------------------------------

func TestSummarizeInstallSuccess(t *testing.T) {
	const result = `{
      "selected": 2, "installed": 2, "skipped_interactive": 0,
      "result_code": 2, "reboot_required": true,
      "updates": [
        {"title": "Cumulative", "kb_article_ids": ["5063878"], "result_code": 2, "hresult": 0},
        {"title": "Defender", "kb_article_ids": ["2267602"], "result_code": 3, "hresult": 0}
      ]
    }`
	output, err := summarizeInstall([]byte(result))
	if err != nil {
		t.Fatalf("a batch where everything applied must succeed: %v", err)
	}
	if !strings.Contains(output, "KB5063878") || !strings.Contains(output, "installée") {
		t.Errorf("output does not name what was installed:\n%s", output)
	}
	// Succeeded-with-errors is still installed — reported, not failed.
	if !strings.Contains(output, "installée avec des erreurs") {
		t.Errorf("partial success not reported:\n%s", output)
	}
	if !strings.Contains(output, "Redémarrage requis") {
		t.Errorf("a pending restart must be announced:\n%s", output)
	}
}

func TestSummarizeInstallFailureKeepsTheBreakdown(t *testing.T) {
	const result = `{
      "selected": 2, "installed": 2, "skipped_interactive": 0,
      "result_code": 4, "reboot_required": false,
      "updates": [
        {"title": "Cumulative", "kb_article_ids": ["5063878"], "result_code": 2, "hresult": 0},
        {"title": "Broken", "kb_article_ids": ["5062660"], "result_code": 4, "hresult": -2145124329}
      ]
    }`
	output, err := summarizeInstall([]byte(result))
	if err == nil {
		t.Fatal("a failed update must fail the command")
	}
	// The per-KB list is the useful part and must survive the failure — without
	// it an admin is sent back to the machine's own WU log.
	if !strings.Contains(output, "KB5063878 — Cumulative : installée") {
		t.Errorf("the successful update disappeared from the summary:\n%s", output)
	}
	// HRESULT in hex: 0x80240017 is searchable, 2149842967 is not.
	if !strings.Contains(output, "0x80240017") {
		t.Errorf("expected the HRESULT in hex:\n%s", output)
	}
}

func TestSummarizeInstallNothingApplicable(t *testing.T) {
	output, err := summarizeInstall([]byte(`{"selected":0,"installed":0,"updates":[]}`))
	if err != nil {
		t.Fatalf("an up-to-date machine is a success, not a failure: %v", err)
	}
	if !strings.Contains(output, "à jour") {
		t.Errorf("output = %q", output)
	}
}

func TestSummarizeInstallReportsSkippedAndUndownloaded(t *testing.T) {
	const result = `{
      "selected": 3, "installed": 1, "skipped_interactive": 2,
      "result_code": 2, "reboot_required": false,
      "updates": [
        {"title": "Cumulative", "kb_article_ids": ["5063878"], "result_code": 2, "hresult": 0}
      ]
    }`
	output, err := summarizeInstall([]byte(result))
	// Two selected updates never reached the installer: their download failed,
	// and WUA reports no per-update result for them — counting them is the only
	// thing that keeps them from vanishing silently.
	if err == nil {
		t.Fatal("updates that never installed must fail the command")
	}
	if !strings.Contains(output, "téléchargée") {
		t.Errorf("undownloaded updates not reported:\n%s", output)
	}
	if !strings.Contains(output, "interaction utilisateur") {
		t.Errorf("interactive updates not reported:\n%s", output)
	}
}

func TestSummarizeInstallRejectsGarbage(t *testing.T) {
	if _, err := summarizeInstall([]byte("{oops")); err == nil {
		t.Error("expected an error on unparseable output")
	}
}

// --- Failure hints ----------------------------------------------------------

func TestWUErrorHint(t *testing.T) {
	cases := map[string]string{
		"Exception from HRESULT: 0x80070422": "wuauserv",
		"Exception from HRESULT: 0x8024402C": "WSUS",
		"Exception from HRESULT: 0x80240016": "TrustedInstaller",
	}
	for message, want := range cases {
		if hint := wuErrorHint(message); !strings.Contains(hint, want) {
			t.Errorf("wuErrorHint(%q) = %q, want it to mention %q", message, hint, want)
		}
	}
	// Undocumented codes are reported raw rather than guessed at — the same
	// discipline as the maintenance verdicts.
	if hint := wuErrorHint("Exception from HRESULT: 0x8007DEAD"); hint != "" {
		t.Errorf("an unknown code must get no invented diagnosis, got %q", hint)
	}
}

func TestWrapWUErrorKeepsTheOriginal(t *testing.T) {
	if wrapWUError(nil) != nil {
		t.Error("nil must stay nil")
	}
	wrapped := wrapWUError(errString("powershell: Exception from HRESULT: 0x80070422"))
	if !strings.Contains(wrapped.Error(), "0x80070422") {
		t.Errorf("the raw code must survive the hint: %v", wrapped)
	}
	if !strings.Contains(wrapped.Error(), "désactivé") {
		t.Errorf("the hint is missing: %v", wrapped)
	}
}

type errString string

func (e errString) Error() string { return string(e) }

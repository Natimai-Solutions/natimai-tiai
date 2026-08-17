package collector

import (
	"strings"
	"testing"
	"unicode/utf16"
)

// catalogueTypes is the catalogue as documented in plan-commandes-distantes.md
// §2, spelled out here rather than derived from the map. The point of a closed
// catalogue is that its contents are a deliberate decision: a type appearing or
// disappearing should cost an edit in this list too, and the backend enum has
// the same guard on its side.
var catalogueTypes = []string{
	"gpo_update",
	"flush_dns",
	"time_resync",
	"cert_pulse",
	"spooler_reset",
	"sfc_scan",
	"dism_restore_health",
	"dism_component_cleanup",
	"chkdsk_scan",
	"gpo_report",
	"net_config",
}

func TestCatalogueMatchesTheDocumentedSet(t *testing.T) {
	if len(maintenanceCatalogue) != len(catalogueTypes) {
		t.Fatalf("catalogue has %d entries, documented set has %d",
			len(maintenanceCatalogue), len(catalogueTypes))
	}
	for _, name := range catalogueTypes {
		if _, ok := maintenanceCatalogue[name]; !ok {
			t.Errorf("catalogue is missing %q", name)
		}
	}
}

// Every entry has to be executable: a spec with no timeout would run forever on
// the single command worker, and one with no verdict would panic on a nil call
// the first time an admin triggered it.
func TestCatalogueEntriesAreWellFormed(t *testing.T) {
	for name, spec := range maintenanceCatalogue {
		if spec.timeout <= 0 {
			t.Errorf("%s: no timeout", name)
		}
		if spec.verdict == nil {
			t.Errorf("%s: no verdict function", name)
		}
		if spec.native {
			if spec.exe != "" || len(spec.args) != 0 {
				t.Errorf("%s: native entry must carry no executable", name)
			}
			continue
		}
		if spec.exe == "" {
			t.Errorf("%s: no executable", name)
		}
		// Resolved against System32, so a path separator here would either
		// escape that directory or produce nonsense.
		if strings.ContainsAny(spec.exe, `\/`) {
			t.Errorf("%s: executable %q must be a bare file name", name, spec.exe)
		}
	}
}

// The `long` flag drives the intermediate `running` post, so it must track the
// timeout class: a command announced as long but capped at five minutes would
// be killed while the console still shows it running.
func TestLongCommandsGetLongTimeouts(t *testing.T) {
	for name, spec := range maintenanceCatalogue {
		if spec.long && spec.timeout <= shortTimeout {
			t.Errorf("%s: marked long but timeout is %s", name, spec.timeout)
		}
		if !spec.long && spec.timeout > shortTimeout {
			t.Errorf("%s: timeout is %s but not marked long", name, spec.timeout)
		}
	}
}

// The per-tool encodings were measured on a real Windows, not guessed (see
// toolEncoding). Pinning them here means a change has to be a deliberate
// re-measurement rather than a drive-by edit.
func TestCatalogueEncodingsArePinned(t *testing.T) {
	special := map[string]toolEncoding{
		"cert_pulse": encANSI,
		"sfc_scan":   encUTF16LE,
	}
	for name, spec := range maintenanceCatalogue {
		want, ok := special[name]
		if !ok {
			want = encOEM
		}
		if spec.enc != want {
			t.Errorf("%s: encoding = %d, want %d", name, spec.enc, want)
		}
	}
}

func TestLookupMaintenance(t *testing.T) {
	if _, ok := LookupMaintenance("update_signatures"); ok {
		t.Error("Defender commands must not resolve through the maintenance catalogue")
	}
	if _, ok := LookupMaintenance("rm -rf /"); ok {
		t.Error("an unknown type must not resolve")
	}
	info, ok := LookupMaintenance("sfc_scan")
	if !ok || !info.Long {
		t.Errorf("sfc_scan = %+v, %v; want long", info, ok)
	}
	info, ok = LookupMaintenance("flush_dns")
	if !ok || info.Long {
		t.Errorf("flush_dns = %+v, %v; want short", info, ok)
	}
}

// --- Output normalisation ---------------------------------------------------

func TestNormalizeConsoleOutputCollapsesProgressRedraws(t *testing.T) {
	// What dism actually writes: one line redrawn with carriage returns.
	raw := "Version : 10.0.26100.1\r\n\r\n" +
		"Image Version: 10.0.26100.1\r\n\r\n" +
		"[=====                      10.0%                          ]" +
		"\r[==========                 20.0%                          ]" +
		"\r[==========================100.0%==========================]\r\n" +
		"L'opération a réussi.\r\n"

	got := normalizeConsoleOutput(raw)
	if strings.Contains(got, "10.0%") || strings.Contains(got, "20.0%") {
		t.Errorf("overwritten progress frames survived:\n%s", got)
	}
	if !strings.Contains(got, "100.0%") {
		t.Errorf("final progress frame lost:\n%s", got)
	}
	if !strings.Contains(got, "L'opération a réussi.") {
		t.Errorf("verdict lost:\n%s", got)
	}
	// A CRLF-terminated line must survive whole: an earlier version of this
	// collapsed on the \r of \r\n and silently deleted every line.
	if !strings.Contains(got, "Image Version: 10.0.26100.1") {
		t.Errorf("CRLF line mangled:\n%s", got)
	}
}

func TestNormalizeConsoleOutputCollapsesBlankRuns(t *testing.T) {
	got := normalizeConsoleOutput("\r\n\r\nCarte Ethernet :\r\n\r\n\r\n\r\n   Suffixe DNS. . : lan\r\n\r\n")
	want := "Carte Ethernet :\n\n   Suffixe DNS. . : lan"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestLastSignificantLine(t *testing.T) {
	cases := map[string]string{
		"a\nb\nc\n\n  \n": "c",
		"seule":           "seule",
		"":                "",
		"\n\n":            "",
	}
	for in, want := range cases {
		if got := lastSignificantLine(in); got != want {
			t.Errorf("lastSignificantLine(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestTruncateOutputKeepsHeadAndMarks(t *testing.T) {
	if got := truncateOutput("court", 1024); got != "court" {
		t.Errorf("short output must pass through, got %q", got)
	}

	long := strings.Repeat("a", 4096)
	got := truncateOutput(long, 1024)
	if !strings.HasPrefix(got, strings.Repeat("a", 1024)) {
		t.Error("head was not preserved")
	}
	if !strings.Contains(got, "tronquée") {
		t.Errorf("no truncation marker: %q", got[len(got)-60:])
	}
}

// Cutting a French diagnostic dump at an arbitrary byte offset must not leave
// half a rune behind — the console renders the column verbatim.
func TestTruncateOutputDoesNotSplitRunes(t *testing.T) {
	// "é" is two bytes: a limit of 5 lands inside the third one.
	got := truncateOutput("ééé", 5)
	if !strings.HasPrefix(got, "éé") {
		t.Errorf("got %q, want it to start with two complete runes", got)
	}
	if strings.ContainsRune(got, '�') {
		t.Errorf("truncation produced a replacement character: %q", got)
	}
}

// --- sfc's UTF-16 output ----------------------------------------------------

// encodeUTF16LE builds the NUL-interleaved bytes sfc writes, so the test feeds
// the decoder the same shape a real capture has.
func encodeUTF16LE(s string, bom bool) []byte {
	var out []byte
	if bom {
		out = append(out, 0xff, 0xfe)
	}
	for _, u := range utf16.Encode([]rune(s)) {
		out = append(out, byte(u), byte(u>>8))
	}
	return out
}

// The tools disagree on encoding (ipconfig OEM, certutil ANSI, gpresult UTF-8),
// so the one encoding that identifies itself has to be recognised — otherwise
// gpresult's output is decoded as CP850 and every accent becomes two glyphs.
func TestIsProbablyUTF8(t *testing.T) {
	cases := []struct {
		name string
		in   []byte
		want bool
	}{
		{"gpresult (utf-8)", []byte("Accès refusé."), true},
		// "Accès refusé." as CP850 and as CP1252: neither forms valid UTF-8.
		{"ipconfig (cp850)", []byte{'A', 'c', 'c', 0x8a, 's', ' ', 'r', 'e', 'f', 'u', 's', 0x82}, false},
		{"certutil (cp1252)", []byte{'A', 'c', 'c', 0xe8, 's', ' ', 'r', 'e', 'f', 'u', 's', 0xe9}, false},
		// Decodes the same either way, so it is left to the code-page branch.
		{"pure ascii", []byte("Windows IP Configuration"), false},
		{"empty", nil, false},
	}
	for _, c := range cases {
		if got := isProbablyUTF8(c.in); got != c.want {
			t.Errorf("%s: isProbablyUTF8 = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestFormatExitCode(t *testing.T) {
	// A small code stays readable as a decimal…
	if got := formatExitCode(3010); got != "3010" {
		t.Errorf("got %q, want %q", got, "3010")
	}
	// …while an HRESULT is only recognisable in hex: 2147942405 says nothing,
	// 0x80070005 says "access denied".
	if got := formatExitCode(2147942405); got != "0x80070005" {
		t.Errorf("got %q, want %q", got, "0x80070005")
	}
}

func TestLooksUTF16LE(t *testing.T) {
	cases := []struct {
		name string
		in   []byte
		want bool
	}{
		{"sfc capture", encodeUTF16LE("La protection des ressources Windows", false), true},
		{"with BOM", encodeUTF16LE("ok", true), true},
		{"plain console text", []byte("Configuration IP de Windows\r\n\r\n   Nom de l'hôte"), false},
		{"empty", nil, false},
		{"too short", []byte{0x41, 0x00}, false},
	}
	for _, c := range cases {
		if got := looksUTF16LE(c.in); got != c.want {
			t.Errorf("%s: looksUTF16LE = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestDecodeUTF16LE(t *testing.T) {
	const text = "La protection des ressources Windows n'a trouvé aucune violation d'intégrité."
	for _, bom := range []bool{false, true} {
		if got := decodeUTF16LE(encodeUTF16LE(text, bom)); got != text {
			t.Errorf("bom=%v: got %q, want %q", bom, got, text)
		}
	}
	// A capture cut mid-unit must still yield readable text rather than panic.
	b := encodeUTF16LE("abc", false)
	if got := decodeUTF16LE(b[:len(b)-1]); got != "ab" {
		t.Errorf("odd-length input: got %q, want %q", got, "ab")
	}
}

// The whole point of the UTF-16 branch: an sfc verdict must arrive readable,
// not as text with a NUL between every character.
func TestSFCPipelineProducesReadableText(t *testing.T) {
	raw := encodeUTF16LE(
		"\rVérification 40 % terminée.\rVérification 100 % terminée.\r\n"+
			"La protection des ressources Windows n'a trouvé aucune violation d'intégrité.\r\n",
		false)
	if !looksUTF16LE(raw) {
		t.Fatal("fixture is not detected as UTF-16LE")
	}
	got := normalizeConsoleOutput(decodeUTF16LE(raw))
	if strings.Contains(got, "\x00") {
		t.Error("NUL bytes survived decoding")
	}
	if strings.Contains(got, "40 %") {
		t.Errorf("overwritten progress survived:\n%s", got)
	}
	if lastSignificantLine(got) != "La protection des ressources Windows n'a trouvé aucune violation d'intégrité." {
		t.Errorf("verdict line not recoverable:\n%s", got)
	}
}

// --- Verdicts ---------------------------------------------------------------

func TestVerdictExitCode(t *testing.T) {
	if out, err := verdictExitCode(0, "ok"); err != nil || out != "ok" {
		t.Errorf("exit 0 = %q, %v; want success", out, err)
	}
	out, err := verdictExitCode(2, "détail utile")
	if err == nil {
		t.Fatal("non-zero exit must fail")
	}
	// The output travels with the failure: for these tools it is the explanation.
	if out != "détail utile" {
		t.Errorf("output dropped on failure: %q", out)
	}
	if !strings.Contains(err.Error(), "2") {
		t.Errorf("error should name the code: %v", err)
	}
}

func TestVerdictSFCQuotesTheLocalizedVerdict(t *testing.T) {
	const verdict = "La protection des ressources Windows a trouvé des fichiers endommagés " +
		"mais n'a pas pu en réparer certains."
	_, err := verdictSFC(1, "Début de l'analyse\n"+verdict)
	if err == nil {
		t.Fatal("non-zero exit must fail")
	}
	if !strings.Contains(err.Error(), verdict) {
		t.Errorf("verdict line not surfaced: %v", err)
	}
	if _, err := verdictSFC(0, "aucune violation"); err != nil {
		t.Errorf("exit 0 must succeed, got %v", err)
	}
}

func TestVerdictDISMSourceMissingIsActionable(t *testing.T) {
	raw := "Erreur : 0x800f081f\n\nLes fichiers sources sont introuvables."
	_, err := verdictDISM(1, raw)
	if err == nil {
		t.Fatal("a missing repair source must fail")
	}
	// The point is that the message says what to fix, not what dism printed.
	for _, want := range []string{"source de réparation inaccessible", "WSUS"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("message %q missing %q", err.Error(), want)
		}
	}
}

func TestVerdictDISMRebootRequiredIsASuccess(t *testing.T) {
	out, err := verdictDISM(dismRebootRequired, "L'opération a réussi.")
	if err != nil {
		t.Fatalf("3010 must be a success, got %v", err)
	}
	if !strings.Contains(out, "Redémarrage requis") {
		t.Errorf("reboot notice missing from output: %q", out)
	}
}

func TestVerdictDISMPlainFailure(t *testing.T) {
	if _, err := verdictDISM(0, "L'opération a réussi."); err != nil {
		t.Errorf("exit 0 must succeed, got %v", err)
	}
	if _, err := verdictDISM(87, "paramètre incorrect"); err == nil {
		t.Error("non-zero exit must fail")
	}
}

func TestVerdictChkdsk(t *testing.T) {
	if _, err := verdictChkdsk(0, ""); err != nil {
		t.Errorf("exit 0 must succeed, got %v", err)
	}
	_, err := verdictChkdsk(1, "")
	if err == nil {
		t.Fatal("errors found must be reported as a failure")
	}
	if !strings.Contains(err.Error(), "spotfix") {
		t.Errorf("message should point at the offline repair: %v", err)
	}
	// An undocumented code is reported raw rather than mistranslated.
	_, err = verdictChkdsk(42, "")
	if err == nil || !strings.Contains(err.Error(), "42") {
		t.Errorf("unknown code should surface as-is, got %v", err)
	}
}

func TestVerdictTimeResyncNamesTheStoppedService(t *testing.T) {
	_, err := verdictTimeResync(1, "Le service n'a pas été démarré. (0x80070426)")
	if err == nil {
		t.Fatal("a failed resync must fail")
	}
	if !strings.Contains(err.Error(), "W32Time") {
		t.Errorf("message should name the service to start: %v", err)
	}
	if _, err := verdictTimeResync(0, "La commande s'est terminée correctement."); err != nil {
		t.Errorf("exit 0 must succeed, got %v", err)
	}
}

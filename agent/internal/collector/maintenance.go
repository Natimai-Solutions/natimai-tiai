package collector

import (
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"
	"unicode/utf8"
)

// Remote maintenance and diagnostic commands (plan-commandes-distantes.md).
//
// The security model is the catalogue itself: the server sends a *type name*
// and nothing else — no arguments, no command line, no script. The executable
// and its fixed arguments live in the table below, inside the agent's own
// signed binary, so a compromised server can only ever trigger one of these
// eleven actions. Nothing here reads from the network, and nothing here should
// ever grow a parameter that does.
//
// Everything in this file is pure: the table, the output normalisation and the
// exit-code verdicts. Only the actual execution is Windows-specific
// (maintenance_windows.go), which keeps the interesting logic unit-testable on
// any platform — same split as the Defender and Security Center collectors.

// Timeout classes. A command that outlives its class is killed and reported as
// a timeout: leaving a dism running for a day would pin the (single) command
// worker and silently starve every later command for that machine.
const (
	// shortTimeout covers the commands that finish in seconds. Five minutes is
	// already generous — it is a hang detector, not a budget.
	shortTimeout = 5 * time.Minute
	// sfcTimeout: a full sfc /scannow runs ~10–20 min on a healthy machine, more
	// on a spinning disk.
	sfcTimeout = 30 * time.Minute
	// longTimeout: dism component cleanup and chkdsk /scan on a large volume.
	longTimeout = 1 * time.Hour
	// dismRestoreTimeout: /restorehealth downloads replacement payloads from
	// Windows Update or WSUS, which on a slow link is the dominant cost.
	dismRestoreTimeout = 2 * time.Hour
)

// maxOutputBytes bounds what one command sends back. Console tools are chatty
// (a gpresult /r on a machine with many GPOs runs to tens of kilobytes) and the
// text lands in a database column and then in a browser dialog. The server caps
// it again on receipt — this is the polite side of the same limit.
const maxOutputBytes = 64 * 1024

// toolEncoding is how a tool encodes what it writes to a redirected handle.
//
// There is no single answer, which is the whole reason this exists. Measured on
// a French Windows 11, capturing through a pipe: ipconfig and w32tm write the
// OEM code page (CP850 — 0x93 for "ô"), certutil writes ANSI (CP1252 — 0xE9 for
// "é", 0xA0 for a non-breaking space), gpresult writes UTF-8, and sfc writes
// NUL-interleaved UTF-16LE. Guessing one encoding for the lot turns half the
// catalogue's output into mojibake in the console.
//
// Note this is *not* the console's code page: GetConsoleOutputCP on that same
// machine reported 65001, while ipconfig still emitted CP850 — what a tool does
// when redirected does not depend on the terminal that launched it, and in
// production (a service) there is no terminal at all.
type toolEncoding int

const (
	// encOEM is the default and the common case: the system OEM code page.
	encOEM toolEncoding = iota
	// encANSI is the system ANSI code page (certutil).
	encANSI
	// encUTF16LE is NUL-interleaved UTF-16LE (sfc). Verified against the bytes
	// before being applied, never assumed.
	encUTF16LE
)

// maintenanceSpec is one catalogue entry: what to run, for how long, and how to
// read what came back.
type maintenanceSpec struct {
	// exe is a bare file name resolved against %SystemRoot%\System32 at run
	// time — never looked up in PATH. The agent runs as LocalSystem, so a
	// writable directory ahead of System32 in PATH would otherwise be a
	// straight path to SYSTEM code execution.
	exe  string
	args []string
	// native marks the one entry that is not an .exe call at all (spooler_reset,
	// driven through the service manager). exe is empty for it.
	native  bool
	timeout time.Duration
	// long marks a command worth announcing: the agent posts an intermediate
	// `running` status so the console shows "en cours" rather than "transmise"
	// for the tens of minutes these take.
	long bool
	// enc is how this tool encodes its redirected output. Zero value is encOEM,
	// which covers most of them.
	enc toolEncoding
	// verdict turns an exit code plus the collected output into the result the
	// console shows: a nil error means succeeded.
	verdict func(code int, output string) (string, error)
}

// maintenanceCatalogue is the closed set of remotely triggerable commands.
//
// Deliberately absent, and not to be reintroduced piecemeal: any free-form
// script runner, and anything that edits the registry, the filesystem, the
// firewall or local accounts. `netsh winsock reset` is also out for now — it
// needs a reboot behind it, so it belongs with the Phase 2 `reboot` command.
var maintenanceCatalogue = map[string]maintenanceSpec{
	// --- Maintenance -------------------------------------------------------

	// /target:computer, not a bare gpupdate: running as LocalSystem there is no
	// user hive to refresh, so only computer policy can apply. The console label
	// says so rather than letting an admin expect user policy to move.
	"gpo_update": {
		exe:     "gpupdate.exe",
		args:    []string{"/target:computer", "/force"},
		timeout: shortTimeout,
		verdict: verdictExitCode,
	},
	"flush_dns": {
		exe:     "ipconfig.exe",
		args:    []string{"/flushdns"},
		timeout: shortTimeout,
		verdict: verdictExitCode,
	},
	"time_resync": {
		exe:     "w32tm.exe",
		args:    []string{"/resync"},
		timeout: shortTimeout,
		verdict: verdictTimeResync,
	},
	// Forces an immediate certificate autoenrollment pass against the internal
	// CA — the fix for a machine whose certificate did not renew on its own.
	// The odd one out on encoding: certutil writes ANSI where its neighbours
	// write OEM.
	"cert_pulse": {
		exe:     "certutil.exe",
		args:    []string{"-pulse"},
		timeout: shortTimeout,
		enc:     encANSI,
		verdict: verdictExitCode,
	},
	"spooler_reset": {
		native:  true,
		timeout: shortTimeout,
		verdict: verdictExitCode,
	},
	"sfc_scan": {
		exe:     "sfc.exe",
		args:    []string{"/scannow"},
		timeout: sfcTimeout,
		long:    true,
		enc:     encUTF16LE,
		verdict: verdictSFC,
	},
	"dism_restore_health": {
		exe:     "dism.exe",
		args:    []string{"/online", "/cleanup-image", "/restorehealth"},
		timeout: dismRestoreTimeout,
		long:    true,
		verdict: verdictDISM,
	},
	"dism_component_cleanup": {
		exe:     "dism.exe",
		args:    []string{"/online", "/cleanup-image", "/startcomponentcleanup"},
		timeout: longTimeout,
		long:    true,
		verdict: verdictDISM,
	},
	// /scan is the *online* pass: it reports, it never repairs, so it is safe to
	// fire on a machine somebody is working on. Repairing needs /spotfix, which
	// takes the volume offline — out of catalogue on purpose.
	"chkdsk_scan": {
		exe:     "chkdsk.exe",
		args:    []string{"/scan"},
		timeout: longTimeout,
		long:    true,
		verdict: verdictChkdsk,
	},

	// --- Diagnostics (read-only) -------------------------------------------

	"gpo_report": {
		exe:     "gpresult.exe",
		args:    []string{"/r", "/scope:computer"},
		timeout: shortTimeout,
		verdict: verdictExitCode,
	},
	"net_config": {
		exe:     "ipconfig.exe",
		args:    []string{"/all"},
		timeout: shortTimeout,
		verdict: verdictExitCode,
	},
}

// MaintenanceInfo is what the polling loop needs to know about a command type
// it did not have to hard-code: that the catalogue holds it, and whether it
// runs long enough to be worth announcing.
type MaintenanceInfo struct {
	Long bool
}

// LookupMaintenance resolves a server-sent command type against the catalogue.
func LookupMaintenance(cmdType string) (MaintenanceInfo, bool) {
	spec, ok := maintenanceCatalogue[cmdType]
	if !ok {
		return MaintenanceInfo{}, false
	}
	return MaintenanceInfo{Long: spec.long}, true
}

// --- Output handling --------------------------------------------------------

// normalizeConsoleOutput renders a console tool's raw text the way a terminal
// would, then tidies it.
//
// dism and sfc report progress by redrawing one line with carriage returns
// ("\r[====      20.0%    ]"), which read as hundreds of duplicate lines once
// captured through a pipe. Replaying the overwrite — everything before the last
// \r on a line has been overwritten, so only the tail survives — collapses the
// whole progress animation to its final frame. That is exactly what a person
// watching the console would have seen, and unlike matching on "%" it depends
// on no language and no tool-specific format.
func normalizeConsoleOutput(s string) string {
	s = strings.ReplaceAll(s, "\r\n", "\n")

	out := make([]string, 0, 32)
	blank := false
	for _, line := range strings.Split(s, "\n") {
		if i := strings.LastIndex(line, "\r"); i >= 0 {
			line = line[i+1:]
		}
		line = strings.TrimRight(line, " \t")
		if line == "" {
			// One blank line separates sections (ipconfig /all leans on them);
			// a run of them is just the tool breathing.
			if blank {
				continue
			}
			blank = true
		} else {
			blank = false
		}
		out = append(out, line)
	}
	return strings.TrimSpace(strings.Join(out, "\n"))
}

// lastSignificantLine returns the last non-empty line, which for these tools is
// the verdict ("Windows Resource Protection did not find any integrity
// violations", localized). Empty when there is nothing to quote.
func lastSignificantLine(s string) string {
	lines := strings.Split(s, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		if t := strings.TrimSpace(lines[i]); t != "" {
			return t
		}
	}
	return ""
}

// truncateOutput caps the reported text, keeping the head.
//
// The head, not the tail: for the diagnostics (ipconfig /all, gpresult) the
// interesting part comes first, and for the long commands the verdict is lifted
// into the error message rather than left to survive at the end of a stream.
func truncateOutput(s string, max int) string {
	if len(s) <= max {
		return s
	}
	cut := s[:max]
	// Never leave half a multi-byte rune at the seam.
	for len(cut) > 0 {
		r, size := utf8.DecodeLastRuneInString(cut)
		if r != utf8.RuneError || size > 1 {
			break
		}
		cut = cut[:len(cut)-1]
	}
	return cut + fmt.Sprintf("\n[…] sortie tronquée à %d Kio par l'agent", max/1024)
}

// isProbablyUTF8 reports whether bytes should be read as UTF-8 rather than
// through a single-byte code page.
//
// This is what keeps the per-tool encoding table small: UTF-8 is
// self-identifying, so a tool that already writes it (gpresult) needs no entry
// and no maintenance. A lone CP850 or CP1252 accented byte — 0x82, 0xE9, 0x93 —
// is never the start of a well-formed multi-byte sequence, so code-page text
// essentially cannot pass this test.
//
// Pure ASCII deliberately does *not* pass: it decodes identically either way,
// and leaving it on the code-page path keeps one branch instead of two.
func isProbablyUTF8(b []byte) bool {
	if !utf8.Valid(b) {
		return false
	}
	for _, c := range b {
		if c >= 0x80 {
			return true
		}
	}
	return false
}

// looksUTF16LE reports whether b is the NUL-interleaved UTF-16LE that sfc
// writes to a redirected handle.
//
// Checked rather than assumed: the behaviour is a quirk of one tool on one
// platform, and misreading plain bytes as UTF-16 would produce Chinese
// characters instead of a verdict. A majority of NULs in the odd positions is
// conclusive enough for Latin-script output and costs one pass over a sample.
func looksUTF16LE(b []byte) bool {
	if len(b) < 4 {
		return false
	}
	if b[0] == 0xff && b[1] == 0xfe { // explicit BOM
		return true
	}
	n := len(b)
	if n > 512 {
		n = 512
	}
	nulls, odd := 0, 0
	for i := 1; i < n; i += 2 {
		odd++
		if b[i] == 0 {
			nulls++
		}
	}
	return odd > 0 && nulls*2 > odd
}

// decodeUTF16LE decodes NUL-interleaved UTF-16LE, tolerating a BOM and a
// trailing odd byte (a truncated capture must still yield readable text).
func decodeUTF16LE(b []byte) string {
	if len(b) >= 2 && b[0] == 0xff && b[1] == 0xfe {
		b = b[2:]
	}
	units := make([]uint16, 0, len(b)/2)
	for i := 0; i+1 < len(b); i += 2 {
		units = append(units, uint16(b[i])|uint16(b[i+1])<<8)
	}
	return string(utf16.Decode(units))
}

// --- Verdicts ---------------------------------------------------------------
//
// These messages are read by an administrator in the console, which is in
// French — unlike the log lines, which stay English like the rest of the code.
// The tool's own (localized) output always travels alongside, so the message's
// job is to say what to *do*, not to paraphrase what the tool printed.

// formatExitCode renders an exit code the way it can actually be looked up.
// Windows tools return HRESULTs, which arrive as a large unsigned decimal:
// "2147942405" is unsearchable where the same value written 0x80070005 is
// recognisable on sight (access denied) and the first hit in any search engine.
func formatExitCode(code int) string {
	if code < 0 || code > 0xffff {
		return fmt.Sprintf("0x%08x", uint32(code))
	}
	return strconv.Itoa(code)
}

// verdictExitCode is the default reading: zero succeeds, anything else fails.
// The code is reported raw rather than translated — these tools document their
// codes unevenly, and inventing a meaning would be worse than a number sitting
// next to the tool's own output.
func verdictExitCode(code int, output string) (string, error) {
	if code == 0 {
		return output, nil
	}
	return output, fmt.Errorf("code de retour %s", formatExitCode(code))
}

// verdictSFC reads sfc /scannow. The tool's wording *is* the verdict and it is
// localized, so the last significant line is quoted as-is rather than matched
// against English strings a French Windows never prints.
func verdictSFC(code int, output string) (string, error) {
	if code == 0 {
		return output, nil
	}
	if summary := lastSignificantLine(output); summary != "" {
		return output, fmt.Errorf("sfc a terminé en erreur (code %s) : %s",
			formatExitCode(code), summary)
	}
	return output, fmt.Errorf("sfc a terminé en erreur (code %s)", formatExitCode(code))
}

// dismSourceMissing is the HRESULT dism reports when it cannot reach the source
// holding the replacement payloads. In a managed parc this is the failure of
// /restorehealth: the machine is pointed at a WSUS server by GPO and that
// server carries no repair source. Worth naming, because dism's own wording
// sends the reader to a log file instead of to the actual cause.
const dismSourceMissing = "0x800f081f"

// dismRebootRequired is ERROR_SUCCESS_REBOOT_REQUIRED: the operation worked,
// the machine needs a restart to finish it. A success, not a failure — Phase 2
// owns the reboot command, so here it is only reported.
const dismRebootRequired = 3010

func verdictDISM(code int, output string) (string, error) {
	if strings.Contains(strings.ToLower(output), dismSourceMissing) {
		return output, fmt.Errorf(
			"source de réparation inaccessible (%s) : ce poste ne joint ni Windows Update "+
				"ni son serveur WSUS, ou la source de réparation n'y est pas publiée",
			dismSourceMissing)
	}
	switch code {
	case 0:
		return output, nil
	case dismRebootRequired:
		return output + "\n\nRedémarrage requis pour finaliser l'opération.", nil
	}
	return output, fmt.Errorf("dism a terminé en erreur (code %s)", formatExitCode(code))
}

// chkdskMeanings holds the exit codes Microsoft actually documents for chkdsk.
// Anything else is reported as a bare number rather than guessed at.
var chkdskMeanings = map[int]string{
	1: "des erreurs ont été trouvées",
	2: "le volume n'a pas pu être entièrement vérifié",
	3: "le volume n'a pas pu être vérifié",
}

// verdictChkdsk reads chkdsk /scan. The online scan only ever *reports*; any
// non-zero code therefore means the volume needs an offline pass, which is the
// actionable part and the only thing the message needs to convey.
func verdictChkdsk(code int, output string) (string, error) {
	if code == 0 {
		return output, nil
	}
	msg, known := chkdskMeanings[code]
	if !known {
		return output, fmt.Errorf("chkdsk a terminé avec le code %s", formatExitCode(code))
	}
	return output, fmt.Errorf(
		"chkdsk : %s (code %d) — une réparation hors ligne (chkdsk /spotfix, "+
			"appliquée au redémarrage) est nécessaire", msg, code)
}

// w32tmServiceStopped is the Win32 error (ERROR_SERVICE_NOT_ACTIVE) w32tm
// returns when the Windows Time service is not running — the usual reason a
// resync fails, and one an admin fixes by starting a service rather than by
// reading w32tm's output.
const w32tmServiceStopped = "0x80070426"

func verdictTimeResync(code int, output string) (string, error) {
	if code == 0 {
		return output, nil
	}
	if strings.Contains(output, w32tmServiceStopped) {
		return output, fmt.Errorf(
			"le service de temps Windows (W32Time) est arrêté sur ce poste (%s)",
			w32tmServiceStopped)
	}
	return output, fmt.Errorf("la resynchronisation de l'horloge a échoué (code %s)",
		formatExitCode(code))
}

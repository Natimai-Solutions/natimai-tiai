package msg

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"
)

var update = flag.Bool("update", false, "rewrite testdata/messages_fr.json from the catalogue")

const fixture = "testdata/messages_fr.json"

// cases fills every code of the catalogue, some several ways: the shared set
// the console's French is checked against (frontend/src/services/commandResults.spec.ts).
func cases() []Message {
	return []Message{
		New("agent.backlog_full", Params{"max": 64}),
		New("agent.stopped", nil),
		New("agent.unsupported_type", Params{"type": Quote("format_c"), "version": "1.3.0"}),
		New("agent.power_pending", Params{"action": "reboot"}),
		New("agent.power_pending", Params{"action": "shutdown"}),
		New("power.too_soon", Params{"action": "reboot", "ago": "3 min", "min": "10 min"}),
		New("power.too_soon", Params{"action": "shutdown", "ago": "45 s", "min": "10 min"}),
		New("power.too_soon_boot", Params{"ago": "2 min", "min": "10 min"}),
		New("power.scheduled", Params{"action": "reboot", "seconds": 60}),
		New("power.scheduled", Params{"action": "shutdown", "seconds": 60}),
		New("power.schedule_failed", Params{"action": "reboot", "code": "1190"}),
		New("power.schedule_failed", Params{"action": "shutdown", "code": "0x80070005"}),
		New("wu.scan", Params{"count": 0}),
		New("wu.scan", Params{"count": 7}),
		New("wu.timeout", nil),
		New("wu.interrupted", nil),
		New("wu.known_error", Params{"hresult": "0x80070422", "detail": "powershell: exit status 1 (Exception from HRESULT: 0x80070422)"}),
		New("wu.known_error", Params{"hresult": "0x8024402c", "detail": "x"}),
		New("wu.known_error", Params{"hresult": "0x80072ee2", "detail": "x"}),
		New("wu.known_error", Params{"hresult": "0x8024002e", "detail": "x"}),
		New("wu.known_error", Params{"hresult": "0x80248014", "detail": "x"}),
		New("wu.known_error", Params{"hresult": "0x80244022", "detail": "x"}),
		New("wu.known_error", Params{"hresult": "0x80240016", "detail": "x"}),
		New("wu.known_error", Params{"hresult": "0x80240438", "detail": "x"}),
		New("wu.install_incomplete", Params{"failed": 2, "selected": 5}),
		New("wu.install_result", Params{"result": "succeeded", "code": 2}),
		New("wu.install_result", Params{"result": "succeeded_with_errors", "code": 3}),
		New("wu.install_result", Params{"result": "failed", "code": 4}),
		New("wu.install_result", Params{"result": "aborted", "code": 5}),
		New("wu.install_result", Params{"result": "in_progress", "code": 1}),
		New("wu.install_result", Params{"result": "not_started", "code": 0}),
		New("inventory.scan", Params{"disks": 1, "volumes": 2, "nics": 1, "software": 143}),
		New("inventory.scan_without_software", Params{"disks": 2, "volumes": 3, "nics": 2}),
		New("inventory.unavailable", nil),
		New("defender.quick_scan.timeout", Params{"budget": "1 h"}),
		New("defender.full_scan.timeout", Params{"budget": "8 h"}),
		New("defender.signatures.timeout", Params{"budget": "1 h 30 min"}),
		New("defender.quick_scan.interrupted", nil),
		New("defender.full_scan.interrupted", nil),
		New("defender.signatures.interrupted", nil),
		New("maintenance.timeout", Params{"exe": "sfc.exe"}),
		New("maintenance.interrupted", Params{"exe": "dism.exe"}),
		New("maintenance.launch_failed", Params{"exe": "gpupdate.exe", "detail": "exec: file does not exist"}),
		New("maintenance.exit_code", Params{"code": "1"}),
		New("sfc.failed", Params{"code": "1"}),
		New("sfc.failed_summary", Params{"code": "0x800f081f", "summary": "La protection des ressources Windows a trouvé des fichiers corrompus."}),
		New("dism.source_missing", Params{"hresult": "0x800f081f"}),
		New("dism.failed", Params{"code": "87"}),
		New("chkdsk.failed", Params{"code": "0xc0000005"}),
		New("chkdsk.offline_repair", Params{"meaning": "errors_found", "code": 1}),
		New("chkdsk.offline_repair", Params{"meaning": "partly_checked", "code": 2}),
		New("chkdsk.offline_repair", Params{"meaning": "not_checked", "code": 3}),
		New("time.service_stopped", Params{"hresult": "0x80070426"}),
		New("time.failed", Params{"code": "0x800705b4"}),
		New("spooler.reset", Params{"removed": 3}),
		New("spooler.stop_failed", Params{"detail": "Access is denied."}),
		New("spooler.start_failed", Params{"detail": "The service did not respond."}),
		New("spooler.purge_failed", Params{"detail": "lecture de C:\\Windows\\System32\\spool\\PRINTERS : Access is denied."}),
		New("wol.relay.sent", Params{"mac": "AA:BB:CC:DD:EE:FF", "copies": 3, "targets": "192.168.1.255:9, 10.4.255.255:9"}),
		New("wol.relay.no_subnet", nil),
		New("wol.relay.nic_failed", Params{"detail": "The system cannot find the file specified."}),
		New("wol.relay.send_failed", Params{"detail": "network is unreachable"}),
		New("wol.relay.bad_mac", Params{"mac": Quote("00:00:00:00:00:00")}),
		New("deploy.unsupported", nil),
		New("deploy.not_enabled", nil),
		New("deploy.no_package", nil),
		New("deploy.package_id_refused", Params{"id": Quote("../etc")}),
		New("deploy.bad_manifest", nil),
		New("deploy.no_step", Params{"action": "install"}),
		New("deploy.no_step", Params{"action": "uninstall"}),
		New("deploy.no_trust_method", nil),
		New("deploy.unsigned_no_publisher", nil),
		New("deploy.install_removes", nil),
		New("deploy.method_a.msiexec", nil),
		New("deploy.method_a.exe_only", nil),
		New("deploy.method_a.too_large", Params{"gib": 8}),
		New("deploy.method_a.loadable", Params{"file": Quote("version.dll")}),
		New("deploy.signature.unsigned", nil),
		New("deploy.signature.bad_certificate", nil),
		New("deploy.signature.untrusted", Params{"thumbprint": "0A1B2C"}),
		New("deploy.signature.unreadable_certificate", Params{"detail": "x509: malformed certificate"}),
		New("deploy.signature.bad_signature", nil),
		New("deploy.signature.algorithm_mismatch", nil),
		New("deploy.signature.invalid", nil),
		New("deploy.signature.unsupported_key", nil),
		New("deploy.not_signed", nil),
		New("deploy.authenticode_refused", Params{"file": "setup.exe", "detail": "fichier non signé (pas de signature Authenticode)"}),
		New("deploy.publisher_not_approved", Params{"publisher": Quote("Contoso Ltd")}),
		New("deploy.download_failed", Params{"file": "setup.exe", "detail": "serveur occupé (429)"}),
		New("deploy.launch_failed", Params{"file": "setup.exe", "detail": "The system cannot find the file specified."}),
		New("deploy.manifest.unreadable", Params{"detail": "json: unknown field \"x\""}),
		New("deploy.manifest.trailing_data", nil),
		New("deploy.manifest.unknown_format", Params{"format": Quote("tiai-package-9")}),
		New("deploy.manifest.other_package", nil),
		New("deploy.manifest.no_file", nil),
		New("deploy.manifest.bad_name", Params{"name": Quote("nul.txt")}),
		New("deploy.manifest.bad_hash", Params{"name": Quote("setup.exe")}),
		New("deploy.manifest.not_in_package", Params{"file": Quote("setup.exe")}),
		New("deploy.manifest.bad_argument", nil),
		New("deploy.unknown_kind", Params{"kind": Quote("zip")}),
		New("deploy.package_dir", Params{"detail": "mkdir C:\\ProgramData\\Tiai: Access is denied."}),
		New("deploy.hash_mismatch", nil),
		New("deploy.launch_timeout", Params{"detail": "context deadline exceeded"}),
		New("deploy.download.restart", nil),
		New("deploy.download.busy", Params{"status": 429}),
		New("deploy.download.size_announced", Params{"path": "/api/v1/agent/packages/p/files/f", "announced": 2048, "expected": 1024}),
		New("deploy.download.too_long", Params{"path": "/api/v1/agent/packages/p/files/f", "size": 1024}),
		New("deploy.download.interrupted", Params{"detail": "unexpected EOF"}),
		New("spooler.state_timeout", Params{"timeout": "30s"}),
		// A coded cause inside a coded sentence: its code goes along.
		Wrap("deploy.download_failed", Params{"file": "setup.exe"}, Err("deploy.hash_mismatch", nil)).Message,
		Wrap("deploy.download_failed", Params{"file": "setup.exe"}, Err("deploy.download.busy", Params{"status": 503})).Message,
		Wrap("deploy.authenticode_refused", Params{"file": "setup.exe"}, Err("deploy.not_signed", nil)).Message,
		New("deploy.exit_code", Params{"file": "setup.exe", "code": 1603}),
		New("deploy.exit_code", Params{"file": "setup.exe", "code": 1603, "trust": "signer", "by": "CN=Lycée Test"}),
		New("deploy.exit_code", Params{"file": "setup.exe", "code": 2, "trust": "publisher", "by": "Igor Pavlov"}),
		New("deploy.exit_code", Params{"file": "setup.exe", "code": 2, "trust": "publisher", "by": "Igor Pavlov", "revocation_offline": true}),
		New("deploy.done", Params{"action": "install", "name": "7-Zip 23.01", "package_id": "p", "method": "A", "reboot": false, "trust": "publisher", "by": "Igor Pavlov"}),
		New("deploy.done", Params{"action": "install", "name": "7-Zip 23.01", "package_id": "p", "method": "A", "reboot": true, "trust": "publisher", "by": "Igor Pavlov", "revocation_offline": true}),
		New("deploy.done", Params{"action": "uninstall", "name": "", "package_id": "0b9c6a4e-6c1d-4a51-9a51-2f1e8f0c3d11", "method": "A", "reboot": false}),
		New("deploy.done", Params{"action": "install", "name": "Outil", "package_id": "p", "method": "B", "reboot": false, "trust": "signer", "by": "CN=DSI"}),
		New("deploy.winget_done", Params{"action": "install", "id": "Mozilla.Firefox", "already": false}),
		New("deploy.winget_done", Params{"action": "uninstall", "id": "Mozilla.Firefox", "already": true}),
		New("deploy.winget_no_match", nil),
		New("deploy.winget_failed", Params{"code": "0x8A150001"}),
		New("deploy.winget_not_enabled", nil),
		New("deploy.winget_missing", nil),
		New("deploy.winget_refused", Params{"id": Quote("-x")}),
		New("deploy.winget_not_allowed", Params{"id": Quote("Mozilla.Firefox")}),
		New("deploy.winget_version_refused", Params{"version": Quote("1 2")}),
		// The composite texts (reports.go), and what they quote.
		New("dism.reboot_required", Params{"output": "Deployment Image Servicing and Management tool\nThe operation completed successfully."}),
		New("dism.reboot_required", Params{"output": ""}),
		WUInstall{Selected: 2, Installed: 2, Reboot: true, Updates: []WUInstalled{
			{Name: "KB5063878 — 2025-08 Cumulative Update", Result: "succeeded"},
			{Name: "KB2267602 — Defender", Result: "succeeded_with_errors"},
		}}.Message(),
		WUInstall{Selected: 4, Installed: 3, Skipped: 1, Updates: []WUInstalled{
			{Name: "KB5063878 — Cumulative", Result: "succeeded"},
			{Name: "KB5062660 — Broken", Result: "failed", HResult: "0x80240017"},
			{Name: "Driver", Result: "aborted", HResult: "0x00000000"},
		}}.Message(),
		WUInstall{}.Message(),
		WUInstall{Skipped: 2}.Message(),
		WUInstall{Selected: 1, Installed: 1, Updates: []WUInstalled{{Name: "KB1 — X", Result: "in_progress", HResult: "0x00000001"}}}.Message(),
		WUInstall{Selected: 1, Installed: 1, Updates: []WUInstalled{{Name: "KB1 — X", Result: "not_started", HResult: "0x00000002"}}}.Message(),
		wuResetWhole,
		wuResetPartial,
		wuResetPartialError.Message,
		wuResetStopError.Message,
		New("wu_reset.backup_not_removed", Params{"path": `C:\Windows\SoftwareDistribution.old`, "detail": "Access is denied."}),
		New("service.manager_failed", Params{"detail": "Access is denied."}),
		New("service.open_failed", Params{"service": "Spooler", "detail": "The specified service does not exist as an installed service."}),
		New("service.query_failed", Params{"detail": "Access is denied."}),
		SpoolerReport(4, nil, false),
		SpoolerReport(0, Wrap("spooler.files_not_removed", Params{"failed": 2}, errors.New("The process cannot access the file.")), true),
		SpoolerReport(0, Wrap("spooler.queue_unreadable", Params{"dir": `C:\Windows\System32\spool\PRINTERS`}, errors.New("Access is denied.")), false),
		SpoolerReport(0, errors.New("boom"), true),
		New("spooler.queue_unreadable", Params{"dir": `C:\Windows\System32\spool\PRINTERS`, "detail": "Access is denied."}),
		New("spooler.files_not_removed", Params{"failed": 2, "detail": "The process cannot access the file."}),
		Wrap("spooler.purge_failed", nil, Wrap("spooler.files_not_removed", Params{"failed": 1}, errors.New("Access is denied."))).Message,
		BothMethodsRefused(Err("deploy.signature.untrusted", Params{"thumbprint": "0A1B2C"}), Err("deploy.method_a.exe_only", nil)).Message,
		BothMethodsRefused(Err("deploy.signature.invalid", nil), Err("deploy.publisher_not_approved", Params{"publisher": Quote("Contoso Ltd")})).Message,
		BothMethodsRefused(Err("deploy.signature.invalid", nil),
			Wrap("deploy.authenticode_refused", Params{"file": "setup.exe"}, Err("deploy.not_signed", nil))).Message,
		BothMethodsRefused(errors.New("x509: unknown authority"), errors.New("unexpected")).Message,
		// A coded cause whose own detail is quoted: it goes along too.
		Wrap("deploy.download_failed", Params{"file": "setup.exe"},
			Wrap("deploy.download.interrupted", nil, errors.New("unexpected EOF"))).Message,
	}
}

// The steps of a whole reset, of a partial one, and the latter's verdict.
var (
	wuResetWhole, _ = WUResetReport([]WUResetStep{
		{Kind: WUResetStopped, Subject: "wuauserv"},
		{Kind: WUResetAlreadyStopped, Subject: "cryptsvc"},
		{Kind: WUResetStopped, Subject: "bits"},
		{Kind: WUResetAlreadyStopped, Subject: "msiserver"},
		{Kind: WUResetRenamed, Subject: "software_distribution", Arg: "SoftwareDistribution.old"},
		{Kind: WUResetAbsent, Subject: "catroot2"},
		{Kind: WUResetRestarted, Subject: "wuauserv"},
		{Kind: WUResetRestarted, Subject: "bits"},
		{Kind: WUResetNext},
	})
	wuResetPartial, wuResetPartialError = WUResetReport([]WUResetStep{
		{Kind: WUResetStopped, Subject: "wuauserv"},
		{Kind: WUResetRenamed, Subject: "software_distribution", Arg: "SoftwareDistribution.old"},
		{Kind: WUResetRenameFailed, Subject: "catroot2", Arg: `C:\Windows\System32\catroot2`,
			Err: FromError(Wrap("wu_reset.backup_not_removed", Params{"path": `C:\Windows\System32\catroot2.old`}, errors.New("Access is denied.")))},
		{Kind: WUResetRestartFailed, Subject: "wuauserv", Err: Plain("The service did not respond.")},
	})
	_, wuResetStopError = WUResetReport([]WUResetStep{
		{Kind: WUResetStopFailed, Subject: "cryptsvc", Err: FromError(Err("spooler.state_timeout", Params{"timeout": "30s"}))},
		{Kind: WUResetAlreadyStopped, Subject: "msiserver"},
		{Kind: WUResetKept},
	})
)

type fixtureCase struct {
	Code    string `json:"code"`
	Params  Params `json:"params"`
	Message string `json:"message"`
}

func fixtureCases() []fixtureCase {
	out := []fixtureCase{}
	for _, m := range cases() {
		out = append(out, fixtureCase{Code: m.Code, Params: m.Params, Message: m.Text})
	}
	return out
}

// The console words these codes; its French must be the agent's, case by
// case. Regenerate after a deliberate change: go test ./internal/msg -update.
func TestTheSharedCasesAreTheCatalogues(t *testing.T) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", " ")
	if err := enc.Encode(fixtureCases()); err != nil {
		t.Fatal(err)
	}
	if *update {
		if err := os.WriteFile(fixture, buf.Bytes(), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	stored, err := os.ReadFile(fixture)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(stored, buf.Bytes()) {
		t.Errorf("%s is not what the catalogue writes: run go test ./internal/msg -update, "+
			"then match frontend/src/i18n/messages/commands.ts", fixture)
	}
}

func TestEveryCodeHasACaseAndFitsTheServer(t *testing.T) {
	pattern := regexp.MustCompile(`^[a-z0-9_.]{1,64}$`)
	covered := map[string]bool{}
	for _, m := range cases() {
		if m.Code == "" {
			t.Errorf("a case has no code: %q", m.Text)
		}
		if !Fits(m.Params) {
			t.Errorf("%s: params beyond what the server keeps", m.Code)
		}
		covered[m.Code] = true
	}
	for code := range french {
		if !pattern.MatchString(code) {
			t.Errorf("%q is not a code the server accepts", code)
		}
		if !covered[code] {
			t.Errorf("%s has no case in the shared set", code)
		}
		// No code is a prefix of another: the console's catalogue nests them.
		for other := range french {
			if strings.HasPrefix(other, code+".") {
				t.Errorf("%s is a prefix of %s", code, other)
			}
		}
	}
}

// A code written in the agent's source and missing from the catalogue would
// send the code itself as text: every literal one is checked here, and the
// three Defender families built from a prefix (collector.defenderAction).
// The reverse: a code of the catalogue that nothing sends is a sentence the
// agent still writes uncoded somewhere (wu.timeout and wu.interrupted were,
// verification of 2026-11-18). A code built from a prefix (defender actions'
// ".timeout" and ".interrupted") counts when its prefix is in the source.
func TestEveryCodeOfTheCatalogueIsSent(t *testing.T) {
	var source strings.Builder
	// The reports' builders (reports.go) send codes of their own; the
	// catalogue itself names them all, and does not count.
	err := filepath.WalkDir("..", func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") ||
			path == filepath.Join("..", "msg", "catalogue.go") {
			return err
		}
		src, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		source.Write(src)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	text := source.String()
	for code := range french {
		if strings.Contains(text, `"`+code+`"`) {
			continue
		}
		base := strings.TrimSuffix(strings.TrimSuffix(code, ".timeout"), ".interrupted")
		if base != code && strings.Contains(text, `"`+base+`"`) {
			continue
		}
		t.Errorf("code %q is in the catalogue but nothing in the agent sends it", code)
	}
}

func TestEveryCodeInTheSourceIsInTheCatalogue(t *testing.T) {
	call := regexp.MustCompile(`msg\.(?:New|Err|Wrap)\("([^"]+)"`)
	// Inside this package (reports.go), without the qualifier.
	inside := regexp.MustCompile(`(?:^|[^.\w])(?:New|Err|Wrap|checked)\("([^"]+)"`)
	found := 0
	err := filepath.WalkDir("..", func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return err
		}
		src, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		find := call
		if filepath.Dir(path) == filepath.Join("..", "msg") {
			find = inside
		}
		for _, m := range find.FindAllStringSubmatch(string(src), -1) {
			found++
			if _, ok := french[m[1]]; !ok {
				t.Errorf("%s: code %q is not in the catalogue", path, m[1])
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if found < 50 {
		t.Errorf("only %d coded messages found in the source", found)
	}
	for _, action := range []string{"defender.quick_scan", "defender.full_scan", "defender.signatures"} {
		for _, suffix := range []string{".timeout", ".interrupted"} {
			if _, ok := french[action+suffix]; !ok {
				t.Errorf("%s%s is not in the catalogue", action, suffix)
			}
		}
	}
}

// The sentences the agent wrote before its messages had codes, word for
// word: an older server shows the text, and must show what it showed.
func TestTheTextsAreTheOnesTheAgentAlwaysWrote(t *testing.T) {
	for _, c := range []struct {
		got, want string
	}{
		{New("agent.backlog_full", Params{"max": 64}).Text,
			"file d'attente de l'agent pleine (64 commandes) : commande non exécutée, à relancer"},
		{New("agent.unsupported_type", Params{"type": Quote("x"), "version": "1.2.0"}).Text,
			`type de commande "x" non pris en charge par l'agent 1.2.0 : mettez l'agent à jour`},
		{New("power.too_soon", Params{"action": "shutdown", "ago": "3 min", "min": "10 min"}).Text,
			"opération refusée : un arrêt a déjà été programmé sur ce poste il y a 3 min (délai minimum 10 min)"},
		{New("power.scheduled", Params{"action": "reboot", "seconds": 60}).Text,
			"Redémarrage programmé dans 60 secondes.\n"},
		{New("chkdsk.offline_repair", Params{"meaning": "errors_found", "code": 1}).Text,
			"chkdsk : des erreurs ont été trouvées (code 1) — une réparation hors ligne (chkdsk /spotfix, appliquée au redémarrage) est nécessaire"},
		{New("deploy.done", Params{"action": "install", "name": "App 1.0", "package_id": "p", "method": "A",
			"reboot": true, "trust": "publisher", "by": "Ed", "revocation_offline": true}).Text,
			"Installation de App 1.0 terminée (méthode A, éditeur approuvé : Ed (révocation non vérifiable hors ligne))\nRedémarrage requis pour terminer."},
		{New("deploy.done", Params{"action": "uninstall", "name": "", "package_id": "id", "method": "A"}).Text,
			"Désinstallation de paquet id terminée (méthode A)"},
		{New("wu.known_error", Params{"hresult": "0x80240438", "detail": "boom"}).Text,
			"aucune source de mises à jour n'est configurée sur ce poste (boom)"},
	} {
		if c.got != c.want {
			t.Errorf("got  %q\nwant %q", c.got, c.want)
		}
	}
}

func TestOfReadsOnlyAWholeCodedMessage(t *testing.T) {
	base := errors.New("cause")
	coded := Wrap("wol.relay.send_failed", nil, base)
	if coded.Error() != "émission du paquet magique impossible : cause" {
		t.Errorf("text = %q", coded.Error())
	}
	if !errors.Is(coded, base) {
		t.Error("the cause must stay reachable")
	}
	if code, params := Of(coded); code != "wol.relay.send_failed" || params["detail"] != "cause" {
		t.Errorf("Of = %q %v", code, params)
	}
	// Inside a longer sentence, the code would word only part of it.
	if code, _ := Of(fmt.Errorf("méthode B : %w", coded)); code != "" {
		t.Errorf("a coded error inside another sentence kept its code %q", code)
	}
	if code, _ := Of(errors.New("plain")); code != "" {
		t.Error("an uncoded error has no code")
	}
	if code, _ := Of(nil); code != "" {
		t.Error("no error, no code")
	}
	// Too long for the server: the text goes alone.
	nested := Wrap("deploy.download_failed", Params{"file": "a.exe"}, Err("deploy.download.busy", Params{"status": 429}))
	if nested.Params["detail_code"] != "deploy.download.busy" || nested.Params["detail_status"] != 429 ||
		nested.Params["detail"] != "serveur occupé (429)" {
		t.Errorf("a coded cause hands on its code and parameters: %#v", nested.Params)
	}
	if plainCause := Wrap("deploy.download_failed", nil, errors.New("x")); plainCause.Params["detail_code"] != nil {
		t.Errorf("an uncoded cause has no detail_code: %#v", plainCause.Params)
	}
	long := Wrap("wol.relay.send_failed", nil, errors.New(strings.Repeat("x", 2000)))
	if code, params := Of(long); code != "" || params != nil {
		t.Errorf("an oversized message kept its code %q", code)
	}
	if !strings.HasSuffix(long.Error(), strings.Repeat("x", 2000)) {
		t.Error("the text stays whole")
	}
}

func TestAnUnknownCodeDegradesToText(t *testing.T) {
	m := New("no.such.code", Params{"a": 1})
	if m.Code != "" || m.Text != "no.such.code" {
		t.Errorf("New(unknown) = %+v", m)
	}
}

func TestFitsMirrorsTheServerBounds(t *testing.T) {
	many := Params{}
	for i := range 17 {
		many[fmt.Sprintf("k%d", i)] = i
	}
	for _, p := range []Params{
		many,
		{"long": strings.Repeat("é", 1025)},
		{strings.Repeat("k", 33): 1},
		{"a": strings.Repeat("x", 1000), "b": strings.Repeat("x", 1000), "c": strings.Repeat("x", 1000), "d": strings.Repeat("x", 1000)},
	} {
		if Fits(p) {
			t.Errorf("Fits(%d keys) = true", len(p))
		}
	}
	if !Fits(Params{"text": strings.Repeat("é", 1024), "n": 1, "b": true}) {
		t.Error("a message within bounds must fit")
	}
	if !slices.Contains([]bool{Fits(nil)}, true) {
		t.Error("no params fit")
	}
}

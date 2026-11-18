package msg

import (
	"errors"
	"fmt"
	"strings"
	"testing"
)

// A coded cause hands on its own detail too: the console words the cause
// from its parameters, and without it read « transfer interrupted: ».
func TestWrapHandsOnTheCausesOwnDetail(t *testing.T) {
	inner := Wrap("deploy.download.interrupted", nil, errors.New("unexpected EOF"))
	outer := Wrap("deploy.download_failed", Params{"file": "a.exe"}, inner)
	p := outer.Params
	if p["detail_code"] != "deploy.download.interrupted" || p["detail_detail"] != "unexpected EOF" {
		t.Errorf("params = %v", p)
	}
	if outer.Text != "téléchargement de a.exe : transfert interrompu : unexpected EOF" {
		t.Errorf("text = %q", outer.Text)
	}
	if !errors.Is(outer, inner) {
		t.Error("the cause stays reachable")
	}
}

func TestNestQuotesAMessageWithItsCode(t *testing.T) {
	p := Params{}
	Nest(p, "e1", FromError(Err("spooler.state_timeout", Params{"timeout": "30s"})))
	if p["e1"] != "le service n'a pas atteint l'état attendu en 30s" || p["e1_code"] != "spooler.state_timeout" ||
		p["e1_timeout"] != "30s" {
		t.Errorf("params = %v", p)
	}
	// Text alone: an uncoded message; one with a parameter named code (it
	// would take the place of e1_code); one whose names the server refuses.
	for _, m := range []Message{
		Plain("Access is denied."),
		New("dism.failed", Params{"code": "87"}),
		New("maintenance.timeout", Params{"exe": "x", strings.Repeat("k", 30): 1}),
	} {
		p := Params{}
		Nest(p, "e1", m)
		if len(p) != 1 || p["e1"] != m.Text {
			t.Errorf("%q: params = %v", m.Text, p)
		}
	}
	if Unnested(Params{"a": 1, "e1": "x", "e1_code": "c", "e1_detail": "d", "e10": "y"}, "e1")["e1_detail"] != nil {
		t.Error("Unnested keeps nothing nested under the key")
	}
}

// The output of a failed command, when the agent wrote it, rides beside the
// error's parameters; never at the cost of the error's code.
func TestWithOutput(t *testing.T) {
	report := SpoolerReport(3, nil, false)
	p := WithOutput(Params{"detail": "x"}, report)
	if p["output_code"] != "spooler.report" || p["output_removed"] != 3 || p["output_restarted"] != false ||
		p["detail"] != "x" || p["output"] != nil {
		t.Errorf("params = %v", p)
	}
	if got := WithOutput(Params{"detail": "x"}, Plain("tool")); len(got) != 1 {
		t.Errorf("a tool's output adds nothing: %v", got)
	}
	full := Params{}
	for i := range 15 {
		full[fmt.Sprintf("k%d", i)] = i
	}
	if got := WithOutput(full, report); len(got) != 15 || !Fits(got) {
		t.Errorf("beyond the server's bounds, the error's own params: %v", got)
	}
}

// What a list cannot carry, and what the server would not keep, goes as
// text alone — the text it always was.
func TestReportsFallBackToText(t *testing.T) {
	odd := WUInstall{Selected: 1, Installed: 1, Updates: []WUInstalled{{Name: "A\nB", Result: "succeeded"}}}.Message()
	if odd.Code != "" || odd.Text != "1 mise(s) à jour retenue(s), 1 installée(s).\nA\nB : installée" {
		t.Errorf("odd = %+v", odd)
	}
	var many []WUInstalled
	for i := range 40 {
		many = append(many, WUInstalled{Name: fmt.Sprintf("KB%d — A rather long update title", i), Result: "succeeded"})
	}
	if code, _ := Coded(WUInstall{Selected: 40, Installed: 40, Updates: many}.Message()); code != "" {
		t.Errorf("a list beyond 1024 characters kept its code %q", code)
	}

	// Many failures with coded errors: the errors' codes go, the report's
	// code stays.
	var steps []WUResetStep
	for _, name := range []string{"wuauserv", "cryptsvc", "bits", "msiserver"} {
		steps = append(steps, WUResetStep{Kind: WUResetStopFailed, Subject: name,
			Err: FromError(Wrap("service.query_failed", nil, Err("spooler.state_timeout", Params{"timeout": "30s"})))})
	}
	steps = append(steps, WUResetStep{Kind: WUResetKept})
	report, verdict := WUResetReport(steps)
	code, params := Coded(report)
	if code != "wu_reset.report" || params["e4"] == nil || params["e1_code"] != nil {
		t.Errorf("report = %q %v", code, params)
	}
	if code, _ := Of(verdict); code != "wu_reset.incomplete" {
		t.Errorf("verdict = %q", code)
	}
	if !strings.HasPrefix(report.Text, "ÉCHEC — arrêt du service Windows Update (wuauserv) : interrogation du service : ") {
		t.Errorf("text = %q", report.Text)
	}
	// A path with a line break: the text alone, report and verdict.
	odd2, verdict2 := WUResetReport([]WUResetStep{{Kind: WUResetRenameFailed, Subject: "catroot2", Arg: "C:\\a\nb", Err: Plain("x")}})
	if odd2.Code != "" || verdict2.Code != "" || verdict2.Text != "réinitialisation incomplète : renommage de C:\\a\nb" {
		t.Errorf("odd path: %+v %+v", odd2, verdict2.Message)
	}
	// Two long refusals: the text alone.
	both := BothMethodsRefused(errors.New(strings.Repeat("b", 1100)), errors.New("a"))
	if code, _ := Of(both); code != "" || !strings.HasPrefix(both.Error(), "méthode B : bbb") {
		t.Errorf("long refusal: %q", code)
	}
}

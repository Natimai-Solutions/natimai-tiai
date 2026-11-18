package agent

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// The verdict carries the agent's code beside its text (plan console
// bilingue, I5): the error's on a failure, the output's on a success.
func TestResultOfCarriesTheCodeOfTheWholeText(t *testing.T) {
	failed := resultOf(msg.Plain("tool output"), msg.Err("maintenance.exit_code", msg.Params{"code": "1"}))
	if failed.Status != "failed" || failed.Output != "tool output" || failed.Error != "code de retour 1" {
		t.Errorf("failed = %+v", failed)
	}
	if failed.MessageCode != "maintenance.exit_code" || failed.MessageParams["code"] != "1" {
		t.Errorf("failed code = %q %v", failed.MessageCode, failed.MessageParams)
	}

	done := resultOf(msg.New("wu.scan", msg.Params{"count": 3}), nil)
	if done.Status != "succeeded" || done.Output != "3 mise(s) à jour en attente." || done.MessageCode != "wu.scan" {
		t.Errorf("done = %+v", done)
	}

	// A tool's output, and an uncoded error: text alone, as before.
	tool := resultOf(msg.Plain("Windows IP Configuration"), nil)
	if tool.MessageCode != "" || tool.MessageParams != nil {
		t.Errorf("a tool output has no code: %+v", tool)
	}
	plain := resultOf(msg.Message{}, errors.New("powershell: exit status 1"))
	if plain.MessageCode != "" {
		t.Errorf("an uncoded error has no code: %+v", plain)
	}
	// A coded success whose output is cut short by a failure: the code is the
	// error's, never the output's.
	mixed := resultOf(msg.New("wu.scan", msg.Params{"count": 1}), errors.New("boom"))
	if mixed.MessageCode != "" {
		t.Errorf("a failure is worded from its error alone: %+v", mixed)
	}
}

// A failure whose output is the agent's own report — a spooler reset that
// emptied the queue but could not restart it — carries the report's code
// beside the error's, for the console to word both.
func TestAFailedResultCarriesTheCodeOfItsReport(t *testing.T) {
	report := msg.SpoolerReport(4, nil, false)
	res := resultOf(report, msg.Wrap("spooler.start_failed", nil, errors.New("Access is denied.")))
	if res.Output != "Spouleur d'impression arrêté.\nFile d'impression purgée (4 fichier(s)).\n"+
		"Le spouleur n'a PAS pu être redémarré." || res.Error != "démarrage du spouleur : Access is denied." {
		t.Errorf("texts = %q / %q", res.Output, res.Error)
	}
	p := res.MessageParams
	if res.MessageCode != "spooler.start_failed" || p["detail"] != "Access is denied." ||
		p["output_code"] != "spooler.report" || p["output_removed"] != 4 || p["output_restarted"] != false {
		t.Errorf("code = %q %v", res.MessageCode, p)
	}
	// A tool's output stays text: no output_code.
	tool := resultOf(msg.Plain("dism"), msg.Err("dism.failed", msg.Params{"code": "87"}))
	if _, ok := tool.MessageParams["output_code"]; ok {
		t.Errorf("a tool's output has no code: %v", tool.MessageParams)
	}
}

// What travels: the two fields when there is a code, nothing new otherwise —
// the body an older server has always read.
func TestTheResultOnTheWire(t *testing.T) {
	coded, _ := json.Marshal(resultOf(msg.Message{}, abandonedOnStop))
	if !strings.Contains(string(coded), `"message_code":"agent.stopped"`) {
		t.Errorf("coded body = %s", coded)
	}
	if !strings.Contains(string(coded), `"error":"interrompue par l'arrêt de l'agent avant d'avoir commencé : à relancer"`) {
		t.Errorf("the text still travels: %s", coded)
	}
	plain, _ := json.Marshal(models.CommandResult{Status: "succeeded", Output: "ok"})
	if string(plain) != `{"status":"succeeded","output":"ok"}` {
		t.Errorf("uncoded body = %s", plain)
	}
}

func TestAPowerRefusalIsCoded(t *testing.T) {
	g := upSince(3 * time.Minute)
	code, params := msg.Of(g.allow(time.Now()))
	if code != "power.too_soon_boot" || params["ago"] != "3 min" || params["min"] != "10 min" {
		t.Errorf("boot refusal = %q %v", code, params)
	}

	g = upSince(3 * time.Hour)
	now := time.Now()
	g.markScheduled(now, actionShutdown)
	err := g.allow(now.Add(2 * time.Minute))
	code, params = msg.Of(err)
	if code != "power.too_soon" || params["action"] != "shutdown" {
		t.Errorf("repeat refusal = %q %v", code, params)
	}
	if !errors.Is(err, errPowerActionTooSoon) {
		t.Error("the refusal still wraps errPowerActionTooSoon")
	}
	if !strings.HasPrefix(err.Error(), "opération refusée : un arrêt a déjà été programmé") {
		t.Errorf("text = %q", err)
	}
}

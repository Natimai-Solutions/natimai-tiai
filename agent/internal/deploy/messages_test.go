package deploy

import (
	"context"
	"errors"
	"maps"
	"strings"
	"testing"

	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// A deployment's verdicts carry the code the console words them from (plan
// console bilingue, I5), the French staying the text it was.
func TestDeploymentVerdictsAreCoded(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, code: 3010}
	res, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pronote(t, env))
	if err != nil {
		t.Fatal(err)
	}
	if res.Message.Code != "deploy.done" || res.Message.Text != res.Output {
		t.Errorf("message = %+v", res.Message)
	}
	p := res.Message.Params
	if p["action"] != "install" || p["method"] != "A" || p["trust"] != "publisher" || p["reboot"] != true {
		t.Errorf("params = %v", p)
	}

	// Refused: the error is coded.
	_, err = Execute(context.Background(), env, Policy{}, "package_install", pronote(t, env))
	if code, _ := msg.Of(err); code != "deploy.not_enabled" {
		t.Errorf("no GPO: code %q (%v)", code, err)
	}
	_, err = Execute(context.Background(), env, Policy{Publishers: []string{"Someone Else"}}, "package_install", pronote(t, env))
	if code, params := msg.Of(err); code != "deploy.publisher_not_approved" || params["publisher"] != `"INDEX EDUCATION SAS"` {
		t.Errorf("other publisher: %q %v (%v)", code, params, err)
	}

	// The installer's own failure, with what let it run.
	env.code = 1603
	_, err = Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pronote(t, env))
	if code, params := msg.Of(err); code != "deploy.exit_code" || params["by"] != "INDEX EDUCATION SAS" {
		t.Errorf("exit code: %q %v (%v)", code, params, err)
	}
}

func TestWingetVerdictsAreCoded(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	pkg := &models.PackageDelivery{ID: "w", Kind: "winget", WingetID: "Mozilla.Firefox"}
	res, err := Execute(context.Background(), env, Policy{Winget: true}, "package_install", pkg)
	if err != nil {
		t.Fatal(err)
	}
	if res.Output != "winget install Mozilla.Firefox : terminé" || res.Message.Code != "deploy.winget_done" {
		t.Errorf("res = %+v", res)
	}
	env.code = wingetAlreadyInstalled
	res, _ = Execute(context.Background(), env, Policy{Winget: true}, "package_install", pkg)
	if res.Output != "winget install Mozilla.Firefox : terminé (déjà installé, rien à faire)" || res.Message.Params["already"] != true {
		t.Errorf("already: %+v", res)
	}
	env.code = wingetNoPackageFound
	_, err = Execute(context.Background(), env, Policy{Winget: true}, "package_install", pkg)
	if code, _ := msg.Of(err); code != "deploy.winget_no_match" || err.Error() != "aucun paquet winget ne correspond à cet identifiant" {
		t.Errorf("no match: %q %v", code, err)
	}
	env.code = 0x8A150001
	_, err = Execute(context.Background(), env, Policy{Winget: true}, "package_install", pkg)
	if code, params := msg.Of(err); code != "deploy.winget_failed" || params["code"] != "0x8A150001" ||
		err.Error() != "winget a échoué (code 0x8A150001)" {
		t.Errorf("failed: %q %v %v", code, params, err)
	}
}

// A method B refusal followed by method A's: one sentence of two, coded
// deploy.both_refused, each refusal quoted with its own code — the text the
// agent always wrote (verification of 2026-11-18: it was uncoded, and reached
// an English console in French).
func TestBothMethodsRefusedIsCoded(t *testing.T) {
	err := bothMethodsRefused(
		msg.Err("deploy.signature.untrusted", msg.Params{"thumbprint": "0A1B"}),
		msg.Err("deploy.method_a.exe_only", nil))
	if err.Error() != "méthode B : certificat de signature non approuvé sur ce poste (empreinte 0A1B absente de DeploySigners) ; "+
		"méthode A : seul un exécutable (.exe) signé par un éditeur approuvé peut être lancé — signez le paquet (méthode B)" {
		t.Errorf("text = %q", err)
	}
	code, params := msg.Of(err)
	if code != "deploy.both_refused" || params["b_code"] != "deploy.signature.untrusted" ||
		params["b_thumbprint"] != "0A1B" || params["a_code"] != "deploy.method_a.exe_only" {
		t.Errorf("code = %q %v", code, params)
	}

	// Method A's refusal without its prefix gets it, as it always did; an
	// uncoded refusal is quoted as text.
	err = bothMethodsRefused(msg.Err("deploy.signature.invalid", nil),
		msg.Err("deploy.publisher_not_approved", msg.Params{"publisher": msg.Quote("X")}))
	if err.Error() != `méthode B : signature invalide : le manifeste a changé depuis sa signature ; `+
		`méthode A : éditeur "X" non approuvé sur ce poste (DeployPublishers)` {
		t.Errorf("text = %q", err)
	}
	err = bothMethodsRefused(errors.New("b"), errors.New("a"))
	if code, params := msg.Of(err); err.Error() != "méthode B : b ; méthode A : a" ||
		code != "deploy.both_refused" || params["a_code"] != nil {
		t.Errorf("uncoded: %q %q %v", err, code, params)
	}
}

// A publisher check that carried a note the console has no words for: the
// verdict keeps the note in its text and drops its code — worded from the
// code, the console would lose the note. Without a note, the code stays.
func TestNotedDropsTheCodeForAnUnknownNote(t *testing.T) {
	plain := msg.Params{"trust": "publisher", "by": "ACME SAS"}
	withNote := msg.Params{"trust": "publisher", "by": "ACME SAS", "note": "chaîne non vérifiée"}
	params := func(trust msg.Params) msg.Params {
		p := msg.Params{"action": "install", "name": "App 1.0", "package_id": "p1", "method": "A",
			"file": "setup.exe", "code": 1}
		maps.Copy(p, trust)
		return p
	}
	for _, code := range []string{"deploy.done", "deploy.exit_code"} {
		if m := noted(msg.New(code, params(plain)), plain); m.Code != code {
			t.Errorf("%s: without a note the code stays, got %+v", code, m)
		}
		m := noted(msg.New(code, params(withNote)), withNote)
		if m.Code != "" || m.Params != nil {
			t.Errorf("%s: an unknown note must drop the code, got %+v", code, m)
		}
		if !strings.Contains(m.Text, "éditeur approuvé : ACME SAS (chaîne non vérifiée)") {
			t.Errorf("%s: the note is lost: %q", code, m.Text)
		}
	}
}

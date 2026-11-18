package deploy

import (
	"context"
	"errors"
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

// A method B refusal followed by method A's: one sentence of two, with no
// code — neither code words the whole of it.
func TestBothMethodsRefusedHasNoCode(t *testing.T) {
	err := bothMethodsRefused(msg.Err("deploy.signature.invalid", nil), msg.Err("deploy.method_a.exe_only", nil))
	if code, _ := msg.Of(err); code != "" {
		t.Errorf("composite refusal kept code %q", code)
	}
	if !errors.Is(err, err) || err.Error() == "" {
		t.Error("the text stays")
	}
}

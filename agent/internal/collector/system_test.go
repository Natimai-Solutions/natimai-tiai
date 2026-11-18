package collector

import "testing"

// A power action whose tool printed nothing is the coded sentence alone; one
// whose tool said something keeps that output as text, and so goes without a
// code — the console, wording the code, would otherwise hide what
// shutdown.exe said.
func TestPoweredOutputCodesOnlyTheBareSentence(t *testing.T) {
	bare := poweredOutput("reboot", 60, "")
	if bare.Code != "power.scheduled" || bare.Params["action"] != "reboot" || bare.Params["seconds"] != 60 {
		t.Errorf("bare = %+v", bare)
	}

	withOutput := poweredOutput("reboot", 60, "x")
	if withOutput.Code != "" || withOutput.Params != nil {
		t.Errorf("output from the tool must drop the code, got %+v", withOutput)
	}
	if want := bare.Text + "x"; withOutput.Text != want {
		t.Errorf("text = %q, want %q", withOutput.Text, want)
	}
}

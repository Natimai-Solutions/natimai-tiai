package collector

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"tiai/agent/internal/msg"
)

// --- The tables -------------------------------------------------------------

// The four services Microsoft's procedure names, in its order. Spelled out
// rather than derived from the table, like the maintenance catalogue: this is a
// documented recipe, and adding a service to it should cost a deliberate edit
// here as well as there.
func TestWUResetServicesMatchTheDocumentedProcedure(t *testing.T) {
	want := []string{"wuauserv", "cryptsvc", "bits", "msiserver"}
	for _, name := range wuResetServices {
		if strings.TrimSpace(msg.WUResetServices[name]) == "" {
			t.Errorf("%s: no label — the report is read by a human", name)
		}
	}
	if strings.Join(wuResetServices, ",") != strings.Join(want, ",") {
		t.Errorf("services = %v, want %v", wuResetServices, want)
	}
}

// The two directories, and — the point of the test — the fact that the name
// they are renamed to is a bare name. It is joined onto the directory's own
// parent, so a separator or a `..` in there would move a directory of
// %SystemRoot% somewhere else entirely.
func TestWUResetFoldersStayUnderSystemRoot(t *testing.T) {
	if len(wuResetFolders) != 2 {
		t.Fatalf("expected the two documented folders, got %d", len(wuResetFolders))
	}
	for _, f := range wuResetFolders {
		if len(f.elems) == 0 {
			t.Errorf("%s: no path", f.key)
		}
		for _, e := range f.elems {
			if strings.ContainsAny(e, `\/`) || e == ".." {
				t.Errorf("%s: path element %q must be a bare name", f.key, e)
			}
		}
		if strings.ContainsAny(f.backup, `\/`) || f.backup == ".." {
			t.Errorf("%s: backup name %q must be a bare name", f.key, f.backup)
		}
		if strings.TrimSpace(msg.WUResetFolders[f.key]) == "" {
			t.Errorf("%v: no label", f.elems)
		}
	}
}

// A reset that fails to restart a service must be able to say so before its
// deadline: the envelope has to clear the worst case of four stops and four
// starts, each capped at serviceStateTimeout.
func TestWUResetTimeoutCoversEveryServiceTransition(t *testing.T) {
	worst := 2 * len(wuResetServices) * int(serviceStateTimeout)
	if int(wuResetTimeout) <= worst {
		t.Errorf("wuResetTimeout = %s, must exceed %d transitions of %s",
			wuResetTimeout, 2*len(wuResetServices), serviceStateTimeout)
	}
}

// --- The report -------------------------------------------------------------

// A whole reset: the report reads, byte for byte, what the agent wrote
// before it had a code, and carries the code the console words it from.
func TestWUResetLogSucceedsWhenNothingFailed(t *testing.T) {
	var log wuResetLog
	log.step(msg.WUResetStopped, "wuauserv", "")
	log.step(msg.WUResetAlreadyStopped, "cryptsvc", "")
	log.step(msg.WUResetRenamed, "software_distribution", "SoftwareDistribution.old")
	log.step(msg.WUResetAbsent, "catroot2", "")
	log.step(msg.WUResetRestarted, "wuauserv", "")
	log.step(msg.WUResetNext, "", "")

	if log.failed() {
		t.Error("a log with no failure must not report one")
	}
	out, err := log.verdict()
	if err != nil {
		t.Fatalf("verdict = %v, want success", err)
	}
	want := "Windows Update (wuauserv) : arrêté.\n" +
		"Services de chiffrement (cryptsvc) : déjà arrêté.\n" +
		"Magasin Windows Update (SoftwareDistribution) : renommé en SoftwareDistribution.old.\n" +
		"Cache de signatures de catalogues (catroot2) : absent, rien à renommer.\n" +
		"Windows Update (wuauserv) : redémarré.\n" +
		"\n" +
		"Windows reconstruira ces dossiers à la prochaine recherche : lancer « Rechercher les mises à jour » pour vérifier que le poste repart."
	if out.Text != want {
		t.Errorf("report:\n%q\nwant\n%q", out.Text, want)
	}
	if code, _ := msg.Coded(out); code != "wu_reset.report" {
		t.Errorf("code = %q", code)
	}
}

// The interesting outcome, and the common one: SoftwareDistribution moved but
// catroot2 did not. A useful run that still has to read as failed — and whose
// report has to carry both halves, because that is the diagnosis.
func TestWUResetLogReportsAPartialRun(t *testing.T) {
	var log wuResetLog
	log.step(msg.WUResetRenamed, "software_distribution", "SoftwareDistribution.old")
	log.fail(msg.WUResetRenameFailed, "catroot2", `C:\Windows\System32\catroot2`, errors.New("access is denied"))
	log.step(msg.WUResetRestarted, "wuauserv", "")

	if !log.failed() {
		t.Fatal("a recorded failure must show")
	}
	out, err := log.verdict()
	if err == nil {
		t.Fatal("a partial reset must fail the command")
	}
	// What did work is not dropped: the poste's store *has* moved, and an
	// administrator reading only "échec" would redo the whole thing. The
	// failing step is in the report too, with the underlying cause.
	want := "Magasin Windows Update (SoftwareDistribution) : renommé en SoftwareDistribution.old.\n" +
		`ÉCHEC — renommage de C:\Windows\System32\catroot2 : access is denied` + "\n" +
		"Windows Update (wuauserv) : redémarré."
	if out.Text != want {
		t.Errorf("report:\n%q\nwant\n%q", out.Text, want)
	}
	if err.Error() != `réinitialisation incomplète : renommage de C:\Windows\System32\catroot2` {
		t.Errorf("the error should name what did not work: %v", err)
	}
	if code, params := msg.Of(err); code != "wu_reset.incomplete" ||
		params["failed"] != "rename_failed\tcatroot2\t"+`C:\Windows\System32\catroot2` {
		t.Errorf("error code = %q %v", code, params)
	}
	if code, params := msg.Coded(out); code != "wu_reset.report" || params["e1"] != "access is denied" {
		t.Errorf("report code = %q %v", code, params)
	}
}

func TestWUResetLogJoinsEveryFailure(t *testing.T) {
	var log wuResetLog
	log.fail(msg.WUResetStopFailed, "bits", "", errors.New("timeout"))
	log.step(msg.WUResetKept, "", "")
	log.fail(msg.WUResetRestartFailed, "wuauserv", "",
		msg.Wrap("service.query_failed", nil, errors.New("access denied")))

	out, err := log.verdict()
	if err == nil {
		t.Fatal("failures must fail the command")
	}
	if err.Error() != "réinitialisation incomplète : arrêt du service Transfert intelligent en arrière-plan (BITS) (bits) ; "+
		"redémarrage du service Windows Update (wuauserv)" {
		t.Errorf("error = %q", err)
	}
	want := "ÉCHEC — arrêt du service Transfert intelligent en arrière-plan (BITS) (bits) : timeout\n" +
		"Aucun dossier renommé : un service tient encore le magasin de mises à jour.\n" +
		"ÉCHEC — redémarrage du service Windows Update (wuauserv) : interrogation du service : access denied"
	if out.Text != want {
		t.Errorf("report:\n%q\nwant\n%q", out.Text, want)
	}
	// Each failure's error is quoted with its own code, when it has one.
	_, params := msg.Coded(out)
	if params["e1"] != "timeout" || params["e1_code"] != nil ||
		params["e2_code"] != "service.query_failed" || params["e2_detail"] != "access denied" {
		t.Errorf("params = %v", params)
	}
}

// The command puts a poste back in a state where it *can* update; it does not
// update it. The last line of a successful run says so, and points at the
// command that verifies the repair.
func TestWUResetNextStepPointsAtTheSearch(t *testing.T) {
	if !strings.Contains(msg.WUResetNextStep, "Rechercher les mises à jour") {
		t.Errorf("the guidance should name the follow-up command: %q", msg.WUResetNextStep)
	}
}

// --- Moving a directory aside -----------------------------------------------

func TestMoveAsideRenamesWithinTheParent(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "SoftwareDistribution")
	if err := os.MkdirAll(filepath.Join(dir, "Download"), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := moveAside(dir, "SoftwareDistribution.old"); err != nil {
		t.Fatalf("moveAside = %v, want success", err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Error("the original directory is still there")
	}
	// Renamed, not deleted: the previous store stays readable until the next
	// reset drops it.
	if _, err := os.Stat(filepath.Join(root, "SoftwareDistribution.old", "Download")); err != nil {
		t.Errorf("content did not travel with the rename: %v", err)
	}
}

// The deviation from Microsoft's written `ren`, and the reason for it: an
// administrator running this twice on a poste that did not come back the first
// time is the normal case, and the article's version fails outright there.
func TestMoveAsideIsRepeatable(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "catroot2")

	for run := 1; run <= 2; run++ {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		marker := filepath.Join(dir, "run.txt")
		if err := os.WriteFile(marker, []byte(strings.Repeat("x", run)), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := moveAside(dir, "catroot2.old"); err != nil {
			t.Fatalf("run %d: moveAside = %v, want success", run, err)
		}
	}

	// The backup is the *latest* run, not the first: the stale one was dropped
	// rather than left to block the rename.
	data, err := os.ReadFile(filepath.Join(root, "catroot2.old", "run.txt"))
	if err != nil {
		t.Fatalf("second backup missing: %v", err)
	}
	if len(data) != 2 {
		t.Errorf("backup holds run %d, want the second one", len(data))
	}
}

func TestMoveAsideReportsAnAbsentFolder(t *testing.T) {
	// Distinct from a failure: Windows recreates these on demand, so an absent
	// one is a poste that has not searched since its last reset.
	err := moveAside(filepath.Join(t.TempDir(), "nowhere"), "nowhere.old")
	if !errors.Is(err, errWUResetFolderAbsent) {
		t.Errorf("moveAside on a missing directory = %v, want errWUResetFolderAbsent", err)
	}
}

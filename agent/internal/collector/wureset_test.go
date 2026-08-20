package collector

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// --- The tables -------------------------------------------------------------

// The four services Microsoft's procedure names, in its order. Spelled out
// rather than derived from the table, like the maintenance catalogue: this is a
// documented recipe, and adding a service to it should cost a deliberate edit
// here as well as there.
func TestWUResetServicesMatchTheDocumentedProcedure(t *testing.T) {
	want := []string{"wuauserv", "cryptsvc", "bits", "msiserver"}
	got := make([]string, 0, len(wuResetServices))
	for _, s := range wuResetServices {
		got = append(got, s.name)
		if strings.TrimSpace(s.label) == "" {
			t.Errorf("%s: no label — the report is read by a human", s.name)
		}
	}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Errorf("services = %v, want %v", got, want)
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
			t.Errorf("%s: no path", f.label)
		}
		for _, e := range f.elems {
			if strings.ContainsAny(e, `\/`) || e == ".." {
				t.Errorf("%s: path element %q must be a bare name", f.label, e)
			}
		}
		if strings.ContainsAny(f.backup, `\/`) || f.backup == ".." {
			t.Errorf("%s: backup name %q must be a bare name", f.label, f.backup)
		}
		if strings.TrimSpace(f.label) == "" {
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

func TestWUResetLogSucceedsWhenNothingFailed(t *testing.T) {
	var log wuResetLog
	log.step("Windows Update (%s) : arrêté.", "wuauserv")
	log.step("Magasin : renommé.")

	if log.failed() {
		t.Error("a log with no failure must not report one")
	}
	out, err := log.verdict()
	if err != nil {
		t.Fatalf("verdict = %v, want success", err)
	}
	if !strings.Contains(out, "wuauserv") || !strings.Contains(out, "renommé") {
		t.Errorf("steps lost from the report:\n%s", out)
	}
}

// The interesting outcome, and the common one: SoftwareDistribution moved but
// catroot2 did not. A useful run that still has to read as failed — and whose
// report has to carry both halves, because that is the diagnosis.
func TestWUResetLogReportsAPartialRun(t *testing.T) {
	var log wuResetLog
	log.step("Magasin Windows Update : renommé en SoftwareDistribution.old.")
	log.fail("renommage de C:\\Windows\\System32\\catroot2", errors.New("access is denied"))
	log.step("Windows Update (wuauserv) : redémarré.")

	if !log.failed() {
		t.Fatal("a recorded failure must show")
	}
	out, err := log.verdict()
	if err == nil {
		t.Fatal("a partial reset must fail the command")
	}
	if !strings.Contains(err.Error(), "catroot2") {
		t.Errorf("the error should name what did not work: %v", err)
	}
	// What did work is not dropped: the poste's store *has* moved, and an
	// administrator reading only "échec" would redo the whole thing.
	if !strings.Contains(out, "SoftwareDistribution.old") {
		t.Errorf("successful steps lost from the report:\n%s", out)
	}
	// The failing step is in the report too, with the underlying cause.
	if !strings.Contains(out, "access is denied") {
		t.Errorf("the cause is missing from the report:\n%s", out)
	}
}

func TestWUResetLogJoinsEveryFailure(t *testing.T) {
	var log wuResetLog
	log.fail("arrêt du service BITS (bits)", errors.New("timeout"))
	log.fail("redémarrage du service Windows Update (wuauserv)", errors.New("access denied"))

	_, err := log.verdict()
	if err == nil {
		t.Fatal("failures must fail the command")
	}
	for _, want := range []string{"bits", "wuauserv"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q does not name %q", err, want)
		}
	}
}

// The command puts a poste back in a state where it *can* update; it does not
// update it. The last line of a successful run says so, and points at the
// command that verifies the repair.
func TestWUResetNextStepPointsAtTheSearch(t *testing.T) {
	if !strings.Contains(wuResetNextStep, "Rechercher les mises à jour") {
		t.Errorf("the guidance should name the follow-up command: %q", wuResetNextStep)
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

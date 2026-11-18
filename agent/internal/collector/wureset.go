package collector

import (
	"errors"
	"os"
	"path/filepath"
	"time"

	"tiai/agent/internal/msg"
)

// Reset of the Windows Update components — the procedure Microsoft documents
// for a poste whose updates no longer search, download or install (« Réinitialiser
// les composants Windows Update »): stop the services that hold the update
// store, move the store and the catalogue signature cache aside, start the
// services again. Windows rebuilds both directories at the next search.
//
// Written natively rather than as the shell one-liner the article gives, for
// the same reasons as spooler_reset (see maintenance_windows.go): the service
// manager reports the real state of a service instead of a localized sentence,
// it lets the rename genuinely *wait* for the services to let go of their
// handles, and it keeps the agent free of a shell. It also fixes the article's
// one practical flaw — `ren` fails outright the second time it is run, because
// `SoftwareDistribution.old` is already there, and running it twice on a
// stubborn poste is the normal case rather than the exception.
//
// Deliberately *not* included, though they appear in older or third-party
// versions of the same recipe: re-registering the WU DLLs with regsvr32 (a
// no-op since Windows 8, the components are registered by servicing),
// `netsh winsock reset` (requires a restart behind it — see the note in
// plan-commandes-distantes.md §2), and rewriting the service security
// descriptors with `sc sdset` (which locks an administrator out of the service
// when it gets it wrong). None of them is needed on a supported build, and
// each of them is harder to undo than the whole of what this command does.
//
// As with the rest of the collector, the interesting logic lives here rather
// than behind a build tag — the tables, the report, the verdict, and the
// rename itself, which is plain os/filepath and so can be exercised against a
// real directory on any platform. Only the service manager, which has no
// counterpart elsewhere, lives in wureset_windows.go. The report's sentences
// are msg's (msg.WUResetReport), coded for the console.

// wuResetTimeout bounds the whole operation. Each individual service
// transition is already capped at serviceStateTimeout; this is the envelope
// for the four of them plus the two renames, and it is a hang detector rather
// than a budget — the nominal run takes seconds.
const wuResetTimeout = 10 * time.Minute

// errWUResetFolderAbsent means there was nothing to move: reported as a step,
// not as a failure. A poste can legitimately have no catroot2 if a previous
// reset left it to be rebuilt and nothing has searched for updates since.
var errWUResetFolderAbsent = errors.New("dossier absent")

// wuResetServices are the services that hold the update store open, by
// their service name; the report names them (msg.WUResetServices).
//
// The order is Microsoft's, and it is also the order they are started again
// in: none of the four depends on another, so the article's order is kept
// rather than a reversal that would only look cleverer.
var wuResetServices = []string{"wuauserv", "cryptsvc", "bits", "msiserver"}

// wuResetFolder is one directory renamed aside, relative to %SystemRoot%.
//
// The path is held as its elements rather than as a string with separators in
// it: this file is compiled on every platform, and joining is the Windows
// implementation's job.
type wuResetFolder struct {
	// key names the folder in the report (msg.WUResetFolders).
	key   string
	elems []string
	// backup is a bare name, joined onto the directory's own parent — never a
	// path. Enforced by a test: this is the one place the command writes
	// outside a directory Windows owns and rebuilds.
	backup string
}

var wuResetFolders = []wuResetFolder{
	{
		// The update store: metadata, the download cache and the update
		// history the Settings app shows. Moving it aside is what actually
		// fixes a poste; the cost is that history, and a first search that has
		// to fetch everything again.
		key:    "software_distribution",
		elems:  []string{"SoftwareDistribution"},
		backup: "SoftwareDistribution.old",
	},
	{
		// The catalogue signature cache. Held open by cryptsvc, which is why
		// that service is in the list at all.
		key:    "catroot2",
		elems:  []string{"System32", "catroot2"},
		backup: "catroot2.old",
	},
}

// wuResetLog accumulates the report the console shows, step by step, the
// failures among them deciding the verdict.
//
// A partial reset is the interesting outcome and the common one: catroot2
// held open by a straggler while SoftwareDistribution moved fine is a
// *useful* run that still has to be reported as failed. The steps say what
// happened, the failures what to do about it.
type wuResetLog struct {
	steps []msg.WUResetStep
}

// step records something that went as intended: its kind (msg.WUReset*),
// the service or folder it is about, and arg — the backup's name for a
// folder renamed.
func (l *wuResetLog) step(kind, subject, arg string) {
	l.steps = append(l.steps, msg.WUResetStep{Kind: kind, Subject: subject, Arg: arg})
}

// fail records a step that did not, both in the report and in the verdict;
// arg is the folder's path for a rename.
func (l *wuResetLog) fail(kind, subject, arg string, err error) {
	l.steps = append(l.steps, msg.WUResetStep{Kind: kind, Subject: subject, Arg: arg, Err: msg.FromError(err)})
}

// failed reports whether anything has gone wrong so far. Read between phases:
// the folders are not touched while a service that holds them is still up.
func (l *wuResetLog) failed() bool {
	for _, s := range l.steps {
		if s.Failed() {
			return true
		}
	}
	return false
}

// verdict renders the report and the outcome.
//
// The report is returned in both cases, like the maintenance verdicts: for
// this command the step-by-step *is* the diagnosis, and an error with no list
// behind it would send an administrator to the poste itself — the thing the
// command exists to avoid.
func (l *wuResetLog) verdict() (msg.Message, error) {
	report, err := msg.WUResetReport(l.steps)
	if err != nil {
		return report, err
	}
	return report, nil
}

// moveAside renames dir to backup within its own parent, discarding a backup
// left by a previous reset first.
//
// That discard is what makes the command repeatable, and it is the one
// deviation from Microsoft's written procedure: `ren` fails the second time
// because the target already exists, and an administrator running this twice
// on a poste that did not come back the first time is the normal case. The
// previous backup is the older of two copies of a cache Windows rebuilds by
// itself, so dropping it costs nothing an admin would miss.
func moveAside(dir, backup string) error {
	if _, err := os.Stat(dir); err != nil {
		if os.IsNotExist(err) {
			return errWUResetFolderAbsent
		}
		return err
	}
	// backup is a bare name from wuResetFolders, joined onto this directory's
	// own parent — nothing here comes from the network (a test pins that).
	target := filepath.Join(filepath.Dir(dir), backup)
	if err := os.RemoveAll(target); err != nil {
		return msg.Wrap("wu_reset.backup_not_removed", msg.Params{"path": target}, err)
	}
	return os.Rename(dir, target)
}

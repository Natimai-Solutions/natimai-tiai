package msg

import (
	"fmt"
	"strings"
)

// The agent's composite texts — a report of several lines, two refusals in
// one sentence — coded too (verification of 2026-11-18: they reached an
// English console in French).
//
// A parameter is a flat value, so a list travels as one text: one item per
// line, its fields separated by tabs, the free text last (listParam). What
// an item quotes — the error of a failed step — goes beside, numbered, as
// Nest puts it (e1, e1_code, e1_detail…). The console reads them back the
// same way (frontend/src/services/commands.ts).
//
// Each builder writes the French from the report itself, then checks that
// the code's sentence, written from the parameters, reads the same: a value
// the list cannot carry (a line break in an update's title) sends the text
// alone, as before. So does a report beyond what the server keeps (Coded).

// listParam joins items, one per line, their fields separated by tabs.
func listParam(items [][]string) string {
	lines := make([]string, 0, len(items))
	for _, fields := range items {
		lines = append(lines, strings.Join(fields, "\t"))
	}
	return strings.Join(lines, "\n")
}

// listItems splits what listParam joined: n fields per item at most, the
// last one keeping any tab of its own.
func listItems(value string, n int) [][]string {
	if value == "" {
		return nil
	}
	var items [][]string
	for _, line := range strings.Split(value, "\n") {
		fields := strings.SplitN(line, "\t", n)
		for len(fields) < n {
			fields = append(fields, "")
		}
		items = append(items, fields)
	}
	return items
}

func intParam(p Params, key string) int {
	switch v := p[key].(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	}
	return 0
}

// checked is the message of code with params, when its sentence reads
// text; else text alone.
func checked(code string, params Params, text string) Message {
	if m := New(code, params); m.Text == text {
		return m
	}
	return Plain(text)
}

// --- Windows Update: the install report (wu.install_report). ----------------

// WUInstall is what an install did (collector.summarizeInstall).
type WUInstall struct {
	Selected, Installed, Skipped int
	Reboot                       bool
	Updates                      []WUInstalled
}

// WUInstalled is one update's outcome: its name (« KB5063878 — Titre »,
// Windows' own words), its result (a key of WUResults) and, when something
// went wrong, its HRESULT in hex.
type WUInstalled struct {
	Name, Result, HResult string
}

// Message is the report, coded "wu.install_report".
func (r WUInstall) Message() Message {
	updates := make([][]string, 0, len(r.Updates))
	for _, u := range r.Updates {
		updates = append(updates, []string{u.Result, u.HResult, u.Name})
	}
	params := Params{"selected": r.Selected, "installed": r.Installed, "skipped": r.Skipped,
		"reboot": r.Reboot, "updates": listParam(updates)}
	return checked("wu.install_report", params, r.french())
}

func wuInstallFrom(p Params) WUInstall {
	r := WUInstall{Selected: intParam(p, "selected"), Installed: intParam(p, "installed"),
		Skipped: intParam(p, "skipped"), Reboot: boolParam(p, "reboot")}
	for _, f := range listItems(str(p, "updates"), 3) {
		r.Updates = append(r.Updates, WUInstalled{Result: f[0], HResult: f[1], Name: f[2]})
	}
	return r
}

func (r WUInstall) french() string {
	var lines []string
	switch {
	case r.Selected == 0 && r.Skipped == 0:
		lines = append(lines, "Aucune mise à jour applicable : le poste est à jour.")
	case r.Selected == 0:
		lines = append(lines, "Aucune mise à jour installable sans intervention sur le poste.")
	default:
		lines = append(lines, fmt.Sprintf("%d mise(s) à jour retenue(s), %d installée(s).",
			r.Selected, r.Installed))
	}
	if r.Skipped > 0 {
		lines = append(lines, fmt.Sprintf(
			"%d ignorée(s) : elles réclament une interaction utilisateur, impossible depuis un service.",
			r.Skipped))
	}
	for _, u := range r.Updates {
		if u.HResult == "" {
			lines = append(lines, fmt.Sprintf("%s : %s", u.Name, WUResults[u.Result]))
		} else {
			lines = append(lines, fmt.Sprintf("%s : %s (%s)", u.Name, WUResults[u.Result], u.HResult))
		}
	}
	if missing := r.Selected - r.Installed; missing > 0 {
		lines = append(lines, fmt.Sprintf(
			"%d mise(s) à jour n'ont pas pu être téléchargée(s), et n'ont donc pas été installée(s).",
			missing))
	}
	if r.Reboot {
		lines = append(lines,
			"", "Redémarrage requis pour finaliser l'installation (commande « Redémarrer »).")
	}
	return strings.Join(lines, "\n")
}

// --- Windows Update: the reset's steps (wu_reset.report, wu_reset.incomplete).

// The steps of a reset (WUResetStep.Kind).
const (
	WUResetAlreadyStopped = "already_stopped"
	WUResetStopped        = "stopped"
	WUResetStopFailed     = "stop_failed"
	WUResetKept           = "kept" // no folder renamed: a service still holds the store
	WUResetRenamed        = "renamed"
	WUResetAbsent         = "absent"
	WUResetRenameFailed   = "rename_failed"
	WUResetRestarted      = "restarted"
	WUResetRestartFailed  = "restart_failed"
	WUResetNext           = "next" // what to run next, after a whole reset
)

// WUResetServices names the services a reset stops, by their service name.
// The service names are opaque (`bits`, `cryptsvc`) and the report is read
// by a human deciding whether the poste came back whole.
var WUResetServices = map[string]string{
	"wuauserv":  "Windows Update",
	"cryptsvc":  "Services de chiffrement",
	"bits":      "Transfert intelligent en arrière-plan (BITS)",
	"msiserver": "Windows Installer",
}

// WUResetFolders names the folders a reset renames aside.
var WUResetFolders = map[string]string{
	"software_distribution": "Magasin Windows Update (SoftwareDistribution)",
	"catroot2":              "Cache de signatures de catalogues (catroot2)",
}

// WUResetNextStep is the last line of a whole reset. The command puts a
// poste back in a state where it *can* update; it does not update it, and
// the reader should not have to infer that.
const WUResetNextStep = "Windows reconstruira ces dossiers à la prochaine recherche : " +
	"lancer « Rechercher les mises à jour » pour vérifier que le poste repart."

// WUResetStep is one step of a reset: its kind, the service (its name) or
// the folder (a key of WUResetFolders) it is about, Arg — the backup's name
// for a folder renamed, the folder's path for a rename that failed — and,
// for a failure, its error.
type WUResetStep struct {
	Kind, Subject, Arg string
	Err                Message
}

// Failed reports whether the step is a failure.
func (s WUResetStep) Failed() bool {
	switch s.Kind {
	case WUResetStopFailed, WUResetRenameFailed, WUResetRestartFailed:
		return true
	}
	return false
}

// WUResetReport is a reset's report, coded "wu_reset.report", and its
// verdict: nil when every step went, else "wu_reset.incomplete" naming what
// did not. The report is returned in both cases: for this command the
// step-by-step *is* the diagnosis.
func WUResetReport(steps []WUResetStep) (Message, *Error) {
	items := make([][]string, 0, len(steps))
	var failed [][]string
	params := Params{}
	for _, s := range steps {
		item := []string{s.Kind, s.Subject}
		if s.Arg != "" {
			item = append(item, s.Arg)
		}
		items = append(items, item)
		if s.Failed() {
			failed = append(failed, item)
			Nest(params, fmt.Sprintf("e%d", len(failed)), s.Err)
		}
	}
	params["steps"] = listParam(items)
	// The errors' own codes, when the whole would not fit with them.
	if !Fits(params) {
		for i := range failed {
			params = Unnested(params, fmt.Sprintf("e%d", i+1))
		}
	}
	report := checked("wu_reset.report", params, wuResetFrench(steps))
	if len(failed) == 0 {
		return report, nil
	}
	whats := make([]string, 0, len(failed))
	for _, s := range steps {
		if s.Failed() {
			whats = append(whats, s.what())
		}
	}
	text := "réinitialisation incomplète : " + strings.Join(whats, " ; ")
	return report, &Error{Message: checked("wu_reset.incomplete", Params{"failed": listParam(failed)}, text)}
}

func wuResetStepsFrom(p Params) []WUResetStep {
	var steps []WUResetStep
	n := 0
	for _, f := range listItems(str(p, "steps"), 3) {
		s := WUResetStep{Kind: f[0], Subject: f[1], Arg: f[2]}
		if s.Failed() {
			n++
			s.Err = Plain(str(p, fmt.Sprintf("e%d", n)))
		}
		steps = append(steps, s)
	}
	return steps
}

func (s WUResetStep) service() string {
	label := WUResetServices[s.Subject]
	if label == "" {
		label = s.Subject
	}
	return fmt.Sprintf("%s (%s)", label, s.Subject)
}

func (s WUResetStep) folder() string {
	if label := WUResetFolders[s.Subject]; label != "" {
		return label
	}
	return s.Subject
}

// what names a failed step, in the report and in the verdict.
func (s WUResetStep) what() string {
	switch s.Kind {
	case WUResetStopFailed:
		return "arrêt du service " + s.service()
	case WUResetRestartFailed:
		return "redémarrage du service " + s.service()
	}
	return "renommage de " + s.Arg
}

func wuResetFrench(steps []WUResetStep) string {
	var lines []string
	for _, s := range steps {
		switch s.Kind {
		case WUResetAlreadyStopped:
			lines = append(lines, s.service()+" : déjà arrêté.")
		case WUResetStopped:
			lines = append(lines, s.service()+" : arrêté.")
		case WUResetRestarted:
			lines = append(lines, s.service()+" : redémarré.")
		case WUResetKept:
			lines = append(lines, "Aucun dossier renommé : un service tient encore le magasin de mises à jour.")
		case WUResetRenamed:
			lines = append(lines, fmt.Sprintf("%s : renommé en %s.", s.folder(), s.Arg))
		case WUResetAbsent:
			lines = append(lines, s.folder()+" : absent, rien à renommer.")
		case WUResetNext:
			lines = append(lines, "", WUResetNextStep)
		default:
			if s.Failed() {
				lines = append(lines, fmt.Sprintf("ÉCHEC — %s : %s", s.what(), s.Err.Text))
			}
		}
	}
	return strings.Join(lines, "\n")
}

func wuResetIncompleteFrench(p Params) string {
	var whats []string
	for _, f := range listItems(str(p, "failed"), 3) {
		whats = append(whats, WUResetStep{Kind: f[0], Subject: f[1], Arg: f[2]}.what())
	}
	return "réinitialisation incomplète : " + strings.Join(whats, " ; ")
}

// --- The print spooler's reset that went partly (spooler.report). -----------

// SpoolerReport is what a spooler reset did: the queue emptied of removed
// files, or purgeErr; the spooler restarted or not. The nominal run is
// "spooler.reset"; the others, "spooler.report", the queue's error quoted
// as "purge" (Nest).
func SpoolerReport(removed int, purgeErr error, restarted bool) Message {
	if purgeErr == nil && restarted {
		return New("spooler.reset", Params{"removed": removed})
	}
	params := Params{"restarted": restarted}
	if purgeErr != nil {
		Nest(params, "purge", FromError(purgeErr))
	} else {
		params["removed"] = removed
	}
	return New("spooler.report", params)
}

func spoolerReportFrench(p Params) string {
	lines := []string{"Spouleur d'impression arrêté."}
	if _, failed := p["purge"]; failed {
		lines = append(lines, "Purge incomplète de la file : "+str(p, "purge"))
	} else {
		lines = append(lines, fmt.Sprintf("File d'impression purgée (%v fichier(s)).", p["removed"]))
	}
	if boolParam(p, "restarted") {
		lines = append(lines, "Spouleur d'impression redémarré.")
	} else {
		lines = append(lines, "Le spouleur n'a PAS pu être redémarré.")
	}
	return strings.Join(lines, "\n")
}

// --- A signed package refused by both methods (deploy.both_refused). --------

// BothMethodsRefused reports a signed package that method B refused and
// method A refused after it: method B first — the administrator signed the
// package, its refusal is the cause — then method A, each quoted (Nest).
func BothMethodsRefused(methodB, methodA error) *Error {
	params := Params{}
	Nest(params, "b", FromError(methodB))
	Nest(params, "a", FromError(methodA))
	if !Fits(params) {
		params = Unnested(Unnested(params, "a"), "b")
	}
	return &Error{Message: New("deploy.both_refused", params)}
}

func bothRefusedFrench(p Params) string {
	a := str(p, "a")
	if !strings.HasPrefix(a, "méthode A") {
		a = "méthode A : " + a
	}
	return fmt.Sprintf("méthode B : %s ; %s", str(p, "b"), a)
}

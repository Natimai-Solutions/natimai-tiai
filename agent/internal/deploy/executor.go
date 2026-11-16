package deploy

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"tiai/agent/internal/models"
)

// Env is what the executor needs from the outside world: the server, Windows,
// the process table. Real on Windows (env_windows.go), fake in tests.
type Env interface {
	// Download fetches one file of the package to dest, resuming a partial
	// file, and checks its size and SHA-256 before returning.
	Download(ctx context.Context, packageID string, f FileRef, dest string) error
	// VerifyAuthenticode asks Windows whether the file's signature is valid
	// and trusted (WinVerifyTrust). A note is returned when the check passed
	// with a reservation worth showing (revocation not checkable offline).
	VerifyAuthenticode(path string) (note string, err error)
	// Run starts exe with args — directly, never through a shell — and
	// returns its exit code.
	Run(ctx context.Context, exe string, args []string, dir string) (int64, error)
	// WingetPath locates winget.exe for SYSTEM.
	WingetPath() (string, error)
	// MsiExecPath is %SystemRoot%\System32\msiexec.exe.
	MsiExecPath() string
	// PackagesDir is where packages are unpacked (C:\ProgramData\Tiai\packages).
	PackagesDir() string
}

// Result is what the console shows.
type Result struct {
	Output         string
	RebootRequired bool
}

// Execute runs a package_install or package_uninstall.
func Execute(ctx context.Context, env Env, policy Policy, cmdType string, pkg *models.PackageDelivery) (Result, error) {
	if pkg == nil {
		return Result{}, errors.New("commande sans paquet")
	}
	action := "install"
	if cmdType == "package_uninstall" {
		action = "uninstall"
	}
	if !policy.Enabled() {
		return Result{}, errNotEnabled
	}
	switch pkg.Kind {
	case "winget":
		return executeWinget(ctx, env, policy, action, pkg)
	case "files":
		return executeFiles(ctx, env, policy, action, pkg)
	}
	return Result{}, fmt.Errorf("type de paquet inconnu %q", pkg.Kind)
}

func executeWinget(ctx context.Context, env Env, policy Policy, action string, pkg *models.PackageDelivery) (Result, error) {
	if err := WingetAllowed(pkg.WingetID, policy); err != nil {
		return Result{}, err
	}
	version := pkg.WingetVersion
	if action == "uninstall" {
		version = ""
	}
	args, err := WingetArgs(action, pkg.WingetID, version)
	if err != nil {
		return Result{}, err
	}
	exe, err := env.WingetPath()
	if err != nil {
		return Result{}, err
	}
	code, err := env.Run(ctx, exe, args, filepath.Dir(exe))
	if err != nil {
		return Result{}, fmt.Errorf("winget : %w", err)
	}
	ok, note := WingetVerdict(code)
	if !ok {
		return Result{}, errors.New(note)
	}
	out := fmt.Sprintf("winget %s %s : terminé", action, pkg.WingetID)
	if note != "" {
		out += " (" + note + ")"
	}
	return Result{Output: out}, nil
}

func executeFiles(ctx context.Context, env Env, policy Policy, action string, pkg *models.PackageDelivery) (Result, error) {
	if !ValidPackageID(pkg.ID) {
		return Result{}, fmt.Errorf("identifiant de paquet refusé : %q", pkg.ID)
	}
	raw, err := base64.StdEncoding.DecodeString(pkg.Manifest)
	if err != nil || len(raw) == 0 {
		return Result{}, errors.New("manifeste absent ou mal encodé")
	}
	manifest, err := ParseManifest(raw, pkg.ID)
	if err != nil {
		return Result{}, err
	}
	step := manifest.Install
	if action == "uninstall" {
		step = manifest.Uninstall
	}
	if step == nil {
		return Result{}, fmt.Errorf("le paquet ne définit pas de %s", map[string]string{
			"install": "installation", "uninstall": "désinstallation"}[action])
	}

	dir, err := PackageDir(env.PackagesDir(), pkg.ID)
	if err != nil {
		return Result{}, err
	}

	// Method B first: when it holds, the manifest is the administrator's
	// word for every file and argument.
	method := ""
	var trustNote string
	// Why method B refused a signed package, kept when method A is tried
	// next: the administrator signed it, so that refusal — a thumbprint
	// missing from DeploySigners, a manifest changed since — is the one they
	// act on, not whatever method A then has to say about it.
	var methodBErr error
	if len(policy.Signers) > 0 && pkg.Signature != "" {
		subject, verr := VerifyAdminSignature(raw, pkg.Signature, pkg.SignatureAlgorithm, pkg.Certificate, policy.Signers)
		if verr == nil {
			method = "B"
			trustNote = "paquet signé par " + subject
		} else if len(policy.Publishers) == 0 {
			return Result{}, verr
		} else {
			methodBErr = verr
		}
	}
	// refused closes a method A run with a refusal no retry can lift, and
	// takes the package's folder with it. Under method A the manifest is the
	// server's word, package id included: a folder kept for a retry that
	// cannot succeed is up to the cap of disk per id, for as many ids as a
	// server cares to send (audit S24). What a retry resumes is kept — see
	// resumable, and the exit code below.
	refused := func(err error) (Result, error) {
		_ = os.RemoveAll(dir)
		if methodBErr != nil {
			err = bothMethodsRefused(methodBErr, err)
		}
		return Result{}, err
	}
	if method == "" {
		if len(policy.Publishers) == 0 {
			if len(policy.Signers) == 0 {
				return Result{}, errors.New("aucune méthode de confiance pour les paquets de fichiers n'est activée sur ce poste (DeploySigners / DeployPublishers)")
			}
			return Result{}, errors.New("paquet non signé, et aucun éditeur approuvé sur ce poste (DeployPublishers)")
		}
		method = "A"
		checked, aerr := MethodAStep(*step)
		if aerr != nil {
			return refused(aerr)
		}
		step = &checked
	}

	files := manifest.Files
	if method == "A" {
		if step.Run == MsiExec {
			// msiexec /x {code}: the agent built the command line, no file
			// of the package is needed.
			files = nil
		} else if err := MethodAFiles(files, step.Run, policy.MethodAMaxBytes()); err != nil {
			// The manifest is the server's word here: nothing it names
			// besides the file that runs may be something Windows would
			// load or run from that folder (audit S02).
			return refused(err)
		}
	}

	// Before this folder is made: the ones earlier runs left and nobody came
	// back for.
	PruneStalePackages(env.PackagesDir(), pkg.ID, time.Now())
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return Result{}, fmt.Errorf("dossier du paquet : %w", err)
	}
	// Whatever an earlier attempt left that this manifest does not name goes
	// before anything runs: a failed run must not leave a file for the next.
	if err := PruneDir(dir, files); err != nil {
		return Result{}, fmt.Errorf("dossier du paquet : %w", err)
	}
	// What gets downloaded is what the manifest names — by hash. Under method
	// A an unsigned manifest names them too, but the file that runs is then
	// checked by Windows, and the others are data it reads (MethodAFiles).
	for _, f := range files {
		if err := env.Download(ctx, pkg.ID, f, filepath.Join(dir, f.Name)); err != nil {
			err = fmt.Errorf("téléchargement de %s : %w", f.Name, err)
			if method == "A" && !resumable(err) {
				return refused(err)
			}
			return Result{}, err
		}
	}

	exe := env.MsiExecPath()
	if step.Run != MsiExec {
		exe = filepath.Join(dir, step.Run)
	}
	if method == "A" && step.Run != MsiExec {
		note, verr := env.VerifyAuthenticode(exe)
		if verr != nil {
			return refused(fmt.Errorf("signature de %s refusée par Windows : %w", step.Run, verr))
		}
		name, nerr := SignerName(exe)
		if nerr != nil {
			return refused(nerr)
		}
		if !PublisherApproved(name, policy.Publishers) {
			return refused(fmt.Errorf("éditeur %q non approuvé sur ce poste (DeployPublishers)", name))
		}
		trustNote = "éditeur approuvé : " + name
		if note != "" {
			trustNote += " (" + note + ")"
		}
	}

	code, err := env.Run(ctx, exe, ExpandArgs(step.Args, dir), dir)
	if err != nil {
		return Result{}, fmt.Errorf("lancement de %s : %w", step.Run, err)
	}
	ok, reboot := ExitVerdict(code, manifest.SuccessCodes)
	if !ok {
		msg := fmt.Sprintf("%s a renvoyé le code %d", step.Run, code)
		if trustNote != "" {
			msg += " (" + trustNote + ")"
		}
		return Result{}, errors.New(msg)
	}
	// The files have done their job; a failed run keeps them for a retry
	// (PruneDir clears anything the next manifest does not name).
	_ = os.RemoveAll(dir)

	verb := map[string]string{"install": "Installation", "uninstall": "Désinstallation"}[action]
	// Built from the parts that are there: a package without a version, or a
	// method A uninstall by product code (no file, so no publisher to name),
	// must not read « de App  terminée (méthode A, ) ».
	what := joinNonEmpty(" ", manifest.Name, manifest.Version)
	if what == "" {
		what = "paquet " + pkg.ID
	}
	lines := []string{fmt.Sprintf("%s de %s terminée (%s)", verb, what,
		joinNonEmpty(", ", "méthode "+method, trustNote))}
	if reboot {
		lines = append(lines, "Redémarrage requis pour terminer.")
	}
	return Result{Output: strings.Join(lines, "\n"), RebootRequired: reboot}, nil
}

// bothMethodsRefused reports a signed package that method B refused and
// method A refused after it: method B first — the administrator signed the
// package, its refusal is the cause — then method A.
func bothMethodsRefused(methodB, methodA error) error {
	a := methodA.Error()
	if !strings.HasPrefix(a, "méthode A") {
		a = "méthode A : " + a
	}
	return fmt.Errorf("méthode B : %v ; %s", methodB, a)
}

// joinNonEmpty joins the parts that are not empty.
func joinNonEmpty(sep string, parts ...string) string {
	kept := parts[:0:0]
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			kept = append(kept, p)
		}
	}
	return strings.Join(kept, sep)
}

// resumable tells whether a failed download left something a retry picks up
// where it stopped: the network dropped or the server was busy until the
// attempts ran out (RetryLater), or the run was cut short — the service
// stopping, the budget spent. Anything else is the transfer itself being
// refused: a hash that is not the manifest's, a server sending more than it
// announced, a file it will not serve.
func resumable(err error) bool {
	var later *RetryLater
	return errors.As(err, &later) ||
		errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded)
}

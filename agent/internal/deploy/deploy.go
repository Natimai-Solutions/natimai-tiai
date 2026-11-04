// Package deploy decides whether this poste may run a software package the
// server handed it, and how (dev/plan-deploiement-logiciel.md).
//
// Installing software is running code chosen elsewhere, as SYSTEM: the one
// thing the rest of the command catalogue is built never to do. What keeps it
// bounded is that every trust anchor is local — set by GPO in the registry,
// never by the server (config.Config.Deploy*):
//
//   - winget: allowed only with DeployWinget, and limited to DeployWingetAllow
//     when that list is set; winget itself checks the installer against the
//     hash its manifest publishes;
//   - method B: the package manifest is signed by a certificate whose SHA-256
//     thumbprint is in DeploySigners. The manifest then names the files (by
//     hash) and the command line, and the server can change neither;
//   - method A: failing B, the file to run is an .exe whose Authenticode
//     signature Windows accepts and whose signer is in DeployPublishers.
//
// Everything here is pure Go, testable anywhere. What only Windows can do —
// WinVerifyTrust, finding winget.exe — sits behind Platform.
package deploy

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"regexp"
	"slices"
	"strings"
)

// Policy is the trust a GPO granted on this poste.
type Policy struct {
	Signers     []string // SHA-256 thumbprints, any case, separators ignored
	Publishers  []string // Authenticode signer names
	Winget      bool
	WingetAllow []string // identifiers, or prefixes ending in "*"
}

// Enabled tells whether any deployment is possible at all on this poste.
func (p Policy) Enabled() bool {
	return len(p.Signers) > 0 || len(p.Publishers) > 0 || p.Winget
}

// Step is what to run: a file of the package (or "msiexec") and its arguments.
type Step struct {
	Run  string   `json:"run"`
	Args []string `json:"args"`
}

// FileRef is a file the manifest names.
type FileRef struct {
	Name   string `json:"name"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

// Manifest is a package manifest (format tiai-package-1).
type Manifest struct {
	Format       string    `json:"format"`
	PackageID    string    `json:"package_id"`
	Name         string    `json:"name"`
	Version      string    `json:"version"`
	Files        []FileRef `json:"files"`
	Install      *Step     `json:"install"`
	Uninstall    *Step     `json:"uninstall"`
	SuccessCodes []int64   `json:"success_codes"`
}

// MsiExec is the one value Run may hold that is not a file of the package.
const MsiExec = "msiexec"

const manifestFormat = "tiai-package-1"

var (
	fileName       = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9 ._()+\-]{0,254}$`)
	reservedName   = regexp.MustCompile(`(?i)^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$`)
	sha256Hex      = regexp.MustCompile(`^[0-9a-f]{64}$`)
	wingetID       = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}$`)
	wingetVersion  = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$`)
	productCode    = regexp.MustCompile(`^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$`)
	errNotEnabled  = errors.New("déploiement non activé sur ce poste (aucune clé Deploy* posée par GPO)")
	errNoMsiInMode = errors.New("méthode A : msiexec n'est accepté que pour désinstaller un code produit")
)

const cryptoSHA256 = crypto.SHA256

// ValidFileName mirrors the server's rule: a bare file name, nothing a
// Windows path would read as a directory, a device or a stream.
func ValidFileName(name string) bool {
	return fileName.MatchString(name) && !reservedName.MatchString(name) &&
		!strings.HasSuffix(name, ".") && !strings.HasSuffix(name, " ")
}

// ParseManifest decodes and checks a manifest for package id.
func ParseManifest(raw []byte, packageID string) (*Manifest, error) {
	var m Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fmt.Errorf("manifeste illisible : %w", err)
	}
	if m.Format != manifestFormat {
		return nil, fmt.Errorf("format de manifeste inconnu %q", m.Format)
	}
	if m.PackageID != packageID {
		return nil, errors.New("le manifeste ne décrit pas ce paquet")
	}
	if len(m.Files) == 0 {
		return nil, errors.New("manifeste sans fichier")
	}
	seen := map[string]bool{}
	for _, f := range m.Files {
		if !ValidFileName(f.Name) || seen[strings.ToLower(f.Name)] {
			return nil, fmt.Errorf("nom de fichier refusé dans le manifeste : %q", f.Name)
		}
		seen[strings.ToLower(f.Name)] = true
		if !sha256Hex.MatchString(f.SHA256) || f.Size < 0 {
			return nil, fmt.Errorf("empreinte invalide pour %q", f.Name)
		}
	}
	for _, s := range []*Step{m.Install, m.Uninstall} {
		if s == nil {
			continue
		}
		if s.Run != MsiExec && !seen[strings.ToLower(s.Run)] {
			return nil, fmt.Errorf("%q n'est pas un fichier du paquet", s.Run)
		}
		for _, a := range s.Args {
			if strings.ContainsRune(a, 0) {
				return nil, errors.New("argument invalide")
			}
		}
	}
	if len(m.SuccessCodes) == 0 {
		m.SuccessCodes = []int64{0, 3010, 1641}
	}
	return &m, nil
}

// NormalizeThumbprint upper-cases a thumbprint and drops the separators
// certmgr or PowerShell may print (spaces, colons, dashes).
func NormalizeThumbprint(t string) string {
	var b strings.Builder
	for _, r := range strings.ToUpper(t) {
		if (r >= '0' && r <= '9') || (r >= 'A' && r <= 'F') {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// VerifyAdminSignature checks a method B signature: the certificate is one the
// GPO trusts, and the signature over manifest is valid for its key. Returns
// the signer's subject for the result line.
func VerifyAdminSignature(manifest []byte, sigB64, algorithm, certB64 string, signers []string) (string, error) {
	if sigB64 == "" || certB64 == "" {
		return "", errors.New("paquet non signé")
	}
	der, err := base64.StdEncoding.DecodeString(certB64)
	if err != nil {
		return "", errors.New("certificat de signature mal encodé")
	}
	sum := sha256.Sum256(der)
	thumb := strings.ToUpper(hex.EncodeToString(sum[:]))
	trusted := false
	for _, s := range signers {
		if NormalizeThumbprint(s) == thumb {
			trusted = true
			break
		}
	}
	if !trusted {
		return "", fmt.Errorf("certificat de signature non approuvé sur ce poste (empreinte %s absente de DeploySigners)", thumb)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		return "", fmt.Errorf("certificat de signature illisible : %w", err)
	}
	sig, err := base64.StdEncoding.DecodeString(sigB64)
	if err != nil {
		return "", errors.New("signature mal encodée")
	}
	digest := sha256.Sum256(manifest)
	switch key := cert.PublicKey.(type) {
	case *rsa.PublicKey:
		if algorithm != "rsa-pkcs1-sha256" {
			return "", errors.New("algorithme incompatible avec la clé")
		}
		if err := rsa.VerifyPKCS1v15(key, cryptoSHA256, digest[:], sig); err != nil {
			return "", errors.New("signature invalide : le manifeste a changé depuis sa signature")
		}
	case *ecdsa.PublicKey:
		if algorithm != "ecdsa-sha256" {
			return "", errors.New("algorithme incompatible avec la clé")
		}
		if !verifyECDSA(key, digest[:], sig) {
			return "", errors.New("signature invalide : le manifeste a changé depuis sa signature")
		}
	default:
		return "", errors.New("type de clé non pris en charge")
	}
	return cert.Subject.String(), nil
}

// verifyECDSA accepts both encodings: r‖s as .NET produces it, and DER.
func verifyECDSA(key *ecdsa.PublicKey, digest, sig []byte) bool {
	size := (key.Curve.Params().BitSize + 7) / 8
	if len(sig) == 2*size {
		r := new(big.Int).SetBytes(sig[:size])
		s := new(big.Int).SetBytes(sig[size:])
		if ecdsa.Verify(key, digest, r, s) {
			return true
		}
	}
	return ecdsa.VerifyASN1(key, digest, sig)
}

// PublisherApproved tells whether an Authenticode signer name is in the list
// the GPO set. Case-insensitive, trimmed: the name is typed by an
// administrator from the "Signatures numériques" tab.
func PublisherApproved(name string, publishers []string) bool {
	name = strings.TrimSpace(name)
	if name == "" {
		return false
	}
	for _, p := range publishers {
		if strings.EqualFold(strings.TrimSpace(p), name) {
			return true
		}
	}
	return false
}

// MethodAStep checks a step for method A and returns what to run. The file
// must be an .exe of the package; an uninstall may instead be msiexec with a
// product code, in which case the arguments are rebuilt here, whatever the
// server sent — msiexec takes far more than "/x" (an /i of any URL, among
// others), and nobody signed these.
func MethodAStep(step Step) (Step, error) {
	if step.Run == MsiExec {
		for _, a := range step.Args {
			if productCode.MatchString(a) {
				return Step{Run: MsiExec, Args: []string{"/x", a, "/qn", "/norestart"}}, nil
			}
		}
		return Step{}, errNoMsiInMode
	}
	if !strings.HasSuffix(strings.ToLower(step.Run), ".exe") {
		return Step{}, errors.New("méthode A : seul un exécutable (.exe) signé par un éditeur approuvé peut être lancé — signez le paquet (méthode B)")
	}
	return step, nil
}

// ExpandArgs replaces {dir} with the folder holding the package files.
func ExpandArgs(args []string, dir string) []string {
	out := make([]string, len(args))
	for i, a := range args {
		out[i] = strings.ReplaceAll(a, "{dir}", dir)
	}
	return out
}

// ExitVerdict reads an installer's exit code.
func ExitVerdict(code int64, success []int64) (ok bool, rebootRequired bool) {
	ok = slices.Contains(success, code)
	return ok, ok && (code == 3010 || code == 1641)
}

// --- winget -------------------------------------------------------------------

// WingetAllowed checks a winget identifier against the policy.
func WingetAllowed(id string, p Policy) error {
	if !p.Winget {
		return errors.New("winget non activé sur ce poste (valeur DeployWinget absente ou à 0)")
	}
	if !wingetID.MatchString(id) {
		return fmt.Errorf("identifiant winget refusé : %q", id)
	}
	if len(p.WingetAllow) == 0 {
		return nil
	}
	for _, allowed := range p.WingetAllow {
		allowed = strings.TrimSpace(allowed)
		if prefix, ok := strings.CutSuffix(allowed, "*"); ok {
			if strings.HasPrefix(strings.ToLower(id), strings.ToLower(prefix)) {
				return nil
			}
		} else if strings.EqualFold(allowed, id) {
			return nil
		}
	}
	return fmt.Errorf("identifiant winget %q absent de DeployWingetAllow", id)
}

// WingetArgs builds the winget command line. Every option is the agent's:
// the server contributes the identifier and, optionally, a version, both
// checked against strict patterns so that neither can read as an option.
func WingetArgs(action, id, version string) ([]string, error) {
	if !wingetID.MatchString(id) {
		return nil, fmt.Errorf("identifiant winget refusé : %q", id)
	}
	var args []string
	switch action {
	case "install":
		args = []string{"install", "--id", id, "--exact", "--source", "winget",
			"--scope", "machine", "--silent", "--accept-package-agreements",
			"--accept-source-agreements", "--disable-interactivity"}
		if version != "" {
			if !wingetVersion.MatchString(version) {
				return nil, fmt.Errorf("version winget refusée : %q", version)
			}
			args = append(args, "--version", version)
		}
	case "uninstall":
		args = []string{"uninstall", "--id", id, "--exact", "--source", "winget",
			"--scope", "machine", "--silent", "--accept-source-agreements",
			"--disable-interactivity"}
	default:
		return nil, fmt.Errorf("action winget inconnue %q", action)
	}
	return args, nil
}

// winget's own result codes worth naming (HRESULTs, as unsigned exit codes).
const (
	wingetNoApplicableUpdate = 0x8A15002B
	wingetAlreadyInstalled   = 0x8A150061
	wingetNoPackageFound     = 0x8A150014
)

// WingetVerdict reads winget's exit code: ok, and a sentence for the console.
func WingetVerdict(code int64) (bool, string) {
	switch uint32(code) {
	case 0:
		return true, ""
	case wingetAlreadyInstalled, wingetNoApplicableUpdate:
		return true, "déjà installé, rien à faire"
	case wingetNoPackageFound:
		return false, "aucun paquet winget ne correspond à cet identifiant"
	}
	return false, fmt.Sprintf("winget a échoué (code 0x%08X)", uint32(code))
}

// LatestWingetDir picks, among DesktopAppInstaller folders, the one with the
// highest version — their names read Microsoft.DesktopAppInstaller_<version>_<arch>__<publisher>.
func LatestWingetDir(dirs []string) string {
	best, bestKey := "", []int(nil)
	for _, d := range dirs {
		base := d[strings.LastIndexAny(d, `\/`)+1:]
		parts := strings.Split(base, "_")
		if len(parts) < 2 {
			continue
		}
		key := versionKey(parts[1])
		if best == "" || slices.Compare(key, bestKey) > 0 {
			best, bestKey = d, key
		}
	}
	return best
}

func versionKey(v string) []int {
	var out []int
	for _, p := range strings.Split(v, ".") {
		n := 0
		for _, r := range p {
			if r < '0' || r > '9' {
				break
			}
			n = n*10 + int(r-'0')
		}
		out = append(out, n)
	}
	return out
}

package deploy

import (
	"bytes"
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"tiai/agent/internal/models"
)

// --- helpers ------------------------------------------------------------------

func selfSigned(t *testing.T, key crypto.Signer, cn string) []byte {
	t.Helper()
	tpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageCodeSigning},
	}
	der, err := x509.CreateCertificate(rand.Reader, tpl, tpl, key.Public(), key)
	if err != nil {
		t.Fatal(err)
	}
	return der
}

func thumb(der []byte) string {
	sum := sha256.Sum256(der)
	return strings.ToUpper(hex.EncodeToString(sum[:]))
}

func sha(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func manifestFor(t *testing.T, id string, files map[string][]byte, install *Step) []byte {
	t.Helper()
	m := Manifest{Format: "tiai-package-1", PackageID: id, Name: "Client PRONOTE", Version: "2026.2.8", Install: install}
	for name, content := range files {
		m.Files = append(m.Files, FileRef{Name: name, SHA256: sha(content), Size: int64(len(content))})
	}
	raw, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

// signedPE builds a PE32+ whose certificate table carries a SignedData naming
// signerCN — with a decoy certificate first, so that the reader must find the
// signer by issuer and serial, as Windows does, and not by position.
func signedPE(t *testing.T, signerCN string) []byte {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	decoy := selfSigned(t, key, "Decoy Publisher")
	signer := selfSigned(t, key, signerCN)
	sc, _ := x509.ParseCertificate(signer)

	raw := func(v any) asn1.RawValue {
		b, err := asn1.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		return asn1.RawValue{FullBytes: b}
	}
	ias := raw(struct {
		Issuer asn1.RawValue
		Serial *big.Int
	}{asn1.RawValue{FullBytes: sc.RawIssuer}, sc.SerialNumber})
	signerInfo := raw(struct {
		Version int
		IAS     asn1.RawValue
	}{1, ias})
	certs := asn1.RawValue{Class: asn1.ClassContextSpecific, Tag: 0, IsCompound: true, Bytes: append(append([]byte{}, decoy...), signer...)}
	signedData := raw(struct {
		Version     int
		Digests     asn1.RawValue
		Content     asn1.RawValue
		Certs       asn1.RawValue
		SignerInfos asn1.RawValue
	}{
		1,
		asn1.RawValue{Class: asn1.ClassUniversal, Tag: asn1.TagSet, IsCompound: true},
		raw(struct{ OID asn1.ObjectIdentifier }{asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 7, 1}}),
		certs,
		asn1.RawValue{Class: asn1.ClassUniversal, Tag: asn1.TagSet, IsCompound: true, Bytes: signerInfo.FullBytes},
	})
	// The [0] wrapper by hand: Marshal writes a RawValue's FullBytes as they
	// are, explicit tag or not.
	blob, err := asn1.Marshal(struct {
		OID     asn1.ObjectIdentifier
		Content asn1.RawValue
	}{asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 7, 2}, asn1.RawValue{
		Class: asn1.ClassContextSpecific, Tag: 0, IsCompound: true, Bytes: signedData.FullBytes,
	}})
	if err != nil {
		t.Fatal(err)
	}

	const peOff, optional = 0x40, 0x40 + 24
	dirs := optional + 112
	certOff := dirs + 16*8
	head := make([]byte, certOff)
	copy(head, "MZ")
	binary.LittleEndian.PutUint32(head[0x3C:], peOff)
	copy(head[peOff:], "PE\x00\x00")
	binary.LittleEndian.PutUint16(head[optional:], 0x20B)
	wc := make([]byte, 8)
	binary.LittleEndian.PutUint32(wc, uint32(8+len(blob)))
	binary.LittleEndian.PutUint16(wc[4:], 0x0200)
	binary.LittleEndian.PutUint16(wc[6:], 0x0002)
	wc = append(wc, blob...)
	binary.LittleEndian.PutUint32(head[dirs+8*4:], uint32(certOff))
	binary.LittleEndian.PutUint32(head[dirs+8*4+4:], uint32(len(wc)))
	return append(head, wc...)
}

// --- manifest ------------------------------------------------------------------

func TestParseManifestRefusesWhatIsNotAPlainFile(t *testing.T) {
	for _, name := range []string{`..\evil.exe`, `C:\Windows\x.exe`, "a/b.exe", "con.exe", "x.exe:stream", "trailing. ",
		"nul .cab", "con .txt", "COM1  .exe"} {
		raw := manifestFor(t, "p", map[string][]byte{name: []byte("x")}, &Step{Run: name})
		if _, err := ParseManifest(raw, "p"); err == nil {
			t.Errorf("%q accepted", name)
		}
	}
}

// A reserved device name is one by its stem — what precedes the first dot —
// in any case, and whatever spaces or dots trail it: Windows drops them
// before it looks the name up, so "nul .cab" is NUL. The server applies the
// same rule (backend/app/features/package/manifest.py, valid_file_name).
func TestValidFileNameRefusesAReservedDeviceStem(t *testing.T) {
	for _, name := range []string{
		"con", "CON", "prn", "aux", "nul", "com1", "COM9", "lpt1", "LPT9", "com0", "lpt0",
		"con.txt", "NUL.cab", "nul.tar.gz", "Aux.h", "com1.exe", "lpt1.txt",
		// A space, or several, before the extension.
		"nul .cab", "con .txt", "NUL  .cab", "Prn .txt", "aux .tar.gz", "com1 .exe", "LPT9 .txt",
		// Dots and spaces mixed after the stem.
		"nul..cab", "nul. .cab", "nul . .cab", "con ..txt", "con .a b.txt",
		// Superscript digits, which Windows takes after COM and LPT: outside
		// what a file name may hold at all.
		"com¹", "COM².txt", "lpt³ .txt",
		// Never a trailing dot or space, device or not.
		"nul ", "nul.", "setup.exe ", "setup.exe.",
	} {
		if ValidFileName(name) {
			t.Errorf("%q accepted", name)
		}
	}
	for _, name := range []string{
		"console.exe", "con1.txt", "nul-device.txt", "nulle part.txt", "con txt.cab", "auxiliary.dll",
		"com10.txt", "lpt.txt", "com.exe", "setup con.exe", "a.nul", "x.con .txt", "data .cab",
		"Install_PRNclient.exe", "ClientPRONOTE.iss", "prn(1).txt",
	} {
		if !ValidFileName(name) {
			t.Errorf("%q refused", name)
		}
	}
}

func TestParseManifestChecksTheRunFileAndThePackage(t *testing.T) {
	raw := manifestFor(t, "p", map[string][]byte{"a.exe": []byte("x")}, &Step{Run: "b.exe"})
	if _, err := ParseManifest(raw, "p"); err == nil {
		t.Error("run file outside the package accepted")
	}
	raw = manifestFor(t, "p", map[string][]byte{"a.exe": []byte("x")}, &Step{Run: "a.exe"})
	if _, err := ParseManifest(raw, "other"); err == nil {
		t.Error("manifest of another package accepted")
	}
	m, err := ParseManifest(raw, "p")
	if err != nil {
		t.Fatal(err)
	}
	if len(m.SuccessCodes) != 3 {
		t.Errorf("default success codes = %v", m.SuccessCodes)
	}
}

// backendManifest is a manifest as the server writes it
// (backend/app/features/package/manifest.py build): keys sorted, two-space
// indent, non-ASCII left as is, a trailing newline, an uninstall by product
// code and every optional key present.
const backendManifest = `{
  "files": [
    {
      "name": "ClientPRONOTE.iss",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000001",
      "size": 22
    },
    {
      "name": "Install_PRNclient.exe",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000002",
      "size": 1048576
    }
  ],
  "format": "tiai-package-1",
  "install": {
    "args": [
      "-s",
      "-f1{dir}\\ClientPRONOTE.iss"
    ],
    "run": "Install_PRNclient.exe"
  },
  "name": "Client PRONOTE é",
  "package_id": "0f1e2d3c-4b5a-4987-8a6b-5c4d3e2f1a0b",
  "success_codes": [
    0,
    3010
  ],
  "uninstall": {
    "args": [
      "/x",
      "{01234567-89AB-CDEF-0123-456789ABCDEF}"
    ],
    "run": "msiexec"
  },
  "version": "2026.2.8"
}
`

// What the server produces must keep parsing once keys are checked strictly:
// the full form above, and the one with neither step (null) and no args.
func TestParseManifestAcceptsWhatTheServerWrites(t *testing.T) {
	m, err := ParseManifest([]byte(backendManifest), pronoteID)
	if err != nil {
		t.Fatal(err)
	}
	if m.Install == nil || len(m.Install.Args) != 2 || m.Uninstall == nil || m.Uninstall.Run != MsiExec ||
		len(m.Files) != 2 || m.Files[1].Size != 1048576 || len(m.SuccessCodes) != 2 || m.Name != "Client PRONOTE é" {
		t.Errorf("decoded %+v", m)
	}
	bare := strings.NewReplacer(
		`"uninstall": {
    "args": [
      "/x",
      "{01234567-89AB-CDEF-0123-456789ABCDEF}"
    ],
    "run": "msiexec"
  }`, `"uninstall": null`,
		`"args": [
      "-s",
      "-f1{dir}\\ClientPRONOTE.iss"
    ],`, `"args": [],`,
		`"success_codes": [
    0,
    3010
  ],`, `"success_codes": [],`).Replace(backendManifest)
	if bare == backendManifest {
		t.Fatal("replacements did not apply")
	}
	m, err = ParseManifest([]byte(bare), pronoteID)
	if err != nil {
		t.Fatal(err)
	}
	if m.Uninstall != nil || len(m.Install.Args) != 0 || len(m.SuccessCodes) != 3 {
		t.Errorf("decoded %+v", m)
	}
}

// encoding/json reads keys without regard to case, Unicode folding included,
// and merges duplicates; PowerShell's ConvertFrom-Json, in the signing script,
// shows the last object. Every such manifest is refused before decoding, so
// the agent cannot run what the administrator was not shown.
func TestParseManifestRefusesAmbiguousKeys(t *testing.T) {
	const files = `"files":[{"name":"setup.exe","sha256":"` + "0000000000000000000000000000000000000000000000000000000000000002" + `","size":1}]`
	head := `{"format":"tiai-package-1","package_id":"p",` + files
	for name, doc := range map[string]string{
		"duplicate step":   head + `,"install":{"run":"setup.exe","args":["/HIDDEN"]},"install":{"run":"setup.exe"}}`,
		"duplicate nested": head + `,"install":{"run":"setup.exe","args":["/S"],"args":[]}}`,
		"duplicate in a file": `{"format":"tiai-package-1","package_id":"p","files":[{"name":"x.exe","name":"setup.exe","sha256":"` +
			"0000000000000000000000000000000000000000000000000000000000000002" + `","size":1}],"install":{"run":"setup.exe"}}`,
		"duplicate top-level scalar":    head + `,"package_id":"p","install":{"run":"setup.exe"}}`,
		"folded top-level key (long s)": head + `,"inſtall":{"run":"setup.exe","args":["/HIDDEN"]}}`,
		"folded nested key (long s)":    head + `,"install":{"run":"setup.exe","argſ":["/HIDDEN"]}}`,
		"other case":                    head + `,"Install":{"run":"setup.exe"}}`,
		"unknown top-level key":         head + `,"install":{"run":"setup.exe"},"postinstall":{"run":"setup.exe"}}`,
		"unknown nested key":            head + `,"install":{"run":"setup.exe","shell":true}}`,
		"trailing document":             head + `,"install":{"run":"setup.exe"}}{"install":{"run":"x"}}`,
	} {
		if _, err := ParseManifest([]byte(doc), "p"); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
	// The same document without the ambiguity parses: the refusals above are
	// about the keys, nothing else.
	if _, err := ParseManifest([]byte(head+`,"install":{"run":"setup.exe","args":["/S"]}}`), "p"); err != nil {
		t.Errorf("plain manifest refused: %v", err)
	}
}

// An unsigned manifest's sizes are the server's word and bound the download:
// beyond the server's own ceiling, method A refuses before fetching anything
// (audit S24).
func TestMethodACapsTheAnnouncedSize(t *testing.T) {
	const gib = int64(1) << 30
	limit := Policy{}.MethodAMaxBytes()
	if limit != 8*gib {
		t.Fatalf("default cap %d, want 8 GiB", limit)
	}
	if err := MethodAFiles([]FileRef{{Name: "setup.exe", Size: 8 * gib}}, "setup.exe", limit); err != nil {
		t.Errorf("an 8 GiB installer refused: %v", err)
	}
	for _, files := range [][]FileRef{
		{{Name: "setup.exe", Size: 8*gib + 1}},
		{{Name: "setup.exe", Size: 5 * gib}, {Name: "data.cab", Size: 5 * gib}},
		{{Name: "setup.exe", Size: 1}, {Name: "data.cab", Size: 1<<63 - 1}},
	} {
		if err := MethodAFiles(files, "setup.exe", limit); err == nil {
			t.Errorf("%v accepted", files)
		}
	}
	// The GPO value DeployMethodAMaxGB replaces the default, either way.
	small := Policy{MethodAMaxGB: 2}.MethodAMaxBytes()
	if err := MethodAFiles([]FileRef{{Name: "setup.exe", Size: 3 * gib}}, "setup.exe", small); err == nil {
		t.Error("3 GiB accepted under a 2 GiB cap")
	}
	large := Policy{MethodAMaxGB: 16}.MethodAMaxBytes()
	if err := MethodAFiles([]FileRef{{Name: "setup.exe", Size: 12 * gib}}, "setup.exe", large); err != nil {
		t.Errorf("12 GiB refused under a 16 GiB cap: %v", err)
	}

	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true}
	env.files = map[string][]byte{"setup.exe": signedPE(t, "INDEX EDUCATION SAS")}
	m := Manifest{Format: "tiai-package-1", PackageID: pronoteID, Install: &Step{Run: "setup.exe"},
		Files: []FileRef{{Name: "setup.exe", SHA256: sha(env.files["setup.exe"]), Size: 1 << 40}}}
	raw, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	pkg := &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg); err == nil {
		t.Error("a 1 TiB manifest went through")
	}
	if _, err := os.Stat(filepath.Join(env.PackagesDir(), pronoteID, "setup.exe")); err == nil {
		t.Error("downloaded despite the cap")
	}
}

// --- method B -------------------------------------------------------------------

func signRSA(t *testing.T, m []byte) (sig, cert string, der []byte) {
	key, _ := rsa.GenerateKey(rand.Reader, 2048)
	der = selfSigned(t, key, "Tiai Signature")
	d := sha256.Sum256(m)
	s, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, d[:])
	if err != nil {
		t.Fatal(err)
	}
	return base64.StdEncoding.EncodeToString(s), base64.StdEncoding.EncodeToString(der), der
}

func TestAdminSignatureRSA(t *testing.T) {
	m := []byte(`{"format":"tiai-package-1"}`)
	sig, cert, der := signRSA(t, m)
	// A thumbprint as certutil prints it, spaced and lower case.
	spaced := strings.ToLower(thumb(der)[:8]) + " " + thumb(der)[8:]
	subject, err := VerifyAdminSignature(m, sig, "rsa-pkcs1-sha256", cert, []string{"ffff", spaced})
	if err != nil {
		t.Fatal(err)
	}
	if subject != "CN=Tiai Signature" {
		t.Errorf("subject = %q", subject)
	}
	if _, err := VerifyAdminSignature(append(m, ' '), sig, "rsa-pkcs1-sha256", cert, []string{thumb(der)}); err == nil {
		t.Error("tampered manifest accepted")
	}
	if _, err := VerifyAdminSignature(m, sig, "rsa-pkcs1-sha256", cert, []string{"00"}); err == nil {
		t.Error("untrusted certificate accepted")
	}
	if _, err := VerifyAdminSignature(m, sig, "ecdsa-sha256", cert, []string{thumb(der)}); err == nil {
		t.Error("algorithm mismatch accepted")
	}
}

func TestAdminSignatureECDSABothEncodings(t *testing.T) {
	m := []byte("manifest")
	key, _ := ecdsa.GenerateKey(elliptic.P384(), rand.Reader)
	der := selfSigned(t, key, "Tiai")
	d := sha256.Sum256(m)
	r, s, _ := ecdsa.Sign(rand.Reader, key, d[:])
	p1363 := append(r.FillBytes(make([]byte, 48)), s.FillBytes(make([]byte, 48))...)
	asn, _ := ecdsa.SignASN1(rand.Reader, key, d[:])
	for _, sig := range [][]byte{p1363, asn} {
		_, err := VerifyAdminSignature(m, base64.StdEncoding.EncodeToString(sig), "ecdsa-sha256",
			base64.StdEncoding.EncodeToString(der), []string{thumb(der)})
		if err != nil {
			t.Errorf("signature of %d bytes refused: %v", len(sig), err)
		}
	}
}

// --- method A -------------------------------------------------------------------

func TestMethodAStep(t *testing.T) {
	guid := "{12345678-1234-1234-1234-123456789ABC}"
	got, err := MethodAStep(Step{Run: MsiExec, Args: []string{"/i", "http://x/evil.msi", guid}}, "uninstall")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(got.Args, " ") != "/x "+guid+" /qn /norestart" {
		t.Errorf("msiexec args not rebuilt: %v", got.Args)
	}
	if _, err := MethodAStep(Step{Run: MsiExec, Args: []string{"/i", "evil.msi"}}, "uninstall"); err == nil {
		t.Error("msiexec without a product code accepted")
	}
	// The rebuilt line is /x {code}: an installation would remove the product.
	for _, args := range [][]string{{"/x", guid}, {"/i", "{dir}/app.msi", guid}, {guid}} {
		if got, err := MethodAStep(Step{Run: MsiExec, Args: args}, "install"); err == nil {
			t.Errorf("installation by msiexec %v accepted under method A, as %v", args, got)
		}
	}
	if _, err := MethodAStep(Step{Run: "setup.msi"}, "install"); err == nil {
		t.Error("an .msi accepted under method A")
	}
	for _, action := range []string{"install", "uninstall"} {
		if _, err := MethodAStep(Step{Run: "Install.EXE", Args: []string{"-s"}}, action); err != nil {
			t.Error(err)
		}
	}
}

// The switches that make msiexec remove a product, however they are spelled
// — and nothing an installation ordinarily passes.
func TestMsiExecRemoves(t *testing.T) {
	const guid = "{12345678-1234-1234-1234-123456789ABC}"
	for _, args := range [][]string{
		{"/x", guid}, {"/X", guid}, {"-x", guid}, {"/x" + guid}, {"/qn", "/uninstall", guid},
		{"/UNINSTALL", "{dir}/app.msi"}, {"-Uninstall", guid},
	} {
		if !MsiExecRemoves(Step{Run: MsiExec, Args: args}) {
			t.Errorf("msiexec %v not seen as a removal", args)
		}
	}
	for _, args := range [][]string{
		{"/i", "{dir}/app.msi", "/qn", "/norestart"}, {"/package", "{dir}/x.msi"}, {"/update", "{dir}/fix.msp"},
		{"/i", "{dir}/x.msi", "TARGETDIR=C:/x"}, {"/fa", guid}, {"/l*v", "{dir}/x.log"}, {"/i", "{dir}/x/y.msi"},
	} {
		if MsiExecRemoves(Step{Run: MsiExec, Args: args}) {
			t.Errorf("msiexec %v seen as a removal", args)
		}
	}
	// Not msiexec: an executable's own /x is its business.
	if MsiExecRemoves(Step{Run: "setup.exe", Args: []string{"/x"}}) {
		t.Error("setup.exe /x seen as an msiexec removal")
	}
}

// An installation is never run as msiexec /x: under method A the agent would
// otherwise rebuild any msiexec step holding a product code into one, and a
// signed manifest that files a removal under "install" is refused too — the
// console would read « Installation terminée » for a product taken off.
func TestAnInstallationNeverRunsAnMsiExecRemoval(t *testing.T) {
	const guid = "{01234567-89AB-CDEF-0123-456789ABCDEF}"
	files := map[string][]byte{"app.msi": []byte("msi")}
	for _, args := range [][]string{{"/x", guid, "/qn"}, {"/i", "{dir}/app.msi", guid}, {guid}} {
		t.Run("method A "+strings.Join(args, " "), func(t *testing.T) {
			env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, files: files}
			raw := manifestFor(t, pronoteID, env.files, &Step{Run: MsiExec, Args: args})
			pkg := &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
			_, err := Execute(context.Background(), env, Policy{Publishers: []string{"X"}}, "package_install", pkg)
			if err == nil || err.Error() != errNoMsiInMode.Error() {
				t.Errorf("verdict = %v, want %q", err, errNoMsiInMode)
			}
			if len(env.ran) != 0 {
				t.Errorf("ran = %v", env.ran)
			}
		})
	}
	for _, args := range [][]string{{"/x", guid, "/qn"}, {"/X" + guid}, {"/qn", "-uninstall", guid}} {
		t.Run("method B "+strings.Join(args, " "), func(t *testing.T) {
			env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, files: files}
			raw := manifestFor(t, signedID, env.files, &Step{Run: MsiExec, Args: args})
			sig, cert, der := signRSA(t, raw)
			pkg := &models.PackageDelivery{ID: signedID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw),
				Signature: sig, SignatureAlgorithm: "rsa-pkcs1-sha256", Certificate: cert}
			_, err := Execute(context.Background(), env, Policy{Signers: []string{thumb(der)}}, "package_install", pkg)
			if err == nil || !strings.Contains(err.Error(), "lance une désinstallation") {
				t.Errorf("verdict = %v", err)
			}
			if len(env.ran) != 0 || len(env.fetched) != 0 {
				t.Errorf("ran = %v, fetched = %v", env.ran, env.fetched)
			}
		})
	}
	// The same step as the uninstallation is what method A is for.
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, files: files}
	m := Manifest{Format: "tiai-package-1", PackageID: pronoteID, Name: "App",
		Files:     []FileRef{{Name: "app.msi", SHA256: sha(files["app.msi"]), Size: 3}},
		Uninstall: &Step{Run: MsiExec, Args: []string{"/x", guid, "/qn"}}}
	raw, _ := json.Marshal(m)
	pkg := &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"X"}}, "package_uninstall", pkg); err != nil || len(env.ran) != 1 {
		t.Errorf("uninstall by product code: %v, ran = %v", err, env.ran)
	}
}

func TestSignerNameFindsTheSignerNotTheFirstCertificate(t *testing.T) {
	path := filepath.Join(t.TempDir(), "Install_PRNclient.exe")
	if err := os.WriteFile(path, signedPE(t, "INDEX EDUCATION SAS"), 0o600); err != nil {
		t.Fatal(err)
	}
	name, err := SignerName(path)
	if err != nil {
		t.Fatal(err)
	}
	if name != "INDEX EDUCATION SAS" {
		t.Errorf("signer = %q", name)
	}
	if !PublisherApproved(name, []string{" index education sas "}) {
		t.Error("case-insensitive match expected")
	}
	plain := filepath.Join(t.TempDir(), "x.iss")
	_ = os.WriteFile(plain, []byte("[InstallShield Silent]"), 0o600)
	if _, err := SignerName(plain); err == nil {
		t.Error("an unsigned file has no signer")
	}
}

// --- winget ---------------------------------------------------------------------

func TestWinget(t *testing.T) {
	if err := WingetAllowed("Mozilla.Firefox", Policy{}); err == nil {
		t.Error("winget allowed without DeployWinget")
	}
	on := Policy{Winget: true}
	for _, bad := range []string{"--source", "-h", "a b", ""} {
		if err := WingetAllowed(bad, on); err == nil {
			t.Errorf("%q allowed", bad)
		}
	}
	limited := Policy{Winget: true, WingetAllow: []string{"Mozilla.*", "7zip.7zip"}}
	for id, want := range map[string]bool{"Mozilla.Firefox": true, "7zip.7zip": true, "7zip.7zip.alpha": false, "Google.Chrome": false} {
		if got := WingetAllowed(id, limited) == nil; got != want {
			t.Errorf("%s allowed = %v", id, got)
		}
	}
	args, _ := WingetArgs("install", "Mozilla.Firefox", "131.0")
	if strings.Join(args, " ") != "install --id Mozilla.Firefox --exact --source winget --scope machine --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --version 131.0" {
		t.Errorf("args = %v", args)
	}
	if _, err := WingetArgs("install", "Mozilla.Firefox", "--override"); err == nil {
		t.Error("an option passed as version")
	}
	if ok, _ := WingetVerdict(0x8A15002B); !ok {
		t.Error("no applicable update is a success")
	}
	if ok, _ := WingetVerdict(1); ok {
		t.Error("1 is a failure")
	}
}

func TestLatestWingetDir(t *testing.T) {
	got := LatestWingetDir([]string{
		`C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_1.9.2411.0_x64__8wekyb3d8bbwe`,
		`C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_1.25.340.0_x64__8wekyb3d8bbwe`,
		`C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_1.10.1.0_x64__8wekyb3d8bbwe`,
	})
	if !strings.Contains(got, "1.25.340.0") {
		t.Errorf("latest = %s", got)
	}
}

func TestExitVerdict(t *testing.T) {
	codes := []int64{0, 3010, 1641}
	if ok, reboot := ExitVerdict(3010, codes); !ok || !reboot {
		t.Error("3010 is success with reboot")
	}
	if ok, _ := ExitVerdict(1603, codes); ok {
		t.Error("1603 is a failure")
	}
}

// --- download ------------------------------------------------------------------

type fakeFetcher struct {
	content []byte
	calls   []int64
	busy    int // 429s to answer first
	ignore  bool
}

func (f *fakeFetcher) FetchPackageFile(_ context.Context, _, _ string, offset, _ int64, file *os.File) error {
	f.calls = append(f.calls, offset)
	if f.busy > 0 {
		f.busy--
		return &RetryLater{Wait: time.Millisecond, Err: errors.New("busy")}
	}
	start := offset
	if f.ignore {
		_ = file.Truncate(0)
		_, _ = file.Seek(0, 0)
		start = 0
	}
	_, err := file.Write(f.content[start:])
	return err
}

func noSleep(context.Context, time.Duration) error { return nil }

func TestDownloadResumesAndVerifies(t *testing.T) {
	content := []byte("0123456789abcdef")
	dest := filepath.Join(t.TempDir(), "f")
	_ = os.WriteFile(dest, content[:6], 0o600)
	fetch := &fakeFetcher{content: content, busy: 2}
	ref := FileRef{Name: "f", SHA256: sha(content), Size: int64(len(content))}
	if err := Download(context.Background(), fetch, "p", ref, dest, noSleep); err != nil {
		t.Fatal(err)
	}
	if fetch.calls[len(fetch.calls)-1] != 6 {
		t.Errorf("did not resume at 6: %v", fetch.calls)
	}
	got, _ := os.ReadFile(dest)
	if string(got) != string(content) {
		t.Errorf("content = %q", got)
	}
	// Already there and intact: no request at all.
	fetch.calls = nil
	if err := Download(context.Background(), fetch, "p", ref, dest, noSleep); err != nil || len(fetch.calls) != 0 {
		t.Errorf("re-downloaded an intact file: %v %v", err, fetch.calls)
	}
}

func TestDownloadRejectsAWrongHash(t *testing.T) {
	dest := filepath.Join(t.TempDir(), "f")
	fetch := &fakeFetcher{content: []byte("not what was signed")}
	ref := FileRef{Name: "f", SHA256: sha([]byte("what was signed....")), Size: 19}
	if err := Download(context.Background(), fetch, "p", ref, dest, noSleep); err == nil {
		t.Fatal("wrong content accepted")
	}
	if _, err := os.Stat(dest); !os.IsNotExist(err) {
		t.Error("rejected file left on disk")
	}
}

// --- executor ------------------------------------------------------------------

type fakeEnv struct {
	SystemEnv
	files   map[string][]byte
	trusted bool
	ran     []string
	code    int64
	// failDownload fails the download of the named file with the given
	// error, after writing half of it — what a dropped transfer leaves.
	failDownload map[string]error
	// fetched names the files actually transferred: like the real Download,
	// a file already there and intact is not fetched again.
	fetched []string
}

func (e *fakeEnv) Download(_ context.Context, _ string, f FileRef, dest string) error {
	if err := e.failDownload[f.Name]; err != nil {
		_ = os.WriteFile(dest, e.files[f.Name][:len(e.files[f.Name])/2], 0o600)
		return err
	}
	if got, err := os.ReadFile(dest); err == nil && bytes.Equal(got, e.files[f.Name]) {
		return nil
	}
	e.fetched = append(e.fetched, f.Name)
	return os.WriteFile(dest, e.files[f.Name], 0o600)
}
func (e *fakeEnv) VerifyAuthenticode(string) (string, error) {
	if !e.trusted {
		return "", errors.New("untrusted")
	}
	return "", nil
}
func (e *fakeEnv) Run(_ context.Context, exe string, args []string, _ string) (int64, error) {
	e.ran = append(e.ran, filepath.Base(exe)+" "+strings.Join(args, " "))
	return e.code, nil
}
func (e *fakeEnv) WingetPath() (string, error) { return "/winget/winget.exe", nil }
func (e *fakeEnv) MsiExecPath() string         { return "/sys/msiexec.exe" }

const (
	pronoteID = "0f1e2d3c-4b5a-4987-8a6b-5c4d3e2f1a0b"
	signedID  = "11111111-2222-4333-8444-555555555555"
)

func pronote(t *testing.T, env *fakeEnv) *models.PackageDelivery {
	env.files = map[string][]byte{
		"Install_PRNclient.exe": signedPE(t, "INDEX EDUCATION SAS"),
		"ClientPRONOTE.iss":     []byte("[InstallShield Silent]"),
	}
	raw := manifestFor(t, pronoteID, env.files, &Step{Run: "Install_PRNclient.exe", Args: []string{"-s", "-f1{dir}/ClientPRONOTE.iss"}})
	return &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
}

func TestExecuteNothingWithoutAGPO(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	pkg := pronote(t, env)
	if _, err := Execute(context.Background(), env, Policy{}, "package_install", pkg); err == nil {
		t.Fatal("ran with no trust anchor")
	}
	if len(env.ran) != 0 {
		t.Error("something ran")
	}
}

func TestExecuteMethodA(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, code: 3010}
	pkg := pronote(t, env)
	res, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg)
	if err != nil {
		t.Fatal(err)
	}
	if !res.RebootRequired || !strings.Contains(res.Output, "méthode A") {
		t.Errorf("result = %+v", res)
	}
	if len(env.ran) != 1 || !strings.HasPrefix(env.ran[0], "Install_PRNclient.exe -s -f1") || strings.Contains(env.ran[0], "{dir}") {
		t.Errorf("ran = %v", env.ran)
	}

	// Another publisher: refused, nothing run.
	env.ran = nil
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"Someone Else"}}, "package_install", pronote(t, env)); err == nil {
		t.Error("unapproved publisher ran")
	}
	// Windows says no: refused, whatever the name.
	env.trusted = false
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pronote(t, env)); err == nil {
		t.Error("a signature Windows rejects ran")
	}
	if len(env.ran) != 0 {
		t.Errorf("ran = %v", env.ran)
	}
}

func TestExecuteMethodB(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	env.files = map[string][]byte{"setup.exe": []byte("unsigned installer"), "app.msi": []byte("msi")}
	raw := manifestFor(t, signedID, env.files, &Step{Run: MsiExec, Args: []string{"/i", "{dir}/app.msi", "/qn"}})
	sig, cert, der := signRSA(t, raw)
	pkg := &models.PackageDelivery{ID: signedID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw),
		Signature: sig, SignatureAlgorithm: "rsa-pkcs1-sha256", Certificate: cert}
	res, err := Execute(context.Background(), env, Policy{Signers: []string{thumb(der)}}, "package_install", pkg)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(res.Output, "méthode B") || len(env.ran) != 1 || !strings.HasPrefix(env.ran[0], "msiexec.exe /i ") {
		t.Errorf("res=%+v ran=%v", res, env.ran)
	}
	// Signed by a certificate this poste does not trust, no publisher: refused.
	env.ran = nil
	if _, err := Execute(context.Background(), env, Policy{Signers: []string{"AB"}}, "package_install", pkg); err == nil || len(env.ran) != 0 {
		t.Errorf("untrusted signer ran: %v %v", err, env.ran)
	}
}

func TestExecuteWinget(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	pkg := &models.PackageDelivery{ID: "w", Kind: "winget", WingetID: "Mozilla.Firefox"}
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"x"}}, "package_install", pkg); err == nil {
		t.Error("winget ran without DeployWinget")
	}
	if _, err := Execute(context.Background(), env, Policy{Winget: true}, "package_uninstall", pkg); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(env.ran[0], "winget.exe uninstall --id Mozilla.Firefox --exact") {
		t.Errorf("ran = %v", env.ran)
	}
}

func TestExecuteRefusesAPackageIDThatIsAPath(t *testing.T) {
	root := t.TempDir()
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: filepath.Join(root, "data")}, trusted: true}
	env.files = map[string][]byte{"setup.exe": signedPE(t, "INDEX EDUCATION SAS")}
	for _, id := range []string{`..\..\..\Windows\System32`, "../../escape", "..", "", "P1",
		"0F1E2D3C-4B5A-4987-8A6B-5C4D3E2F1A0B", pronoteID + "/..", pronoteID + "\\x"} {
		raw := manifestFor(t, id, env.files, &Step{Run: "setup.exe"})
		pkg := &models.PackageDelivery{ID: id, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
		if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg); err == nil {
			t.Errorf("id %q accepted", id)
		}
	}
	if len(env.ran) != 0 {
		t.Errorf("ran = %v", env.ran)
	}
	// Nothing was written anywhere: not even the packages folder.
	if entries, _ := os.ReadDir(root); len(entries) != 0 {
		t.Errorf("written under root: %v", entries)
	}
	if _, err := PackageDir("/x", "../y"); err == nil {
		t.Error("PackageDir accepted a path")
	}
	if dir, err := PackageDir("/x", pronoteID); err != nil || dir != filepath.Join("/x", pronoteID) {
		t.Errorf("PackageDir = %q, %v", dir, err)
	}
}

func TestMethodARefusesLoadableFilesNextToTheExecutable(t *testing.T) {
	for _, extra := range []string{"version.dll", "VERSION.DLL", "setup.exe.manifest", "setup.exe.local",
		"setup.exe.config", "helper.exe", "app.msi", "patch.mst", "run.cmd", "x.ocx", "x.cpl",
		"rtl290.bpl", "_ssl.pyd", "addin.xll", "binding.node", "res.rll", "x.wsc", "x.sct", "X.SCT"} {
		env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true}
		env.files = map[string][]byte{"setup.exe": signedPE(t, "INDEX EDUCATION SAS"), extra: []byte("MZ")}
		raw := manifestFor(t, pronoteID, env.files, &Step{Run: "setup.exe"})
		pkg := &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
		if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg); err == nil {
			t.Errorf("%s accepted next to the executable", extra)
		}
		if len(env.ran) != 0 {
			t.Errorf("%s: ran = %v", extra, env.ran)
		}
		if _, err := os.Stat(filepath.Join(env.PackagesDir(), pronoteID, extra)); err == nil {
			t.Errorf("%s was downloaded", extra)
		}
	}
	// Data files stay allowed (the Pronote case: an .iss answer file).
	if err := MethodAFiles([]FileRef{{Name: "setup.exe"}, {Name: "answers.iss"}, {Name: "data.cab"}, {Name: "conf.ini"}}, "setup.exe", Policy{}.MethodAMaxBytes()); err != nil {
		t.Error(err)
	}
}

func TestMethodAUninstallByProductCodeFetchesNothing(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	env.files = map[string][]byte{"app.msi": []byte("msi")}
	m := Manifest{Format: "tiai-package-1", PackageID: pronoteID, Name: "App", Version: "1",
		Files:     []FileRef{{Name: "app.msi", SHA256: sha(env.files["app.msi"]), Size: 3}},
		Install:   &Step{Run: MsiExec, Args: []string{"/i", "{dir}/app.msi"}},
		Uninstall: &Step{Run: MsiExec, Args: []string{"/x", "{01234567-89AB-CDEF-0123-456789ABCDEF}"}}}
	raw, _ := json.Marshal(m)
	pkg := &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"X"}}, "package_uninstall", pkg); err != nil {
		t.Fatal(err)
	}
	if len(env.ran) != 1 || !strings.HasPrefix(env.ran[0], "msiexec.exe /x {01234567") {
		t.Errorf("ran = %v", env.ran)
	}
}

func TestExecutePrunesWhatAnEarlierAttemptLeft(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, code: 1}
	pkg := pronote(t, env)
	dir := filepath.Join(env.PackagesDir(), pronoteID)
	if err := os.MkdirAll(filepath.Join(dir, "sub"), 0o700); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"version.dll", filepath.Join("sub", "x.dll")} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("planted"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	// The run fails (code 1): the folder is kept, but the planted files went
	// before anything ran.
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg); err == nil {
		t.Fatal("exit code 1 accepted")
	}
	entries, _ := os.ReadDir(dir)
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	if len(names) != 2 || slices.Contains(names, "version.dll") || slices.Contains(names, "sub") {
		t.Errorf("left in the folder: %v", names)
	}
}

// methodAPackage is a method A package for id: a signed installer and one
// data file, plus whatever extra names.
func methodAPackage(t *testing.T, env *fakeEnv, id string, extra map[string][]byte) *models.PackageDelivery {
	t.Helper()
	env.files = map[string][]byte{
		"setup.exe": signedPE(t, "INDEX EDUCATION SAS"),
		"data.cab":  []byte("some data the installer reads"),
	}
	for name, content := range extra {
		env.files[name] = content
	}
	raw := manifestFor(t, id, env.files, &Step{Run: "setup.exe", Args: []string{"/S"}})
	return &models.PackageDelivery{ID: id, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
}

// Audit S24, the residual: the cap is per manifest, and the package id is the
// server's to choose. A method A run refused for a reason no retry lifts must
// not leave its folder — up to the cap, per id, for as many ids as a server
// sends. What a retry resumes stays.
func TestMethodARefusalThatNoRetryLiftsLeavesNoFolder(t *testing.T) {
	approved := Policy{Publishers: []string{"INDEX EDUCATION SAS"}}
	for _, c := range []struct {
		name string
		// arrange tunes the environment, and may replace the package or the
		// policy.
		arrange func(t *testing.T, env *fakeEnv, pkg **models.PackageDelivery, policy *Policy)
		kept    bool
	}{
		{"signature refused by Windows", func(_ *testing.T, env *fakeEnv, _ **models.PackageDelivery, _ *Policy) {
			env.trusted = false
		}, false},
		{"publisher not approved", func(_ *testing.T, _ *fakeEnv, _ **models.PackageDelivery, policy *Policy) {
			policy.Publishers = []string{"Someone Else"}
		}, false},
		{"installer not signed at all", func(t *testing.T, env *fakeEnv, pkg **models.PackageDelivery, _ *Policy) {
			env.files = map[string][]byte{"setup.exe": []byte("MZ, and nothing a signature would be read from")}
			raw := manifestFor(t, pronoteID, env.files, &Step{Run: "setup.exe"})
			*pkg = &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
		}, false},
		{"loadable file next to the installer", func(t *testing.T, env *fakeEnv, pkg **models.PackageDelivery, _ *Policy) {
			*pkg = methodAPackage(t, env, pronoteID, map[string][]byte{"version.dll": []byte("MZ")})
		}, false},
		{"announced size above the cap", func(t *testing.T, env *fakeEnv, pkg **models.PackageDelivery, _ *Policy) {
			m := Manifest{Format: "tiai-package-1", PackageID: pronoteID, Install: &Step{Run: "setup.exe"},
				Files: []FileRef{{Name: "setup.exe", SHA256: sha(env.files["setup.exe"]), Size: 1 << 40}}}
			raw, err := json.Marshal(m)
			if err != nil {
				t.Fatal(err)
			}
			*pkg = &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
		}, false},
		{"not an executable", func(t *testing.T, env *fakeEnv, pkg **models.PackageDelivery, _ *Policy) {
			raw := manifestFor(t, pronoteID, env.files, &Step{Run: "data.cab"})
			*pkg = &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
		}, false},
		{"download refused for good", func(_ *testing.T, env *fakeEnv, _ **models.PackageDelivery, _ *Policy) {
			env.failDownload = map[string]error{"setup.exe": errors.New("empreinte SHA-256 différente de celle du manifeste : fichier rejeté")}
		}, false},
		// What a retry resumes.
		{"network dropped", func(_ *testing.T, env *fakeEnv, _ **models.PackageDelivery, _ *Policy) {
			env.failDownload = map[string]error{"setup.exe": &RetryLater{Err: errors.New("transfert interrompu")}}
		}, true},
		{"service stopping mid-download", func(_ *testing.T, env *fakeEnv, _ **models.PackageDelivery, _ *Policy) {
			env.failDownload = map[string]error{"setup.exe": context.Canceled}
		}, true},
		{"budget spent mid-download", func(_ *testing.T, env *fakeEnv, _ **models.PackageDelivery, _ *Policy) {
			env.failDownload = map[string]error{"setup.exe": context.DeadlineExceeded}
		}, true},
		{"installer exit code not accepted", func(_ *testing.T, env *fakeEnv, _ **models.PackageDelivery, _ *Policy) {
			env.code = 1603
		}, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true}
			pkg := methodAPackage(t, env, pronoteID, nil)
			policy := approved
			c.arrange(t, env, &pkg, &policy)

			// An earlier attempt left this folder, with a file in it: the
			// refusals that come before anything is downloaded find it too.
			dir := filepath.Join(env.PackagesDir(), pronoteID)
			if err := os.MkdirAll(dir, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, "data.cab"), env.files["data.cab"], 0o600); err != nil {
				t.Fatal(err)
			}
			// Another package's folder is not this run's to remove.
			other := filepath.Join(env.PackagesDir(), signedID)
			if err := os.MkdirAll(other, 0o700); err != nil {
				t.Fatal(err)
			}

			if _, err := Execute(context.Background(), env, policy, "package_install", pkg); err == nil {
				t.Fatal("the run was not refused")
			}
			if len(env.ran) != 0 && !c.kept {
				t.Errorf("ran = %v", env.ran)
			}
			_, err := os.Stat(dir)
			if c.kept && err != nil {
				t.Errorf("a retry would have resumed, and the folder is gone: %v", err)
			}
			if !c.kept && !os.IsNotExist(err) {
				entries, _ := os.ReadDir(dir)
				t.Errorf("the folder outlived a refusal no retry lifts (%d file(s) in it)", len(entries))
			}
			if _, err := os.Stat(other); err != nil {
				t.Errorf("another package's folder was touched: %v", err)
			}
		})
	}
}

// A signed package whose signer this poste does not trust, on a poste that also
// approves publishers, falls to method A — and when method A refuses it too,
// the verdict leads with method B's reason: the administrator signed the
// package, the missing thumbprint is what they have to fix.
func TestBothMethodsRefusedReportsMethodBFirst(t *testing.T) {
	sign := func(t *testing.T, env *fakeEnv, step *Step) *models.PackageDelivery {
		raw := manifestFor(t, signedID, env.files, step)
		sig, cert, _ := signRSA(t, raw)
		return &models.PackageDelivery{ID: signedID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw),
			Signature: sig, SignatureAlgorithm: "rsa-pkcs1-sha256", Certificate: cert}
	}
	const methodB = "méthode B : certificat de signature non approuvé sur ce poste (empreinte "
	for _, c := range []struct {
		name      string
		files     map[string][]byte
		step      *Step
		publisher string
		methodA   string
	}{
		{"msiexec install", map[string][]byte{"app.msi": []byte("msi")},
			&Step{Run: MsiExec, Args: []string{"/i", "{dir}/app.msi", "/qn"}}, "X",
			" ; méthode A : msiexec n'est accepté que pour désinstaller un code produit"},
		{"publisher not approved", map[string][]byte{"setup.exe": signedPE(t, "INDEX EDUCATION SAS")},
			&Step{Run: "setup.exe"}, "Someone Else",
			` ; méthode A : éditeur "INDEX EDUCATION SAS" non approuvé sur ce poste (DeployPublishers)`},
	} {
		t.Run(c.name, func(t *testing.T) {
			env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, files: c.files}
			pkg := sign(t, env, c.step)
			policy := Policy{Signers: []string{"AB"}, Publishers: []string{c.publisher}}
			_, err := Execute(context.Background(), env, policy, "package_install", pkg)
			if err == nil {
				t.Fatal("ran")
			}
			msg := err.Error()
			if !strings.HasPrefix(msg, methodB) || !strings.HasSuffix(msg, c.methodA) ||
				strings.Count(msg, "méthode A") != 1 {
				t.Errorf("verdict = %q", msg)
			}
			if len(env.ran) != 0 {
				t.Errorf("ran = %v", env.ran)
			}
		})
	}

	// An unsigned package never went through method B: method A speaks alone.
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true}
	pkg := pronote(t, env)
	_, err := Execute(context.Background(), env, Policy{Signers: []string{"AB"}, Publishers: []string{"Someone Else"}},
		"package_install", pkg)
	if err == nil || strings.Contains(err.Error(), "méthode B") {
		t.Errorf("unsigned package verdict = %v", err)
	}
}

// The success line is built from the parts that exist: no « (méthode A, ) »
// for an uninstall by product code, which names no publisher, and no double
// space for a package without a version.
func TestSuccessLineHasNoEmptyParts(t *testing.T) {
	// Method A, uninstall by product code.
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	m := Manifest{Format: "tiai-package-1", PackageID: pronoteID, Name: "App", Version: "1",
		Files:     []FileRef{{Name: "app.msi", SHA256: sha([]byte("msi")), Size: 3}},
		Uninstall: &Step{Run: MsiExec, Args: []string{"/x", "{01234567-89AB-CDEF-0123-456789ABCDEF}"}}}
	raw, _ := json.Marshal(m)
	pkg := &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
	res, err := Execute(context.Background(), env, Policy{Publishers: []string{"X"}}, "package_uninstall", pkg)
	if err != nil {
		t.Fatal(err)
	}
	if res.Output != "Désinstallation de App 1 terminée (méthode A)" {
		t.Errorf("output = %q", res.Output)
	}

	// Method B, no version.
	env = &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	env.files = map[string][]byte{"app.msi": []byte("msi")}
	m = Manifest{Format: "tiai-package-1", PackageID: signedID, Name: "App",
		Files:   []FileRef{{Name: "app.msi", SHA256: sha(env.files["app.msi"]), Size: 3}},
		Install: &Step{Run: MsiExec, Args: []string{"/i", "{dir}/app.msi", "/qn"}}}
	raw, _ = json.Marshal(m)
	sig, cert, der := signRSA(t, raw)
	pkg = &models.PackageDelivery{ID: signedID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw),
		Signature: sig, SignatureAlgorithm: "rsa-pkcs1-sha256", Certificate: cert}
	res, err = Execute(context.Background(), env, Policy{Signers: []string{thumb(der)}}, "package_install", pkg)
	if err != nil {
		t.Fatal(err)
	}
	if res.Output != "Installation de App terminée (méthode B, paquet signé par CN=Tiai Signature)" {
		t.Errorf("output = %q", res.Output)
	}

	// A failed run under method A by product code: no « () » either.
	env = &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, code: 1603}
	raw, _ = json.Marshal(Manifest{Format: "tiai-package-1", PackageID: pronoteID, Name: "App", Version: "1",
		Files:     []FileRef{{Name: "app.msi", SHA256: sha([]byte("msi")), Size: 3}},
		Uninstall: &Step{Run: MsiExec, Args: []string{"/x", "{01234567-89AB-CDEF-0123-456789ABCDEF}"}}})
	pkg = &models.PackageDelivery{ID: pronoteID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
	if _, err = Execute(context.Background(), env, Policy{Publishers: []string{"X"}}, "package_uninstall", pkg); err == nil ||
		err.Error() != MsiExec+" a renvoyé le code 1603" {
		t.Errorf("failure = %v", err)
	}
}

// Under method B the manifest is the administrator's: a failed run keeps its
// folder as before, whatever the failure — the id and the sizes are not the
// server's word there.
func TestMethodBFailureKeepsItsFolder(t *testing.T) {
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}}
	env.files = map[string][]byte{"setup.exe": []byte("unsigned installer"), "app.msi": []byte("msi")}
	env.failDownload = map[string]error{"app.msi": errors.New("GET …: status 404")}
	raw := manifestFor(t, signedID, env.files, &Step{Run: MsiExec, Args: []string{"/i", "{dir}/app.msi", "/qn"}})
	sig, cert, der := signRSA(t, raw)
	pkg := &models.PackageDelivery{ID: signedID, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw),
		Signature: sig, SignatureAlgorithm: "rsa-pkcs1-sha256", Certificate: cert}
	if _, err := Execute(context.Background(), env, Policy{Signers: []string{thumb(der)}}, "package_install", pkg); err == nil {
		t.Fatal("a failed download went through")
	}
	if _, err := os.Stat(filepath.Join(env.PackagesDir(), signedID)); err != nil {
		t.Errorf("method B folder removed: %v", err)
	}
}

// age sets the modification time of path to d before now.
func age(t *testing.T, path string, now time.Time, d time.Duration) {
	t.Helper()
	when := now.Add(-d)
	if err := os.Chtimes(path, when, when); err != nil {
		t.Fatal(err)
	}
}

// Nothing else sweeps packages/: a folder no retry came back for goes after
// seven days — and only that. Not a folder still being written to, not the
// one in use, not what the agent did not put there.
func TestSweepPackagesRemovesStaleFolders(t *testing.T) {
	const day = 24 * time.Hour
	now := time.Now()
	root := t.TempDir()
	logged(t)
	id := func(n int) string { return strings.Replace(pronoteID, "0f1e2d3c", "0000000"+string(rune('0'+n)), 1) }
	folder := func(name string, dirAge, fileAge time.Duration) string {
		dir := filepath.Join(root, name)
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		file := filepath.Join(dir, "setup.exe")
		if err := os.WriteFile(file, []byte("partial"), 0o600); err != nil {
			t.Fatal(err)
		}
		age(t, file, now, fileAge)
		age(t, dir, now, dirAge) // last: writing the file touched the folder
		return dir
	}

	stale := folder(id(1), 8*day, 8*day)
	justPast := folder(id(2), 7*day+time.Minute, 7*day+time.Minute)
	recent := folder(id(3), 6*day, 6*day)
	// Created long ago, its download resumed yesterday: only the file says so.
	resumed := folder(id(4), 30*day, day)
	inUse := folder(id(5), 30*day, 30*day)
	notOurs := folder("logs", 30*day, 30*day)
	upperCase := folder(strings.ToUpper(id(6)), 30*day, 30*day)
	// A file, not a folder, under a package id.
	strayFile := filepath.Join(root, id(7))
	if err := os.WriteFile(strayFile, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	age(t, strayFile, now, 30*day)
	// Not a direct child: a package id deeper down is nobody's package folder.
	nested := folder(filepath.Join("logs", id(8)), 30*day, 30*day)
	age(t, notOurs, now, 30*day)

	// No cap in the way: age alone decides here.
	SweepPackages(root, id(5), 0, math.MaxInt64, now)

	for _, gone := range []string{stale, justPast} {
		if _, err := os.Stat(gone); !os.IsNotExist(err) {
			t.Errorf("%s: a folder untouched for more than 7 days is still there", filepath.Base(gone))
		}
	}
	for name, path := range map[string]string{
		"touched 6 days ago": recent, "download resumed yesterday": resumed, "the package in use": inUse,
		"a folder that is not a package id": notOurs, "an upper-case id": upperCase,
		"a file named like a package": strayFile, "a package id that is not a direct child": nested,
	} {
		if _, err := os.Stat(path); err != nil {
			t.Errorf("%s was removed: %v", name, err)
		}
	}
	// A root that does not exist yet is no error, and creates nothing.
	missing := filepath.Join(root, "absent")
	SweepPackages(missing, id(1), 0, 0, now)
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Error("pruning created the packages folder")
	}
}

// The sweep runs where folders are made: each deployment that creates one
// first clears what earlier runs left and nobody came back for.
func TestExecuteSweepsStaleSiblingsBeforeCreatingItsFolder(t *testing.T) {
	const day = 24 * time.Hour
	now := time.Now()
	logged(t)
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, code: 1603}
	pkg := methodAPackage(t, env, pronoteID, nil)

	old := filepath.Join(env.PackagesDir(), signedID)
	fresh := filepath.Join(env.PackagesDir(), "22222222-2222-4333-8444-555555555555")
	own := filepath.Join(env.PackagesDir(), pronoteID)
	for _, dir := range []string{old, fresh, own} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "data.cab"), env.files["data.cab"], 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for _, dir := range []string{old, own} {
		age(t, filepath.Join(dir, "data.cab"), now, 8*day)
		age(t, dir, now, 8*day)
	}

	// The run fails on its exit code, so its own folder is kept and seen.
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg); err == nil {
		t.Fatal("exit code 1603 accepted")
	}
	if _, err := os.Stat(old); !os.IsNotExist(err) {
		t.Error("a sibling untouched for 8 days survived a deployment")
	}
	if _, err := os.Stat(fresh); err != nil {
		t.Errorf("a recent sibling was removed: %v", err)
	}
	// Its own folder is as old, and is the one in use: what it held is still
	// there to resume from — only the installer had to be fetched.
	if len(env.fetched) != 1 || env.fetched[0] != "setup.exe" {
		t.Errorf("fetched %v, want setup.exe alone: the folder in use was swept", env.fetched)
	}
}

// logged collects what the deploy package logs during a test.
func logged(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	out, flags := log.Writer(), log.Flags()
	t.Cleanup(func() { log.SetOutput(out); log.SetFlags(flags) })
	log.SetOutput(&buf)
	log.SetFlags(0)
	return &buf
}

// packageFolder makes root/id holding one file of size bytes (sparse: the
// tests below weigh gibibytes), last written d before now.
func packageFolder(t *testing.T, root, id string, size int64, now time.Time, d time.Duration) string {
	t.Helper()
	dir := filepath.Join(root, id)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(dir, "setup.exe")
	f, err := os.Create(file)
	if err != nil {
		t.Fatal(err)
	}
	// Closed before anything can fail: an open handle keeps Windows from
	// removing the test's folder.
	err = makeSparse(f)
	if err == nil {
		err = f.Truncate(size)
	}
	_ = f.Close()
	if err != nil {
		t.Fatal(err)
	}
	age(t, file, now, d)
	age(t, dir, now, d)
	return dir
}

// pkgID is the n-th of a run of package ids.
func pkgID(n int) string { return fmt.Sprintf("%08d-2222-4333-8444-555555555555", n) }

// Audit S24, the residual: age alone bounds nothing — a server can interrupt
// one download after another, each under a new id, and every folder stays
// "recent" for a week. The folders are held under a cap, oldest first, the
// package in use aside and counted for what it will weigh.
func TestSweepPackagesHoldsTheFoldersUnderTheCap(t *testing.T) {
	const day = 24 * time.Hour
	now := time.Now()
	root := t.TempDir()
	buf := logged(t)

	stale := packageFolder(t, root, pkgID(1), 1, now, 8*day)
	oldest := packageFolder(t, root, pkgID(2), 40, now, 3*day)
	older := packageFolder(t, root, pkgID(3), 30, now, 2*day)
	newest := packageFolder(t, root, pkgID(4), 30, now, time.Hour)
	inUse := packageFolder(t, root, pkgID(5), 500, now, 30*day)
	// Not the agent's: neither removed nor counted.
	notOurs := packageFolder(t, root, "logs", 1000, now, 30*day)

	// 40 + 30 + 30 and the 50 the package in use will weigh: 150, cap 100.
	removed := SweepPackages(root, pkgID(5), 50, 100, now)

	var ids []string
	for _, r := range removed {
		if r.Err != nil {
			t.Errorf("%s: %v", r.ID, r.Err)
		}
		ids = append(ids, r.ID)
	}
	if want := []string{pkgID(1), pkgID(2), pkgID(3)}; !slices.Equal(ids, want) {
		t.Errorf("removed %v, want %v (stale, then oldest first down to the cap)", ids, want)
	}
	for _, gone := range []string{stale, oldest, older} {
		if _, err := os.Stat(gone); !os.IsNotExist(err) {
			t.Errorf("%s is still there", filepath.Base(gone))
		}
	}
	for _, kept := range []string{newest, inUse, notOurs} {
		if _, err := os.Stat(kept); err != nil {
			t.Errorf("%s was removed: %v", filepath.Base(kept), err)
		}
	}
	// One line per folder, saying which, how much and why.
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 ||
		!strings.Contains(lines[0], "removed package folder "+pkgID(1)) || !strings.Contains(lines[0], "more than 7 days") ||
		!strings.Contains(lines[1], "removed package folder "+pkgID(2)+" (40 bytes") || !strings.Contains(lines[1], "DeployCacheMaxGB") ||
		!strings.Contains(lines[2], "removed package folder "+pkgID(3)) {
		t.Errorf("logged:\n%s", buf.String())
	}

	// Under the cap: nothing more goes, and nothing is said.
	buf.Reset()
	if removed := SweepPackages(root, pkgID(5), 50, 100, now); len(removed) != 0 || buf.Len() != 0 {
		t.Errorf("removed %v under the cap, logged %q", removed, buf.String())
	}

	// A package that alone weighs more than the cap: every other folder
	// goes, the one in use stays, and the log says so.
	SweepPackages(root, pkgID(5), 200, 100, now)
	if _, err := os.Stat(newest); !os.IsNotExist(err) {
		t.Error("a folder survived a package above the cap on its own")
	}
	if _, err := os.Stat(inUse); err != nil {
		t.Errorf("the package in use was removed: %v", err)
	}
	if !strings.Contains(buf.String(), "package "+pkgID(5)+" announces 200 bytes on its own") {
		t.Errorf("logged:\n%s", buf.String())
	}
}

// At the start of the service nothing is in use: the same sweep, with no
// package kept and nothing to make room for.
func TestSweepPackagesAtStart(t *testing.T) {
	now := time.Now()
	root := t.TempDir()
	logged(t)
	a := packageFolder(t, root, pkgID(1), 60, now, 2*time.Hour)
	b := packageFolder(t, root, pkgID(2), 60, now, time.Hour)
	SweepPackages(root, "", 0, 100, now)
	if _, err := os.Stat(a); !os.IsNotExist(err) {
		t.Error("the older folder outlived a start above the cap")
	}
	if _, err := os.Stat(b); err != nil {
		t.Errorf("the newer folder was removed: %v", err)
	}
}

// The sweep runs where folders are made, and weighs what the package about to
// download announces: folders interrupted one after another under new ids —
// what a compromised server can do — never hold more than the cap.
func TestExecuteHoldsInterruptedDownloadsUnderTheCacheCap(t *testing.T) {
	const gib = int64(1) << 30
	now := time.Now()
	logged(t)
	env := &fakeEnv{SystemEnv: SystemEnv{DataDir: t.TempDir()}, trusted: true, code: 1603}
	pkg := methodAPackage(t, env, pronoteID, nil)
	// Three downloads cut short by the server, 7 GiB each: recent, and 21
	// GiB together.
	var dirs []string
	for i := range 3 {
		dirs = append(dirs, packageFolder(t, env.PackagesDir(), pkgID(i+1), 7*gib, now, time.Duration(3-i)*time.Hour))
	}

	// Default cap (16 GiB): the oldest goes — the other two and this package
	// fit.
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}}, "package_install", pkg); err == nil {
		t.Fatal("exit code 1603 accepted")
	}
	for i, dir := range dirs {
		_, err := os.Stat(dir)
		if gone := i == 0; gone != os.IsNotExist(err) {
			t.Errorf("folder %d: gone = %v, want %v", i+1, os.IsNotExist(err), gone)
		}
	}
	// The folder in use is kept for its retry (exit code), as before.
	if _, err := os.Stat(filepath.Join(env.PackagesDir(), pronoteID)); err != nil {
		t.Errorf("the package's own folder: %v", err)
	}

	// DeployCacheMaxGB lowered to 7: the other two go as well — 7 GiB and
	// this package are above it.
	if _, err := Execute(context.Background(), env, Policy{Publishers: []string{"INDEX EDUCATION SAS"}, CacheMaxGB: 7}, "package_install", pkg); err == nil {
		t.Fatal("exit code 1603 accepted")
	}
	for _, dir := range dirs[1:] {
		if _, err := os.Stat(dir); !os.IsNotExist(err) {
			t.Error("a 7 GiB folder survived a 7 GiB cap next to a package in use")
		}
	}
}

func TestCacheMaxBytes(t *testing.T) {
	if got := (Policy{}).CacheMaxBytes(); got != DefaultCacheMaxGB<<30 || DefaultCacheMaxGB != 16 {
		t.Errorf("default cap = %d", got)
	}
	if got := (Policy{CacheMaxGB: 3}).CacheMaxBytes(); got != 3<<30 {
		t.Errorf("cap = %d", got)
	}
}

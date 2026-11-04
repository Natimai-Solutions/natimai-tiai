package deploy

import (
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
	"math/big"
	"os"
	"path/filepath"
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
	for _, name := range []string{`..\evil.exe`, `C:\Windows\x.exe`, "a/b.exe", "con.exe", "x.exe:stream", "trailing. "} {
		raw := manifestFor(t, "p", map[string][]byte{name: []byte("x")}, &Step{Run: name})
		if _, err := ParseManifest(raw, "p"); err == nil {
			t.Errorf("%q accepted", name)
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
	got, err := MethodAStep(Step{Run: MsiExec, Args: []string{"/i", "http://x/evil.msi", guid}})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(got.Args, " ") != "/x "+guid+" /qn /norestart" {
		t.Errorf("msiexec args not rebuilt: %v", got.Args)
	}
	if _, err := MethodAStep(Step{Run: MsiExec, Args: []string{"/i", "evil.msi"}}); err == nil {
		t.Error("msiexec without a product code accepted")
	}
	if _, err := MethodAStep(Step{Run: "setup.msi"}); err == nil {
		t.Error("an .msi accepted under method A")
	}
	if _, err := MethodAStep(Step{Run: "Install.EXE", Args: []string{"-s"}}); err != nil {
		t.Error(err)
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

func (f *fakeFetcher) FetchPackageFile(_ context.Context, _, _ string, offset int64, file *os.File) error {
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
}

func (e *fakeEnv) Download(_ context.Context, _ string, f FileRef, dest string) error {
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

func pronote(t *testing.T, env *fakeEnv) *models.PackageDelivery {
	env.files = map[string][]byte{
		"Install_PRNclient.exe": signedPE(t, "INDEX EDUCATION SAS"),
		"ClientPRONOTE.iss":     []byte("[InstallShield Silent]"),
	}
	raw := manifestFor(t, "p1", env.files, &Step{Run: "Install_PRNclient.exe", Args: []string{"-s", "-f1{dir}/ClientPRONOTE.iss"}})
	return &models.PackageDelivery{ID: "p1", Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
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
	raw := manifestFor(t, "p2", env.files, &Step{Run: MsiExec, Args: []string{"/i", "{dir}/app.msi", "/qn"}})
	sig, cert, der := signRSA(t, raw)
	pkg := &models.PackageDelivery{ID: "p2", Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw),
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

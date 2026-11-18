package agent

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"tiai/agent/internal/config"
	"tiai/agent/internal/deploy"
	"tiai/agent/internal/models"
)

// packageFolders sets up, under a ProgramData of the test's own, two package
// folders an earlier run left: 9 GiB each, the older written two hours ago,
// the newer one. Together they are above the default cap of 16 GiB and under
// twice that.
func packageFolders(t *testing.T) (older, newer string) {
	t.Helper()
	t.Setenv("ProgramData", t.TempDir())
	packages := filepath.Join(config.DefaultConfigDir(), "packages")
	now := time.Now()
	folder := func(n int, size int64, age time.Duration) string {
		dir := filepath.Join(packages, fmt.Sprintf("%08d-2222-4333-8444-555555555555", n))
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		file := filepath.Join(dir, "setup.exe")
		f, err := os.Create(file)
		if err != nil {
			t.Fatal(err)
		}
		// Sparse: what counts is the size the download reached. Closed
		// before anything can fail, so Windows can remove the folder.
		err = makeSparse(f)
		if err == nil {
			err = f.Truncate(size)
		}
		_ = f.Close()
		if err != nil {
			t.Fatal(err)
		}
		for _, p := range []string{file, dir} {
			if err := os.Chtimes(p, now.Add(-age), now.Add(-age)); err != nil {
				t.Fatal(err)
			}
		}
		return dir
	}
	const gib = int64(1) << 30
	return folder(1, 9*gib, 2*time.Hour), folder(2, 9*gib, time.Hour)
}

// startOnly runs the agent's start and nothing after it: no tick reaches
// anything.
func startOnly(t *testing.T) {
	t.Helper()
	cfg := config.DefaultConfig()
	cfg.APIBaseURL = "https://tiai.invalid"
	cfg.MachineUUID = "11111111-2222-4333-8444-555555555555"
	a := New(cfg, filepath.Join(t.TempDir(), "config.yaml"))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := a.Run(ctx); err != nil {
		t.Fatal(err)
	}
}

// registry stands, for one test, for the Deploy* values a GPO set.
func registry(t *testing.T, trust *config.DeployTrust) {
	t.Helper()
	old := deployKeys
	t.Cleanup(func() { deployKeys = old })
	deployKeys = func() config.DeployTrust { return *trust }
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// Audit S24: the package folders earlier runs left are weighed when the
// service starts, not only at the next deployment — which may never come to
// this poste. Above the cap (DeployCacheMaxGB, 16 GiB by default; no registry
// off Windows), the oldest go first, and the log says which.
func TestRunSweepsThePackageCacheAtStart(t *testing.T) {
	older, newer := packageFolders(t)
	buf := captureLog(t)
	startOnly(t)

	if exists(older) {
		t.Error("18 GiB of folders left at start, above the 16 GiB default cap")
	}
	if !exists(newer) {
		t.Error("the newer folder was removed")
	}
	if !strings.Contains(buf.String(), "deploy: removed package folder 00000001-2222-4333-8444-555555555555 (9.0 GiB") {
		t.Errorf("logged:\n%s", buf.String())
	}
}

// DeployCacheMaxGB is not only read, checked and logged: the value the
// registry holds is the cap the sweep at start applies. Raised to 32, the 18
// GiB the default would trim stay; lowered to 8, the folder the default would
// keep goes too.
func TestTheRegistryCapReachesTheSweepAtStart(t *testing.T) {
	older, newer := packageFolders(t)
	trust := config.DeployTrust{CacheMaxGB: 32}
	registry(t, &trust)
	buf := captureLog(t)
	startOnly(t)
	if !exists(older) || !exists(newer) {
		t.Errorf("DeployCacheMaxGB = 32: 18 GiB of folders trimmed at start (the default cap was applied):\n%s", buf.String())
	}

	trust.CacheMaxGB = 8
	startOnly(t)
	if exists(older) || exists(newer) {
		t.Error("DeployCacheMaxGB = 8: a 9 GiB folder left at start")
	}
	if !strings.Contains(buf.String(), "package cache above its cap of 8.0 GiB (DeployCacheMaxGB)") {
		t.Errorf("logged:\n%s", buf.String())
	}
}

// The same value is the cap of the sweep that precedes a download: read
// afresh for each deployment, and handed to internal/deploy with the rest of
// the trust. The deployment itself fails here — the server has no such file —
// after the sweep ran.
func TestTheRegistryCapReachesTheSweepBeforeADownload(t *testing.T) {
	older, newer := packageFolders(t)
	trust := config.DeployTrust{Publishers: []string{"INDEX EDUCATION SAS"}, CacheMaxGB: 32}
	registry(t, &trust)
	buf := captureLog(t)

	srv := httptest.NewServer(http.NotFoundHandler())
	defer srv.Close()
	cfg := config.DefaultConfig()
	cfg.APIBaseURL = srv.URL
	a := New(cfg, filepath.Join(t.TempDir(), "config.yaml"))

	const id = "0f1e2d3c-4b5a-4987-8a6b-5c4d3e2f1a0b"
	raw, err := json.Marshal(deploy.Manifest{
		Format: "tiai-package-1", PackageID: id, Name: "App",
		Files:   []deploy.FileRef{{Name: "setup.exe", SHA256: strings.Repeat("0", 64), Size: 1 << 20}},
		Install: &deploy.Step{Run: "setup.exe", Args: []string{"/S"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	pkg := &models.PackageDelivery{ID: id, Kind: "files", Manifest: base64.StdEncoding.EncodeToString(raw)}
	deployOnce := func() {
		t.Helper()
		_, err := a.executePackage(context.Background(), "package_install", pkg)
		if err == nil || !strings.Contains(err.Error(), "téléchargement de setup.exe") {
			t.Fatalf("verdict = %v, want the download refused by the server", err)
		}
	}

	deployOnce()
	if !exists(older) || !exists(newer) {
		t.Errorf("DeployCacheMaxGB = 32: 18 GiB of folders trimmed before a download (the default cap was applied):\n%s", buf.String())
	}

	trust.CacheMaxGB = 8
	deployOnce()
	if exists(older) || exists(newer) {
		t.Error("DeployCacheMaxGB = 8: a 9 GiB folder left before a download")
	}
	if !strings.Contains(buf.String(), "package cache above its cap of 8.0 GiB (DeployCacheMaxGB)") {
		t.Errorf("logged:\n%s", buf.String())
	}
}

// Every value the registry holds is handed over: a field forgotten here is a
// setting read, checked, logged — and ignored.
func TestDeployPolicyCarriesEveryRegistryValue(t *testing.T) {
	got := deployPolicy(config.DeployTrust{
		Signers: []string{"AB"}, Publishers: []string{"P"}, Winget: true, WingetAllow: []string{"Mozilla.*"},
		MethodAMaxGB: 3, CacheMaxGB: 5,
	})
	want := deploy.Policy{
		Signers: []string{"AB"}, Publishers: []string{"P"}, Winget: true, WingetAllow: []string{"Mozilla.*"},
		MethodAMaxGB: 3, CacheMaxGB: 5,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("deployPolicy = %+v, want %+v", got, want)
	}
	// And no field of either side is left out of this test.
	if n := reflect.TypeFor[config.DeployTrust]().NumField(); n != 6 {
		t.Errorf("config.DeployTrust has %d fields: complete deployPolicy and this test", n)
	}
	if n := reflect.TypeFor[deploy.Policy]().NumField(); n != 6 {
		t.Errorf("deploy.Policy has %d fields: complete deployPolicy and this test", n)
	}
}

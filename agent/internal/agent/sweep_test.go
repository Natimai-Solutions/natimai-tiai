package agent

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"tiai/agent/internal/config"
)

// Audit S24: the package folders earlier runs left are weighed when the
// service starts, not only at the next deployment — which may never come to
// this poste. Above the cap (DeployCacheMaxGB, 16 GiB by default; no registry
// off Windows), the oldest go first, and the log says which.
func TestRunSweepsThePackageCacheAtStart(t *testing.T) {
	programData := t.TempDir()
	t.Setenv("ProgramData", programData)
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
	older := folder(1, 9*gib, 2*time.Hour)
	newer := folder(2, 9*gib, time.Hour)

	buf := captureLog(t)
	cfg := config.DefaultConfig()
	cfg.APIBaseURL = "https://tiai.invalid"
	cfg.MachineUUID = "11111111-2222-4333-8444-555555555555"
	a := New(cfg, filepath.Join(t.TempDir(), "config.yaml"))
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // the start alone: no tick reaches anything
	if err := a.Run(ctx); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Stat(older); !os.IsNotExist(err) {
		t.Error("18 GiB of folders left at start, above the 16 GiB default cap")
	}
	if _, err := os.Stat(newer); err != nil {
		t.Errorf("the newer folder was removed: %v", err)
	}
	if !strings.Contains(buf.String(), "deploy: removed package folder 00000001-2222-4333-8444-555555555555 (9.0 GiB") {
		t.Errorf("logged:\n%s", buf.String())
	}
}

package logging

import (
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func readLog(t *testing.T, dir string) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(dir, logFileName))
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	return string(data)
}

func TestSetupWritesToFile(t *testing.T) {
	dir := t.TempDir()
	closeLog := Setup(dir, "INFO")
	log.Printf("hello file")
	closeLog()

	if got := readLog(t, dir); !strings.Contains(got, "hello file") {
		t.Fatalf("log file missing entry, got: %q", got)
	}
}

func TestDebugfGatedByLevel(t *testing.T) {
	dir := t.TempDir()
	closeLog := Setup(dir, "INFO")
	Debugf("hidden at info")
	closeLog()
	if got := readLog(t, dir); strings.Contains(got, "hidden at info") {
		t.Fatalf("debug line written at INFO level: %q", got)
	}

	closeLog = Setup(dir, "debug") // case-insensitive
	Debugf("visible at debug")
	closeLog()
	if got := readLog(t, dir); !strings.Contains(got, "visible at debug") {
		t.Fatalf("debug line missing at DEBUG level: %q", got)
	}
}

func TestRotateOversizedLog(t *testing.T) {
	dir := t.TempDir()
	old := maxLogSize
	maxLogSize = 10
	defer func() { maxLogSize = old }()

	path := filepath.Join(dir, logFileName)
	if err := os.WriteFile(path, []byte("0123456789ABCDEF"), 0o640); err != nil {
		t.Fatal(err)
	}

	closeLog := Setup(dir, "INFO")
	log.Printf("fresh entry")
	closeLog()

	if _, err := os.Stat(path + ".old"); err != nil {
		t.Fatalf("expected rotated agent.log.old: %v", err)
	}
	if got := readLog(t, dir); strings.Contains(got, "0123456789ABCDEF") {
		t.Fatalf("fresh log still holds old content: %q", got)
	}
}

// Audit S23: the log rotates while the service runs, not only at startup.
func TestTheLogRotatesWhileRunning(t *testing.T) {
	dir := t.TempDir()
	old := maxLogSize
	maxLogSize = 200
	defer func() { maxLogSize = old }()

	closeLog := Setup(dir, "INFO")
	for i := 0; i < 20; i++ {
		log.Printf("line %02d of a log that keeps growing", i)
	}
	closeLog()

	path := filepath.Join(dir, logFileName)
	cur, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	prev, err := os.Stat(path + ".old")
	if err != nil {
		t.Fatalf("no agent.log.old: %v", err)
	}
	if cur.Size() > maxLogSize || prev.Size() > maxLogSize {
		t.Errorf("sizes %d and %d, bound %d", cur.Size(), prev.Size(), maxLogSize)
	}
	if !strings.Contains(readLog(t, dir), "line 19") {
		t.Error("the last line is missing")
	}
}

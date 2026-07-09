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

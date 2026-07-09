// Package logging tees the standard log package to a file in the agent data
// directory, gated by the configured log level (plan §2.10). Under the Windows
// service, stderr goes nowhere — the file is the only trace of what an agent
// running as LocalSystem did.
package logging

import (
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
)

const logFileName = "agent.log"

// maxLogSize: at startup, a larger agent.log is rotated to agent.log.old,
// bounding disk usage to ~2× this size. Var (not const) so tests can lower it.
var maxLogSize int64 = 5 << 20 // 5 MiB

var debugEnabled atomic.Bool

// Setup gates Debugf on level (case-insensitive "debug") and, if possible,
// tees the standard logger to <dir>/agent.log. It never fails the agent: if
// the file can't be opened, logging stays on stderr and the cause is logged.
// The returned func closes the file and restores stderr-only output.
func Setup(dir, level string) func() {
	debugEnabled.Store(strings.EqualFold(level, "debug"))

	rotate(dir)
	if err := os.MkdirAll(dir, 0o750); err != nil {
		log.Printf("logging: create dir, stderr only: %v", err)
		return func() {}
	}
	f, err := os.OpenFile(
		filepath.Join(dir, logFileName), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o640,
	)
	if err != nil {
		log.Printf("logging: open log file, stderr only: %v", err)
		return func() {}
	}

	// File first: MultiWriter stops at the first failing writer, and under the
	// SCM os.Stderr is an invalid handle — it must not block the file write.
	log.SetOutput(io.MultiWriter(f, os.Stderr))
	return func() {
		log.SetOutput(os.Stderr)
		_ = f.Close()
	}
}

// Debugf logs only when the configured level is DEBUG.
func Debugf(format string, args ...any) {
	if debugEnabled.Load() {
		log.Printf(format, args...)
	}
}

// rotate moves an oversized agent.log to agent.log.old (best effort).
func rotate(dir string) {
	path := filepath.Join(dir, logFileName)
	info, err := os.Stat(path)
	if err != nil || info.Size() < maxLogSize {
		return
	}
	_ = os.Remove(path + ".old")
	_ = os.Rename(path, path+".old")
}

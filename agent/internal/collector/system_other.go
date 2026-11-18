//go:build !windows

package collector

import (
	"context"
	"errors"
	"time"

	"tiai/agent/internal/msg"
)

// Reboot refuses off Windows. A dev build must never restart the developer's
// machine, and there is no meaningful stub for "restart this computer".
func Reboot(ctx context.Context) (msg.Message, error) {
	return msg.Message{}, errors.New("reboot is only supported on windows")
}

// Shutdown refuses off Windows, for the same reason and more so: the one thing
// worse than restarting a developer's machine is stopping it.
func Shutdown(ctx context.Context) (msg.Message, error) {
	return msg.Message{}, errors.New("shutdown is only supported on windows")
}

// Uptime is unavailable off Windows.
//
// An error rather than a plausible-looking zero: the caller rations power
// actions on this reading, and a zero would read as "this machine just booted"
// — the one answer that must never be invented.
func Uptime() (time.Duration, error) {
	return 0, errors.New("uptime is only supported on windows")
}

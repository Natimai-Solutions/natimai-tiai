//go:build !windows

package collector

import (
	"context"
	"errors"
	"time"
)

// Reboot refuses off Windows. A dev build must never restart the developer's
// machine, and there is no meaningful stub for "restart this computer".
func Reboot(ctx context.Context) (string, error) {
	return "", errors.New("reboot is only supported on windows")
}

// Uptime is unavailable off Windows.
//
// An error rather than a plausible-looking zero: the caller rations restarts on
// this reading, and a zero would read as "this machine just booted" — the one
// answer that must never be invented.
func Uptime() (time.Duration, error) {
	return 0, errors.New("uptime is only supported on windows")
}

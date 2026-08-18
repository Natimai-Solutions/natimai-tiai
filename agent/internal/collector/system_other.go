//go:build !windows

package collector

import (
	"context"
	"errors"
)

// Reboot refuses off Windows. A dev build must never restart the developer's
// machine, and there is no meaningful stub for "restart this computer".
func Reboot(ctx context.Context) (string, error) {
	return "", errors.New("reboot is only supported on windows")
}

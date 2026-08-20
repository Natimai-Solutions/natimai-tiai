//go:build !windows

package collector

import (
	"context"
	"errors"
	"time"

	"tiai/agent/internal/models"
)

// errWUUnsupported is returned by the stubs below: the WUA COM API is a Windows
// subsystem, and there is nothing to approximate off it.
var errWUUnsupported = errors.New("windows update is only supported on windows")

// ReadWUState reports an error rather than an empty state off Windows.
//
// An error, unlike the ReadAVProduct stub which returns (nil, nil): this one is
// never called on a schedule the way the antivirus read is, so it costs no log
// noise — and the caller must not mistake a dev build for a machine that has
// genuinely nothing pending.
func ReadWUState(ctx context.Context) (*models.WUState, error) {
	return nil, errWUUnsupported
}

// RunWUInstall refuses on any platform that has no Windows Update.
func RunWUInstall(ctx context.Context, includeDrivers bool, timeout time.Duration) (string, error) {
	return "", errWUUnsupported
}

// RunWUReset refuses off Windows: it drives the Windows service manager and
// renames directories under %SystemRoot%, neither of which has a counterpart.
func RunWUReset(ctx context.Context) (string, error) {
	return "", errWUUnsupported
}

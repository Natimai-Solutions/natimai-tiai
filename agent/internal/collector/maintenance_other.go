//go:build !windows

package collector

import (
	"context"
	"errors"
	"fmt"
)

// errMaintenanceUnsupported is returned by the non-Windows stub: every command
// in the catalogue is a Windows system tool.
var errMaintenanceUnsupported = errors.New("maintenance commands are only supported on windows")

// RunMaintenance still resolves the type against the catalogue before refusing,
// so a dev build reports the same "unknown command" as a real agent would for a
// type the server invented — the two failures are worth telling apart.
func RunMaintenance(ctx context.Context, cmdType string) (string, error) {
	if _, ok := LookupMaintenance(cmdType); !ok {
		return "", fmt.Errorf("unknown maintenance command %q", cmdType)
	}
	return "", errMaintenanceUnsupported
}

//go:build !windows

package collector

import (
	"context"

	"tiai/agent/internal/models"
)

// ReadAVProduct reports no antivirus registry off Windows: the Security Center
// is a Win32 subsystem. nil rather than an empty block, and no error, mirroring
// the ReadIPAddress stub — an empty block would tell the server "this machine
// has no antivirus at all", a claim a Linux dev build has no business making,
// and an error would log noise on every dev-machine tick.
func ReadAVProduct(ctx context.Context) (*models.AVProductState, error) {
	return nil, nil
}

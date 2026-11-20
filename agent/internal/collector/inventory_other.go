//go:build !windows

package collector

import (
	"context"

	"tiai/agent/internal/models"
)

// ReadInventory reports nothing off Windows: every source it reads — WMI, the
// registry, GetAdaptersAddresses — is a Win32 subsystem.
//
// nil with no error, mirroring the ReadAVProduct stub. An empty inventory would
// be a claim about the machine ("no disks, no memory, no software"), and the
// daily cycle logging an error on every dev-machine tick would be noise.
func ReadInventory(ctx context.Context, opts InventoryOptions) (*models.InventoryState, error) {
	return nil, nil
}

// readSecureBoot reports nothing off Windows.
func readSecureBoot() (bool, bool) { return false, false }

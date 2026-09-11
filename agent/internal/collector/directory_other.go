//go:build !windows

package collector

import (
	"context"

	"tiai/agent/internal/models"
)

// readDirectory has nothing to read off Windows: no domain, no ADSI.
func readDirectory(ctx context.Context) *models.DirectoryState { return nil }

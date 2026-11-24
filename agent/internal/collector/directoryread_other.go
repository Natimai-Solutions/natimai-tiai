//go:build !windows

package collector

import (
	"context"

	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// ReadDirectoryObjects reads nothing off Windows: ADSI is a Windows API.
func ReadDirectoryObjects(ctx context.Context, names []string) (*models.DirectoryReading, error) {
	return nil, msg.Err("directory.read.unsupported", nil)
}

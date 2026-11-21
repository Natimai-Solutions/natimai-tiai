//go:build windows

package collector

import (
	"context"
	"errors"
	"time"

	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// directoryReadBudget bounds a reading: a few thousand objects, paged, are
// seconds; a domain controller that does not answer must not hold back the
// commands queued after this one.
const directoryReadBudget = 5 * time.Minute

// ReadDirectoryObjects reads the computer objects the server names, in this
// poste's own domain, as its machine account.
func ReadDirectoryObjects(ctx context.Context, names []string) (*models.DirectoryReading, error) {
	filters := DirectoryFilters(names)
	if len(filters) == 0 {
		return nil, msg.Err("directory.read.no_names", nil)
	}
	ctx, cancel := context.WithTimeout(ctx, directoryReadBudget)
	defer cancel()
	raw, err := runPowerShellJSON(ctx, directoryScript(filters))
	if err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, msg.Err("directory.read.timeout", msg.Params{"budget": "5 min"})
		}
		return nil, msg.Wrap("directory.read.failed", nil, err)
	}
	return ParseDirectoryReading(raw)
}

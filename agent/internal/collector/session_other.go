//go:build !windows

package collector

import (
	"context"

	"tiai/agent/internal/models"
)

// ReadSessionState reports no session off Windows (there is no WTS API). Not an
// error, mirroring the ReadDefenderState stub: the poll loop reads this on
// every heartbeat, and a hard failure would log noise on every dev-machine tick.
func ReadSessionState(ctx context.Context, reportUsername bool) (*models.SessionState, error) {
	return &models.SessionState{}, nil
}

//go:build !windows

package collector

import "context"

// ReadNetwork reports nothing off Windows (GetAdaptersAddresses is a Win32
// API). Not an error, mirroring the ReadSessionState stub: the poll loop reads
// this on every heartbeat, and a hard failure would log noise on every
// dev-machine tick.
func ReadNetwork(ctx context.Context) (NetworkInfo, error) {
	return NetworkInfo{}, nil
}

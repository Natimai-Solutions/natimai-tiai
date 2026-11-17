//go:build !windows

package agent

import "os"

// makeSparse: a file grown by Truncate is already sparse here.
func makeSparse(*os.File) error { return nil }

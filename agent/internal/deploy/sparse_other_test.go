//go:build !windows

package deploy

import "os"

// makeSparse: a file grown by Truncate is already sparse here.
func makeSparse(*os.File) error { return nil }

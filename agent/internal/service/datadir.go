package service

import (
	"path/filepath"
	"strings"
)

// mayHardenDataDir decides whether install and repair may restrict the
// directory that holds the configuration (and, beside it, token.dat).
//
// A protected DACL replaces whatever the directory had, and `--config` accepts
// any path: `--config C:\config.yaml` makes the "data directory" C:\, and
// restricting that to SYSTEM + Administrators would break the machine. So the
// agent only touches a directory that is unambiguously its own — the default
// one (%ProgramData%\Tiai, what the MSI and the GPO script restrict too), or
// one that did not exist before this command created it. Anything else is left
// as it is, and the caller says so.
//
// Compared case-insensitively, like Windows paths are.
func mayHardenDataDir(dir, defaultDir string, existed bool) bool {
	if !existed {
		return true
	}
	return strings.EqualFold(filepath.Clean(dir), filepath.Clean(defaultDir))
}

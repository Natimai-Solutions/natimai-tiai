package deploy

import (
	"context"
	"path/filepath"
)

// SystemEnv is the production Env: the server through Fetcher, Windows
// through the platform files (env_windows.go; elsewhere every deployment is
// refused, env_other.go).
type SystemEnv struct {
	Fetcher Fetcher
	DataDir string // C:\ProgramData\Tiai, whose ACL admits SYSTEM and Administrators only
}

// Download implements Env.
func (e *SystemEnv) Download(ctx context.Context, packageID string, f FileRef, dest string) error {
	return Download(ctx, e.Fetcher, packageID, f, dest, SleepContext)
}

// PackagesDir implements Env. Under the data directory on purpose: its ACL is
// what keeps a user from swapping a verified file before it runs.
func (e *SystemEnv) PackagesDir() string {
	return filepath.Join(e.DataDir, "packages")
}

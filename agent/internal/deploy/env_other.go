//go:build !windows

package deploy

import (
	"context"

	"tiai/agent/internal/msg"
)

// Supported tells whether this platform can deploy at all.
const Supported = false

var errUnsupported = msg.Err("deploy.unsupported", nil)

func (e *SystemEnv) VerifyAuthenticode(string) (string, error) { return "", errUnsupported }

func (e *SystemEnv) Run(context.Context, string, []string, string) (int64, error) {
	return 0, errUnsupported
}

func (e *SystemEnv) WingetPath() (string, error) { return "", errUnsupported }

func (e *SystemEnv) MsiExecPath() string { return "msiexec" }

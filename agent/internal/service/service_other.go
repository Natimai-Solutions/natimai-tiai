//go:build !windows

// Package service: non-Windows stubs. The Windows service control manager is
// unavailable, so these return an explanatory error (the agent still runs in
// the foreground via `run`).
package service

import "errors"

var errUnsupported = errors.New("windows service management is only available on windows")

// IsWindowsService is always false off Windows.
func IsWindowsService() (bool, error) { return false, nil }

func Run(string) error { return errUnsupported }

func Install(string) error { return errUnsupported }

func Repair() error { return errUnsupported }

func Uninstall() error { return errUnsupported }

func Start() error { return errUnsupported }

func Stop() error { return errUnsupported }

func Status() error { return errUnsupported }

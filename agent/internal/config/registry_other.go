//go:build !windows

package config

// applyRegistryOverrides is a no-op off Windows (no registry).
func applyRegistryOverrides(*Config) {}

// DeployKeys is empty off Windows: nothing is trusted, deployment is off.
func DeployKeys() DeployTrust { return DeployTrust{} }

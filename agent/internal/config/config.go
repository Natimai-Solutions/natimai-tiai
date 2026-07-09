// Package config loads agent configuration from C:\ProgramData\Tiai\config.yaml,
// overridable by registry keys under HKLM\SOFTWARE\Tiai (plan §2.10: GPO can
// push either, and the sensitive enrollment secret is better placed in the
// registry than in clear YAML). The per-machine token is never written to YAML;
// it is stored encrypted via DPAPI in token.dat (plan §2.4).
package config

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"

	"tiai/agent/internal/dpapi"
)

const (
	DefaultHeartbeatInterval = 60   // short poll: command pickup (seconds)
	DefaultTelemetryInterval = 900  // long poll: full state report (seconds)
	DefaultRequestTimeout    = 10   // seconds
	DefaultBackoffMax        = 300  // cap for heartbeat retry back-off (seconds)
	DefaultQueueMaxItems     = 1000 // local result queue cap

	tokenFileName = "token.dat"
)

// Config is the agent runtime configuration.
type Config struct {
	APIBaseURL               string `yaml:"api_base_url"`
	MachineUUID              string `yaml:"machine_uuid,omitempty"`      // optional override; else auto-resolved (SMBIOS UUID / agent UUID)
	EnrollmentSecret         string `yaml:"enrollment_secret,omitempty"` // GPO-deployed; prefer registry/DPAPI over clear YAML
	HeartbeatIntervalSeconds int    `yaml:"heartbeat_interval_seconds"`
	TelemetryIntervalSeconds int    `yaml:"telemetry_interval_seconds"`
	RequestTimeoutSeconds    int    `yaml:"request_timeout_seconds"`
	BackoffMaxSeconds        int    `yaml:"backoff_max_seconds"`
	QueueMaxItems            int    `yaml:"queue_max_items"`
	LogLevel                 string `yaml:"log_level"` // INFO (default) or DEBUG (also logs quiet heartbeats)

	// AuthToken is never serialized to YAML — it is stored encrypted (DPAPI) in
	// token.dat and loaded into this field at runtime.
	AuthToken string `yaml:"-"`
}

// DefaultConfig returns sane defaults.
func DefaultConfig() *Config {
	return &Config{
		HeartbeatIntervalSeconds: DefaultHeartbeatInterval,
		TelemetryIntervalSeconds: DefaultTelemetryInterval,
		RequestTimeoutSeconds:    DefaultRequestTimeout,
		BackoffMaxSeconds:        DefaultBackoffMax,
		QueueMaxItems:            DefaultQueueMaxItems,
		LogLevel:                 "INFO",
	}
}

// applyDefaults fills any non-positive interval/cap or empty log level with its
// default, so a hand-edited or partial YAML still yields a usable config.
func (c *Config) applyDefaults() {
	if c.HeartbeatIntervalSeconds <= 0 {
		c.HeartbeatIntervalSeconds = DefaultHeartbeatInterval
	}
	if c.TelemetryIntervalSeconds <= 0 {
		c.TelemetryIntervalSeconds = DefaultTelemetryInterval
	}
	if c.RequestTimeoutSeconds <= 0 {
		c.RequestTimeoutSeconds = DefaultRequestTimeout
	}
	if c.BackoffMaxSeconds <= 0 {
		c.BackoffMaxSeconds = DefaultBackoffMax
	}
	if c.QueueMaxItems <= 0 {
		c.QueueMaxItems = DefaultQueueMaxItems
	}
	if c.LogLevel == "" {
		c.LogLevel = "INFO"
	}
}

// DefaultConfigDir is C:\ProgramData\Tiai.
func DefaultConfigDir() string {
	programData := os.Getenv("ProgramData")
	if programData == "" {
		programData = `C:\ProgramData`
	}
	return filepath.Join(programData, "Tiai")
}

// DefaultConfigPath is C:\ProgramData\Tiai\config.yaml.
func DefaultConfigPath() string {
	return filepath.Join(DefaultConfigDir(), "config.yaml")
}

// Load reads the YAML config, applies registry overrides, loads the DPAPI
// token, and validates.
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}
	cfg := DefaultConfig()
	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}

	applyRegistryOverrides(cfg) // no-op off Windows
	cfg.applyDefaults()         // fill any non-positive / empty values

	token, err := LoadToken(filepath.Dir(path))
	if err != nil {
		return nil, fmt.Errorf("load token: %w", err)
	}
	cfg.AuthToken = token

	if cfg.APIBaseURL == "" {
		return nil, fmt.Errorf("api_base_url is required")
	}
	return cfg, nil
}

// Save persists the config (YAML, without the token) atomically.
func (c *Config) Save(path string) error {
	data, err := yaml.Marshal(c)
	if err != nil {
		return fmt.Errorf("marshal config: %w", err)
	}
	return atomicWrite(path, data, 0o640)
}

// tokenPath is token.dat next to the config file.
func tokenPath(dir string) string { return filepath.Join(dir, tokenFileName) }

// LoadToken reads and decrypts the per-machine token, or returns "" if none is
// stored yet.
func LoadToken(dir string) (string, error) {
	raw, err := os.ReadFile(tokenPath(dir))
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", err
	}
	blob, err := base64.StdEncoding.DecodeString(string(raw))
	if err != nil {
		return "", fmt.Errorf("decode token: %w", err)
	}
	plain, err := dpapi.Unprotect(blob)
	if err != nil {
		return "", fmt.Errorf("unprotect token: %w", err)
	}
	return string(plain), nil
}

// SaveToken encrypts (DPAPI) and stores the per-machine token atomically.
func SaveToken(dir, token string) error {
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}
	blob, err := dpapi.Protect([]byte(token))
	if err != nil {
		return fmt.Errorf("protect token: %w", err)
	}
	encoded := base64.StdEncoding.EncodeToString(blob)
	return atomicWrite(tokenPath(dir), []byte(encoded), 0o600)
}

func atomicWrite(path string, data []byte, perm os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return fmt.Errorf("create dir: %w", err)
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, perm); err != nil {
		return fmt.Errorf("write: %w", err)
	}
	return os.Rename(tmp, path)
}

// Package config loads agent configuration from C:\ProgramData\Tiai\config.yaml,
// overridable by registry keys under HKLM\SOFTWARE\Tiai (plan §2.10: GPO can
// push either, and the sensitive enrollment secret is better placed in the
// registry than in clear YAML). The per-machine token is never written to YAML;
// it is stored encrypted via DPAPI in token.dat (plan §2.4).
package config

import (
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"

	"tiai/agent/internal/dpapi"
)

const (
	DefaultHeartbeatInterval = 60   // short poll: command pickup (seconds)
	DefaultRequestTimeout    = 10   // seconds
	DefaultBackoffMax        = 300  // cap for heartbeat retry back-off (seconds)
	DefaultQueueMaxItems     = 1000 // local result queue cap

	// DefaultWUCollectInterval is the Windows Update cycle: six hours.
	//
	// Its own cycle, deliberately far from the 60 s heartbeat: a WU search takes
	// minutes and hits the WSUS server, so running it on the poll interval would
	// keep every poste of the parc permanently searching. Six hours is well
	// inside the rhythm of Patch Tuesday, and the console can always force a
	// fresh reading with a wu_scan.
	DefaultWUCollectInterval = 21600 // seconds

	// DefaultInventoryCollectInterval is the hardware/software cycle: a day.
	// Slower than Windows Update's six hours because what it reads changes far
	// less — a disk is not swapped between two mornings — and because the block
	// is the largest the agent sends. It costs nothing on the quiet days: the
	// collection runs, the hash matches, and nothing is transmitted at all.
	DefaultInventoryCollectInterval = 86400 // seconds

	// DefaultWUInstallTimeout is two hours. A cumulative update on a slow link
	// is the case that sets it: download and install both happen inside this
	// budget, and blowing it leaves the command reported as timed out while
	// Windows carries on installing.
	DefaultWUInstallTimeout = 7200 // seconds

	tokenFileName = "token.dat"
)

// Config is the agent runtime configuration.
type Config struct {
	APIBaseURL               string `yaml:"api_base_url"`
	MachineUUID              string `yaml:"machine_uuid,omitempty"`      // optional override; else auto-resolved (SMBIOS UUID / agent UUID)
	EnrollmentSecret         string `yaml:"enrollment_secret,omitempty"` // GPO-deployed; prefer registry/DPAPI over clear YAML
	HeartbeatIntervalSeconds int    `yaml:"heartbeat_interval_seconds"`
	RequestTimeoutSeconds    int    `yaml:"request_timeout_seconds"`
	BackoffMaxSeconds        int    `yaml:"backoff_max_seconds"`
	QueueMaxItems            int    `yaml:"queue_max_items"`
	LogLevel                 string `yaml:"log_level"` // INFO (default) or DEBUG (also logs quiet heartbeats)

	// Location is where the poste physically is — a site name such as
	// "Lycée de Taravao" — reported to the server as-is. Free text, and empty
	// by default: the agent has no way to find this out by itself, so it is
	// whatever the deployment wrote in the YAML or in the registry (Location).
	//
	// Two things read it on the server. The console, which filters the parc
	// by it; and the Wake-on-LAN relay, which needs to know which postes are
	// on the same wire as the one to wake — a question the domain cannot
	// answer on a parc where one domain spans several sites.
	Location string `yaml:"location,omitempty"`

	// Windows Update runs on its own clock, away from the heartbeat: one search
	// every WUCollectIntervalSeconds, and an install allowed to run for
	// WUInstallTimeoutSeconds. Both are here rather than hard-coded because they
	// are the two values a slow parc or a slow link actually needs to change.
	WUCollectIntervalSeconds int `yaml:"wu_collect_interval_seconds"`
	// The hardware/software inventory cycle. Its own key rather than sharing
	// the Windows Update one: the two answer different questions at different
	// rates, and a parc that wants its patch state hourly does not want its
	// motherboard model re-read hourly with it.
	InventoryCollectIntervalSeconds int `yaml:"inventory_collect_interval_seconds"`
	WUInstallTimeoutSeconds         int `yaml:"wu_install_timeout_seconds"`

	// ReportSessionUsername controls whether the *name* of the logged-on user is
	// sent to the server; the presence always is. Personal data, so it is
	// switchable fleet-wide from a GPO (registry value ReportSessionUsername).
	//
	// A pointer, not a bool: only a pointer distinguishes "absent from the YAML"
	// (→ default true) from an explicit `false`. A plain bool defaulted in
	// DefaultConfig would be silently flipped off by any Config literal that
	// skips it and then calls Save.
	ReportSessionUsername *bool `yaml:"report_session_username"`

	// Whether the inventory carries the list of installed programs. A pointer for
	// the same reason as the flag above, and switchable by GPO for the same kind
	// of reason: crossing "what is installed" with "who is logged on" is how a
	// fleet inventory turns into something about a named person
	// (dev/plan-inventaire.md §7).
	//
	// Switched off, the registry is never read and the block carries an *empty*
	// list rather than omitting it — which is what makes the guarantee real: the
	// next cycle erases whatever an earlier one stored, instead of leaving it
	// sitting in the database. The hardware inventory is unaffected.
	ReportSoftware *bool `yaml:"report_software"`

	// AuthToken is never serialized to YAML — it is stored encrypted (DPAPI) in
	// token.dat and loaded into this field at runtime.
	AuthToken string `yaml:"-"`
}

// DefaultConfig returns sane defaults.
func DefaultConfig() *Config {
	return &Config{
		HeartbeatIntervalSeconds:        DefaultHeartbeatInterval,
		RequestTimeoutSeconds:           DefaultRequestTimeout,
		BackoffMaxSeconds:               DefaultBackoffMax,
		QueueMaxItems:                   DefaultQueueMaxItems,
		WUCollectIntervalSeconds:        DefaultWUCollectInterval,
		InventoryCollectIntervalSeconds: DefaultInventoryCollectInterval,
		WUInstallTimeoutSeconds:         DefaultWUInstallTimeout,
		LogLevel:                        "INFO",
	}
}

// applyDefaults fills any non-positive interval/cap or empty log level with its
// default, so a hand-edited or partial YAML still yields a usable config.
func (c *Config) applyDefaults() {
	if c.HeartbeatIntervalSeconds <= 0 {
		c.HeartbeatIntervalSeconds = DefaultHeartbeatInterval
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
	if c.WUCollectIntervalSeconds <= 0 {
		c.WUCollectIntervalSeconds = DefaultWUCollectInterval
	}
	if c.InventoryCollectIntervalSeconds <= 0 {
		c.InventoryCollectIntervalSeconds = DefaultInventoryCollectInterval
	}
	if c.WUInstallTimeoutSeconds <= 0 {
		c.WUInstallTimeoutSeconds = DefaultWUInstallTimeout
	}
	if c.LogLevel == "" {
		c.LogLevel = "INFO"
	}
	if c.ReportSessionUsername == nil {
		on := true
		c.ReportSessionUsername = &on
	}
}

// ReportsUsername reports whether the logged-on user's name may be sent, so
// callers never have to dereference the pointer themselves.
// ReportsSoftware reports whether the installed-program list is collected.
// Absent from the YAML means yes, like ReportsUsername.
func (c *Config) ReportsSoftware() bool {
	return c.ReportSoftware == nil || *c.ReportSoftware
}

func (c *Config) ReportsUsername() bool {
	return c.ReportSessionUsername == nil || *c.ReportSessionUsername
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
//
// The YAML file is optional: when it is absent, the defaults plus
// HKLM\SOFTWARE\Tiai are the whole configuration. A GPO can therefore deploy
// the agent with registry values alone, with no file to write or template
// (plan §2.10). Only api_base_url must come from one source or the other.
func Load(path string) (*Config, error) {
	cfg := DefaultConfig()

	data, err := os.ReadFile(path)
	switch {
	case err == nil:
		if err := yaml.Unmarshal(data, cfg); err != nil {
			return nil, fmt.Errorf("parse config: %w", err)
		}
	case !os.IsNotExist(err):
		// Present but unreadable (permissions, I/O) — that is a real failure,
		// unlike "not there at all".
		return nil, fmt.Errorf("read config: %w", err)
	}

	applyRegistryOverrides(cfg) // no-op off Windows
	cfg.applyDefaults()         // fill any non-positive / empty values

	token, err := LoadToken(filepath.Dir(path))
	if err != nil {
		return nil, fmt.Errorf("load token: %w", err)
	}
	cfg.AuthToken = token

	if cfg.APIBaseURL == "" {
		return nil, fmt.Errorf(
			`api_base_url is required: set it in %s or in HKLM\SOFTWARE\Tiai\ApiBaseURL`, path)
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

// Seams for tests: the real providers read (and create) machine-wide state —
// the registry on Windows — which is nothing a unit test should touch.
var (
	readEntropy   = readTokenEntropy
	ensureEntropy = ensureTokenEntropy
)

// LoadToken reads and decrypts the per-machine token, or returns "" if none is
// stored yet.
//
// A token that cannot be read back is also "", whatever killed it: the entropy
// may be gone (registry key deleted, re-imaged system), the file may be
// truncated by a power cut mid-write or locked by an antivirus for the moment
// we look at it. A token nobody can read is a token the agent does not have — it
// re-enrolls with the fleet secret, which is the designed recovery and covers
// every way the blob can die.
//
// Never an error, and that is the point rather than a shortcut. This is called
// from Load, whose failure stops the service before its log file is even open:
// a truncated token.dat used to leave a poste with a service that refuses to
// start, no line anywhere saying why, and a start type of Automatic insisting
// everything is fine.
func LoadToken(dir string) (string, error) {
	raw, err := os.ReadFile(tokenPath(dir))
	if err != nil {
		if !os.IsNotExist(err) {
			log.Printf("config: stored token unreadable (%v); treating as not enrolled", err)
		}
		return "", nil
	}
	blob, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(raw)))
	if err != nil {
		log.Printf("config: stored token is not decodable (%v); treating as not enrolled", err)
		return "", nil
	}
	entropy := readEntropy()
	plain, err := dpapi.Unprotect(blob, entropy)
	if err != nil {
		// Legacy blob, written before the entropy existed.
		plain, err = dpapi.Unprotect(blob, nil)
		if err != nil {
			log.Printf("config: stored token is undecryptable (%v); treating as not enrolled", err)
			return "", nil
		}
		entropy = nil
	}
	if entropy == nil {
		// Decrypted the pre-entropy way: re-protect under an entropy now so
		// the blob any local user can unprotect disappears. Best effort — with
		// no rights to create the entropy, the token simply stays as it was.
		if e := ensureEntropy(); e != nil {
			if err := SaveToken(dir, string(plain)); err != nil {
				log.Printf("config: re-protect token with entropy: %v", err)
			}
		}
	}
	return string(plain), nil
}

// SaveToken encrypts (DPAPI, with the per-install entropy) and stores the
// per-machine token atomically.
func SaveToken(dir, token string) error {
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return fmt.Errorf("create config dir: %w", err)
	}
	blob, err := dpapi.Protect([]byte(token), ensureEntropy())
	if err != nil {
		return fmt.Errorf("protect token: %w", err)
	}
	encoded := base64.StdEncoding.EncodeToString(blob)
	return atomicWrite(tokenPath(dir), []byte(encoded), 0o600)
}

// ClearToken removes the stored per-machine token, if any. Used when the
// server stops honouring it (revocation, allow-reenroll, restored database):
// enrollment only runs when no token is stored, so keeping a dead one would
// pin the agent on 401s for the rest of its life.
func ClearToken(dir string) error {
	if err := os.Remove(tokenPath(dir)); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
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

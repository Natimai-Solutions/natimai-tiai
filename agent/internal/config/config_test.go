package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadYAMLAppliesDefaults(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	if err := (&Config{APIBaseURL: "https://tiai.example.local"}).Save(path); err != nil {
		t.Fatalf("Save: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.APIBaseURL != "https://tiai.example.local" {
		t.Errorf("APIBaseURL = %q", cfg.APIBaseURL)
	}
	if cfg.HeartbeatIntervalSeconds != DefaultHeartbeatInterval {
		t.Errorf("expected default heartbeat interval, got %d", cfg.HeartbeatIntervalSeconds)
	}
	if cfg.QueueMaxItems != DefaultQueueMaxItems {
		t.Errorf("expected default queue cap, got %d", cfg.QueueMaxItems)
	}
	// Windows Update has its own clock, and getting these two wrong is
	// expensive in opposite directions: a short collect interval makes every
	// poste of the parc search WSUS in a loop, a short install timeout reports
	// a cumulative update as failed while Windows is still installing it.
	if cfg.WUCollectIntervalSeconds != DefaultWUCollectInterval {
		t.Errorf("expected default WU collect interval, got %d", cfg.WUCollectIntervalSeconds)
	}
	if cfg.WUInstallTimeoutSeconds != DefaultWUInstallTimeout {
		t.Errorf("expected default WU install timeout, got %d", cfg.WUInstallTimeoutSeconds)
	}
}

// A hand-edited YAML that zeroes an interval must fall back to the default
// rather than spin: a zero collect interval would search Windows Update in a
// tight loop, which on a parc means hammering the WSUS server.
func TestWUIntervalsFallBackWhenZeroed(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	body := "api_base_url: https://tiai.example.local\n" +
		"wu_collect_interval_seconds: 0\n" +
		"wu_install_timeout_seconds: -1\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.WUCollectIntervalSeconds != DefaultWUCollectInterval {
		t.Errorf("collect interval = %d, want the default", cfg.WUCollectIntervalSeconds)
	}
	if cfg.WUInstallTimeoutSeconds != DefaultWUInstallTimeout {
		t.Errorf("install timeout = %d, want the default", cfg.WUInstallTimeoutSeconds)
	}
}

// A GPO can deploy the agent with registry values only, so an absent
// config.yaml must fall through to the defaults + registry rather than fail.
func TestLoadWithoutConfigFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")

	cfg, err := Load(path)
	if err != nil {
		// Nothing can supply api_base_url here (no registry off Windows, and no
		// HKLM\SOFTWARE\Tiai on a clean Windows box), so validation fails — but
		// it must be *that* error, not a read error on the missing file.
		if strings.Contains(err.Error(), "read config") {
			t.Fatalf("an absent config file must not be a read error: %v", err)
		}
		if !strings.Contains(err.Error(), "api_base_url") {
			t.Fatalf("expected the api_base_url validation error, got: %v", err)
		}
		return
	}

	// Windows machine that already has HKLM\SOFTWARE\Tiai\ApiBaseURL: the
	// registry alone is a complete configuration.
	if cfg.HeartbeatIntervalSeconds != DefaultHeartbeatInterval {
		t.Errorf("expected default heartbeat interval, got %d", cfg.HeartbeatIntervalSeconds)
	}
	if cfg.LogLevel == "" {
		t.Error("expected a default log level")
	}
}

func TestLoadRequiresAPIBaseURL(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	if err := (&Config{}).Save(path); err != nil {
		t.Fatalf("Save: %v", err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected error when api_base_url is missing")
	}
}

// The logged-on username is personal data, so the default must be deliberate
// and an explicit `false` must survive a round trip. Together with the test
// below, this proves "absent from the YAML" is not read as "disabled".
func TestReportSessionUsernameDefaultsOn(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	if err := os.WriteFile(path, []byte("api_base_url: https://tiai.example.local\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !cfg.ReportsUsername() {
		t.Error("username reporting must default to on when the key is absent")
	}
}

func TestReportSessionUsernameExplicitFalse(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	// Raw YAML, not Save(): Save writes the value already resolved by
	// applyDefaults, which would not exercise the absent-vs-false distinction.
	body := "api_base_url: https://tiai.example.local\nreport_session_username: false\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.ReportsUsername() {
		t.Error("an explicit report_session_username: false must be honoured")
	}
}

// A Config literal that never went through DefaultConfig must not read as
// "username reporting disabled" — the trap a plain bool would fall into.
func TestReportsUsernameOnZeroValueConfig(t *testing.T) {
	if !(&Config{}).ReportsUsername() {
		t.Error("a zero-value Config must still report usernames")
	}
}

func TestTokenRoundTrip(t *testing.T) {
	dir := t.TempDir()

	// No token stored yet.
	tok, err := LoadToken(dir)
	if err != nil || tok != "" {
		t.Fatalf("expected empty token, got %q err=%v", tok, err)
	}

	if err := SaveToken(dir, "secret-token-123"); err != nil {
		t.Fatalf("SaveToken: %v", err)
	}
	got, err := LoadToken(dir)
	if err != nil {
		t.Fatalf("LoadToken: %v", err)
	}
	if got != "secret-token-123" {
		t.Errorf("token round-trip mismatch: got %q", got)
	}
}

func TestSaveOmitsToken(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	cfg := DefaultConfig()
	cfg.APIBaseURL = "https://tiai.example.local"
	cfg.AuthToken = "should-not-be-written"
	if err := cfg.Save(path); err != nil {
		t.Fatalf("Save: %v", err)
	}

	reloaded, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	// AuthToken comes only from token.dat (none here), never from YAML.
	if reloaded.AuthToken != "" {
		t.Errorf("token must not be persisted in YAML, got %q", reloaded.AuthToken)
	}
}

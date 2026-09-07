package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Unit tests must not touch machine-wide state (HKLM on Windows): pin the
// entropy seams to a fixed in-memory value so token round-trips stay hermetic
// whatever machine — and whatever privileges — they run under.
func TestMain(m *testing.M) {
	fixed := []byte("test-entropy-0123456789abcdef!!!")
	readEntropy = func() []byte { return fixed }
	ensureEntropy = func() []byte { return fixed }
	os.Exit(m.Run())
}

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

func TestClearToken(t *testing.T) {
	dir := t.TempDir()

	// Clearing when nothing is stored is a no-op, not an error: the caller
	// reacts to a 401 and cannot know whether a file ever existed.
	if err := ClearToken(dir); err != nil {
		t.Fatalf("ClearToken on empty dir: %v", err)
	}

	if err := SaveToken(dir, "secret-token-123"); err != nil {
		t.Fatalf("SaveToken: %v", err)
	}
	if err := ClearToken(dir); err != nil {
		t.Fatalf("ClearToken: %v", err)
	}
	tok, err := LoadToken(dir)
	if err != nil || tok != "" {
		t.Fatalf("expected no token after clear, got %q err=%v", tok, err)
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

// A token nobody can read is a token the agent does not have. Never an error:
// Load is called before the service has opened its log file, so failing here
// used to leave a poste with a service that would not start and nothing
// anywhere saying why — while re-enrolling costs one request.
func TestLoadTokenTreatsACorruptFileAsNotEnrolled(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "token.dat"), []byte("not base64 at all !!"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	tok, err := LoadToken(dir)
	if err != nil {
		t.Fatalf("a corrupt token must not fail the load: %v", err)
	}
	if tok != "" {
		t.Errorf("expected no token, got %q", tok)
	}
}

// And the same must hold through Load, which is the path the service takes.
func TestLoadSurvivesACorruptToken(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	if err := os.WriteFile(path, []byte("api_base_url: https://tiai.example.local\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "token.dat"), []byte("\x00\x01truncated"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load must survive a corrupt token.dat: %v", err)
	}
	if cfg.AuthToken != "" {
		t.Errorf("expected an empty token, got %q", cfg.AuthToken)
	}
}

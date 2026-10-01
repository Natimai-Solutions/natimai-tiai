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
	// Too short and a full scan of a large disk is reported as failed while
	// Defender is still running it; absent and a wedged scan holds the
	// sequential command worker forever.
	if cfg.DefenderFullScanTimeoutSeconds != DefaultDefenderFullScanTimeout {
		t.Errorf("expected default full scan timeout, got %d", cfg.DefenderFullScanTimeoutSeconds)
	}
}

// The full-scan budget sits between "a scan that is merely slow" and "a worker
// held for good": hours, not minutes, and still bounded within the day.
func TestDefaultFullScanTimeoutIsHoursNotForever(t *testing.T) {
	if DefaultDefenderFullScanTimeout < 4*3600 {
		t.Errorf("default full scan budget %ds would time out legitimate scans of large disks",
			DefaultDefenderFullScanTimeout)
	}
	if DefaultDefenderFullScanTimeout > 24*3600 {
		t.Errorf("default full scan budget %ds no longer bounds a stuck scan",
			DefaultDefenderFullScanTimeout)
	}
	if DefaultConfig().DefenderFullScanTimeoutSeconds != DefaultDefenderFullScanTimeout {
		t.Error("DefaultConfig must carry the default full scan budget")
	}
}

// The budget is a setting so that a parc with slow disks can raise it — a
// value from the YAML must win, and a zeroed one must not disable the bound.
func TestFullScanTimeoutIsConfigurable(t *testing.T) {
	for body, want := range map[string]int{
		"defender_full_scan_timeout_seconds: 43200\n": 43200,
		"defender_full_scan_timeout_seconds: 0\n":     DefaultDefenderFullScanTimeout,
		"defender_full_scan_timeout_seconds: -5\n":    DefaultDefenderFullScanTimeout,
	} {
		path := filepath.Join(t.TempDir(), "config.yaml")
		if err := os.WriteFile(path, []byte("api_base_url: https://tiai.example.local\n"+body), 0o600); err != nil {
			t.Fatalf("WriteFile: %v", err)
		}
		cfg, err := Load(path)
		if err != nil {
			t.Fatalf("Load: %v", err)
		}
		if cfg.DefenderFullScanTimeoutSeconds != want {
			t.Errorf("%q: full scan timeout = %d, want %d",
				strings.TrimSpace(body), cfg.DefenderFullScanTimeoutSeconds, want)
		}
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

// The site is whatever the deployment wrote, and nothing when it wrote
// nothing: the agent has no way to find it out by itself, and a made-up
// default would file every poste under a location nobody chose.
func TestLocationDefaultsToNoneAndRoundTrips(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	if err := (&Config{APIBaseURL: "https://tiai.example.local"}).Save(path); err != nil {
		t.Fatalf("Save: %v", err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Location != "" {
		t.Errorf("Location = %q, want none by default", cfg.Location)
	}

	body := "api_base_url: https://tiai.example.local\nlocation: Lycée de Taravao\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	cfg, err = Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Location != "Lycée de Taravao" {
		t.Errorf("Location = %q", cfg.Location)
	}
}

// proxy_url: absent means direct — the empty string ParseProxy reads as such —
// and a value round-trips through Save, so init-config followed by a hand edit
// keeps it.
func TestProxyURLDefaultsToDirectAndRoundTrips(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := (&Config{APIBaseURL: "https://tiai.example.local"}).Save(path); err != nil {
		t.Fatalf("Save: %v", err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "proxy_url") {
		t.Errorf("an unset proxy_url must not be written: %s", data)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.ProxyURL != "" {
		t.Errorf("ProxyURL = %q, want empty (direct)", cfg.ProxyURL)
	}

	body := "api_base_url: https://tiai.example.local\nproxy_url: http://proxy.lycee.local:3128\n"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err = Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.ProxyURL != "http://proxy.lycee.local:3128" {
		t.Errorf("ProxyURL = %q", cfg.ProxyURL)
	}
}

// A rotated token that cannot be written must leave the previous one readable:
// the agent keeps using it, and the next start must load it rather than find
// a half-written file. Here the temporary file cannot even be created.
func TestFailedTokenWriteLeavesThePreviousTokenIntact(t *testing.T) {
	dir := t.TempDir()
	if err := SaveToken(dir, "current-token"); err != nil {
		t.Fatalf("SaveToken: %v", err)
	}
	// A directory where the temporary file should go.
	if err := os.Mkdir(tokenPath(dir)+".tmp", 0o750); err != nil {
		t.Fatal(err)
	}

	if err := SaveToken(dir, "rotated-token"); err == nil {
		t.Fatal("SaveToken succeeded although its temporary file could not be written")
	}
	got, err := LoadToken(dir)
	if err != nil || got != "current-token" {
		t.Errorf("after a failed write, LoadToken = %q (err %v), want the previous token", got, err)
	}
}

// A write that fails at the rename leaves no temporary file behind: it holds a
// token, and a stray copy of one is exactly what the ACL on the folder and the
// DPAPI entropy exist to avoid multiplying.
func TestFailedTokenRenameRemovesTheTemporaryFile(t *testing.T) {
	dir := t.TempDir()
	// token.dat is a non-empty directory: nothing can be renamed over it.
	if err := os.MkdirAll(filepath.Join(tokenPath(dir), "blocker"), 0o750); err != nil {
		t.Fatal(err)
	}

	if err := SaveToken(dir, "rotated-token"); err == nil {
		t.Fatal("SaveToken succeeded although token.dat could not be replaced")
	}
	if _, err := os.Stat(tokenPath(dir) + ".tmp"); !os.IsNotExist(err) {
		t.Errorf("temporary token file left behind (stat err: %v)", err)
	}
}

// A successful rotation replaces the stored token, the temporary file gone.
func TestSaveTokenReplacesThePreviousOne(t *testing.T) {
	dir := t.TempDir()
	for _, tok := range []string{"enrolled-token", "rotated-token"} {
		if err := SaveToken(dir, tok); err != nil {
			t.Fatalf("SaveToken(%q): %v", tok, err)
		}
	}
	got, err := LoadToken(dir)
	if err != nil || got != "rotated-token" {
		t.Errorf("LoadToken = %q (err %v), want the rotated token", got, err)
	}
	if _, err := os.Stat(tokenPath(dir) + ".tmp"); !os.IsNotExist(err) {
		t.Errorf("temporary token file left behind (stat err: %v)", err)
	}
}

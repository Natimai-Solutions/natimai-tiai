package config

import (
	"strings"

	"golang.org/x/sys/windows/registry"
)

// applyRegistryOverrides overlays values from HKLM\SOFTWARE\Tiai onto cfg. Any
// present key wins over the YAML file, letting GPO push a single setting (e.g.
// the enrollment secret) without rewriting the config file (plan §2.10).
func applyRegistryOverrides(cfg *Config) {
	k, err := registry.OpenKey(
		registry.LOCAL_MACHINE,
		`SOFTWARE\Tiai`,
		registry.QUERY_VALUE|registry.WOW64_64KEY,
	)
	if err != nil {
		return
	}
	defer k.Close()

	if v, _, err := k.GetStringValue("ApiBaseURL"); err == nil && v != "" {
		cfg.APIBaseURL = v
	}
	if v, _, err := k.GetStringValue("EnrollmentSecret"); err == nil && v != "" {
		cfg.EnrollmentSecret = v
	}
	if v, _, err := k.GetStringValue("MachineUUID"); err == nil && v != "" {
		cfg.MachineUUID = v
	}
	if v, _, err := k.GetStringValue("LogLevel"); err == nil && v != "" {
		cfg.LogLevel = v
	}
	// Non-empty wins, like the strings above: a GPO that wants to *cancel* a
	// proxy a YAML names writes the keyword "direct", not an empty value.
	if v, _, err := k.GetStringValue("ProxyURL"); err == nil && strings.TrimSpace(v) != "" {
		cfg.ProxyURL = strings.TrimSpace(v)
	}
	// Presence wins, like the two flags below and unlike the strings above: an
	// empty Location pushed by a GPO is the way to *remove* a site name a YAML
	// still carries, and it has to be able to.
	if v, _, err := k.GetStringValue("Location"); err == nil {
		cfg.Location = strings.TrimSpace(v)
	}
	// No `v > 0` guard here, unlike the intervals below: 0 is the meaningful
	// value (report presence only), so it is the key's *presence* that wins.
	if v, _, err := k.GetIntegerValue("ReportSessionUsername"); err == nil {
		on := v != 0
		cfg.ReportSessionUsername = &on
	}
	if v, _, err := k.GetIntegerValue("AllowInsecureHTTP"); err == nil {
		cfg.AllowInsecureHTTP = v != 0
	}
	if v, _, err := k.GetIntegerValue("HeartbeatIntervalSeconds"); err == nil && v > 0 {
		cfg.HeartbeatIntervalSeconds = int(v)
	}
	if v, _, err := k.GetIntegerValue("WUCollectIntervalSeconds"); err == nil && v > 0 {
		cfg.WUCollectIntervalSeconds = int(v)
	}
	if v, _, err := k.GetIntegerValue("InventoryCollectIntervalSeconds"); err == nil && v > 0 {
		cfg.InventoryCollectIntervalSeconds = int(v)
	}
	// Presence wins, like ReportSessionUsername and for the same reason: 0 is
	// the meaningful value here, and it is the one an administrator pushes.
	if v, _, err := k.GetIntegerValue("ReportSoftware"); err == nil {
		on := v != 0
		cfg.ReportSoftware = &on
	}
	if v, _, err := k.GetIntegerValue("WUInstallTimeoutSeconds"); err == nil && v > 0 {
		cfg.WUInstallTimeoutSeconds = int(v)
	}
	if v, _, err := k.GetIntegerValue("DefenderFullScanTimeoutSeconds"); err == nil && v > 0 {
		cfg.DefenderFullScanTimeoutSeconds = int(v)
	}
}

// DeployKeys reads the deployment trust anchors afresh, for each deployment:
// a GPO that adds a publisher or switches winget on takes effect at the next
// command, without restarting the service.
func DeployKeys() DeployTrust {
	k, err := registry.OpenKey(
		registry.LOCAL_MACHINE,
		`SOFTWARE\Tiai`,
		registry.QUERY_VALUE|registry.WOW64_64KEY,
	)
	if err != nil {
		return DeployTrust{}
	}
	defer k.Close()
	return readDeployKeys(k)
}

func readDeployKeys(k registry.Key) DeployTrust {
	t := DeployTrust{
		Signers:     readList(k, "DeploySigners"),
		Publishers:  readList(k, "DeployPublishers"),
		WingetAllow: readList(k, "DeployWingetAllow"),
	}
	if v, _, err := k.GetIntegerValue("DeployWinget"); err == nil {
		t.Winget = v != 0
	}
	if v, _, err := k.GetIntegerValue("DeployMethodAMaxGB"); err == nil && v <= 1024 {
		t.MethodAMaxGB = int(v)
	}
	return t
}

// readList reads a list value: REG_MULTI_SZ as a GPO preference writes it, or
// a REG_SZ whose items are separated by ";" for whoever set it by hand.
func readList(k registry.Key, name string) []string {
	if v, _, err := k.GetStringsValue(name); err == nil {
		return SplitList(strings.Join(v, ";"))
	}
	if v, _, err := k.GetStringValue(name); err == nil {
		return SplitList(v)
	}
	return nil
}

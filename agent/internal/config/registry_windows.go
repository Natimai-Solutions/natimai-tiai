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
}

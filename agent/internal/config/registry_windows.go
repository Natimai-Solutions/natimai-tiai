package config

import "golang.org/x/sys/windows/registry"

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
	// No `v > 0` guard here, unlike the intervals below: 0 is the meaningful
	// value (report presence only), so it is the key's *presence* that wins.
	if v, _, err := k.GetIntegerValue("ReportSessionUsername"); err == nil {
		on := v != 0
		cfg.ReportSessionUsername = &on
	}
	if v, _, err := k.GetIntegerValue("HeartbeatIntervalSeconds"); err == nil && v > 0 {
		cfg.HeartbeatIntervalSeconds = int(v)
	}
	if v, _, err := k.GetIntegerValue("TelemetryIntervalSeconds"); err == nil && v > 0 {
		cfg.TelemetryIntervalSeconds = int(v)
	}
}

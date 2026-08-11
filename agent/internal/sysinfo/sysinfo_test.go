package sysinfo

import "testing"

func TestFixProductName(t *testing.T) {
	tests := []struct {
		name    string
		product string
		build   string
		want    string
	}{
		// The bug this guards: Windows 11 still reports "Windows 10" in the
		// registry, so only the build number tells the two apart.
		{"win11 pro reported as win10", "Windows 10 Pro", "26200", "Windows 11 Pro"},
		{"win11 first build", "Windows 10 Pro", "22000", "Windows 11 Pro"},
		{"win11 education", "Windows 10 Education", "22631", "Windows 11 Education"},
		{"win11 enterprise", "Windows 10 Enterprise", "22621", "Windows 11 Enterprise"},

		{"genuine win10 22h2", "Windows 10 Pro", "19045", "Windows 10 Pro"},
		{"win10 last build below threshold", "Windows 10 Pro", "21999", "Windows 10 Pro"},

		// Server SKUs name themselves correctly; 2025 is above the threshold and
		// must not be rewritten.
		{"server 2025 above threshold", "Windows Server 2025 Standard", "26100", "Windows Server 2025 Standard"},
		{"server 2022", "Windows Server 2022 Datacenter", "20348", "Windows Server 2022 Datacenter"},

		{"empty build", "Windows 10 Pro", "", "Windows 10 Pro"},
		{"non-numeric build", "Windows 10 Pro", "abc", "Windows 10 Pro"},
		{"padded build", "Windows 10 Pro", " 26200 ", "Windows 11 Pro"},
		{"empty product", "", "26200", ""},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := fixProductName(tc.product, tc.build); got != tc.want {
				t.Errorf("fixProductName(%q, %q) = %q, want %q", tc.product, tc.build, got, tc.want)
			}
		})
	}
}

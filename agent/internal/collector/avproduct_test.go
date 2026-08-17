package collector

import "testing"

// productState values in the shapes the Security Center actually reports:
// 0xTTRRSS, where RR is the protection byte and SS the signature byte.
const (
	stateDefenderOn      = 0x061100 // Defender running, definitions current
	stateDefenderOff     = 0x060100 // Defender stopped (a third party took over)
	stateThirdPartyOn    = 0x041000 // third party running, definitions current
	stateThirdPartyStale = 0x041010 // third party running, definitions out of date
	stateThirdPartyOff   = 0x040000 // third party stopped
	stateUnreadable      = 0x040800 // protection byte we have no reading for
)

func boolOrNil(t *testing.T, got *bool, want *bool, what string) {
	t.Helper()
	switch {
	case want == nil && got != nil:
		t.Errorf("%s = %v, want unknown", what, *got)
	case want != nil && got == nil:
		t.Errorf("%s = unknown, want %v", what, *want)
	case want != nil && got != nil && *got != *want:
		t.Errorf("%s = %v, want %v", what, *got, *want)
	}
}

func TestDecodeProductState(t *testing.T) {
	tests := []struct {
		name           string
		state          uint32
		wantEnabled    *bool
		wantSignatures *bool
	}{
		{"defender running", stateDefenderOn, boolPtr(true), boolPtr(true)},
		{"defender stopped", stateDefenderOff, boolPtr(false), boolPtr(true)},
		{"third party running", stateThirdPartyOn, boolPtr(true), boolPtr(true)},
		{"third party with stale definitions", stateThirdPartyStale, boolPtr(true), boolPtr(false)},
		{"third party stopped", stateThirdPartyOff, boolPtr(false), boolPtr(true)},
		// The whole point of the conservative decoding: a byte we don't know is
		// reported as unknown, never as "protection disabled".
		{"unreadable protection byte", stateUnreadable, nil, boolPtr(true)},
		{"unreadable signature byte", 0x041020, boolPtr(true), nil},
		{"unreadable both", 0x040820, nil, nil},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			enabled, signatures := decodeProductState(tc.state)
			boolOrNil(t, enabled, tc.wantEnabled, "enabled")
			boolOrNil(t, signatures, tc.wantSignatures, "signaturesUpToDate")
		})
	}
}

func TestIsDefenderProduct(t *testing.T) {
	tests := []struct {
		name    string
		product rawAVProduct
		want    bool
	}{
		{
			name:    "the well-known instance guid, whatever the case",
			product: rawAVProduct{Name: "Sécurité Windows", InstanceGUID: "{D68DDC3A-831F-4FAE-9E44-DA132C1ACF46}"},
			want:    true,
		},
		{
			name:    "the uri Defender registers instead of an executable path",
			product: rawAVProduct{Name: "Antivirus intégré", ProductExe: "windowsdefender://"},
			want:    true,
		},
		{
			name:    "the brand name, which stays untranslated",
			product: rawAVProduct{Name: "Windows Defender"},
			want:    true,
		},
		{
			name: "a third party is not Defender, even next to it",
			product: rawAVProduct{
				Name:         "ESET Endpoint Security",
				InstanceGUID: "{7B8E8B4A-1234-4C3D-9E1F-0A1B2C3D4E5F}",
				ProductExe:   `C:\Program Files\ESET\ESET Security\ecmd.exe`,
			},
			want: false,
		},
		{
			// "Bitdefender" contains "defender": the name fallback must match the
			// qualified vendor names, or every Bitdefender-protected poste would be
			// filed under Defender.
			name:    "a vendor whose name embeds Defender's",
			product: rawAVProduct{Name: "Bitdefender Endpoint Security Tools"},
			want:    false,
		},
		{
			name:    "the other name Microsoft ships",
			product: rawAVProduct{Name: "Microsoft Defender Antivirus"},
			want:    true,
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := isDefenderProduct(tc.product); got != tc.want {
				t.Errorf("isDefenderProduct = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestBuildAVProductState(t *testing.T) {
	defender := rawAVProduct{
		Name:         "Windows Defender",
		State:        stateDefenderOn,
		InstanceGUID: defenderInstanceGUID,
		ProductExe:   "windowsdefender://",
	}
	eset := rawAVProduct{
		Name:       "  ESET Endpoint Security  ",
		State:      stateThirdPartyOn,
		ProductExe: `C:\Program Files\ESET\ecmd.exe`,
	}

	tests := []struct {
		name           string
		products       []rawAVProduct
		wantName       string
		wantIsDefender bool
		wantEnabled    *bool
		wantSignatures *bool
	}{
		{
			// Not an error and not nil: the machine really has no antivirus.
			name:     "nothing registered",
			products: nil,
			wantName: "",
		},
		{
			name:           "Defender alone, the ordinary managed poste",
			products:       []rawAVProduct{defender},
			wantName:       "Windows Defender",
			wantIsDefender: true,
			wantEnabled:    boolPtr(true),
			wantSignatures: boolPtr(true),
		},
		{
			// The case the whole collector exists for: Defender still reports
			// itself as running through its own WMI class, but the third party is
			// what guards the machine.
			name:           "a third party alongside a passive Defender",
			products:       []rawAVProduct{defender, eset},
			wantName:       "ESET Endpoint Security",
			wantIsDefender: false,
			wantEnabled:    boolPtr(true),
			wantSignatures: boolPtr(true),
		},
		{
			// A licence lapsed: Windows re-arms Defender, so Defender is the
			// answer even though a third party is still installed.
			name: "a stopped third party loses to a running Defender",
			products: []rawAVProduct{
				{Name: "ESET Endpoint Security", State: stateThirdPartyOff},
				defender,
			},
			wantName:       "Windows Defender",
			wantIsDefender: true,
			wantEnabled:    boolPtr(true),
			wantSignatures: boolPtr(true),
		},
		{
			name:           "stale definitions are reported, not hidden",
			products:       []rawAVProduct{{Name: "Avast Business Antivirus", State: stateThirdPartyStale}},
			wantName:       "Avast Business Antivirus",
			wantEnabled:    boolPtr(true),
			wantSignatures: boolPtr(false),
		},
		{
			// An unreadable bitfield still beats an explicit "stopped": the
			// product may well be running.
			name: "unknown protection outranks stopped",
			products: []rawAVProduct{
				{Name: "Sophos Endpoint", State: stateThirdPartyOff},
				{Name: "Trellix Endpoint Security", State: stateUnreadable},
			},
			wantName:       "Trellix Endpoint Security",
			wantSignatures: boolPtr(true),
		},
		{
			// Stable, so the console doesn't flap between the two from one poll
			// to the next.
			name: "two running third parties are ordered by name",
			products: []rawAVProduct{
				{Name: "Kaspersky Endpoint Security", State: stateThirdPartyOn},
				{Name: "Bitdefender Endpoint Security Tools", State: stateThirdPartyOn},
			},
			wantName:       "Bitdefender Endpoint Security Tools",
			wantEnabled:    boolPtr(true),
			wantSignatures: boolPtr(true),
		},
		{
			name: "a nameless entry is not a product",
			products: []rawAVProduct{
				{Name: "   ", State: stateThirdPartyOn},
				{Name: "Windows Defender", State: stateDefenderOn},
			},
			wantName:       "Windows Defender",
			wantIsDefender: true,
			wantEnabled:    boolPtr(true),
			wantSignatures: boolPtr(true),
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := buildAVProductState(tc.products)
			if got == nil {
				t.Fatal("buildAVProductState returned nil; only the caller may report unknown")
			}
			if got.Name != tc.wantName {
				t.Errorf("Name = %q, want %q", got.Name, tc.wantName)
			}
			if got.IsDefender != tc.wantIsDefender {
				t.Errorf("IsDefender = %v, want %v", got.IsDefender, tc.wantIsDefender)
			}
			boolOrNil(t, got.Enabled, tc.wantEnabled, "Enabled")
			boolOrNil(t, got.SignaturesUpToDate, tc.wantSignatures, "SignaturesUpToDate")
		})
	}
}

package collector

import (
	"testing"

	"tiai/agent/internal/models"
)

func u32(v uint32) *uint32 { return &v }

func TestEffectiveFirewallPolicyWins(t *testing.T) {
	cases := []struct {
		name          string
		policy, local *uint32
		want          *bool
	}{
		{"neither read", nil, nil, nil},
		{"local only, on", nil, u32(1), boolPtr(true)},
		{"local only, off", nil, u32(0), boolPtr(false)},
		{"gpo turns off what is on locally", u32(0), u32(1), boolPtr(false)},
		{"gpo turns on what is off locally", u32(1), u32(0), boolPtr(true)},
		{"gpo alone", u32(1), nil, boolPtr(true)},
	}
	for _, c := range cases {
		got := EffectiveFirewall(c.policy, c.local)
		if (got == nil) != (c.want == nil) || (got != nil && *got != *c.want) {
			t.Errorf("%s: got %v, want %v", c.name, deref(got), deref(c.want))
		}
	}
}

func deref(b *bool) any {
	if b == nil {
		return nil
	}
	return *b
}

// A French winget's output as captured from a pipe: the spinner rewritten
// with carriage returns, a localised header, a row with nothing newer, a row
// cut by winget with an ellipsis, and the footer.
const wingetFrench = "   - \r   \\ \r   | \r" +
	"Nom                         ID                         Version       Disponible    Source\r\n" +
	"-------------------------------------------------------------------------------------------\r\n" +
	"Mozilla Firefox (x64 fr)    Mozilla.Firefox            128.0.3       131.0         winget\r\n" +
	"7-Zip 24.08 (x64)           7zip.7zip                  24.08                       winget\r\n" +
	"Visual Studio Code          Microsoft.VisualStudioCod… 1.90.0        1.94.2        winget\r\n" +
	"VLC media player            VideoLAN.VLC               3.0.20        3.0.21        winget\r\n" +
	"\r\n" +
	"2 mises à niveau disponibles.\r\n"

func TestParseWingetListReadsTheTable(t *testing.T) {
	got := ParseWingetList(wingetFrench)
	want := []models.WingetPackage{
		{ID: "Mozilla.Firefox", Name: "Mozilla Firefox (x64 fr)", Version: "128.0.3", Available: "131.0"},
		{ID: "7zip.7zip", Name: "7-Zip 24.08 (x64)", Version: "24.08"},
		{ID: "VideoLAN.VLC", Name: "VLC media player", Version: "3.0.20", Available: "3.0.21"},
	}
	if len(got) != len(want) {
		t.Fatalf("got %d packages %+v, want %d", len(got), got, len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("row %d: got %+v, want %+v", i, got[i], want[i])
		}
	}
}

// With nothing to upgrade winget drops the Available column: four columns, the
// fourth being the source.
func TestParseWingetListWithoutAvailableColumn(t *testing.T) {
	out := "Name             Id              Version   Source\n" +
		"--------------------------------------------------\n" +
		"7-Zip 24.08      7zip.7zip       24.08     winget\n"
	got := ParseWingetList(out)
	if len(got) != 1 || got[0].ID != "7zip.7zip" || got[0].Available != "" || got[0].Version != "24.08" {
		t.Fatalf("got %+v", got)
	}
}

func TestParseWingetListNoTable(t *testing.T) {
	if got := ParseWingetList("No installed package found matching input criteria.\n"); got != nil {
		t.Fatalf("got %+v, want nil", got)
	}
	if got := ParseWingetList(""); got != nil {
		t.Fatalf("got %+v, want nil", got)
	}
}

// An empty table is a reading — nothing installed winget knows — not nil.
func TestParseWingetListEmptyTable(t *testing.T) {
	out := "Name   Id   Version   Source\n----------------------------\n\n"
	got := ParseWingetList(out)
	if got == nil || len(got) != 0 {
		t.Fatalf("got %#v, want an empty list", got)
	}
}

// The two new lists are ordered before hashing, so the same group read in
// another order does not resend the inventory.
func TestInventoryHashIgnoresComplianceOrder(t *testing.T) {
	a := &models.InventoryState{
		LocalAdmins:    &[]models.LocalAdmin{{Name: `PC\Administrateur`}, {Name: `LYCEE\Admins du domaine`}},
		WingetPackages: &[]models.WingetPackage{{ID: "b"}, {ID: "a"}},
	}
	b := &models.InventoryState{
		LocalAdmins:    &[]models.LocalAdmin{{Name: `LYCEE\Admins du domaine`}, {Name: `PC\Administrateur`}},
		WingetPackages: &[]models.WingetPackage{{ID: "a"}, {ID: "b"}},
	}
	InventoryHash(a)
	InventoryHash(b)
	if a.Hash != b.Hash {
		t.Fatal("same lists in another order hash differently")
	}
	c := &models.InventoryState{}
	InventoryHash(c)
	if c.Hash == a.Hash {
		t.Fatal("lists absent and present hash the same")
	}
}

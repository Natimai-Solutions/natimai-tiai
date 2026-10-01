package service

import "testing"

// The data directory is restricted only when it is unambiguously the agent's:
// a protected DACL on a directory someone else uses — C:\, a shared tools
// folder — would break far more than it protects.
func TestMayHardenDataDir(t *testing.T) {
	const def = `C:\ProgramData\Tiai`
	cases := []struct {
		name    string
		dir     string
		existed bool
		want    bool
	}{
		{"default, existing", def, true, true},
		{"default, created now", def, false, true},
		{"default, other case", `c:\programdata\TIAI`, true, true},
		{"custom, created now", `D:\Agents\Tiai`, false, true},
		{"custom, pre-existing", `D:\Agents\Tiai`, true, false},
		{"a drive root", `C:\`, true, false},
	}
	for _, c := range cases {
		if got := mayHardenDataDir(c.dir, def, c.existed); got != c.want {
			t.Errorf("%s: mayHardenDataDir(%q, existed=%v) = %v, want %v",
				c.name, c.dir, c.existed, got, c.want)
		}
	}
}

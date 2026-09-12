package collector

import "testing"

func TestParentOU(t *testing.T) {
	cases := []struct {
		dn, name, ouDN string
	}{
		{
			"CN=PC-B12-03,OU=Salle B12,OU=Postes,DC=lycee,DC=local",
			"Salle B12", "OU=Salle B12,OU=Postes,DC=lycee,DC=local",
		},
		// Spaces around the commas, as some tools write them.
		{"CN=PC-1, OU=B13 , DC=corp", "B13", "OU=B13,DC=corp"},
		// An escaped comma inside a value is not a separator.
		{`CN=PC-1,OU=Salle A\, B,DC=corp`, "Salle A, B", `OU=Salle A\, B,DC=corp`},
		// Straight under the domain, or under the Computers container: no OU.
		{"CN=PC-1,DC=corp,DC=local", "", ""},
		{"CN=PC-1,CN=Computers,DC=corp,DC=local", "", ""},
		// Case of the attribute type does not matter.
		{"cn=PC-1,ou=Labo,dc=corp", "Labo", "ou=Labo,dc=corp"},
		{"", "", ""},
		{"CN=PC-1", "", ""},
	}
	for _, c := range cases {
		name, ouDN := parentOU(c.dn)
		if name != c.name || ouDN != c.ouDN {
			t.Errorf("parentOU(%q) = (%q, %q), want (%q, %q)", c.dn, name, ouDN, c.name, c.ouDN)
		}
	}
}

func TestDirectoryState(t *testing.T) {
	if directoryState("  ", "x") != nil {
		t.Fatal("no DN must yield no block")
	}
	st := directoryState("CN=PC-1,OU=B12,DC=corp", " Bât. B ")
	if st.OU != "B12" || st.OUDN != "OU=B12,DC=corp" || st.ADLocation != "Bât. B" {
		t.Fatalf("unexpected state: %+v", st)
	}
	if st.DistinguishedName != "CN=PC-1,OU=B12,DC=corp" {
		t.Fatalf("DN must be kept verbatim: %q", st.DistinguishedName)
	}
}

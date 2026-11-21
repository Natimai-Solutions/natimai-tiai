package collector

import (
	"strings"
	"testing"
)

func TestDirectoryFiltersKeepOnlyNamesAndBatch(t *testing.T) {
	names := []string{"pc-02", "PC-01", "PC-01", "bad name", "x)(objectClass=*", "", "PC-03"}
	got := DirectoryFilters(names)
	want := "(&(objectCategory=computer)(|(sAMAccountName=PC-01$)(sAMAccountName=PC-02$)(sAMAccountName=PC-03$)))"
	if len(got) != 1 || got[0] != want {
		t.Fatalf("got %q", got)
	}

	many := make([]string, 450)
	for i := range many {
		many[i] = "PC-" + strings.Repeat("A", 1+i%40) + string(rune('A'+i%26)) + "-" + itoa(i)
	}
	if got := DirectoryFilters(many); len(got) != 3 {
		t.Fatalf("450 names: %d filters, want 3", len(got))
	}
	if got := DirectoryFilters(nil); got != nil {
		t.Fatalf("no name: %q", got)
	}
}

func itoa(i int) string {
	const digits = "0123456789"
	if i < 10 {
		return digits[i : i+1]
	}
	return itoa(i/10) + digits[i%10:i%10+1]
}

// The filters reach the script single-quoted, and the script only reads.
func TestDirectoryScriptCarriesTheFiltersAndOnlyReads(t *testing.T) {
	script := directoryScript(DirectoryFilters([]string{"PC-01"}))
	if !strings.Contains(script, "@('(&(objectCategory=computer)(|(sAMAccountName=PC-01$)))')") {
		t.Fatalf("filter not in the script:\n%s", script)
	}
	for _, verb := range []string{"CommitChanges", "Put(", "SetInfo", "DeleteTree", "Remove-"} {
		if strings.Contains(script, verb) {
			t.Errorf("the script writes (%s)", verb)
		}
	}
}

func TestParseDirectoryReading(t *testing.T) {
	raw := `{"domain":{"name":"lycee.local","netbios_name":"LYCEE","sid":"S-1-5-21-1-2-3"},
	"objects":[{"object_guid":"0b8f0a52-2c1d-4f0e-9a51-6c3f1b2d4e5f","sam_account_name":"PC-01$",
	"dns_host_name":"pc-01.lycee.local","distinguished_name":"CN=PC-01,OU=B12,DC=lycee,DC=local",
	"location":"","disabled":false}],"subnets":[{"subnet":"10.1.0.0/16","site":"Taravao"}]}`
	r, err := ParseDirectoryReading([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	if r.Domain.NetBIOSName != "LYCEE" || len(r.Objects) != 1 || r.Objects[0].SAMAccountName != "PC-01$" {
		t.Fatalf("got %+v", r)
	}
	if r.Subnets[0].Site != "Taravao" {
		t.Fatalf("subnets %+v", r.Subnets)
	}
	empty, err := ParseDirectoryReading([]byte(`{"domain":{"name":"x","netbios_name":"X","sid":"S-1-5-21-1-2-3"},"objects":null,"subnets":null}`))
	if err != nil || empty.Objects == nil || empty.Subnets == nil {
		t.Fatalf("empty lists must be [] not null: %+v %v", empty, err)
	}
	if _, err := ParseDirectoryReading([]byte(`{"domain":{"name":"x"}}`)); err == nil {
		t.Fatal("a reading without the domain's SID must be refused")
	}
	if _, err := ParseDirectoryReading([]byte(`not json`)); err == nil {
		t.Fatal("garbage must be refused")
	}
}

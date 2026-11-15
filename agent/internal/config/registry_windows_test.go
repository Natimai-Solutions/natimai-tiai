// The registry reading of the deployment keys, against a real key — a
// throw-away one under HKCU, never HKLM\SOFTWARE\Tiai, which no unit test may
// touch.
package config

import (
	"bytes"
	"fmt"
	"log"
	"os"
	"strings"
	"testing"

	"golang.org/x/sys/windows/registry"
)

// scratchKey creates an empty key under HKCU for one test and removes it
// afterwards.
func scratchKey(t *testing.T) registry.Key {
	t.Helper()
	path := fmt.Sprintf(`Software\TiaiAgentTest-%d-%s`, os.Getpid(),
		strings.NewReplacer("/", "-", " ", "-", `\`, "-").Replace(t.Name()))
	k, _, err := registry.CreateKey(registry.CURRENT_USER, path, registry.ALL_ACCESS)
	if err != nil {
		t.Fatalf("create HKCU\\%s: %v", path, err)
	}
	t.Cleanup(func() {
		_ = k.Close()
		_ = registry.DeleteKey(registry.CURRENT_USER, path)
	})
	return k
}

// DeployMethodAMaxGB as the registry holds it: taken when it is a number from
// 1 to 1024, and otherwise ignored *with a line in the log* — 0, a value above
// the ceiling, a REG_SZ. A value that is not set is the default, silently.
func TestReadDeployKeysSaysWhenMethodAMaxGBIsUnusable(t *testing.T) {
	for _, c := range []struct {
		name  string
		set   func(k registry.Key) error
		want  int
		warns bool
	}{
		{name: "not set", set: func(registry.Key) error { return nil }},
		{name: "in range", set: func(k registry.Key) error { return k.SetDWordValue("DeployMethodAMaxGB", 16) }, want: 16},
		{name: "a QWORD in range", set: func(k registry.Key) error { return k.SetQWordValue("DeployMethodAMaxGB", 32) }, want: 32},
		{name: "zero", set: func(k registry.Key) error { return k.SetDWordValue("DeployMethodAMaxGB", 0) }, warns: true},
		{name: "above the ceiling", set: func(k registry.Key) error { return k.SetDWordValue("DeployMethodAMaxGB", 2048) }, warns: true},
		{name: "a string", set: func(k registry.Key) error { return k.SetStringValue("DeployMethodAMaxGB", "16") }, warns: true},
	} {
		t.Run(c.name, func(t *testing.T) {
			k := scratchKey(t)
			if err := c.set(k); err != nil {
				t.Fatalf("set the value: %v", err)
			}
			var buf bytes.Buffer
			out := log.Writer()
			log.SetOutput(&buf)
			t.Cleanup(func() { log.SetOutput(out) })

			trust := readDeployKeys(k)

			if trust.MethodAMaxGB != c.want {
				t.Errorf("MethodAMaxGB = %d, want %d (0: the agent's default)", trust.MethodAMaxGB, c.want)
			}
			logged := buf.String()
			if c.warns != strings.Contains(logged, "DeployMethodAMaxGB") {
				t.Errorf("logged %q, want a line about the value: %v", logged, c.warns)
			}
			if n := strings.Count(logged, "\n"); c.warns && n != 1 {
				t.Errorf("%d line(s) logged, want exactly one:\n%s", n, logged)
			}
		})
	}
}

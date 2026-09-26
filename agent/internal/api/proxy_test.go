package api

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"tiai/agent/internal/models"
)

// The bug this setting exists for: a parc that pushes HTTPS_PROXY as a system
// variable had every heartbeat sent to the establishment's proxy, which
// answered 407. With no setting at all, the environment must now be ignored.
func TestDefaultIgnoresTheProxyEnvironment(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"commands":[]}`))
	}))
	defer srv.Close()

	// A proxy nothing listens on: reached, the request fails; ignored, it
	// succeeds. Both spellings, since Windows reads either.
	t.Setenv("HTTP_PROXY", "http://127.0.0.1:9")
	t.Setenv("HTTPS_PROXY", "http://127.0.0.1:9")
	t.Setenv("http_proxy", "http://127.0.0.1:9")
	t.Setenv("https_proxy", "http://127.0.0.1:9")

	proxy, err := ParseProxy("")
	if err != nil {
		t.Fatalf("ParseProxy(\"\"): %v", err)
	}
	if proxy != nil {
		t.Fatal("an empty proxy_url must mean a direct connection")
	}
	c := New(srv.URL, "token", time.Second, proxy)
	if _, err := c.Heartbeat(context.Background(), models.HeartbeatRequest{}); err != nil {
		t.Fatalf("the default must not cross the environment's proxy: %v", err)
	}
}

// A proxy_url that is a URL sends every request through that proxy — the case
// of an establishment whose server sits behind one on purpose.
func TestAProxyURLIsUsedForEveryRequest(t *testing.T) {
	var seen atomic.Int32
	var target atomic.Value
	proxySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Through a proxy the request line carries the absolute URL, so the
		// host the client meant is in r.Host, not the proxy's own address.
		seen.Add(1)
		target.Store(r.Host)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"commands":[]}`))
	}))
	defer proxySrv.Close()

	proxy, err := ParseProxy(proxySrv.URL)
	if err != nil {
		t.Fatalf("ParseProxy: %v", err)
	}
	// A server that does not exist: only the proxy can answer for it.
	c := New("http://tiai.invalid:8800", "token", time.Second, proxy)
	if _, err := c.Heartbeat(context.Background(), models.HeartbeatRequest{}); err != nil {
		t.Fatalf("the request must go through the proxy: %v", err)
	}
	if seen.Load() != 1 {
		t.Fatalf("expected one request at the proxy, got %d", seen.Load())
	}
	if got, _ := target.Load().(string); got != "tiai.invalid:8800" {
		t.Errorf("the proxy must be asked for the server, got Host %q", got)
	}
}

func TestParseProxyKeywords(t *testing.T) {
	for _, s := range []string{"", "direct", "Direct", " none ", "DIRECT"} {
		p, err := ParseProxy(s)
		if err != nil || p != nil {
			t.Errorf("ParseProxy(%q) = %v, %v; want direct", s, p, err)
		}
	}
	for _, s := range []string{"environment", "Environment", "env"} {
		p, err := ParseProxy(s)
		if err != nil || p == nil {
			t.Errorf("ParseProxy(%q) = %v, %v; want the environment", s, p, err)
		}
	}
}

// A typo must be an error the agent can log, not a silent direct connection
// the administrator takes for a working proxy — or, worse, a proxy of "proxy".
func TestParseProxyRejectsWhatIsNotAProxy(t *testing.T) {
	for _, s := range []string{"proxy:3128", "ftp://proxy:3128", "http://", "system", "10.0.0.1:3128"} {
		if _, err := ParseProxy(s); err == nil {
			t.Errorf("ParseProxy(%q) accepted", s)
		}
	}
	for _, s := range []string{"http://proxy:3128", "https://proxy.lycee.local", "socks5://10.0.0.1:1080", "http://user:pass@proxy:3128"} {
		if _, err := ParseProxy(s); err != nil {
			t.Errorf("ParseProxy(%q): %v", s, err)
		}
	}
}

// The log names the proxy, never its password.
func TestDescribeProxyRedactsCredentials(t *testing.T) {
	got := DescribeProxy("http://svc-tiai:S3cret!@proxy.lycee.local:3128")
	if strings.Contains(got, "S3cret") {
		t.Fatalf("password leaked into %q", got)
	}
	if !strings.Contains(got, "proxy.lycee.local:3128") || !strings.Contains(got, "svc-tiai") {
		t.Errorf("the proxy and its user must stay readable, got %q", got)
	}
	if DescribeProxy("") != ProxyDirect || DescribeProxy("ENV") != ProxyEnvironment {
		t.Error("keywords must be described as themselves")
	}
}

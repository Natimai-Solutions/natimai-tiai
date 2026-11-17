package api

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"tiai/agent/internal/models"
)

// The budget moved off http.Client and onto the request, so the first thing to
// prove is that it is still there: an unbounded client would have a poste hang
// on a server that accepts the connection and never answers.
func TestConfiguredTimeoutStillBoundsARequest(t *testing.T) {
	// A bounded sleep rather than a handler waiting for the client to give up:
	// httptest.Server.Close waits for its handlers to return, so one that never
	// does would hang this test rather than fail it.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(2 * time.Second)
	}))
	defer srv.Close()

	c := New(srv.URL, "token", 100*time.Millisecond, nil)
	start := time.Now()
	_, err := c.Heartbeat(context.Background(), models.HeartbeatRequest{})
	if err == nil {
		t.Fatal("a server that never answers must not hold the agent forever")
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Errorf("the configured timeout did not apply: waited %s", elapsed)
	}
}

// And the second: a caller that hands in a wider deadline gets it. This is what
// lets the heartbeat carrying an inventory — the largest thing the agent ever
// sends — outlast the ten seconds a normal poll is given.
func TestACallersDeadlineWinsOverTheConfiguredTimeout(t *testing.T) {
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-release:
		case <-r.Context().Done():
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"commands":[]}`))
	}))
	defer srv.Close()

	c := New(srv.URL, "token", 50*time.Millisecond, nil)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go func() {
		time.Sleep(300 * time.Millisecond) // well past the configured timeout
		close(release)
	}()
	if _, err := c.Heartbeat(ctx, models.HeartbeatRequest{}); err != nil {
		t.Fatalf("the wider deadline must win, got %v", err)
	}
}

// A non-2xx stays typed, because the agent reacts to 401 specifically.
func TestStatusErrorSurvivesTheTimeoutWrapping(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer srv.Close()

	c := New(srv.URL, "stale", time.Second, nil)
	_, err := c.Heartbeat(context.Background(), models.HeartbeatRequest{})
	var se *StatusError
	if !errors.As(err, &se) || se.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected a typed 401, got %v", err)
	}
}

// The token changes under a running agent — a rotation, from the polling loop —
// while the command worker posts results from its own goroutine. Run under
// -race, this is what proves the swap is safe; and every request must carry
// one of the two tokens whole, never a mix.
func TestTokenSwapUnderConcurrentRequests(t *testing.T) {
	var mu sync.Mutex
	var seen []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		seen = append(seen, strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "))
		mu.Unlock()
	}))
	defer srv.Close()

	c := New(srv.URL, "old-token", time.Second, nil)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 5; j++ {
				_ = c.PostResult(context.Background(), "cmd", models.CommandResult{Status: "succeeded"})
			}
		}()
	}
	c.SetToken("new-token")
	wg.Wait()

	if got := c.Token(); got != "new-token" {
		t.Errorf("Token() = %q after SetToken, want new-token", got)
	}
	mu.Lock()
	defer mu.Unlock()
	for _, tok := range seen {
		if tok != "old-token" && tok != "new-token" {
			t.Fatalf("a request carried %q", tok)
		}
	}
}

// Audit S24: a server that sends more than the manifest's size is cut off
// at size+1 bytes, not left to fill the disk.
func TestADownloadStopsAtTheAnnouncedSize(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		chunk := strings.Repeat("x", 1024)
		for i := 0; i < 1024; i++ { // 1 MiB, far beyond the 10 bytes announced
			if _, err := w.Write([]byte(chunk)); err != nil {
				return
			}
		}
	}))
	defer srv.Close()
	c := New(srv.URL, "t", 5*time.Second, nil)
	f, err := os.CreateTemp(t.TempDir(), "pkg")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	err = c.FetchPackageFile(context.Background(), "p", "s", 0, 10, f)
	if err == nil || !strings.Contains(err.Error(), "plus que") {
		t.Fatalf("err = %v", err)
	}
	info, _ := f.Stat()
	if info.Size() > 11 {
		t.Errorf("wrote %d bytes", info.Size())
	}
}

// Audit S22, S23: a redirect is not followed (the secret header would go
// along), and an error body is bounded.
func TestNoRedirectAndABoundedErrorBody(t *testing.T) {
	hits := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		if r.URL.Path == "/elsewhere" {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.Header.Get("X-Enrollment-Secret") != "" && r.URL.Path == "/api/v1/agent/enroll" {
			http.Redirect(w, r, "/elsewhere", http.StatusMovedPermanently)
			return
		}
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(strings.Repeat("e", 100000)))
	}))
	defer srv.Close()
	c := New(srv.URL, "", 5*time.Second, nil)
	_, err := c.Enroll(context.Background(), "secret", models.EnrollRequest{MachineUUID: "u"})
	if err == nil || hits != 1 {
		t.Fatalf("redirect followed: err=%v hits=%d", err, hits)
	}
	_, err = c.Heartbeat(context.Background(), models.HeartbeatRequest{})
	var se *StatusError
	if !errors.As(err, &se) || len(se.Body) > maxErrorBody {
		t.Fatalf("err = %v", err)
	}
}

// An error body is the answerer's text and ends up in the agent's log with
// the error: rendered on one line, it cannot start a line of its own there.
// The body itself is kept as received — the agent reads codes in it.
func TestAStatusErrorIsRenderedOnOneLine(t *testing.T) {
	const body = "{\"error\":{\"code\":\"machine.enrollment.revoked\"}}\n" +
		"2026/11/15 08:00:00 agent: first heartbeat accepted by the server\r\n" +
		"more\u2028and\u2029more\x00\x1b[2J\u0085"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()
	c := New(srv.URL, "tok", 5*time.Second, nil)

	_, err := c.Heartbeat(context.Background(), models.HeartbeatRequest{})
	var se *StatusError
	if !errors.As(err, &se) {
		t.Fatalf("err = %v", err)
	}
	if se.Body != body {
		t.Errorf("Body = %q, want it as received", se.Body)
	}
	msg := err.Error()
	if strings.ContainsFunc(msg, func(r rune) bool {
		return r < 0x20 || r == 0x7f || r == 0x85 || r == 0x2028 || r == 0x2029
	}) {
		t.Errorf("the error message carries a control character or a line break: %q", msg)
	}
	if !strings.Contains(msg, "status 403") || !strings.Contains(msg, "machine.enrollment.revoked") {
		t.Errorf("the error message lost what it reports: %q", msg)
	}
}

// Every request body leaves without C0 control characters, tab, line feed and
// carriage return excepted: the server's database refuses a NUL (500), and a
// heartbeat refused that way would take the poste offline, a verdict refused
// that way would hold the local queue. Every string field is covered, however
// deep — the strip runs on the encoded document, not field by field.
func TestRequestsLeaveWithoutControlCharacters(t *testing.T) {
	var mu sync.Mutex
	var bodies []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		bodies = append(bodies, string(b))
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()
	c := New(srv.URL, "tok", 5*time.Second, nil)
	ctx := context.Background()

	const dirty = "a\x00b\x01c\x1fd\te\nf\rg"
	if _, err := c.Enroll(ctx, "s", models.EnrollRequest{Hostname: dirty}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Heartbeat(ctx, models.HeartbeatRequest{
		Hostname:      dirty,
		Session:       &models.SessionState{Username: dirty},
		WindowsUpdate: &models.WUState{Pending: []models.PendingUpdate{{Title: dirty}}},
		Inventory:     &models.InventoryState{Software: []models.Software{{Name: dirty, Publisher: dirty}}},
	}); err != nil {
		t.Fatal(err)
	}
	if err := c.PostResult(ctx, "id", models.CommandResult{Status: "succeeded", Output: dirty, Error: dirty}); err != nil {
		t.Fatal(err)
	}

	const clean = `ab` + `cd\te\nf\rg`
	for _, body := range bodies {
		for _, esc := range []string{`\u0000`, `\u0001`, `\u001f`} {
			if strings.Contains(body, esc) {
				t.Errorf("%s left in %s", esc, body)
			}
		}
		if n := strings.Count(body, `"`+clean+`"`); n == 0 {
			t.Errorf("cleaned value missing from %s", body)
		}
	}
	if len(bodies) != 3 {
		t.Fatalf("%d requests", len(bodies))
	}
	if n := strings.Count(bodies[1], `"`+clean+`"`); n != 5 {
		t.Errorf("heartbeat: %d field(s) cleaned, want 5: %s", n, bodies[1])
	}
}

// The strip works escape by escape: a literal backslash followed by the text
// "u0000" — a Windows path, a regex in a log excerpt — is data and stays; and
// characters above the C0 range, escaped by encoding/json too, are kept.
func TestStripControlEscapesKeepsWhatIsNotAControlCharacter(t *testing.T) {
	for in, want := range map[string]string{
		`{"p":"C:\\u0000\\x"}`:             `{"p":"C:\\u0000\\x"}`,
		`{"p":"C:\\\u0000u0000"}`:          `{"p":"C:\\u0000"}`,
		`{"p":"\u003c\u0026\u2028\u007f"}`: `{"p":"\u003c\u0026\u2028\u007f"}`,
		`{"p":"\t\n\r\u0009\u000a\u000D"}`: `{"p":"\t\n\r\u0009\u000a\u000D"}`,
		`{"p":"\u0000\u000B\u001F\u001f"}`: `{"p":""}`,
		`{"p":"\u0020\u0100\u00ff"}`:       `{"p":"\u0020\u0100\u00ff"}`,
		`{"p":"\\"}`:                       `{"p":"\\"}`,
		`{"p":1}`:                          `{"p":1}`,
	} {
		if got := string(stripControlEscapes([]byte(in))); got != want {
			t.Errorf("stripControlEscapes(%s) = %s, want %s", in, got, want)
		}
	}
}

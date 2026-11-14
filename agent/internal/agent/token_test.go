package agent

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/config"
	"tiai/agent/internal/models"
)

func TestAdoptRotatedToken(t *testing.T) {
	failing := func(string) error { return errors.New("disk full") }
	for _, c := range []struct {
		name      string
		offered   string
		save      func(string) error
		want      string
		wantErr   bool
		wantSaved bool
	}{
		{name: "no offer", offered: "", want: "old"},
		{name: "same token", offered: "old", want: "old"},
		{name: "stored", offered: "new", want: "new", wantSaved: true},
		{name: "write fails", offered: "new", save: failing, want: "old", wantErr: true},
	} {
		t.Run(c.name, func(t *testing.T) {
			saved := false
			save := c.save
			if save == nil {
				save = func(string) error { saved = true; return nil }
			}
			got, err := adoptRotatedToken("old", c.offered, save)
			if got != c.want {
				t.Errorf("token = %q, want %q", got, c.want)
			}
			if (err != nil) != c.wantErr {
				t.Errorf("err = %v, wantErr %v", err, c.wantErr)
			}
			if saved != c.wantSaved {
				t.Errorf("saved = %v, want %v — nothing is written unless a new token is adopted",
					saved, c.wantSaved)
			}
		})
	}
}

// authRecorder is a server that answers every heartbeat with an empty
// command list and remembers the bearer token each one carried.
func authRecorder(t *testing.T) (*httptest.Server, func() []string) {
	t.Helper()
	var mu sync.Mutex
	var seen []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		seen = append(seen, r.Header.Get("Authorization"))
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"commands":[]}`))
	}))
	t.Cleanup(srv.Close)
	return srv, func() []string {
		mu.Lock()
		defer mu.Unlock()
		return append([]string(nil), seen...)
	}
}

func rotationAgent(t *testing.T, url string) *Agent {
	t.Helper()
	cfg := config.DefaultConfig()
	cfg.AuthToken = "old"
	return &Agent{
		cfg:     cfg,
		cfgPath: filepath.Join(t.TempDir(), "config.yaml"),
		client:  api.New(url, cfg.AuthToken, 5*time.Second, nil),
	}
}

// stubSave replaces the token write for one test. The real one goes through
// config.SaveToken, whose round trip and failure modes are tested in the
// config package — under pinned entropy, because on Windows the real entropy
// lives in HKLM, which no unit test may touch.
func stubSave(t *testing.T, fn func(dir, token string) error) {
	t.Helper()
	orig := saveToken
	t.Cleanup(func() { saveToken = orig })
	saveToken = fn
}

// The nominal path: the offered token is written to disk first, and only then
// carried — from the very next request on.
func TestRotateTokenStoresThenSwitchesTheNextRequest(t *testing.T) {
	srv, seen := authRecorder(t)
	a := rotationAgent(t, srv.URL)

	var stored, inUseWhileStoring string
	stubSave(t, func(_ string, token string) error {
		stored = token
		inUseWhileStoring = a.client.Token()
		return nil
	})

	a.rotateToken("new")

	if stored != "new" {
		t.Fatalf("stored %q, want the offered token", stored)
	}
	if inUseWhileStoring != "old" {
		t.Errorf("the client carried %q while the token was being written — "+
			"a token must be on disk before the server can see it used", inUseWhileStoring)
	}
	if a.cfg.AuthToken != "new" {
		t.Errorf("cfg.AuthToken = %q, want the new token", a.cfg.AuthToken)
	}
	if _, err := a.client.Heartbeat(context.Background(), models.HeartbeatRequest{}); err != nil {
		t.Fatalf("heartbeat: %v", err)
	}
	if got := seen(); len(got) != 1 || got[0] != "Bearer new" {
		t.Errorf("next request carried %v, want [Bearer new]", got)
	}
}

// A write that fails keeps the agent on its current token: the server still
// honours it until the new one is used, so nothing is lost but this offer.
func TestRotateTokenKeepsTheCurrentTokenWhenTheWriteFails(t *testing.T) {
	srv, seen := authRecorder(t)
	a := rotationAgent(t, srv.URL)
	stubSave(t, func(string, string) error { return errors.New("access denied") })

	a.rotateToken("new")

	if a.cfg.AuthToken != "old" || a.client.Token() != "old" {
		t.Errorf("token switched to cfg=%q client=%q despite the failed write",
			a.cfg.AuthToken, a.client.Token())
	}
	if _, err := a.client.Heartbeat(context.Background(), models.HeartbeatRequest{}); err != nil {
		t.Fatalf("heartbeat: %v", err)
	}
	if got := seen(); len(got) != 1 || got[0] != "Bearer old" {
		t.Errorf("next request carried %v, want [Bearer old]", got)
	}
}

// The heartbeat announces the capability, and a NewToken in its response goes
// through the same path; an absent one leaves everything alone.
func TestHeartbeatWireFormatForRotation(t *testing.T) {
	var gotBody []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"commands":[],"new_token":"rotated"}`))
	}))
	t.Cleanup(srv.Close)

	client := api.New(srv.URL, "old", 5*time.Second, nil)
	resp, err := client.Heartbeat(context.Background(),
		models.HeartbeatRequest{SupportsTokenRotation: true})
	if err != nil {
		t.Fatalf("heartbeat: %v", err)
	}
	if resp.NewToken != "rotated" {
		t.Errorf("NewToken = %q, want it decoded from new_token", resp.NewToken)
	}
	if want := `"supports_token_rotation":true`; !strings.Contains(string(gotBody), want) {
		t.Errorf("request body %s does not announce %s", gotBody, want)
	}
}

// enrollServer counts enrollments and answers them with status, handing out
// token "fresh" on success.
func enrollServer(t *testing.T, status int) (*httptest.Server, func() int) {
	t.Helper()
	var mu sync.Mutex
	n := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agent/enroll" {
			t.Errorf("unexpected request %s", r.URL.Path)
		}
		mu.Lock()
		n++
		mu.Unlock()
		w.WriteHeader(status)
		if status == http.StatusOK {
			_, _ = w.Write([]byte(`{"machine_id":"m1","token":"fresh"}`))
		}
	}))
	t.Cleanup(srv.Close)
	return srv, func() int {
		mu.Lock()
		defer mu.Unlock()
		return n
	}
}

// stubTokenFile replaces the reads and removals of token.dat for one test.
func stubTokenFile(t *testing.T, load func(string) (string, error), clear func(string) error) {
	t.Helper()
	origLoad, origClear := loadToken, clearToken
	t.Cleanup(func() { loadToken, clearToken = origLoad, origClear })
	loadToken, clearToken = load, clear
}

// Audit B32: a token.dat unreadable at start-up, readable at the next attempt,
// is used as it is — no enrollment, which would wait for an approval the
// poste does not need.
func TestEnsureEnrolledReusesATokenThatBecameReadable(t *testing.T) {
	srv, enrolls := enrollServer(t, http.StatusServiceUnavailable)
	a := rotationAgent(t, srv.URL)
	a.cfg.AuthToken = ""
	a.client.SetToken("")
	onDisk := ""
	stubTokenFile(t, func(string) (string, error) { return onDisk, nil }, func(string) error { return nil })
	stubSave(t, func(string, string) error { t.Error("nothing to save"); return nil })

	if err := a.ensureEnrolled(context.Background()); err == nil {
		t.Fatal("enrolled against a server answering 503")
	}
	onDisk = "valid"
	if err := a.ensureEnrolled(context.Background()); err != nil {
		t.Fatal(err)
	}
	if n := enrolls(); n != 1 {
		t.Errorf("%d enrollment(s), want only the first attempt", n)
	}
	if a.cfg.AuthToken != "valid" || a.client.Token() != "valid" {
		t.Errorf("token cfg=%q client=%q, want the one read back", a.cfg.AuthToken, a.client.Token())
	}
}

// The B32 reread must not resurrect the token the server just refused: when
// ClearToken could not delete token.dat, the poste enrolls again and
// overwrites it, instead of heartbeating with a dead token for ever.
func TestEnsureEnrolledDoesNotReuseTheRefusedToken(t *testing.T) {
	srv, enrolls := enrollServer(t, http.StatusOK)
	a := rotationAgent(t, srv.URL)
	a.cfg.AuthToken = "dead"
	a.client.SetToken("dead")
	onDisk := "dead"
	stubTokenFile(t, func(string) (string, error) { return onDisk, nil },
		func(string) error { return errors.New("access denied") })
	stubSave(t, func(_ string, token string) error { onDisk = token; return nil })

	a.dropToken() // what tick does on a 401; the file stays

	for range 2 {
		if err := a.ensureEnrolled(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if n := enrolls(); n != 1 {
		t.Errorf("%d enrollment(s), want one", n)
	}
	if a.cfg.AuthToken != "fresh" || a.client.Token() != "fresh" || onDisk != "fresh" {
		t.Errorf("token cfg=%q client=%q disk=%q, want the enrolled one everywhere",
			a.cfg.AuthToken, a.client.Token(), onDisk)
	}
}

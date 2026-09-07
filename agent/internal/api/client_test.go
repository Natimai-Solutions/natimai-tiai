package api

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
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

	c := New(srv.URL, "token", 100*time.Millisecond)
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

	c := New(srv.URL, "token", 50*time.Millisecond)
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

	c := New(srv.URL, "stale", time.Second)
	_, err := c.Heartbeat(context.Background(), models.HeartbeatRequest{})
	var se *StatusError
	if !errors.As(err, &se) || se.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected a typed 401, got %v", err)
	}
}

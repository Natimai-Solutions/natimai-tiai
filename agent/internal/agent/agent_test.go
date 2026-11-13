package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/collector"
	"tiai/agent/internal/config"
	"tiai/agent/internal/models"
	"tiai/agent/internal/queue"
)

func TestNextBackoffDoublesAndCaps(t *testing.T) {
	base := 60 * time.Second
	max := 300 * time.Second

	got := nextBackoff(base, max)
	if got != 120*time.Second {
		t.Errorf("first backoff = %s, want 2m", got)
	}
	got = nextBackoff(got, max)
	if got != 240*time.Second {
		t.Errorf("second backoff = %s, want 4m", got)
	}
	// 240 * 2 = 480 > 300 → capped.
	got = nextBackoff(got, max)
	if got != max {
		t.Errorf("third backoff = %s, want cap %s", got, max)
	}
	// Stays capped.
	if got = nextBackoff(got, max); got != max {
		t.Errorf("backoff should stay at cap, got %s", got)
	}
}

// The 401 detection is what turns a revocation into a re-enrollment instead of
// an endless 401 loop, so it must see the status through the client's wrapping
// — and must NOT fire on anything else (a 403 is "stay away", not "retry").
func TestIsUnauthorized(t *testing.T) {
	wrapped := fmt.Errorf("POST /api/v1/agent/heartbeat: %w",
		&api.StatusError{StatusCode: 401, Body: "revoked"})
	if !isUnauthorized(wrapped) {
		t.Error("wrapped 401 not detected")
	}
	forbidden := fmt.Errorf("POST /api/v1/agent/enroll: %w",
		&api.StatusError{StatusCode: 403, Body: "machine.enrollment.revoked"})
	if isUnauthorized(forbidden) {
		t.Error("403 must not count as unauthorized")
	}
	if isUnauthorized(fmt.Errorf("dial tcp: connection refused")) {
		t.Error("transport error must not count as unauthorized")
	}
	if isUnauthorized(nil) {
		t.Error("nil error must not count as unauthorized")
	}
}

// The heartbeat carrying an inventory gets a budget of its own: timing it out
// at the poll timeout never loses just that heartbeat, it loses the inventory
// on every retry after it, for as long as the poste keeps trying.
func TestHeavyTimeoutOutlastsThePollTimeout(t *testing.T) {
	a := &Agent{cfg: &config.Config{RequestTimeoutSeconds: config.DefaultRequestTimeout}}
	if got := a.heavyTimeout(); got != heavyHeartbeatTimeout {
		t.Errorf("expected the heavy budget %s, got %s", heavyHeartbeatTimeout, got)
	}
	// A parc that widened the request timeout meant it for this request above
	// all — the wider value wins.
	wide := int(heavyHeartbeatTimeout.Seconds()) * 2
	a = &Agent{cfg: &config.Config{RequestTimeoutSeconds: wide}}
	if got := a.heavyTimeout(); got != time.Duration(wide)*time.Second {
		t.Errorf("a configured timeout above the default must win, got %s", got)
	}
}

// The jittered delay stays inside [step/2, step]: never sooner than half the
// step — a fleet hammering a server that is down is what back-off prevents —
// and never past the step, so the configured cap remains a ceiling.
func TestJitterBackoffStaysWithinHalfToFullStep(t *testing.T) {
	for _, step := range []time.Duration{
		120 * time.Second, 240 * time.Second, 300 * time.Second, 3, 2,
	} {
		for range 500 {
			got := jitterBackoff(step)
			if got < step-step/2 || got > step {
				t.Fatalf("jitterBackoff(%s) = %s, want within [%s, %s]",
					step, got, step-step/2, step)
			}
		}
	}
}

// The point of the jitter is that two agents failing together do not retry
// together: the draws must actually spread, and reach both ends of the range.
func TestJitterBackoffSpreads(t *testing.T) {
	const step = 4 * time.Nanosecond // range {2,3,4}: small enough to hit both ends
	seen := map[time.Duration]bool{}
	for range 1000 {
		seen[jitterBackoff(step)] = true
	}
	for _, want := range []time.Duration{2, 3, 4} {
		if !seen[want] {
			t.Errorf("jitterBackoff(%d) never returned %d (seen %v)", step, want, seen)
		}
	}

	big := map[time.Duration]bool{}
	for range 200 {
		big[jitterBackoff(300*time.Second)] = true
	}
	if len(big) < 2 {
		t.Error("a fixed retry delay would bring the whole parc back at the same second")
	}
}

// Degenerate steps never panic (rand.N rejects a non-positive bound) and are
// returned as they are.
func TestJitterBackoffDegenerateSteps(t *testing.T) {
	for _, step := range []time.Duration{0, 1, -time.Second} {
		if got := jitterBackoff(step); got != step {
			t.Errorf("jitterBackoff(%s) = %s, want it unchanged", step, got)
		}
	}
}

// A full scan is bounded by the configured budget — the sequential worker
// would otherwise be held for good by a scan that never returns — and is
// announced with `running`, since it lasts tens of minutes at the very least.
func TestFullScanRunsUnderTheConfiguredBudget(t *testing.T) {
	var got time.Duration
	orig := runFullScan
	t.Cleanup(func() { runFullScan = orig })
	runFullScan = func(_ context.Context, timeout time.Duration) (string, error) {
		got = timeout
		return "", nil
	}

	for _, c := range []struct {
		name    string
		seconds int
		want    time.Duration
	}{
		{"configured", 12 * 3600, 12 * time.Hour},
		{"default", config.DefaultConfig().DefenderFullScanTimeoutSeconds,
			config.DefaultDefenderFullScanTimeout * time.Second},
		// A Config built by hand, without Load: the bound must not vanish.
		{"unset", 0, config.DefaultDefenderFullScanTimeout * time.Second},
	} {
		t.Run(c.name, func(t *testing.T) {
			got = 0
			a := &Agent{cfg: &config.Config{DefenderFullScanTimeoutSeconds: c.seconds}}
			run, long, ok := a.resolve(models.Command{ID: "c1", Type: "full_scan"})
			if !ok {
				t.Fatal("full_scan must be a known command")
			}
			if !long {
				t.Error("full_scan must post an intermediate `running`")
			}
			if _, err := run(context.Background()); err != nil {
				t.Fatalf("run: %v", err)
			}
			if got != c.want {
				t.Errorf("full scan budget = %s, want %s", got, c.want)
			}
		})
	}
}

// The quick scan and the signature update stay short commands: a `running`
// for something that ends in minutes is noise on the console.
func TestShortDefenderCommandsAreNotAnnounced(t *testing.T) {
	a := &Agent{cfg: config.DefaultConfig()}
	for _, typ := range []string{"quick_scan", "update_signatures"} {
		_, long, ok := a.resolve(models.Command{Type: typ})
		if !ok {
			t.Errorf("%s must be a known command", typ)
		}
		if long {
			t.Errorf("%s must not post `running`", typ)
		}
	}
}

// resolve keeps what execute used to decide inline: the maintenance catalogue
// still carries its own `long` flag, and an unknown type is refused rather
// than run.
func TestResolveMaintenanceAndUnknownTypes(t *testing.T) {
	a := &Agent{cfg: config.DefaultConfig()}
	info, found := collector.LookupMaintenance("sfc_scan")
	if !found {
		t.Fatal("sfc_scan must be in the maintenance catalogue")
	}
	if _, long, ok := a.resolve(models.Command{Type: "sfc_scan"}); !ok || long != info.Long {
		t.Errorf("sfc_scan: ok=%v long=%v, want ok and long=%v", ok, long, info.Long)
	}
	if _, _, ok := a.resolve(models.Command{Type: "format_c"}); ok {
		t.Error("a type outside every catalogue must not resolve")
	}
}

// Command ids as the server writes them: UUIDs, lowercase.
const (
	c1 = "3f1c2a4e-9b7d-4c1e-8a2f-0d5e6b7c8a90"
	c2 = "3f1c2a4e-9b7d-4c1e-8a2f-0d5e6b7c8a91"
	c3 = "3f1c2a4e-9b7d-4c1e-8a2f-0d5e6b7c8a92"
)

// The server hands a command out once: one the agent cannot take must come
// back as `failed`, through the local queue, never be dropped (audit B15).
func TestAFullBacklogAnswersFailed(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	a := &Agent{queue: q, commands: make(chan models.Command, 1), running: map[string]struct{}{}}
	a.accept(models.Command{ID: c1, Type: "quick_scan"})
	a.accept(models.Command{ID: c2, Type: "quick_scan"})

	item, _, err := q.Peek()
	if err != nil || item == nil {
		t.Fatalf("nothing queued: %v", err)
	}
	if item.CommandID != c2 || item.Result.Status != "failed" || !strings.Contains(item.Result.Error, "pleine") {
		t.Errorf("queued %+v", item)
	}
	// c2 is free to come again; c1 waits for the worker.
	if _, held := a.running[c2]; held {
		t.Error("c2 still held")
	}
}

// On shutdown, what waits in the backlog is answered `failed` (audit B16).
func TestStoppingAnswersTheBacklog(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	a := &Agent{queue: q, commands: make(chan models.Command, 4), running: map[string]struct{}{}}
	a.accept(models.Command{ID: c1, Type: "wu_install"})
	a.accept(models.Command{ID: c2, Type: "sfc_scan"})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	a.wg.Add(1)
	a.worker(ctx)

	var ids []string
	for {
		item, path, err := q.Peek()
		if err != nil {
			t.Fatal(err)
		}
		if item == nil {
			break
		}
		if item.Result.Status != "failed" || !strings.Contains(item.Result.Error, "arrêt de l'agent") {
			t.Errorf("queued %+v", item)
		}
		ids = append(ids, item.CommandID)
		if err := q.Remove(path); err != nil {
			t.Fatal(err)
		}
	}
	if len(ids) != 2 {
		t.Errorf("answered %v, want c1 and c2", ids)
	}
	if len(a.running) != 0 {
		t.Errorf("still held: %v", a.running)
	}
}

// Audit B33: waiting for approval, or revoked, is not retried every 5 min.
func TestAnEnrollmentOnHoldIsRecognised(t *testing.T) {
	held := fmt.Errorf("POST /api/v1/agent/enroll: %w", &api.StatusError{
		StatusCode: 403, Body: `{"error":{"code":"machine.enrollment.approval_required"}}`})
	if !enrollmentOnHold(held) {
		t.Error("approval_required not recognised")
	}
	revoked := &api.StatusError{StatusCode: 403, Body: `{"error":{"code":"machine.enrollment.revoked"}}`}
	if !enrollmentOnHold(revoked) {
		t.Error("revoked not recognised")
	}
	if enrollmentOnHold(&api.StatusError{StatusCode: 403, Body: `{"error":{"code":"auth.enrollment_secret.invalid"}}`}) {
		t.Error("a wrong secret is not on hold")
	}
	if enrollmentOnHold(errors.New("network down")) {
		t.Error("a network error is not on hold")
	}
}

// drain empties a queue, returning its items oldest first.
func drain(t *testing.T, q *queue.Queue) []queue.Item {
	t.Helper()
	var out []queue.Item
	for {
		item, path, err := q.Peek()
		if err != nil {
			t.Fatal(err)
		}
		if item == nil {
			return out
		}
		out = append(out, *item)
		if err := q.Remove(path); err != nil {
			t.Fatal(err)
		}
	}
}

// A command id names a file of the local queue and a path of the API: one
// that is not a UUID is refused on arrival, never handed to the worker nor
// queued (same class as audit S01).
func TestAcceptRefusesACommandIDThatIsNotAUUID(t *testing.T) {
	root := t.TempDir()
	q, err := queue.New(filepath.Join(root, "a", "b", "queue"), 100)
	if err != nil {
		t.Fatal(err)
	}
	// A backlog of one, already full: the path that writes to the queue.
	a := &Agent{queue: q, commands: make(chan models.Command, 1), running: map[string]struct{}{}}
	a.accept(models.Command{ID: c1, Type: "quick_scan"})
	for _, id := range []string{"../../../escaped", `..\..\escaped`, "c1", "", c2 + "/x",
		"3f1c2a4e9b7d4c1e8a2f0d5e6b7c8a90"} {
		a.accept(models.Command{ID: id, Type: "quick_scan"})
	}
	if len(a.commands) != 1 || len(a.running) != 1 {
		t.Errorf("handed on: %d in the backlog, %v held", len(a.commands), a.running)
	}
	if items := drain(t, q); len(items) != 0 {
		t.Errorf("queued %+v", items)
	}
	_ = filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err == nil && !info.IsDir() {
			t.Errorf("file written: %s", path)
		}
		return nil
	})
	// Either case of a UUID is a command id.
	a.commands = make(chan models.Command, 2)
	a.accept(models.Command{ID: strings.ToUpper(c3), Type: "quick_scan"})
	if len(a.commands) != 1 {
		t.Error("an upper-case UUID was refused")
	}
}

// Audit B16, the residual race: the service stops between the heartbeat's
// answer and the accept loop. The worker has drained its backlog and left; a
// command accepted then must still get its `failed`, not sit in the channel.
func TestACommandAcceptedAfterTheWorkerStoppedIsAnswered(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	a := &Agent{queue: q, commands: make(chan models.Command, 4), running: map[string]struct{}{}}
	ctx, cancel := context.WithCancel(context.Background())
	a.wg.Add(1)
	go a.worker(ctx)
	cancel()
	a.wg.Wait() // the worker has stopped and drained an empty backlog

	a.accept(models.Command{ID: c1, Type: "quick_scan"})

	if len(a.commands) != 0 {
		t.Error("the command sits in a channel nobody reads")
	}
	items := drain(t, q)
	if len(items) != 1 || items[0].CommandID != c1 || items[0].Result.Status != "failed" ||
		!strings.Contains(items[0].Result.Error, "arrêt de l'agent") {
		t.Errorf("queued %+v, want one failed verdict for %s", items, c1)
	}
	if len(a.running) != 0 {
		t.Errorf("still held: %v", a.running)
	}
}

// resultRecorder is a server answering every verdict with the status status
// returns for its command id, and recording those it took.
func resultRecorder(t *testing.T, status func(id string) int) (*httptest.Server, func() map[string]models.CommandResult) {
	t.Helper()
	var mu sync.Mutex
	got := map[string]models.CommandResult{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/api/v1/agent/commands/"), "/result")
		code := status(id)
		if code < 300 {
			var res models.CommandResult
			if err := json.NewDecoder(r.Body).Decode(&res); err != nil {
				t.Errorf("decode: %v", err)
			}
			mu.Lock()
			got[id] = res
			mu.Unlock()
		}
		w.WriteHeader(code)
	}))
	t.Cleanup(srv.Close)
	return srv, func() map[string]models.CommandResult {
		mu.Lock()
		defer mu.Unlock()
		return maps.Clone(got)
	}
}

// Audit B34: a type this agent does not know is answered `failed`, naming the
// agent version so the console says what to do — posted at once, and queued
// when the server cannot take it.
func TestAnUnknownTypeIsAnsweredFailedNamingTheVersion(t *testing.T) {
	for _, up := range []bool{true, false} {
		q, err := queue.New(t.TempDir(), 100)
		if err != nil {
			t.Fatal(err)
		}
		srv, got := resultRecorder(t, func(string) int {
			if up {
				return http.StatusOK
			}
			return http.StatusServiceUnavailable
		})
		a := &Agent{cfg: config.DefaultConfig(), queue: q, client: api.New(srv.URL, "tok", 5*time.Second, nil)}
		a.execute(context.Background(), models.Command{ID: c1, Type: "format_c"})

		var res models.CommandResult
		if up {
			res = got()[c1]
			if items := drain(t, q); len(items) != 0 {
				t.Errorf("delivered and queued: %+v", items)
			}
		} else {
			items := drain(t, q)
			if len(items) != 1 || items[0].CommandID != c1 {
				t.Fatalf("server down: queued %+v", items)
			}
			res = items[0].Result
		}
		if res.Status != "failed" || !strings.Contains(res.Error, `"format_c"`) ||
			!strings.Contains(res.Error, "l'agent "+Version) {
			t.Errorf("server up=%v: verdict %+v", up, res)
		}
	}
}

// A verdict the server refuses for good (a 4xx other than 401, 403, 408, 429)
// is dropped and the replay goes on; anything that may pass later stops it
// with the queue intact.
func TestFlushQueueSkipsAVerdictRefusedForGood(t *testing.T) {
	for _, c := range []struct {
		status  int
		dropped bool
	}{
		{http.StatusBadRequest, true},
		{http.StatusNotFound, false},
		{http.StatusConflict, true},
		{http.StatusUnprocessableEntity, true},
		{http.StatusUnauthorized, false},
		{http.StatusForbidden, false},
		{http.StatusRequestTimeout, false},
		{http.StatusTooManyRequests, false},
		{http.StatusInternalServerError, false},
		{http.StatusServiceUnavailable, false},
	} {
		t.Run(http.StatusText(c.status), func(t *testing.T) {
			q, err := queue.New(t.TempDir(), 100)
			if err != nil {
				t.Fatal(err)
			}
			for _, id := range []string{c1, c2} {
				if err := q.Enqueue(queue.Item{CommandID: id, Result: models.CommandResult{Status: "failed"}}); err != nil {
					t.Fatal(err)
				}
			}
			srv, got := resultRecorder(t, func(id string) int {
				if id == c1 {
					return c.status
				}
				return http.StatusOK
			})
			a := &Agent{queue: q, client: api.New(srv.URL, "tok", 5*time.Second, nil)}
			a.flushQueue(context.Background())

			_, delivered := got()[c2]
			if c.dropped {
				if !delivered || q.Depth() != 0 {
					t.Errorf("c2 delivered=%v, depth %d: the refused head blocks the queue", delivered, q.Depth())
				}
			} else if delivered || q.Depth() != 2 {
				t.Errorf("c2 delivered=%v, depth %d: a verdict that may pass later was dropped", delivered, q.Depth())
			}
		})
	}
	// A network error stops the replay too.
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	_ = q.Enqueue(queue.Item{CommandID: c1, Result: models.CommandResult{Status: "failed"}})
	srv := httptest.NewServer(http.NotFoundHandler())
	srv.Close()
	a := &Agent{queue: q, client: api.New(srv.URL, "tok", 5*time.Second, nil)}
	a.flushQueue(context.Background())
	if q.Depth() != 1 {
		t.Error("a verdict was dropped on a network error")
	}
}

package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/collector"
	"tiai/agent/internal/config"
	"tiai/agent/internal/logging"
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

var (
	errHeld = fmt.Errorf("POST /api/v1/agent/enroll: %w", &api.StatusError{
		StatusCode: 403, Body: `{"error":{"code":"machine.enrollment.approval_required"}}`})
	errRevoked = fmt.Errorf("POST /api/v1/agent/enroll: %w", &api.StatusError{
		StatusCode: 403, Body: `{"error":{"code":"machine.enrollment.revoked"}}`})
)

// An enrollment on hold is retried one minute later, then twice as long each
// time up to a quarter of an hour — an approval given in the console must
// bring the poste back within minutes, not half an hour. A success ends the
// hold, and nothing else does: the next hold starts over from the short step,
// while a server that goes down in the middle of one leaves it where it was.
func TestEnrollmentHoldStepsEscalateAndEndOnASuccess(t *testing.T) {
	p := newRetryPlan(time.Minute, 5*time.Minute)
	steps := func(err error, n int, wantHeld bool) []time.Duration {
		t.Helper()
		var out []time.Duration
		for range n {
			step, held := p.next(err)
			if held != wantHeld {
				t.Fatalf("next(%v) held = %v", err, held)
			}
			out = append(out, step)
		}
		return out
	}
	m := time.Minute
	want := []time.Duration{m, 2 * m, 4 * m, 8 * m, 15 * m, 15 * m}
	if got := steps(errHeld, 6, true); !slices.Equal(got, want) {
		t.Errorf("approval hold steps = %v, want %v", got, want)
	}
	// Approved: the plain interval, and the hold is forgotten.
	if got := steps(nil, 1, false); got[0] != time.Minute {
		t.Errorf("after the approval: %v", got)
	}
	if got := steps(errRevoked, 3, true); !slices.Equal(got, want[:3]) {
		t.Errorf("revoked steps after a success = %v, want %v", got, want[:3])
	}
	// A server that goes down ends nothing: the larger of the hold step and
	// the ordinary back-off (2, 4 then 5 minutes), still on hold, and the
	// hold goes on from where it was once the server answers again.
	down := errors.New("dial tcp: connection refused")
	if got := steps(down, 3, true); !slices.Equal(got, []time.Duration{4 * m, 4 * m, 5 * m}) {
		t.Errorf("steps while the server is down = %v", got)
	}
	if got := steps(errHeld, 1, true); got[0] != 8*m {
		t.Errorf("the hold resumed at %v", got)
	}
	// Ordinary failures keep their own back-off, untouched by a hold that a
	// success ended.
	steps(nil, 1, false)
	if got := steps(errors.New("status 502"), 4, false); !slices.Equal(got, []time.Duration{2 * m, 4 * m, 5 * m, 5 * m}) {
		t.Errorf("ordinary back-off = %v", got)
	}
}

// What is slept on a hold is the step with jitter — one enrollment attempt
// per step, never later than the step — with one log line per step that says
// why, and the watchdog is told when the next poll is due.
func TestScheduleNextLogsEachHoldStep(t *testing.T) {
	buf := captureLog(t)
	a := &Agent{cfg: &config.Config{}}
	p := newRetryPlan(time.Minute, 5*time.Minute)
	now := time.Unix(1_800_000_000, 0)
	for i, step := range []time.Duration{time.Minute, 2 * time.Minute, 4 * time.Minute} {
		err := errHeld
		if i == 2 {
			err = errRevoked
		}
		sleep := a.scheduleNext(p, err, now)
		if sleep < step/2 || sleep > step {
			t.Errorf("hold step %s slept %s", step, sleep)
		}
		if got := a.nextPollAt.Load(); got != now.Add(sleep).Unix() {
			t.Errorf("next poll due at %d, want %d", got, now.Add(sleep).Unix())
		}
	}
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 ||
		!strings.Contains(lines[0], "waiting for an administrator's approval, next enrollment attempt in") ||
		!strings.Contains(lines[2], "revoked") || strings.Contains(buf.String(), "tick failed") {
		t.Errorf("logged:\n%s", buf.String())
	}
}

// Waiting on purpose — an enrollment hold of a quarter of an hour — is not a
// poll that hangs: the watchdog stays silent, and so no "polling resumed"
// follows. A poll that does hang once it was due is still reported.
func TestWatchdogDoesNotReportADeliberateWait(t *testing.T) {
	buf := captureLog(t)
	a := &Agent{}
	start := time.Unix(1_800_000_000, 0)
	a.lastPollDone.Store(start.Unix())
	a.phase("idle")
	// The loop sleeps a 15-minute hold step after that poll.
	a.nextPollAt.Store(start.Add(15 * time.Minute).Unix())
	for m := 1; m <= 15; m++ {
		a.checkStall(start.Add(time.Duration(m)*time.Minute), start.Unix())
	}
	a.pollFinished()
	if out := buf.String(); out != "" {
		t.Errorf("a deliberate wait was reported:\n%s", out)
	}

	// The next poll starts when due and hangs: reported ten minutes after it
	// was due, not before.
	a.lastPollDone.Store(start.Unix())
	a.phase("defender state")
	for m := 16; m <= 24; m++ {
		a.checkStall(start.Add(time.Duration(m)*time.Minute), start.Unix())
	}
	if out := buf.String(); out != "" {
		t.Errorf("reported before the poll was ten minutes late:\n%s", out)
	}
	a.checkStall(start.Add(25*time.Minute), start.Unix())
	if out := buf.String(); !strings.Contains(out, `stuck in "defender state"`) {
		t.Errorf("a hung poll was not reported:\n%s", out)
	}
}

// Hours that a clock set forward, or a machine asleep, put between two looks
// of the watchdog are not hours a poll spent hanging: nothing is reported for
// them — at the first look of a service started before the clock was
// corrected, or at any later one — and a poll that does hang from there is
// reported ten minutes after the look that noticed, like any other.
func TestWatchdogDoesNotReportAClockSetForward(t *testing.T) {
	for name, polled := range map[string]bool{"before the first poll": false, "between two polls": true} {
		t.Run(name, func(t *testing.T) {
			buf := captureLog(t)
			a := &Agent{}
			start := time.Unix(1_800_000_000, 0)
			a.phase("enroll")
			at := start
			look := func(d time.Duration) string {
				at = at.Add(d)
				a.checkStall(at, start.Unix())
				return buf.String()
			}
			if polled {
				a.lastPollDone.Store(start.Unix())
				a.phase("idle")
				a.nextPollAt.Store(start.Add(time.Minute).Unix())
				look(time.Minute)
			}
			// Eight hours appear between two looks a minute apart.
			if out := look(8*time.Hour + time.Minute); out != "" {
				t.Fatalf("a clock set forward was reported as a stuck poll:\n%s", out)
			}
			for range 9 {
				if out := look(time.Minute); out != "" {
					t.Fatalf("reported %s after the jump:\n%s", at.Sub(start)-8*time.Hour, out)
				}
			}
			if out := look(time.Minute); !strings.Contains(out, "no poll has completed for 10m0s") {
				t.Errorf("a poll hung since the jump was not reported ten minutes later:\n%s", out)
			}
		})
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

// A verdict the server keeps answering 5xx to stays at the head of the queue —
// and says so, once per failed replay, naming its command: the queue that
// held back every verdict behind it used to leave no trace in the log.
func TestFlushQueueLogsEachFailedReplay(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{c1, c2} {
		if err := q.Enqueue(queue.Item{CommandID: id, Result: models.CommandResult{Status: "failed"}}); err != nil {
			t.Fatal(err)
		}
	}
	srv, _ := resultRecorder(t, func(string) int { return http.StatusInternalServerError })
	a := &Agent{queue: q, client: api.New(srv.URL, "tok", 5*time.Second, nil)}
	buf := captureLog(t)
	for range 3 {
		a.flushQueue(context.Background())
	}
	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 3 {
		t.Fatalf("want one line per failed replay, got:\n%s", buf.String())
	}
	for _, line := range lines {
		if !strings.Contains(line, "command "+c1+" not delivered") || !strings.Contains(line, "status 500") {
			t.Errorf("line = %q", line)
		}
	}
	if q.Depth() != 2 {
		t.Errorf("depth %d", q.Depth())
	}
}

// A NUL in a command's output — what a tool writing UTF-16 into a pipe leaves
// — is refused by the server's database (500), and the verdict then held the
// queue for good. The agent strips it, whether the verdict is posted at once
// or replayed from a queue an older agent filled.
func TestAVerdictWithANulIsDelivered(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	dirty := models.CommandResult{Status: "failed", Output: "S\x00F\x00C\x00\tok\r\n", Error: "boom\x00\x1b[31m"}
	if err := q.Enqueue(queue.Item{CommandID: c1, Result: dirty}); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	got := map[string]models.CommandResult{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		// What PostgreSQL does with a NUL in a text column.
		if bytes.Contains(body, []byte(`\u0000`)) {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		var res models.CommandResult
		_ = json.Unmarshal(body, &res)
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/api/v1/agent/commands/"), "/result")
		mu.Lock()
		got[id] = res
		mu.Unlock()
	}))
	t.Cleanup(srv.Close)
	a := &Agent{queue: q, client: api.New(srv.URL, "tok", 5*time.Second, nil)}
	a.flushQueue(context.Background())
	if err := a.client.PostResult(context.Background(), c2, dirty); err != nil {
		t.Fatal(err)
	}
	if q.Depth() != 0 {
		t.Fatal("the verdict with a NUL is still queued")
	}
	want := models.CommandResult{Status: "failed", Output: "SFC\tok\r\n", Error: "boom[31m"}
	for _, id := range []string{c1, c2} {
		if got[id] != want {
			t.Errorf("%s: server got %+v, want %+v", id, got[id], want)
		}
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

// A verdict the server refuses for good is dropped and the replay goes on:
// that is a 422, the one refusal its result route writes (besides the 401 of
// a token). Every other status stops the replay with the queue intact — it
// may pass later, or it was answered by something on the way (a proxy's 407,
// a portal's 400, a WAF's 405…) that answers every verdict alike, and would
// otherwise empty the whole queue in one poll.
func TestFlushQueueSkipsAVerdictRefusedForGood(t *testing.T) {
	for _, c := range []struct {
		status  int
		dropped bool
	}{
		{http.StatusUnprocessableEntity, true},
		{http.StatusBadRequest, false},
		{http.StatusUnauthorized, false},
		{http.StatusPaymentRequired, false},
		{http.StatusForbidden, false},
		{http.StatusNotFound, false},
		{http.StatusMethodNotAllowed, false},
		{http.StatusNotAcceptable, false},
		{http.StatusProxyAuthRequired, false},
		{http.StatusRequestTimeout, false},
		{http.StatusConflict, false},
		{http.StatusGone, false},
		{http.StatusRequestEntityTooLarge, false},
		{http.StatusUnsupportedMediaType, false},
		{http.StatusTooManyRequests, false},
		{http.StatusUnavailableForLegalReasons, false},
		{http.StatusInternalServerError, false},
		{http.StatusBadGateway, false},
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

// A middlebox answering every request alike — here a forward proxy's 407 —
// must cost the queue nothing: before, one poll dropped every verdict in it.
func TestFlushQueueKeepsEverythingBehindABlanketRefusal(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{c1, c2, c3} {
		if err := q.Enqueue(queue.Item{CommandID: id, Result: models.CommandResult{Status: "succeeded"}}); err != nil {
			t.Fatal(err)
		}
	}
	var blanket atomic.Int64
	blanket.Store(http.StatusProxyAuthRequired)
	srv, got := resultRecorder(t, func(string) int { return int(blanket.Load()) })
	a := &Agent{queue: q, client: api.New(srv.URL, "tok", 5*time.Second, nil)}
	a.flushQueue(context.Background())
	if q.Depth() != 3 {
		t.Fatalf("depth %d after a poll through a proxy answering 407, want the 3 verdicts kept", q.Depth())
	}
	// The proxy lets go: everything is delivered, in order, nothing was lost.
	blanket.Store(http.StatusOK)
	a.flushQueue(context.Background())
	if q.Depth() != 0 || len(got()) != 3 {
		t.Errorf("depth %d, delivered %v", q.Depth(), got())
	}
}

// Audit B16, what keeps it closed: accept sends to the worker under the lock
// the worker takes to stop. The seam stands at the send itself; from there the
// test stops the worker. If the lock is held, the worker cannot get past
// stop() before the command is in the channel, and drains it. If it is not —
// the send moved back out of the lock — the worker is left to stop and drain
// an empty backlog first, exactly the interleaving that used to leave a
// command in a channel nobody reads, with no verdict.
func TestAcceptSendsUnderTheLockTheWorkerStopsWith(t *testing.T) {
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	a := &Agent{queue: q, commands: make(chan models.Command, 4), running: map[string]struct{}{}}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	a.beforeEnqueue = func() {
		// accept has seen `stopped` false and is about to send.
		locked := !a.mu.TryLock()
		if !locked {
			a.mu.Unlock()
		}
		a.wg.Add(1)
		go a.worker(ctx) // the service stops: the worker closes and drains
		if !locked {
			a.wg.Wait() // nothing holds it back: it is gone before the send
		}
	}

	a.accept(models.Command{ID: c1, Type: "quick_scan"})
	a.wg.Wait()

	if n := len(a.commands); n != 0 {
		t.Errorf("%d command(s) sit in a channel nobody reads", n)
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

// captureLog collects what the agent logs during a test, without timestamps:
// one logged line is then one line of the result, starting with its prefix.
func captureLog(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	out, flags := log.Writer(), log.Flags()
	t.Cleanup(func() {
		log.SetOutput(out)
		log.SetFlags(flags)
		logging.SetLevel("info")
	})
	log.SetOutput(&buf)
	log.SetFlags(0)
	logging.SetLevel("debug")
	return &buf
}

// A command type is the server's string, and it reaches the log before
// anything has checked it: on every path that declines a command. Written
// with %q, a line break in it stays inside the quotes — it cannot start a
// line of its own that reads as the agent's.
func TestACommandTypeCannotForgeALogLine(t *testing.T) {
	const forged = "agent: first heartbeat accepted by the server"
	evil := "quick_scan\n" + forged + "\r\n" + forged
	newAgent := func(backlog int) *Agent {
		q, err := queue.New(t.TempDir(), 100)
		if err != nil {
			t.Fatal(err)
		}
		return &Agent{cfg: config.DefaultConfig(), queue: q,
			commands: make(chan models.Command, backlog), running: map[string]struct{}{}}
	}
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()

	for name, run := range map[string]func(){
		"already in flight": func() {
			a := newAgent(4)
			a.accept(models.Command{ID: c1, Type: "quick_scan"})
			a.accept(models.Command{ID: c1, Type: evil})
		},
		"accepted after the worker stopped": func() {
			a := newAgent(4)
			a.stopped = true
			a.accept(models.Command{ID: c1, Type: evil})
		},
		"backlog full": func() {
			a := newAgent(1)
			a.accept(models.Command{ID: c1, Type: "quick_scan"})
			a.accept(models.Command{ID: c2, Type: evil})
		},
		"abandoned on stop": func() {
			a := newAgent(4)
			a.accept(models.Command{ID: c1, Type: evil})
			a.wg.Add(1)
			a.worker(cancelled)
		},
		"unknown type refused": func() {
			a := newAgent(4)
			srv, _ := resultRecorder(t, func(string) int { return http.StatusOK })
			a.client = api.New(srv.URL, "tok", 5*time.Second, nil)
			a.execute(context.Background(), models.Command{ID: c1, Type: evil})
		},
	} {
		t.Run(name, func(t *testing.T) {
			buf := captureLog(t)
			run()
			out := buf.String()
			if !strings.Contains(out, "quick_scan") {
				t.Fatalf("the path logged nothing about the command:\n%s", out)
			}
			for _, line := range strings.FieldsFunc(out, func(r rune) bool { return r == '\n' || r == '\r' }) {
				if strings.HasPrefix(line, forged) {
					t.Errorf("a command type wrote a log line of its own:\n%s", out)
				}
			}
		})
	}
}

// The same holds for the machine id an enrollment answers with: the server's
// string, logged once, quoted.
func TestAnEnrolledMachineIDCannotForgeALogLine(t *testing.T) {
	const forged = "agent: token renewed by the server, stored and in use"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(models.EnrollResponse{MachineID: "m1\n" + forged, Token: "tok"})
	}))
	t.Cleanup(srv.Close)
	stubSave(t, func(string, string) error { return nil })
	a := &Agent{
		cfg:     config.DefaultConfig(),
		cfgPath: filepath.Join(t.TempDir(), "config.yaml"),
		client:  api.New(srv.URL, "", 5*time.Second, nil),
	}
	buf := captureLog(t)
	if err := a.ensureEnrolled(context.Background()); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	if !strings.Contains(out, "enrolled as machine") {
		t.Fatalf("enrollment not logged:\n%s", out)
	}
	for _, line := range strings.Split(out, "\n") {
		if strings.HasPrefix(line, forged) {
			t.Errorf("a machine id wrote a log line of its own:\n%s", out)
		}
	}
}

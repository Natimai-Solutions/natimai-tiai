package agent

import (
	"container/heap"
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"math/rand/v2"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/config"
)

// errLimited is the enrollment limiter's refusal, as the server sends it: 30
// enrollments per five minutes per source address, and Retry-After: 300.
var errLimited = fmt.Errorf("POST /api/v1/agent/enroll: %w", &api.StatusError{
	StatusCode: 429, Body: `{"error":{"code":"rate_limited"}}`, RetryAfter: 300 * time.Second})

// The regression of the short hold steps: a 429 between two hold refusals —
// a room of held postes behind one address fills the enrollment limiter —
// sent the hold back to its first step, so the next refusal was retried
// within the minute and the limiter never emptied. An answer that is not a
// success ends nothing: whatever the server alternates, the step never comes
// back down.
func TestAHoldSurvivesAnAnswerThatIsNotASuccess(t *testing.T) {
	down := errors.New("dial tcp: connection refused")
	for name, other := range map[string]error{"429": errLimited, "network": down, "502": errors.New("status 502")} {
		t.Run(name, func(t *testing.T) {
			p := newRetryPlan(time.Minute, 5*time.Minute)
			var last time.Duration
			for i := range 40 {
				err := errHeld
				if i%2 == 1 {
					err = other
				}
				step, held := p.next(err)
				if !held {
					t.Fatalf("answer %d (%v): the hold ended without a success", i, err)
				}
				if step < last {
					t.Fatalf("answer %d (%v): step back down from %s to %s", i, err, last, step)
				}
				last = step
			}
			if last < enrollmentHoldMax {
				t.Errorf("after 20 refusals the step is %s, below the ceiling", last)
			}
		})
	}
}

// A 429 while on hold is one more refused enrollment: it doubles the step
// like the hold refusal does, up to the same quarter of an hour. Received at
// that ceiling, it says the address asks for more than the limiter gives —
// the poste goes to half an hour and stays there, hold refusals or not,
// until it enrolls. A poste that was never held is not on hold for a 429.
func TestA429RaisesTheHoldStep(t *testing.T) {
	m := time.Minute
	p := newRetryPlan(m, 5*m)
	var got []time.Duration
	for _, err := range []error{errHeld, errLimited, errLimited, errHeld, errHeld, errHeld, errLimited, errHeld, errLimited, errHeld} {
		step, held := p.next(err)
		if !held {
			t.Fatalf("next(%v): not on hold", err)
		}
		got = append(got, step)
	}
	// The last two 429 also count for the ordinary back-off, which is below
	// the hold step throughout (5 minutes at most).
	want := []time.Duration{m, 2 * m, 4 * m, 8 * m, 15 * m, 15 * m, 30 * m, 30 * m, 30 * m, 30 * m}
	if !slices.Equal(got, want) {
		t.Errorf("steps = %v, want %v", got, want)
	}
	// Enrolled: the next hold is an ordinary one again.
	p.next(nil)
	if step, _ := p.next(errHeld); step != m {
		t.Errorf("after a success the hold starts at %s", step)
	}

	// Never held: the ordinary back-off, and no hold to speak of.
	p = newRetryPlan(m, 5*m)
	got = nil
	for range 4 {
		step, held := p.next(errLimited)
		if held {
			t.Fatal("a 429 alone put the poste on hold")
		}
		got = append(got, step)
	}
	if want := []time.Duration{2 * m, 4 * m, 5 * m, 5 * m}; !slices.Equal(got, want) {
		t.Errorf("steps of a poste never held = %v, want %v", got, want)
	}
	if step, _ := p.next(errHeld); step != m {
		t.Errorf("its first hold starts at %s", step)
	}

	// A back-off configured above the hold steps wins: the larger of the two.
	p = newRetryPlan(m, time.Hour)
	p.next(errHeld)
	for range 5 {
		p.next(errors.New("status 502"))
	}
	if step, held := p.next(errors.New("status 502")); step != time.Hour || !held {
		t.Errorf("step = %s, held = %v; want the configured back-off of 1h, on hold", step, held)
	}
}

// fixJitter replaces the jitter's draw for one test: draw receives the bound
// n of a draw in [0, n).
func fixJitter(t *testing.T, draw func(n time.Duration) time.Duration) {
	t.Helper()
	old := jitterDraw
	t.Cleanup(func() { jitterDraw = old })
	jitterDraw = draw
}

// quietLog drops what the agent logs during a test that schedules thousands
// of retries.
func quietLog(t *testing.T) {
	t.Helper()
	out := log.Writer()
	t.Cleanup(func() { log.SetOutput(out) })
	log.SetOutput(io.Discard)
}

// seedJitter makes the jitter's draws, for one test, those of a generator
// seeded with seed — the same at every run — and returns it for the test's
// own draws.
func seedJitter(t *testing.T, seed uint64) *rand.Rand {
	t.Helper()
	rng := rand.New(rand.NewPCG(seed, 2026))
	fixJitter(t, func(n time.Duration) time.Duration { return time.Duration(rng.Int64N(int64(n))) })
	return rng
}

// A hold step is slept with jitter, like any other back-off step: anywhere
// from half the step to the step itself, both ends included, and not always
// the same. Without it the postes of a room held together — a site whose
// machines were re-imaged — would retry together, for as long as they wait.
func TestAHoldStepIsJittered(t *testing.T) {
	a := &Agent{cfg: &config.Config{}}
	quietLog(t)
	now := time.Unix(1_800_000_000, 0)
	atCeiling := func() *retryPlan {
		p := newRetryPlan(time.Minute, 5*time.Minute)
		for range 4 {
			p.next(errHeld)
		}
		return p
	}

	fixJitter(t, func(time.Duration) time.Duration { return 0 })
	if got := a.scheduleNext(atCeiling(), errHeld, now); got != enrollmentHoldMax/2 {
		t.Errorf("lowest draw: slept %s, want half the step (%s)", got, enrollmentHoldMax/2)
	}
	fixJitter(t, func(n time.Duration) time.Duration { return n - 1 })
	if got := a.scheduleNext(atCeiling(), errHeld, now); got != enrollmentHoldMax {
		t.Errorf("highest draw: slept %s, want the step (%s)", got, enrollmentHoldMax)
	}

	// And with the real draw: spread, inside the range.
	jitterDraw = rand.N[time.Duration]
	seen := map[time.Duration]bool{}
	for range 200 {
		got := a.scheduleNext(atCeiling(), errRevoked, now)
		if got < enrollmentHoldMax/2 || got > enrollmentHoldMax {
			t.Fatalf("slept %s on a %s hold step", got, enrollmentHoldMax)
		}
		seen[got] = true
	}
	if len(seen) < 100 {
		t.Errorf("200 hold steps slept only %d different waits", len(seen))
	}
}

// A 429 names its own wait (Retry-After, the length of the limiter's window):
// the next attempt is never sooner, whatever the back-off step drew, and never
// later than a hold step lasts, whatever the header says. No other answer's
// Retry-After is read.
func TestScheduleNextHonoursRetryAfterOnA429(t *testing.T) {
	buf := captureLog(t)
	a := &Agent{cfg: &config.Config{}}
	now := time.Unix(1_800_000_000, 0)
	limited := func(after time.Duration) error {
		return fmt.Errorf("POST /api/v1/agent/enroll: %w", &api.StatusError{StatusCode: 429, RetryAfter: after})
	}
	m := time.Minute

	// A poste never held, first failure: the step is 2 minutes, slept 1 to 2;
	// the server asked for 5.
	if got := a.scheduleNext(newRetryPlan(m, 5*m), limited(5*m), now); got != 5*m {
		t.Errorf("slept %s after a 429 asking for 5m", got)
	}
	if got := a.nextPollAt.Load(); got != now.Add(5*m).Unix() {
		t.Errorf("the watchdog was told %d, want %d", got, now.Add(5*m).Unix())
	}
	// Shorter than the step draws: the step stands.
	if got := a.scheduleNext(newRetryPlan(m, 5*m), limited(10*time.Second), now); got < m || got > 2*m {
		t.Errorf("slept %s after a 429 asking for 10s, want the 2m step with jitter", got)
	}
	// No header: the step alone.
	if got := a.scheduleNext(newRetryPlan(m, 5*m), limited(0), now); got < m || got > 2*m {
		t.Errorf("slept %s after a 429 without Retry-After", got)
	}
	// A day asked for: a quarter of an hour slept.
	if got := a.scheduleNext(newRetryPlan(m, 5*m), limited(24*time.Hour), now); got != retryAfterMax || retryAfterMax != 15*m {
		t.Errorf("slept %s after a 429 asking for a day, want %s", got, retryAfterMax)
	}
	// Not a 429: its Retry-After is not this agent's business.
	busy := fmt.Errorf("POST /api/v1/agent/heartbeat: %w", &api.StatusError{StatusCode: 503, RetryAfter: 10 * m})
	if got := a.scheduleNext(newRetryPlan(m, 5*m), busy, now); got < m || got > 2*m {
		t.Errorf("slept %s after a 503 with Retry-After", got)
	}

	// On hold: the first step is a minute, the limiter asks for five — and
	// the log says the enrollment is still on hold, not that it failed anew.
	p := newRetryPlan(m, 5*m)
	a.scheduleNext(p, errHeld, now)
	buf.Reset()
	if got := a.scheduleNext(p, errLimited, now); got != 5*m {
		t.Errorf("on hold, slept %s after a 429 asking for 5m", got)
	}
	if out := buf.String(); !strings.HasPrefix(out, "agent: tick failed while the enrollment is on hold, retrying in 5m0s: POST /api/v1/agent/enroll: status 429") {
		t.Errorf("logged: %s", out)
	}
	// At the ceiling, the step is what counts: 15 to 30 minutes.
	for range 4 {
		p.next(errHeld)
	}
	if got := a.scheduleNext(p, errLimited, now); got < 15*m || got > 30*m {
		t.Errorf("at the ceiling, slept %s after a 429", got)
	}
}

// Once the enrollment went through, nothing is on hold, whatever the tick
// returned after it: the heartbeat that follows an approval and fails — the
// server restarting under it — is retried as any failed heartbeat, not a
// quarter of an hour later.
func TestAHoldEndsOnceThePosteHoldsAToken(t *testing.T) {
	buf := captureLog(t)
	a := &Agent{cfg: &config.Config{}}
	now := time.Unix(1_800_000_000, 0)
	m := time.Minute
	p := newRetryPlan(m, 5*m)
	for range 5 {
		a.scheduleNext(p, errHeld, now)
	}
	// Still no token: a failure in between leaves the hold where it was.
	failed := fmt.Errorf("POST /api/v1/agent/heartbeat: %w", &api.StatusError{StatusCode: 500})
	if got := a.scheduleNext(p, failed, now); got < 7*m+30*time.Second {
		t.Errorf("without a token, slept %s on a 15m hold step", got)
	}
	buf.Reset()
	// Approved, enrolled, and the heartbeat fails.
	a.cfg.AuthToken = "token"
	if got := a.scheduleNext(p, failed, now); got > 5*m {
		t.Errorf("enrolled, slept %s after a failed heartbeat: the hold was still applied", got)
	}
	if out := buf.String(); !strings.HasPrefix(out, "agent: tick failed, retrying in ") {
		t.Errorf("logged: %s", out)
	}
	// Revoked later on: a new hold, from its first step.
	a.cfg.AuthToken = ""
	if got := a.scheduleNext(p, errRevoked, now); got > m {
		t.Errorf("the next hold started at %s", got)
	}
}

// --- a room of held postes behind one address ---------------------------------

// enrollLimiter models the server's limiter on /agent/enroll for one source
// address (backend/app/core/ratelimit.py, enroll_limiter): a sliding window
// of 30 attempts per 300 seconds, a refused attempt not counted.
type enrollLimiter struct{ hits []time.Duration }

const (
	enrollLimiterMax    = 30
	enrollLimiterWindow = 300 * time.Second
)

func (l *enrollLimiter) expire(now time.Duration) {
	for len(l.hits) > 0 && l.hits[0] <= now-enrollLimiterWindow {
		l.hits = l.hits[1:]
	}
}

// full tells whether an attempt at now would be refused, without making it.
func (l *enrollLimiter) full(now time.Duration) bool {
	l.expire(now)
	return len(l.hits) >= enrollLimiterMax
}

func (l *enrollLimiter) allow(now time.Duration) bool {
	if l.full(now) {
		return false
	}
	l.hits = append(l.hits, now)
	return true
}

// attempt is one poste's next enrollment attempt, in simulated time.
type attempt struct {
	at    time.Duration
	poste int
}
type attempts []attempt

func (q attempts) Len() int           { return len(q) }
func (q attempts) Less(i, j int) bool { return q[i].at < q[j].at }
func (q attempts) Swap(i, j int)      { q[i], q[j] = q[j], q[i] }
func (q *attempts) Push(x any)        { *q = append(*q, x.(attempt)) }
func (q *attempts) Pop() any          { o := *q; x := o[len(o)-1]; *q = o[:len(o)-1]; return x }

// heldRoom is what one simulated run of a room measured.
type heldRoom struct {
	// From the end of the first hour on: enrollment attempts, those the
	// limiter answered 429, and the share of the time the limiter was full —
	// when a poste that is not held, new or just approved, would be refused.
	attempts, limited int
	fullShare         float64
	// How long after its approval the approved poste enrolled.
	approvedAfter time.Duration
	// Postes whose step a 429 took above the ceiling.
	slowed int
}

// simulateHeldRoom runs n held postes behind one source address for twelve
// hours of simulated time: a room switched on, its boots spread over two
// minutes, every enrollment answered « held » — or 429 when the limiter is
// full. Each poste follows the agent's own schedule (scheduleNext), with
// jitter drawn from rng (seedJitter). Three hours in, one poste is approved:
// its next attempt the limiter lets through enrolls it.
func simulateHeldRoom(rng *rand.Rand, n int) heldRoom {
	const (
		end       = 12 * time.Hour
		warmUp    = time.Hour
		approveAt = 3 * time.Hour
	)
	a := &Agent{cfg: &config.Config{}}
	plans := make([]*retryPlan, n)
	var q attempts
	for i := range plans {
		// The agent's defaults: a heartbeat a minute, back-off up to five.
		plans[i] = newRetryPlan(time.Duration(config.DefaultHeartbeatInterval)*time.Second,
			time.Duration(config.DefaultBackoffMax)*time.Second)
		heap.Push(&q, attempt{at: time.Duration(i) * 2 * time.Minute / time.Duration(n), poste: i})
	}
	approved := rng.IntN(n)
	lim := &enrollLimiter{}
	out := heldRoom{approvedAfter: -1}
	var fullFor, lastAt time.Duration
	origin := time.Unix(1_800_000_000, 0)
	for q.Len() > 0 {
		e := heap.Pop(&q).(attempt)
		if e.at > end {
			break
		}
		// The limiter only changes state at an attempt, or by the oldest one
		// leaving the window: between two attempts it is full until then.
		if lastAt >= warmUp && lim.full(lastAt) {
			fullFor += min(e.at, lim.hits[0]+enrollLimiterWindow) - lastAt
		}
		lastAt = e.at
		err := errHeld
		if !lim.allow(e.at) {
			err = errLimited
		} else if e.poste == approved && e.at >= approveAt {
			out.approvedAfter = e.at - approveAt
			continue // enrolled: it heartbeats from now on
		}
		if e.at >= warmUp {
			out.attempts++
			if err == errLimited {
				out.limited++
			}
		}
		heap.Push(&q, attempt{at: e.at + a.scheduleNext(plans[e.poste], err, origin.Add(e.at)), poste: e.poste})
	}
	out.fullShare = float64(fullFor) / float64(end-warmUp)
	for _, p := range plans {
		if p.hold > enrollmentHoldMax {
			out.slowed++
		}
	}
	return out
}

// Forty, then a hundred held postes behind one source address — a remote
// site's NAT, a proxy — against the server's limiter of 30 enrollments per
// five minutes per address. The room starts together, so the first hour is a
// burst whatever the agents do (five short steps each); what must not happen
// is what the short steps first brought: a limiter kept full for good by the
// postes it refuses, each 429 sending a poste back to its one-minute step —
// 60 % of the attempts answered 429 at forty postes, 81 % at a hundred, 22
// and 19 attempts an hour per poste, and a poste approved in that state
// waiting up to three quarters of an hour.
//
// After the first hour:
//
//   - the limiter is left with room: under 2 % of the attempts refused at
//     forty postes — their 5.3 attempts an hour each are 60 % of what the
//     limiter admits — and under 10 % at a hundred, where the arithmetic says
//     5.3 an hour cannot fit (533 against 360) and the 429 at the ceiling
//     makes them fit (enrollmentHoldCongested); and it is full, for a poste
//     that would arrive then, less than a tenth of the time;
//   - no poste retries more than its hold step allows: six attempts an hour
//     at most, refusals included;
//   - a poste approved in that state enrolls at its next attempt, so within
//     one hold step: a quarter of an hour at forty postes, where no step was
//     raised and no attempt of an approved poste refused; at a hundred, half
//     an hour in nine rooms out of ten at least, and an hour in every room —
//     the second step is for a 429 falling on that very attempt, which waits
//     one step more and no longer starts a series of them.
//
// Seeded: the same draws at each run, twenty rooms of each size. Over four
// hundred rooms of each, the worst seen was 0.1 % of refusals and 14 minutes
// at forty postes, 5.3 % and 53 minutes at a hundred (23 minutes for nine
// rooms out of ten).
func TestARoomOfHeldPostesBehindOneAddressLeavesTheLimiterRoom(t *testing.T) {
	quietLog(t)
	for _, c := range []struct {
		postes     int
		maxLimited float64 // share of the attempts answered 429
		maxSlowed  int     // postes above the ceiling, per room, on average
		// What an approved poste waits: in nine rooms out of ten, and at most.
		approvedMostly, approvedAtMost time.Duration
	}{
		{postes: 40, maxLimited: 0.02, maxSlowed: 2,
			approvedMostly: enrollmentHoldMax, approvedAtMost: enrollmentHoldMax},
		{postes: 100, maxLimited: 0.10, maxSlowed: 100,
			approvedMostly: enrollmentHoldCongested, approvedAtMost: 2 * enrollmentHoldCongested},
	} {
		t.Run(fmt.Sprintf("%d postes", c.postes), func(t *testing.T) {
			const rooms = 20
			rng := seedJitter(t, uint64(c.postes))
			var waits []time.Duration
			var limited, total, slowed int
			for room := range rooms {
				r := simulateHeldRoom(rng, c.postes)
				share := float64(r.limited) / float64(r.attempts)
				perHour := float64(r.attempts) / float64(c.postes) / 11
				if share > c.maxLimited {
					t.Errorf("room %d: %.1f %% of the attempts answered 429 after the first hour, want under %.0f %%",
						room, 100*share, 100*c.maxLimited)
				}
				if r.fullShare > 0.10 {
					t.Errorf("room %d: the limiter was full %.1f %% of the time after the first hour", room, 100*r.fullShare)
				}
				if perHour > 6 {
					t.Errorf("room %d: %.1f attempts an hour per poste", room, perHour)
				}
				if r.approvedAfter < 0 {
					t.Fatalf("room %d: the approved poste never enrolled", room)
				}
				if r.approvedAfter > c.approvedAtMost {
					t.Errorf("room %d: the approved poste enrolled after %s, want within %s",
						room, r.approvedAfter.Round(time.Second), c.approvedAtMost)
				}
				waits = append(waits, r.approvedAfter)
				limited, total, slowed = limited+r.limited, total+r.attempts, slowed+r.slowed
			}
			slices.Sort(waits)
			if p90 := waits[rooms*9/10-1]; p90 > c.approvedMostly {
				t.Errorf("nine approved postes out of ten enrolled within %s, want within %s",
					p90.Round(time.Second), c.approvedMostly)
			}
			if slowed > c.maxSlowed*rooms {
				t.Errorf("%d postes slowed down per room on average, want %d at most: a room this size fits the limiter as it is",
					slowed/rooms, c.maxSlowed)
			}
			t.Logf("%d postes: %.1f %% of %d attempts answered 429 after the first hour; approved poste enrolled after %s (median), %s (worst); %d postes per room at the half-hour step",
				c.postes, 100*float64(limited)/float64(total), total/rooms,
				waits[rooms/2].Round(time.Second), waits[rooms-1].Round(time.Second), slowed/rooms)
		})
	}
}

// On a network where nothing else is held — the limiter never in the way —
// the short first steps are what an approval meets: given a few minutes after
// the poste asked, it is taken up within four more.
func TestAnApprovedPosteOnAQuietNetworkResumesWithinMinutes(t *testing.T) {
	quietLog(t)
	rng := seedJitter(t, 1)
	a := &Agent{cfg: &config.Config{}}
	origin := time.Unix(1_800_000_000, 0)
	var worst time.Duration
	for range 2000 {
		p := newRetryPlan(time.Minute, 5*time.Minute)
		// Approved anywhere in the three minutes that follow the first
		// refusal: the administrator was looking at the console.
		approveAt := time.Duration(rng.Int64N(int64(3 * time.Minute)))
		var at time.Duration
		for at < approveAt {
			at += a.scheduleNext(p, errHeld, origin.Add(at))
		}
		worst = max(worst, at-approveAt)
	}
	if worst > 4*time.Minute {
		t.Errorf("an approval given within three minutes was taken up after %s", worst.Round(time.Second))
	}
}

// From the wire to the wait: the server holds the enrollment, then its
// limiter answers 429 with Retry-After: 300, as backend/app/core/ratelimit.py
// does. The agent comes back five minutes later — not within the minute, as
// the first hold step alone would have it — and is still on hold.
func TestAnEnrollmentRefusedByTheLimiterWaitsWhatItAsks(t *testing.T) {
	buf := captureLog(t)
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.Header().Set("Content-Type", "application/json")
		if calls == 1 {
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"error":{"code":"machine.enrollment.approval_required","message":"x"}}`))
			return
		}
		w.Header().Set("Retry-After", "300")
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = w.Write([]byte(`{"error":{"code":"rate_limited","message":"Too many attempts; try again later"}}`))
	}))
	defer srv.Close()
	cfg := config.DefaultConfig()
	cfg.APIBaseURL = srv.URL
	cfg.EnrollmentSecret = "secret"
	a := New(cfg, filepath.Join(t.TempDir(), "config.yaml"))
	p := newRetryPlan(time.Minute, 5*time.Minute)
	now := time.Unix(1_800_000_000, 0)

	if got := a.scheduleNext(p, a.tick(context.Background()), now); got < 30*time.Second || got > time.Minute {
		t.Fatalf("first hold step slept %s", got)
	}
	if got := a.scheduleNext(p, a.tick(context.Background()), now); got != 5*time.Minute {
		t.Errorf("slept %s after a 429 with Retry-After: 300", got)
	}
	if !strings.Contains(buf.String(), "tick failed while the enrollment is on hold, retrying in 5m0s") {
		t.Errorf("logged:\n%s", buf.String())
	}
	if step, held := p.next(errHeld); step != 4*time.Minute || !held {
		t.Errorf("after the 429 the hold goes on at %s (held %v), want 4m", step, held)
	}
}

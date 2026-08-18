package agent

import (
	"testing"

	"tiai/agent/internal/models"
)

func wuState(pending int) *models.WUState {
	updates := make([]models.PendingUpdate, pending)
	for i := range updates {
		updates[i] = models.PendingUpdate{UpdateID: "u", Type: "software"}
	}
	return &models.WUState{Pending: updates}
}

// Nothing collected yet means nothing to say: the heartbeat omits the block and
// the server keeps whatever it already knows, rather than being told "no pending
// updates" by an agent that has not looked.
func TestWUCacheStartsEmpty(t *testing.T) {
	var c wuCache
	if state, _ := c.pending(); state != nil {
		t.Error("an agent that has not collected yet must attach no block")
	}
}

func TestWUCacheSendsEachReadingOnce(t *testing.T) {
	var c wuCache
	c.store(wuState(3))

	state, gen := c.pending()
	if state == nil || len(state.Pending) != 3 {
		t.Fatalf("a fresh reading must be offered, got %v", state)
	}
	// Still pending until the heartbeat actually lands: an attempt that never
	// reached the server has reported nothing.
	if again, _ := c.pending(); again == nil {
		t.Error("the block must stay pending until acknowledged")
	}

	c.markSent(gen)
	if after, _ := c.pending(); after != nil {
		t.Error("an acknowledged reading must not be re-sent every 60 s")
	}
}

// The race the generation counter exists for: a six-hourly collection landing
// between the moment a heartbeat picks up its payload and the moment that
// heartbeat succeeds. Acknowledging the *old* generation must not bury the new
// reading until the next cycle, six hours later.
func TestWUCacheKeepsAReadingStoredMidFlight(t *testing.T) {
	var c wuCache
	c.store(wuState(1))
	inFlight, gen := c.pending()
	if inFlight == nil {
		t.Fatal("expected a pending reading")
	}

	c.store(wuState(7)) // the cycle finishes while the heartbeat is in flight
	c.markSent(gen)     // the heartbeat succeeds, acknowledging the older one

	state, _ := c.pending()
	if state == nil {
		t.Fatal("the reading collected mid-flight was lost")
	}
	if len(state.Pending) != 7 {
		t.Errorf("expected the newer reading (7 updates), got %d", len(state.Pending))
	}
}

// A late acknowledgement — a slow heartbeat replying after a newer one — must
// not move the mark backwards and cause a re-send.
func TestWUCacheIgnoresStaleAcknowledgements(t *testing.T) {
	var c wuCache
	c.store(wuState(1))
	_, first := c.pending()
	c.store(wuState(2))
	_, second := c.pending()

	c.markSent(second)
	c.markSent(first) // arrives late, out of order

	if state, _ := c.pending(); state != nil {
		t.Error("a stale acknowledgement must not reopen an acknowledged reading")
	}
}

// A collector that failed returns nil, and the caller must not be able to wipe
// the last good reading with it.
func TestWUCacheIgnoresNilReadings(t *testing.T) {
	var c wuCache
	c.store(wuState(2))
	c.store(nil)

	state, _ := c.pending()
	if state == nil || len(state.Pending) != 2 {
		t.Errorf("a failed collection must leave the last reading alone, got %v", state)
	}
}

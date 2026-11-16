package agent

import "sync"

// stateCache holds the last reading of a slow-cycle block between the goroutine
// that produces it and the heartbeat that ships it.
//
// A block is attached to a heartbeat only when it holds something the server has
// not acknowledged yet. A Windows Update state is a few dozen updates with their
// titles and an inventory is a few hundred programs: re-sending either every 60
// seconds would multiply the parc's heartbeat payload for no new information,
// while re-writing the same rows server-side on every poll.
//
// "Acknowledged" is tracked with a generation counter rather than a boolean, and
// that is the whole point of the type. A collection finishing *between* the
// moment a heartbeat picks up its payload and the moment that heartbeat succeeds
// must not be marked as sent: with a flag it would be, and the fresh reading
// would then sit in the cache until the next cycle — six hours later for updates,
// a day for the inventory.
//
// Generic over the block it holds, because there are two of them now and the
// race is the same race.
type stateCache[T any] struct {
	mu    sync.Mutex
	state *T
	// gen increments on every store; sentGen is the last generation the server
	// acknowledged. Equal means there is nothing new to send.
	gen     uint64
	sentGen uint64
}

// store records a fresh reading, making it pending again.
func (c *stateCache[T]) store(state *T) {
	if state == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state = state
	c.gen++
}

// pending returns the state to attach to the next heartbeat and the generation
// to acknowledge afterwards, or (nil, 0) when the server is already up to date.
func (c *stateCache[T]) pending() (*T, uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state == nil || c.gen == c.sentGen {
		return nil, 0
	}
	return c.state, c.gen
}

// markSent acknowledges a generation after a successful heartbeat. A newer
// reading stored in the meantime keeps the cache pending, which is exactly the
// race the counter exists for.
func (c *stateCache[T]) markSent(gen uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if gen > c.sentGen {
		c.sentGen = gen
	}
}

// resend makes the reading the server already acknowledged pending again, and
// reports whether there was one to offer. A new generation rather than a
// rewound sentGen: the acknowledgement of a heartbeat still in flight then
// cannot cancel it, for the same reason it cannot bury a fresh reading.
func (c *stateCache[T]) resend() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state == nil {
		return false
	}
	c.gen++
	return true
}

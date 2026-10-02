package agent

import (
	"log"
	"path/filepath"

	"tiai/agent/internal/config"
)

// saveToken persists a per-machine token: DPAPI with the per-install entropy,
// written atomically — the very path enrollment uses. A variable so a test can
// make the write fail without having to break a disk.
var saveToken = config.SaveToken

// adoptRotatedToken decides which token the next request carries once the
// server has offered a new one, and stores it first.
//
// Stored before it is used, never the other way round: the server retires the
// old token on the first request carrying the new one, so an agent that
// switched in memory and then failed to write would come back from its next
// restart with a token.dat holding a dead token — and a re-enrollment to pay
// for it. When the write fails the current token is kept: the server still
// honours it, and offers a new token again on a later heartbeat.
//
// An empty offer, or one equal to the current token, changes nothing and
// writes nothing.
func adoptRotatedToken(current, offered string, save func(string) error) (string, error) {
	if offered == "" || offered == current {
		return current, nil
	}
	if err := save(offered); err != nil {
		return current, err
	}
	return offered, nil
}

// rotateToken applies a token offered on a heartbeat: stored, then used from
// the next request on. Called from the polling loop only, like ensureEnrolled
// and dropToken, the other two writers of cfg.AuthToken.
func (a *Agent) rotateToken(offered string) {
	dir := filepath.Dir(a.cfgPath)
	next, err := adoptRotatedToken(a.cfg.AuthToken, offered, func(token string) error {
		return saveToken(dir, token)
	})
	if err != nil {
		log.Printf("agent: could not store the renewed token, keeping the current one "+
			"(still valid; the server will offer another): %v", err)
		return
	}
	if next == a.cfg.AuthToken {
		return
	}
	a.cfg.AuthToken = next
	a.client.SetToken(next)
	// The token itself is never logged, at any level.
	log.Printf("agent: token renewed by the server, stored and in use")
}

package collector

import (
	"strings"

	"tiai/agent/internal/models"
)

// WTS_CONNECTSTATE_CLASS values we care about. Mirrored here rather than
// imported from golang.org/x/sys/windows (which is //go:build windows) so the
// election logic stays compilable — and unit-testable — off Windows.
const wtsActive = 0

// Session state labels sent to the server.
const (
	sessionStateActive       = "active"
	sessionStateDisconnected = "disconnected"
)

// rawSession is one Windows terminal session as read from the WTS API.
type rawSession struct {
	ID        uint32
	State     uint32 // WTS_CONNECTSTATE_CLASS
	User      string // WTSUserName; "" for system / listener / logon-screen sessions
	Domain    string // WTSDomainName (the computer name for a local account)
	IsConsole bool   // matches WTSGetActiveConsoleSessionId()
}

// buildSessionState turns the enumerated sessions into the wire block, applying
// the privacy setting: when reportUsername is false, only presence and state
// are reported. The name is read locally — it is how we know a session belongs
// to a user rather than to the logon screen — then dropped here, before it can
// reach the wire.
func buildSessionState(sessions []rawSession, reportUsername bool) *models.SessionState {
	elected := electSession(sessions)
	if elected == nil {
		return &models.SessionState{}
	}
	state := &models.SessionState{
		UserPresent: true,
		State:       stateLabel(elected.State),
		IsRemote:    !elected.IsConsole,
	}
	if reportUsername {
		state.Username = qualifiedUser(elected.Domain, elected.User)
	}
	return state
}

// electSession picks the session to report when several exist (RDS, fast user
// switching): an active session beats a disconnected one, and within each, the
// console session beats a remote one. Ties go to the lowest session id so the
// answer stays stable from one poll to the next.
func electSession(sessions []rawSession) *rawSession {
	var best *rawSession
	for i := range sessions {
		s := &sessions[i]
		if best == nil {
			best = s
			continue
		}
		switch r, br := sessionRank(*s), sessionRank(*best); {
		case r > br:
			best = s
		case r == br && s.ID < best.ID:
			best = s
		}
	}
	return best
}

// sessionRank orders candidate sessions: active before disconnected, console
// before remote.
func sessionRank(s rawSession) int {
	rank := 0
	if s.State == wtsActive {
		rank += 2
	}
	if s.IsConsole {
		rank++
	}
	return rank
}

// stateLabel maps a connect state to the two labels the console understands.
// Anything that is not active is reported as disconnected rather than guessed
// at: the user is logged on but not interacting, which is what matters here.
func stateLabel(state uint32) string {
	if state == wtsActive {
		return sessionStateActive
	}
	return sessionStateDisconnected
}

// qualifiedUser renders DOMAIN\user the way Windows displays it, or the bare
// name on a machine with no domain (local account).
func qualifiedUser(domain, user string) string {
	user = strings.TrimSpace(user)
	domain = strings.TrimSpace(domain)
	if user == "" || domain == "" {
		return user
	}
	return domain + `\` + user
}

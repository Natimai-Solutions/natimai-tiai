package collector

import (
	"encoding/json"
	"strings"
	"testing"

	"tiai/agent/internal/models"
)

// WTS_CONNECTSTATE_CLASS values used by the fixtures below.
const (
	wtsDisconnected = 4
	wtsListen       = 6
)

func TestElectSession(t *testing.T) {
	tests := []struct {
		name     string
		sessions []rawSession
		wantID   uint32
		wantNone bool
	}{
		{
			name:     "no session at all",
			sessions: nil,
			wantNone: true,
		},
		{
			name:     "lone active console session",
			sessions: []rawSession{{ID: 1, State: wtsActive, User: "jdupont", IsConsole: true}},
			wantID:   1,
		},
		{
			// Someone is physically at the machine: that beats a remote user.
			name: "active console beats active rdp",
			sessions: []rawSession{
				{ID: 3, State: wtsActive, User: "remote"},
				{ID: 1, State: wtsActive, User: "local", IsConsole: true},
			},
			wantID: 1,
		},
		{
			// Interacting beats merely logged on, console or not.
			name: "active rdp beats disconnected console",
			sessions: []rawSession{
				{ID: 1, State: wtsDisconnected, User: "left", IsConsole: true},
				{ID: 3, State: wtsActive, User: "remote"},
			},
			wantID: 3,
		},
		{
			// Still logged on: processes running, profile loaded. Report it.
			name:     "disconnected only is still reported",
			sessions: []rawSession{{ID: 2, State: wtsDisconnected, User: "left"}},
			wantID:   2,
		},
		{
			// Stability across polls matters more than which one we pick.
			name: "tie goes to the lowest session id",
			sessions: []rawSession{
				{ID: 7, State: wtsActive, User: "b"},
				{ID: 4, State: wtsActive, User: "a"},
				{ID: 9, State: wtsActive, User: "c"},
			},
			wantID: 4,
		},
		{
			name: "listener state ranks below an active session",
			sessions: []rawSession{
				{ID: 2, State: wtsListen, User: "svc", IsConsole: true},
				{ID: 5, State: wtsActive, User: "real"},
			},
			wantID: 5,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := electSession(tc.sessions)
			if tc.wantNone {
				if got != nil {
					t.Fatalf("electSession() = %+v, want nil", got)
				}
				return
			}
			if got == nil {
				t.Fatal("electSession() = nil, want a session")
			}
			if got.ID != tc.wantID {
				t.Errorf("elected session %d, want %d", got.ID, tc.wantID)
			}
		})
	}
}

func TestBuildSessionState(t *testing.T) {
	tests := []struct {
		name           string
		sessions       []rawSession
		reportUsername bool
		want           models.SessionState
	}{
		{
			name:           "nobody logged on",
			sessions:       nil,
			reportUsername: true,
			want:           models.SessionState{},
		},
		{
			name:           "domain user on the console",
			sessions:       []rawSession{{ID: 1, State: wtsActive, User: "jdupont", Domain: "CORP", IsConsole: true}},
			reportUsername: true,
			want: models.SessionState{
				UserPresent: true,
				Username:    `CORP\jdupont`,
				State:       sessionStateActive,
			},
		},
		{
			// The privacy assertion: presence and state survive, the name does not.
			name:           "username withheld by configuration",
			sessions:       []rawSession{{ID: 1, State: wtsActive, User: "jdupont", Domain: "CORP", IsConsole: true}},
			reportUsername: false,
			want: models.SessionState{
				UserPresent: true,
				State:       sessionStateActive,
			},
		},
		{
			name:           "local account has no domain prefix",
			sessions:       []rawSession{{ID: 1, State: wtsActive, User: "admin", IsConsole: true}},
			reportUsername: true,
			want: models.SessionState{
				UserPresent: true,
				Username:    "admin",
				State:       sessionStateActive,
			},
		},
		{
			name:           "disconnected rdp session",
			sessions:       []rawSession{{ID: 3, State: wtsDisconnected, User: "jdupont", Domain: "CORP"}},
			reportUsername: true,
			want: models.SessionState{
				UserPresent: true,
				Username:    `CORP\jdupont`,
				State:       sessionStateDisconnected,
				IsRemote:    true,
			},
		},
		{
			name:           "whitespace is trimmed off the qualified name",
			sessions:       []rawSession{{ID: 1, State: wtsActive, User: " jdupont ", Domain: " CORP ", IsConsole: true}},
			reportUsername: true,
			want: models.SessionState{
				UserPresent: true,
				Username:    `CORP\jdupont`,
				State:       sessionStateActive,
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := buildSessionState(tc.sessions, tc.reportUsername)
			if got == nil {
				t.Fatal("buildSessionState() = nil, want a state")
			}
			if *got != tc.want {
				t.Errorf("buildSessionState() = %+v, want %+v", *got, tc.want)
			}
		})
	}
}

func TestQualifiedUser(t *testing.T) {
	tests := []struct {
		domain, user, want string
	}{
		{"CORP", "jdupont", `CORP\jdupont`},
		{"", "admin", "admin"},
		{"CORP", "", ""},
		{"", "", ""},
		{"  ", "  admin  ", "admin"},
	}
	for _, tc := range tests {
		if got := qualifiedUser(tc.domain, tc.user); got != tc.want {
			t.Errorf("qualifiedUser(%q, %q) = %q, want %q", tc.domain, tc.user, got, tc.want)
		}
	}
}

// The zero value must serialize both bools explicitly: an omitted
// "user_present": false would read server-side as "never reported", which is a
// different state entirely. Guards against someone adding omitempty later.
func TestSessionStateJSONKeepsBools(t *testing.T) {
	b, err := json.Marshal(models.SessionState{})
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}
	for _, want := range []string{`"user_present":false`, `"is_remote":false`} {
		if !strings.Contains(string(b), want) {
			t.Errorf("marshalled zero value %s, missing %s", b, want)
		}
	}
}

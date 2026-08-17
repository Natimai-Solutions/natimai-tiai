package collector

import (
	"context"
	"fmt"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"

	"tiai/agent/internal/models"
)

// x/sys/windows exposes WTSEnumerateSessions, WTSFreeMemory and
// WTSGetActiveConsoleSessionId, but not WTSQuerySessionInformationW — so only
// that one needs the LazyDLL treatment (same pattern as netapi32 in sysinfo).
var (
	wtsapi32                       = windows.NewLazySystemDLL("wtsapi32.dll")
	procWTSQuerySessionInformation = wtsapi32.NewProc("WTSQuerySessionInformationW")
)

// WTS_INFO_CLASS values (wtsapi32.h).
const (
	wtsUserName   = 5
	wtsDomainName = 7
)

// servicesSessionID is session 0, where the services (including this agent)
// live. It never hosts an interactive user.
const servicesSessionID = 0

// ReadSessionState reports whether a user is logged on to this workstation.
// reportUsername=false yields presence and state only.
//
// The agent runs as LocalSystem in session 0, so os/user and %USERNAME% are
// useless here; WTSEnumerateSessions enumerates every local session regardless
// of the caller's own, which is exactly what the API is for.
func ReadSessionState(ctx context.Context, reportUsername bool) (*models.SessionState, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	sessions, err := enumerateSessions()
	if err != nil {
		return nil, err
	}
	return buildSessionState(sessions, reportUsername), nil
}

func enumerateSessions() ([]rawSession, error) {
	var infos *windows.WTS_SESSION_INFO
	var count uint32
	// Handle 0 is WTS_CURRENT_SERVER_HANDLE (this machine); version must be 1.
	if err := windows.WTSEnumerateSessions(0, 0, 1, &infos, &count); err != nil {
		return nil, fmt.Errorf("WTSEnumerateSessions: %w", err)
	}
	defer windows.WTSFreeMemory(uintptr(unsafe.Pointer(infos)))

	console := windows.WTSGetActiveConsoleSessionId()
	out := make([]rawSession, 0, count)
	for _, s := range unsafe.Slice(infos, count) {
		if s.SessionID == servicesSessionID {
			continue
		}
		user := querySessionString(s.SessionID, wtsUserName)
		if user == "" {
			// Logon screen, RDP-Tcp listener, UMFD/DWM stations: a session
			// exists but nobody is logged on to it.
			continue
		}
		out = append(out, rawSession{
			ID:     s.SessionID,
			State:  s.State,
			User:   user,
			Domain: querySessionString(s.SessionID, wtsDomainName),
			// During a fast-user-switch the console id is 0xFFFFFFFF, which
			// matches nothing — the election then falls back on connect state.
			IsConsole: s.SessionID == console,
		})
	}
	return out, nil
}

// querySessionString reads one string WTS_INFO_CLASS; any failure yields ""
// (best-effort, like the other host reads). Each returned buffer is freed here:
// leaking one string per session per 60 s heartbeat would be a slow leak in a
// service that runs for months.
func querySessionString(sessionID uint32, infoClass uint32) string {
	var buf *uint16
	var n uint32
	r, _, _ := procWTSQuerySessionInformation.Call(
		0, // WTS_CURRENT_SERVER_HANDLE
		uintptr(sessionID),
		uintptr(infoClass),
		uintptr(unsafe.Pointer(&buf)),
		uintptr(unsafe.Pointer(&n)),
	)
	if r == 0 || buf == nil {
		return ""
	}
	defer windows.WTSFreeMemory(uintptr(unsafe.Pointer(buf)))
	return strings.TrimSpace(windows.UTF16PtrToString(buf))
}

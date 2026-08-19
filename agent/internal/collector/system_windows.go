package collector

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"golang.org/x/sys/windows"
)

var procGetTickCount64 = windows.NewLazySystemDLL("kernel32.dll").NewProc("GetTickCount64")

// Uptime reports how long this machine has been running.
//
// GetTickCount64 rather than reading a boot timestamp out of WMI or the event
// log: it is a single call into kernel32, needs no privilege and no COM, and
// cannot fail on a machine whose WMI repository is exactly the kind of thing
// somebody is rebooting to fix. It counts sleep and hibernation as elapsed
// time, which is the reading we want — a laptop booted this morning and shut
// twice since is not a machine that just restarted.
func Uptime() (time.Duration, error) {
	ms, _, _ := procGetTickCount64.Call()
	return time.Duration(ms) * time.Millisecond, nil
}

// Reboot schedules a restart of the machine after rebootDelay, with a message
// for whoever is logged on.
//
// Scheduled rather than immediate, and that delay is load-bearing twice over:
// it gives a user time to save their work, and it gives the caller time to post
// the result before the machine goes down. Should the POST fail anyway, the
// durable local queue replays it after the restart — the same mechanism that
// covers a scan finishing while the server is unreachable.
//
// shutdown.exe rather than the InitiateSystemShutdownEx API: the tool already
// carries the privilege handling (SeShutdownPrivilege), the user notification
// and the message display, and reimplementing all three to save one process
// launch on a command triggered by hand would be a poor trade.
func Reboot(ctx context.Context) (string, error) {
	seconds := strconv.Itoa(int(rebootDelay.Seconds()))
	ctx, cancel := context.WithTimeout(ctx, rebootTimeout)
	defer cancel()

	raw, code, err := runSystem32(ctx, "shutdown.exe",
		"/r", "/t", seconds, "/c", rebootMessage)
	output := truncateOutput(normalizeConsoleOutput(decodeToolOutput(raw, encOEM)), maxOutputBytes)
	if err != nil {
		return output, err
	}
	if code != 0 {
		return output, fmt.Errorf("le redémarrage n'a pas pu être programmé (code %s)",
			formatExitCode(code))
	}
	return fmt.Sprintf("Redémarrage programmé dans %s secondes.\n%s", seconds, output), nil
}

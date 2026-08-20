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

// Reboot schedules a restart of the machine after powerActionDelay, with a
// message for whoever is logged on.
func Reboot(ctx context.Context) (string, error) {
	return schedulePowerAction(ctx, "/r", rebootMessage, "Redémarrage")
}

// Shutdown schedules a full stop of the machine, same delay and same warning.
//
// /s and not /p or /f: a stop that skips the notification, or forces
// applications closed without asking them, is exactly what the delay above
// exists to avoid. The machine ends up off either way; only the user's chance
// to save their work differs.
//
// Note what is *not* here: no /hybrid and no hibernation. A poste stopped with
// Windows' fast start-up leaves its network adapter in a state where
// Wake-on-LAN is unreliable, which would make the console offer a wake that
// works on some machines and not others. The plain stop is the one whose
// counterpart is a magic packet that actually arrives.
func Shutdown(ctx context.Context) (string, error) {
	return schedulePowerAction(ctx, "/s", shutdownMessage, "Arrêt")
}

// schedulePowerAction runs shutdown.exe for one of the two power commands and
// turns what came back into the result the console shows.
//
// Scheduled rather than immediate, and that delay is load-bearing twice over:
// it gives a user time to save their work, and it gives the caller time to post
// the result before the machine goes down. Should the POST fail anyway, the
// durable local queue replays it after the restart — the same mechanism that
// covers a scan finishing while the server is unreachable. (After a *shutdown*
// the replay waits for the next boot, which is the honest behaviour: nobody is
// watching a poste that is off.)
//
// shutdown.exe rather than the InitiateSystemShutdownEx API: the tool already
// carries the privilege handling (SeShutdownPrivilege), the user notification
// and the message display, and reimplementing all three to save one process
// launch on a command triggered by hand would be a poor trade.
func schedulePowerAction(ctx context.Context, flag, message, label string) (string, error) {
	seconds := strconv.Itoa(int(powerActionDelay.Seconds()))
	ctx, cancel := context.WithTimeout(ctx, powerActionTimeout)
	defer cancel()

	raw, code, err := runSystem32(ctx, "shutdown.exe",
		flag, "/t", seconds, "/c", message)
	output := truncateOutput(normalizeConsoleOutput(decodeToolOutput(raw, encOEM)), maxOutputBytes)
	if err != nil {
		return output, err
	}
	if code != 0 {
		return output, fmt.Errorf("%s : l'opération n'a pas pu être programmée (code %s)",
			label, formatExitCode(code))
	}
	return fmt.Sprintf("%s programmé dans %s secondes.\n%s", label, seconds, output), nil
}

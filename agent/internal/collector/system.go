package collector

import "time"

// Restarting the machine — the one command in the catalogue whose effect
// outlives the agent process that ran it.
//
// It exists because Windows Update needs it and the agent must never take it on
// itself: an update that reports "restart required" is reported as such and
// nothing more, and the restart is a separate, explicitly triggered command
// behind a confirmation in the console (plan-phase2-windows-update.md §1).

const (
	// rebootDelay is what stands between the command and a lost document. A
	// restart triggered from the console lands on a machine somebody may well be
	// working on: Windows displays the message below for the whole delay, and a
	// user who needs another minute can save their work. Long enough to be
	// noticed, short enough that the administrator who asked for it does not
	// wonder whether the command was lost.
	rebootDelay = 60 * time.Second

	// rebootMessage is displayed to the logged-on user by shutdown.exe. In
	// French, and naming the tool: the point is that a user seeing it knows the
	// restart was asked for, rather than suspecting a crash.
	rebootMessage = "Redémarrage demandé par l'administrateur (Tiai)."

	// rebootTimeout bounds the call itself, not the restart. shutdown.exe only
	// schedules the operation and returns at once; if it has not, something is
	// wrong with the machine and not with the delay.
	rebootTimeout = 1 * time.Minute
)

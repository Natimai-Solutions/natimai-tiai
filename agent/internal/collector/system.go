package collector

import "time"

// Powering the machine down — restarting it, or stopping it outright. The two
// commands in the catalogue whose effect outlives the agent process that ran
// them.
//
// The restart exists because Windows Update needs it and the agent must never
// take it on itself: an update that reports "restart required" is reported as
// such and nothing more, and the restart is a separate, explicitly triggered
// command behind a confirmation in the console
// (plan-phase2-windows-update.md §1). The shutdown answers the other half of
// the question — a poste to be stopped for the weekend, a site to be powered
// down before a works outage — and is the counterpart of the Wake-on-LAN the
// server emits to bring it back.

const (
	// powerActionDelay is what stands between the command and a lost document.
	// A restart or a shutdown triggered from the console lands on a machine
	// somebody may well be working on: Windows displays the message below for
	// the whole delay, and a user who needs another minute can save their work.
	// Long enough to be noticed, short enough that the administrator who asked
	// for it does not wonder whether the command was lost.
	powerActionDelay = 60 * time.Second

	// rebootMessage and shutdownMessage are displayed to the logged-on user by
	// shutdown.exe. In French, and naming the tool: the point is that a user
	// seeing one knows the operation was asked for, rather than suspecting a
	// crash. They name the *right* operation too — a user told "redémarrage"
	// while the machine is in fact stopping would wait in front of a poste that
	// never comes back.
	rebootMessage   = "Redémarrage demandé par l'administrateur (Tiai)."
	shutdownMessage = "Arrêt du poste demandé par l'administrateur (Tiai)."

	// powerActionTimeout bounds the call itself, not the restart. shutdown.exe
	// only schedules the operation and returns at once; if it has not,
	// something is wrong with the machine and not with the delay.
	powerActionTimeout = 1 * time.Minute
)

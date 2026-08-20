package collector

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"

	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

// RunWUReset stops the Windows Update services, moves the update store and the
// catalogue signature cache aside, and starts the services again.
//
// Three ordering rules carry the whole safety of this, and none of them is
// negotiable:
//
//   - The renames happen only once *every* service has actually reached
//     Stopped. A directory still held open cannot be renamed anyway, and
//     racing it would leave a half-moved store.
//   - A service that could not be stopped cancels the renames outright rather
//     than letting them fail one by one — a poste is better left untouched
//     than left with SoftwareDistribution moved and wuauserv still holding a
//     handle into it.
//   - The services are started again whatever happened above, exactly as
//     spooler_reset restarts the spooler over a failed purge. A poste with no
//     Windows Update service at all is a worse outcome than one whose store
//     did not move.
//
// Only the services this call actually stopped are started again: `wuauserv`
// and `msiserver` are demand-start on a modern Windows and are routinely found
// stopped, and one disabled by GPO must stay that way — starting it would be
// this command quietly overriding an administrator's policy.
func RunWUReset(ctx context.Context) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, wuResetTimeout)
	defer cancel()

	m, err := mgr.Connect()
	if err != nil {
		return "", fmt.Errorf("connexion au gestionnaire de services : %w", err)
	}
	defer m.Disconnect()

	var log wuResetLog

	// --- Stop -------------------------------------------------------------
	stopped := make([]wuResetService, 0, len(wuResetServices))
	for _, s := range wuResetServices {
		wasRunning, err := stopWUService(ctx, m, s.name)
		if err != nil {
			log.fail(fmt.Sprintf("arrêt du service %s (%s)", s.label, s.name), err)
			continue
		}
		if !wasRunning {
			log.step("%s (%s) : déjà arrêté.", s.label, s.name)
			continue
		}
		log.step("%s (%s) : arrêté.", s.label, s.name)
		stopped = append(stopped, s)
	}

	// --- Move aside -------------------------------------------------------
	if log.failed() {
		log.step("Aucun dossier renommé : un service tient encore le magasin de mises à jour.")
	} else {
		root := systemRoot()
		for _, f := range wuResetFolders {
			dir := filepath.Join(append([]string{root}, f.elems...)...)
			switch err := moveAside(dir, f.backup); {
			case err == nil:
				log.step("%s : renommé en %s.", f.label, f.backup)
			case errors.Is(err, errWUResetFolderAbsent):
				// Nothing to move is not a failure: Windows recreates these on
				// demand, so an absent one is simply a poste that has not
				// searched since the last reset.
				log.step("%s : absent, rien à renommer.", f.label)
			default:
				log.fail(fmt.Sprintf("renommage de %s", dir), err)
			}
		}
	}

	// --- Start again ------------------------------------------------------
	for _, s := range stopped {
		if err := startWUService(ctx, m, s.name); err != nil {
			log.fail(fmt.Sprintf("redémarrage du service %s (%s)", s.label, s.name), err)
			continue
		}
		log.step("%s (%s) : redémarré.", s.label, s.name)
	}

	if !log.failed() {
		log.step("")
		log.step("%s", wuResetNextStep)
	}
	return log.verdict()
}

// stopWUService stops one service if it is up, reporting whether it was
// actually running — which is what decides if it has to be started again.
func stopWUService(ctx context.Context, m *mgr.Mgr, name string) (bool, error) {
	s, err := m.OpenService(name)
	if err != nil {
		return false, err
	}
	defer s.Close()

	status, err := s.Query()
	if err != nil {
		return false, fmt.Errorf("interrogation du service : %w", err)
	}
	if status.State == svc.Stopped {
		return false, nil
	}
	if err := setServiceState(ctx, s, svc.Stop, svc.Stopped); err != nil {
		return false, err
	}
	return true, nil
}

// startWUService starts one service and waits for it to be Running.
func startWUService(ctx context.Context, m *mgr.Mgr, name string) error {
	s, err := m.OpenService(name)
	if err != nil {
		return err
	}
	defer s.Close()
	// A zero control code means "start" — same convention as runSpoolerReset.
	return setServiceState(ctx, s, svc.Cmd(0), svc.Running)
}

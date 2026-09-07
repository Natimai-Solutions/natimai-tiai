package agent

import (
	"context"
	"fmt"
	"log"
	"math/rand/v2"
	"time"

	"tiai/agent/internal/collector"
	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
)

// inventoryFirstCollectDelay keeps the first collection off the boot path, like
// the Windows Update one — and a minute later than it, so the two do not open a
// dozen WMI queries at the same moment on a machine that has just started.
//
// Three minutes and not an hour, because of the poste that is switched on for a
// morning and off again: a laptop that never stays up long enough to reach its
// daily tick would otherwise never be inventoried at all.
const inventoryFirstCollectDelay = 3 * time.Minute

// inventoryFirstCollectSpread staggers that first collection across the parc.
//
// Without it a fleet-wide deployment — a new agent pushed by GPO, a room of
// postes started at eight — has every machine collect its inventory at the same
// second and send the heaviest payload of its life to the server at once. The
// server then writes a few hundred catalogue rows per poste against a connection
// pool of twenty, every heartbeat waits on it, and the agents that time out
// re-send exactly the same block on the next tick: a stampede that feeds itself
// and reports nothing. Randomising the first delay over a few minutes costs one
// morning's freshness and removes the pile-up.
const inventoryFirstCollectSpread = 5 * time.Minute

// inventoryCache is the daily cycle's cache. Same mechanism as the Windows
// Update one, generation counter included — see cache.go.
type inventoryCache = stateCache[models.InventoryState]

// inventoryLoop collects the hardware and software inventory once a day.
//
// Its own goroutine for the same reason as the Windows Update cycle: a dozen WMI
// queries and two registry walks take seconds, sometimes more on a tired
// machine, and pollOnce has to stay short enough to keep the 60 s heartbeat.
func (a *Agent) inventoryLoop(ctx context.Context) {
	defer a.wg.Done()

	interval := time.Duration(a.cfg.InventoryCollectIntervalSeconds) * time.Second
	timer := time.NewTimer(inventoryFirstDelay())
	defer timer.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-timer.C:
		}
		a.collectInventory(ctx)
		timer.Reset(interval)
	}
}

// inventoryFirstDelay is the wait before the first collection: the fixed delay
// that keeps it off the boot path, plus a random share of the spread that keeps
// the parc from collecting in unison.
func inventoryFirstDelay() time.Duration {
	return inventoryFirstCollectDelay + rand.N(inventoryFirstCollectSpread)
}

// collectInventory refreshes the cache — but only stores a reading that differs
// from the last one sent.
//
// That check is what keeps a stable parc quiet, and it is deliberately made
// *here* rather than left to the server: a poste whose hardware has not changed
// and whose software has not moved sends nothing at all, so the heartbeat stays
// the size it was before this module existed. The server has its own copy of the
// same check, for the case this one cannot cover — an agent that restarted has
// forgotten what it sent.
//
// A failure is logged and nothing else, like the Windows Update cycle: the block
// is simply not attached, the server keeps what it had, and the machine still
// reports its Defender state, its session and its address.
func (a *Agent) collectInventory(ctx context.Context) {
	a.inventoryOp.Lock()
	defer a.inventoryOp.Unlock()
	if ctx.Err() != nil {
		return
	}

	start := time.Now()
	inv, err := collector.ReadInventory(ctx, a.cfg.ReportsSoftware())
	if err != nil {
		log.Printf("agent: inventory: %v", err)
		return
	}
	if inv == nil {
		return // not a Windows host; the stub said so without an error
	}
	if inv.Hash != "" && inv.Hash == a.inventorySent {
		logging.Debugf("agent: inventory unchanged (%s), nothing to send",
			time.Since(start).Round(time.Millisecond))
		return
	}
	a.inventorySent = inv.Hash
	a.inventory.store(inv)
	log.Printf("agent: inventory collected in %s: %d disque(s), %d volume(s), "+
		"%d carte(s) réseau, %d logiciel(s)",
		time.Since(start).Round(time.Millisecond),
		len(inv.Disks), len(inv.Volumes), len(inv.Nics), len(inv.Software))
}

// runInventoryScan forces a collection and reports what it found.
//
// Its value is immediacy, like wu_scan's: an administrator who has just added
// memory to a poste, or uninstalled a program across a room, wants to see it now
// rather than tomorrow.
//
// The hash check is deliberately bypassed — the cache is stored whatever the
// hash says. Somebody asked; an answer of "nothing changed, so the console still
// shows last week's reading" would be indistinguishable from the command having
// silently failed.
func (a *Agent) runInventoryScan(ctx context.Context) (string, error) {
	a.inventoryOp.Lock()
	defer a.inventoryOp.Unlock()

	inv, err := collector.ReadInventory(ctx, a.cfg.ReportsSoftware())
	if err != nil {
		return "", err
	}
	if inv == nil {
		return "", fmt.Errorf("inventaire indisponible sur cette plateforme")
	}
	a.inventorySent = inv.Hash
	a.inventory.store(inv)
	return inventoryScanSummary(inv, a.cfg.ReportsSoftware()), nil
}

// inventoryScanSummary is what the console shows in the command's result cell.
//
// It names the software count only when software is actually collected: "0
// logiciel" on a poste whose collection is switched off by GPO reads as a failed
// read, when it is a policy working exactly as intended.
func inventoryScanSummary(inv *models.InventoryState, withSoftware bool) string {
	summary := fmt.Sprintf("%d disque(s), %d volume(s), %d carte(s) réseau",
		len(inv.Disks), len(inv.Volumes), len(inv.Nics))
	if withSoftware {
		return fmt.Sprintf("%s, %d logiciel(s).", summary, len(inv.Software))
	}
	return summary + ", inventaire logiciel désactivé sur ce poste."
}

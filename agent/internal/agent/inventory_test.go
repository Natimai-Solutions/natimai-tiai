package agent

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/collector"
	"tiai/agent/internal/config"
	"tiai/agent/internal/models"
	"tiai/agent/internal/queue"
)

func TestInventoryCacheSharesTheWindowsUpdateMechanism(t *testing.T) {
	var c inventoryCache
	if state, _ := c.pending(); state != nil {
		t.Error("an agent that has not collected yet must attach no block")
	}

	c.store(&models.InventoryState{HWModel: "OptiPlex 7010"})
	state, gen := c.pending()
	if state == nil {
		t.Fatal("a fresh reading must be offered")
	}
	// Still pending until the heartbeat actually lands.
	if again, _ := c.pending(); again == nil {
		t.Error("the block must stay pending until acknowledged")
	}
	c.markSent(gen)
	if after, _ := c.pending(); after != nil {
		t.Error("an acknowledged reading must not be re-sent every 60 s")
	}
}

// The race the generation counter exists for, restated for the daily cycle: a
// collection landing between the moment a heartbeat picks up its payload and the
// moment that heartbeat succeeds must not be buried until *tomorrow*.
func TestInventoryCacheKeepsAReadingStoredMidFlight(t *testing.T) {
	var c inventoryCache
	c.store(&models.InventoryState{HWModel: "before"})
	_, gen := c.pending()

	c.store(&models.InventoryState{HWModel: "after"})
	c.markSent(gen)

	state, _ := c.pending()
	if state == nil || state.HWModel != "after" {
		t.Fatalf("the newer reading must survive the older acknowledgement, got %v", state)
	}
}

// resend re-offers what the server acknowledged, as a generation of its own:
// nothing when nothing was ever read, and never cancelled by the
// acknowledgement of an older heartbeat.
func TestInventoryCacheResendReoffersTheAcknowledgedReading(t *testing.T) {
	var c inventoryCache
	if c.resend() {
		t.Error("an empty cache has nothing to send again")
	}
	if state, _ := c.pending(); state != nil {
		t.Error("a resend on an empty cache made something pending")
	}

	c.store(&models.InventoryState{HWModel: "OptiPlex 7010"})
	_, gen := c.pending()
	c.markSent(gen)
	if !c.resend() {
		t.Fatal("an acknowledged reading must be offered again")
	}
	c.markSent(gen) // the same acknowledgement, late or repeated
	state, again := c.pending()
	if state == nil || state.HWModel != "OptiPlex 7010" {
		t.Fatalf("pending = %v, want the acknowledged reading back", state)
	}
	c.markSent(again)
	if after, _ := c.pending(); after != nil {
		t.Error("a re-sent reading must be acknowledged like any other")
	}
}

// "0 logiciel" on a poste whose collection is switched off by GPO reads as a
// failed read, when it is a policy working exactly as intended.
func TestInventoryScanSummarySaysWhenSoftwareIsOff(t *testing.T) {
	inv := &models.InventoryState{
		Disks:    []models.Disk{{DeviceID: "0"}},
		Volumes:  []models.Volume{{Letter: "C:"}, {Letter: "D:"}},
		Nics:     []models.Nic{{Key: "A"}},
		Software: nil,
	}
	off := inventoryScanSummary(inv, false).Text
	if !strings.Contains(off, "désactivé") {
		t.Errorf("a disabled collection must say so, got %q", off)
	}
	if strings.Contains(off, "0 logiciel") {
		t.Errorf("a disabled collection must not report a count, got %q", off)
	}

	inv.Software = []models.Software{{Name: "7-Zip"}}
	on := inventoryScanSummary(inv, true).Text
	if !strings.Contains(on, "1 logiciel(s)") {
		t.Errorf("an enabled collection must report its count, got %q", on)
	}
}

// The first collection must stay off the boot path and still not have a whole
// parc collect in unison — the pile-up that has every poste send its heaviest
// payload at the same second.
func TestInventoryFirstDelayIsSpread(t *testing.T) {
	seen := make(map[time.Duration]bool)
	for range 200 {
		d := inventoryFirstDelay()
		if d < inventoryFirstCollectDelay {
			t.Fatalf("first collection must not run before %s, got %s",
				inventoryFirstCollectDelay, d)
		}
		if d >= inventoryFirstCollectDelay+inventoryFirstCollectSpread {
			t.Fatalf("first collection must stay inside the spread, got %s", d)
		}
		seen[d] = true
	}
	if len(seen) < 2 {
		t.Error("a fixed delay would have every poste of the parc collect at once")
	}
}

// heartbeatScript is a server that records the inventory block of each
// heartbeat it receives (nil when there was none) and answers the n-th with
// answers[n] — `{"commands":[]}` once the script runs out.
func heartbeatScript(t *testing.T, answers ...string) (*httptest.Server, func() []*models.InventoryState) {
	t.Helper()
	var mu sync.Mutex
	var seen []*models.InventoryState
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req models.HeartbeatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Errorf("decode heartbeat: %v", err)
		}
		mu.Lock()
		answer := `{"commands":[]}`
		if n := len(seen); n < len(answers) {
			answer = answers[n]
		}
		seen = append(seen, req.Inventory)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(answer))
	}))
	t.Cleanup(srv.Close)
	return srv, func() []*models.InventoryState {
		mu.Lock()
		defer mu.Unlock()
		return append([]*models.InventoryState(nil), seen...)
	}
}

// stubInventory stands in for WMI and the registry: a poste that never
// changes, read with or without its software as the agent asks. It returns
// the includeSoftware values the agent passed, one per collection.
func stubInventory(t *testing.T) func() []bool {
	t.Helper()
	var mu sync.Mutex
	var asked []bool
	orig := readInventory
	t.Cleanup(func() { readInventory = orig })
	readInventory = func(_ context.Context, opts collector.InventoryOptions) (*models.InventoryState, error) {
		includeSoftware := opts.Software
		mu.Lock()
		asked = append(asked, includeSoftware)
		mu.Unlock()
		inv := &models.InventoryState{Hash: "hardware-only", HWModel: "OptiPlex 7010"}
		if includeSoftware {
			inv.Hash = "with-software"
			inv.Software = []models.Software{{Name: "7-Zip", Version: "24.08"}}
		}
		return inv, nil
	}
	return func() []bool {
		mu.Lock()
		defer mu.Unlock()
		return append([]bool(nil), asked...)
	}
}

func pollingAgent(t *testing.T, url string) *Agent {
	t.Helper()
	q, err := queue.New(t.TempDir(), 100)
	if err != nil {
		t.Fatal(err)
	}
	return &Agent{cfg: config.DefaultConfig(), queue: q, client: api.New(url, "tok", 5*time.Second, nil)}
}

// poll sends one heartbeat and handles its answer, as pollOnce does once it
// has read the machine — which a test has no Windows to do.
func poll(t *testing.T, a *Agent) {
	t.Helper()
	if err := a.heartbeat(context.Background(), hostReading{}); err != nil {
		t.Fatalf("heartbeat: %v", err)
	}
}

// The protocol's resend_inventory: a server that no longer holds what a poste
// reported asks for it, and the next heartbeat carries the block although the
// poste's hash has not moved — which is exactly what keeps it silent otherwise.
func TestResendInventoryMakesTheNextHeartbeatCarryAnUnchangedInventory(t *testing.T) {
	const quiet, resend = `{"commands":[]}`, `{"commands":[],"resend_inventory":true}`
	srv, seen := heartbeatScript(t,
		quiet,  // 0: carries the first reading
		quiet,  // 1: nothing new
		resend, // 2: nothing new — the server asks
		quiet,  // 3: must carry the block again
		quiet,  // 4: once, not on every heartbeat after
		`{"commands":[],"resend_inventory":false}`, // 5: an explicit false is a no
		quiet, // 6
	)
	stubInventory(t)
	a := pollingAgent(t, srv.URL)

	a.collectInventory(context.Background())
	poll(t, a) // 0
	a.collectInventory(context.Background())
	poll(t, a) // 1: the daily collection found the same hash
	poll(t, a) // 2
	a.collectInventory(context.Background())
	poll(t, a) // 3: the hash is still the one already sent
	poll(t, a) // 4
	poll(t, a) // 5
	poll(t, a) // 6

	got := seen()
	if len(got) != 7 {
		t.Fatalf("%d heartbeat(s) received, want 7", len(got))
	}
	for i, want := range []bool{true, false, false, true, false, false, false} {
		if (got[i] != nil) != want {
			t.Errorf("heartbeat %d: inventory attached = %v, want %v", i, got[i] != nil, want)
		}
	}
	if got[0] == nil || got[3] == nil {
		t.FailNow()
	}
	if got[3].Hash != got[0].Hash || got[3].Hash != "with-software" || len(got[3].Software) != 1 {
		t.Errorf("re-sent %+v, want the unchanged reading %+v", got[3], got[0])
	}
	// The poste still knows what the server holds: the next daily collection,
	// unchanged, stays quiet.
	a.collectInventory(context.Background())
	if inv, _ := a.inventory.pending(); inv != nil {
		t.Error("an unchanged collection after a resend is pending again")
	}
}

// A server that goes on asking gets one block per request, on the heartbeat
// that follows — and the answer to the heartbeat that carried the block is not
// a request: the server had just been handed what that answer asks for.
func TestResendInventoryIsAnsweredOncePerRequest(t *testing.T) {
	const resend = `{"commands":[],"resend_inventory":true}`
	srv, seen := heartbeatScript(t, resend, resend, resend, resend, resend, resend)
	asked := stubInventory(t)
	a := pollingAgent(t, srv.URL)

	// Asked before the first collection: nothing to send again, and nothing
	// collected on the polling loop to satisfy it.
	poll(t, a) // 0
	poll(t, a) // 1
	if n := len(asked()); n != 0 {
		t.Fatalf("%d collection(s) run from the polling loop", n)
	}
	a.collectInventory(context.Background())
	poll(t, a) // 2: the first reading, sent as it always is
	poll(t, a) // 3: its answer asked again — it predates the block
	poll(t, a) // 4: the answer to 3 is a request
	poll(t, a) // 5

	got := seen()
	if len(got) != 6 {
		t.Fatalf("%d heartbeat(s) received, want 6", len(got))
	}
	for i, want := range []bool{false, false, true, false, true, false} {
		if (got[i] != nil) != want {
			t.Errorf("heartbeat %d: inventory attached = %v, want %v", i, got[i] != nil, want)
		}
	}
	if n := len(asked()); n != 1 {
		t.Errorf("%d collection(s), want the one the test ran: a resend re-offers, it does not collect", n)
	}
}

// ReportSoftware = 0 holds for a resend like for any other report: the block
// goes again, hardware only, and the program list is never read.
func TestResendInventoryRespectsReportSoftware(t *testing.T) {
	srv, seen := heartbeatScript(t, `{"commands":[]}`, `{"commands":[],"resend_inventory":true}`)
	asked := stubInventory(t)
	a := pollingAgent(t, srv.URL)
	off := false
	a.cfg.ReportSoftware = &off

	a.collectInventory(context.Background())
	poll(t, a) // 0: first reading
	poll(t, a) // 1: the server asks
	poll(t, a) // 2: re-sent

	got := seen()
	if len(got) != 3 || got[0] == nil || got[1] != nil || got[2] == nil {
		t.Fatalf("inventory attached to heartbeats: %v", got)
	}
	if len(got[2].Software) != 0 || got[2].Hash != "hardware-only" {
		t.Errorf("re-sent %+v, want the hardware and no software", got[2])
	}
	for _, withSoftware := range asked() {
		if withSoftware {
			t.Error("the software list was read on a poste told not to report it")
		}
	}
}

// The configuration's three switches reach the collection as they are set.
func TestInventoryOptionsFollowTheSwitches(t *testing.T) {
	a := &Agent{cfg: config.DefaultConfig()}
	if got := a.inventoryOptions(); got != (collector.InventoryOptions{Software: true}) {
		t.Fatalf("defaults: got %+v", got)
	}
	on, off := true, false
	a.cfg.ReportSoftware = &off
	a.cfg.ReportLocalAdmins = &on
	a.cfg.ReportWingetPackages = &on
	want := collector.InventoryOptions{Software: false, LocalAdmins: true, WingetPackages: true}
	if got := a.inventoryOptions(); got != want {
		t.Fatalf("switched: got %+v, want %+v", got, want)
	}
}

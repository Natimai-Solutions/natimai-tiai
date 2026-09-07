package collector

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/yusufpapurcu/wmi"

	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
)

const defenderNamespace = `root\Microsoft\Windows\Defender`

// wmiClient tolerates Defender's large class schemas (AllowMissingFields) and
// maps WMI NULLs to nil pointers (PtrNil) so absent timestamps stay nil.
//
// NonePtrZero does the same for the fields that are *not* pointers, and the
// inventory is why it is here: its raw rows are plain strings and integers, and
// a property WMI hands back empty rather than null — a motherboard serial no OEM
// flashed, a resolution on an adapter nothing is plugged into — would otherwise
// come back as an error for the whole class instead of as the zero value.
var wmiClient = &wmi.Client{AllowMissingFields: true, PtrNil: true, NonePtrZero: true}

// wmiQueryTimeout is how long one WMI query may run before the agent stops
// waiting for it.
//
// Generous, because a first MSFT_MpComputerStatus on a loaded poste takes tens
// of seconds and must not be mistaken for a hang. But finite, because the
// alternative is the failure that produced "starting, identity, then nothing":
// the WMI library serialises every query in the process behind one mutex, a
// provider that never answers (BitLocker's, the Storage one, Defender's on a
// broken repository) keeps that mutex for good, and from then on every
// heartbeat blocks on its first Defender read — no error, no log line, no
// contact, a poste shown off while it is on, and a service the SCM still calls
// Running because nothing in it ever returned.
const wmiQueryTimeout = 90 * time.Second

// wmiStuck is set while a query is overdue, and cleared when it finally returns.
var wmiStuck atomic.Bool

// queryNamespace runs a WMI query against a namespace on a locked OS thread
// (COM apartment hygiene for a long-running service), bounded by
// wmiQueryTimeout.
//
// A field mismatch is logged and swallowed, and that is not indulgence: the
// library reports it *after* filling the destination, so the rows are there and
// only one property of them could not be mapped. Returning it would have every
// caller throw away a complete reading — and for the inventory, whose first
// query is its one hard failure, a single unmappable property on
// Win32_ComputerSystem would cost the whole machine's hardware and software
// report, day after day, with one debug line to show for it.
func queryNamespace(query string, dst any, namespace string) error {
	if wmiStuck.Load() {
		return ErrWMIUnavailable
	}

	// On a goroutine of its own so the caller can stop waiting: a COM call has
	// no cancellation, and the only way out of one that never returns is to
	// leave it behind. The destination is written by that goroutine whenever
	// the query does come back — every caller allocates it per call and reads
	// it only on success, so a late write lands on memory nobody looks at.
	start := time.Now()
	done := make(chan error, 1)
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		// Args mirror QueryNamespace: server=nil (local), then the namespace.
		done <- wmiClient.Query(query, dst, nil, namespace)
	}()

	select {
	case err := <-done:
		return tolerateMismatch(query, err)
	case <-time.After(wmiQueryTimeout):
	}

	wmiStuck.Store(true)
	log.Printf("agent: wmi: %q (%s) has not returned after %s — WMI reads are "+
		"skipped until it does; heartbeats continue without them",
		query, namespace, wmiQueryTimeout)
	go func() {
		err := <-done
		wmiStuck.Store(false)
		log.Printf("agent: wmi: the overdue query returned after %s (%v); WMI reads resume",
			time.Since(start).Round(time.Second), err)
	}()
	return ErrWMIUnavailable
}

// tolerateMismatch turns the library's field-mismatch report into a debug line.
func tolerateMismatch(query string, err error) error {
	var mismatch *wmi.ErrFieldMismatch
	if errors.As(err, &mismatch) {
		logging.Debugf("agent: wmi: %s: %v (rows kept)", query, err)
		return nil
	}
	return err
}

// --- State -----------------------------------------------------------------

type mpComputerStatus struct {
	AntivirusEnabled              *bool
	RealTimeProtectionEnabled     *bool
	AntivirusSignatureVersion     string
	AntivirusSignatureLastUpdated *time.Time
	QuickScanEndTime              *time.Time
	FullScanEndTime               *time.Time
	// Added in Windows 10 1903; absent on older builds, which AllowMissingFields
	// turns into an empty string rather than an error.
	AMRunningMode string
}

// ReadDefenderState returns the current Defender status from
// MSFT_MpComputerStatus.
func ReadDefenderState(ctx context.Context) (*models.DefenderState, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	var rows []mpComputerStatus
	if err := queryNamespace("SELECT * FROM MSFT_MpComputerStatus", &rows, defenderNamespace); err != nil {
		return nil, fmt.Errorf("query MSFT_MpComputerStatus: %w", err)
	}
	if len(rows) == 0 {
		return &models.DefenderState{}, nil
	}
	r := rows[0]
	return &models.DefenderState{
		RTPEnabled:           r.RealTimeProtectionEnabled,
		AVEnabled:            r.AntivirusEnabled,
		SignatureVersion:     strings.TrimSpace(r.AntivirusSignatureVersion),
		SignatureLastUpdated: r.AntivirusSignatureLastUpdated,
		SignatureAgeDays:     signatureAgeDays(r.AntivirusSignatureLastUpdated, time.Now().UTC()),
		LastQuickScan:        r.QuickScanEndTime,
		LastFullScan:         r.FullScanEndTime,
		RunningMode:          strings.TrimSpace(r.AMRunningMode),
	}, nil
}

// --- Threats ---------------------------------------------------------------

type mpThreatDetection struct {
	DetectionID          string
	ThreatID             uint64
	ThreatStatusID       uint32
	InitialDetectionTime *time.Time
}

type mpThreat struct {
	ThreatID   uint64
	ThreatName string
	SeverityID uint32
	CategoryID uint32
}

// ReadThreats returns Defender detections joined with the threat catalog. Each
// carries a stable DetectionID used server-side for dedup (plan §2.7).
func ReadThreats(ctx context.Context) ([]models.Threat, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	var detections []mpThreatDetection
	if err := queryNamespace("SELECT * FROM MSFT_MpThreatDetection", &detections, defenderNamespace); err != nil {
		return nil, fmt.Errorf("query MSFT_MpThreatDetection: %w", err)
	}
	if len(detections) == 0 {
		return nil, nil
	}

	// Catalog: ThreatID -> name/severity/category (best-effort; absence is fine).
	catalog := make(map[uint64]mpThreat)
	var threats []mpThreat
	if err := queryNamespace("SELECT * FROM MSFT_MpThreat", &threats, defenderNamespace); err == nil {
		for _, t := range threats {
			catalog[t.ThreatID] = t
		}
	}

	out := make([]models.Threat, 0, len(detections))
	for _, d := range detections {
		t := models.Threat{
			DetectionID: detectionID(d),
			Status:      mapThreatStatus(d.ThreatStatusID),
			DetectedAt:  d.InitialDetectionTime,
		}
		if cat, ok := catalog[d.ThreatID]; ok {
			t.ThreatName = strings.TrimSpace(cat.ThreatName)
			t.Severity = mapSeverity(cat.SeverityID)
			t.Category = mapCategory(cat.CategoryID)
		}
		out = append(out, t)
	}
	return out, nil
}

// detectionID prefers Defender's GUID DetectionID; if absent it falls back to
// the ThreatID so dedup still has a stable key.
func detectionID(d mpThreatDetection) string {
	if id := strings.TrimSpace(d.DetectionID); id != "" {
		return id
	}
	return strconv.FormatUint(d.ThreatID, 10)
}

// --- Actions (PowerShell) --------------------------------------------------

// RunQuickScan triggers a Defender quick scan (blocks until it completes).
func RunQuickScan(ctx context.Context) (string, error) {
	return runPowerShell(ctx, "Start-MpScan -ScanType QuickScan")
}

// RunFullScan triggers a Defender full scan (blocks until it completes).
func RunFullScan(ctx context.Context) (string, error) {
	return runPowerShell(ctx, "Start-MpScan -ScanType FullScan")
}

// UpdateSignatures triggers a Defender signature update.
func UpdateSignatures(ctx context.Context) (string, error) {
	return runPowerShell(ctx, "Update-MpSignature")
}

// runPowerShell executes a script and returns its combined output. Windows
// PowerShell encodes redirected output with the legacy console code page
// (CP850/CP1252 on French systems, never UTF-8), so accented characters would
// become U+FFFD once the bytes are treated as UTF-8 downstream. The wrapper
// captures every stream as text and writes it back as raw UTF-8 bytes,
// bypassing the console encoder — [Console]::OutputEncoding can't be used
// instead, as setting it throws when no console is attached (service context).
// $Error drives the exit code so failures still surface as a non-nil err.
func runPowerShell(ctx context.Context, script string) (string, error) {
	wrapped := "$Error.Clear(); " +
		"try { $out = & { " + script + " } 2>&1 | Out-String } catch { $out = $_ | Out-String }; " +
		"$b = [Text.Encoding]::UTF8.GetBytes($out); " +
		"$s = [Console]::OpenStandardOutput(); $s.Write($b, 0, $b.Length); $s.Flush(); " +
		"if ($Error.Count) { exit 1 }"
	cmd := exec.CommandContext(ctx, "powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("powershell: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return strings.TrimSpace(string(out)), nil
}

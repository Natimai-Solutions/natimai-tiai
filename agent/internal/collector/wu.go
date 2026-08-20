package collector

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"tiai/agent/internal/models"
)

// Windows Update: reading what a machine is missing, and installing it on
// demand (plan-phase2-windows-update.md).
//
// Everything is driven through the **WUA COM API** (`Microsoft.Update.Session`)
// from PowerShell, not through the PSWindowsUpdate module: that module is not
// shipped with Windows, and an agent deployed by GPO cannot assume a machine
// has it — nor should it install one. WUA is in-box on every supported build.
//
// The search deliberately uses whatever update source the machine is configured
// for: on a domain poste that is the WSUS server the GPO points at, and
// overriding it to reach Microsoft Update directly would hand out patches the
// administrator has not approved.
//
// As with the maintenance catalogue, everything in this file is pure — the
// scripts, the criteria, the mappings, the verdicts — so it is unit-testable on
// any platform. Only the execution lives in wu_windows.go.

const (
	// wuSearchTimeout bounds one collection. A WU search is genuinely slow: a
	// poste that has not been patched in a year, on a spinning disk, takes tens
	// of minutes to evaluate its applicability rules. This is a hang detector,
	// not a budget.
	wuSearchTimeout = 30 * time.Minute
)

// Update types, as the server stores them.
const (
	updateTypeSoftware = "software"
	updateTypeDriver   = "driver"
)

// WUA's UpdateType enum: utSoftware = 1, utDriver = 2.
const (
	wuTypeIDSoftware = 1
	wuTypeIDDriver   = 2
)

// OperationResultCode, the verdict WUA returns per update and per operation.
const (
	wuResultNotStarted          = 0
	wuResultInProgress          = 1
	wuResultSucceeded           = 2
	wuResultSucceededWithErrors = 3
	wuResultFailed              = 4
	wuResultAborted             = 5
)

// --- Search criteria --------------------------------------------------------

// wuSearchCriteria builds the WUA search string.
//
// The driver filter is applied *here*, in the criteria, rather than by skipping
// updates after the search: WUA then never downloads or evaluates them, and the
// two install variants differ by one documented token instead of by a loop the
// reader has to trust. Collection (includeDrivers = true) always asks for
// everything — the console shows the drivers and lets the admin decide.
func wuSearchCriteria(includeDrivers bool) string {
	const base = "IsInstalled=0 and IsHidden=0"
	if includeDrivers {
		return base
	}
	return base + " and Type='Software'"
}

// --- The scripts ------------------------------------------------------------

// wuDateHelper renders a WUA timestamp as the UTC ISO 8601 string parseWUTime
// expects. Its own const so a test can run it without searching Windows Update.
//
// WUA already reports these dates in UTC, but the COM marshaller hands the DATE
// back as a DateTime with Kind = Unspecified. ToUniversalTime() then reads that
// as *local* time and shifts it a second time: a poste in Pacific/Tahiti (UTC-10)
// reported timestamps ten hours in the future, which the console — converting
// back to local for display — showed as a search that had not happened yet. So
// the kind we know is stamped on rather than converted, and only a value that
// arrives explicitly Local is shifted.
const wuDateHelper = `
function ConvertTo-WUDate($value) {
  if ($null -eq $value) { return $null }
  try { $d = [datetime]$value } catch { return $null }
  # WUA reports "never" as 1601-01-01 (and sometimes 1900), not as null.
  if ($d.Year -lt 1980) { return $null }
  if ($d.Kind -eq [System.DateTimeKind]::Local) { $d = $d.ToUniversalTime() }
  else { $d = [datetime]::SpecifyKind($d, [System.DateTimeKind]::Utc) }
  return $d.ToString('yyyy-MM-ddTHH:mm:ssZ')
}
`

// wuCollectScript searches for applicable updates and reports the machine's WU
// state. It emits one JSON object, which runPowerShellJSON serialises for it.
//
// The two dates are best-effort in their own try/catch: Microsoft.Update.AutoUpdate
// is absent or throws on a machine whose Automatic Updates are managed away, and
// losing the whole pending list over a missing timestamp would be a poor trade.
const wuCollectScript = wuDateHelper + `

$rebootRequired = $false
try { $rebootRequired = [bool](New-Object -ComObject Microsoft.Update.SystemInfo).RebootRequired } catch { }

$lastSearch = $null
$lastInstall = $null
try {
  $results = (New-Object -ComObject Microsoft.Update.AutoUpdate).Results
  $lastSearch = ConvertTo-WUDate $results.LastSearchSuccessDate
  $lastInstall = ConvertTo-WUDate $results.LastInstallationSuccessDate
} catch { }

$searcher = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
$found = $searcher.Search($CRITERIA)

$updates = @()
foreach ($u in $found.Updates) {
  $categories = @()
  foreach ($c in $u.Categories) { $categories += [string]$c.Name }
  $kbs = @()
  foreach ($k in $u.KBArticleIDs) { $kbs += [string]$k }
  $size = 0
  try { $size = [double]$u.MaxDownloadSize } catch { }
  $updates += @{
    update_id      = [string]$u.Identity.UpdateID
    revision       = [int]$u.Identity.RevisionNumber
    title          = [string]$u.Title
    severity       = [string]$u.MsrcSeverity
    type_id        = [int]$u.Type
    categories     = @($categories)
    kb_article_ids = @($kbs)
    is_downloaded  = [bool]$u.IsDownloaded
    size_bytes     = $size
  }
}

@{
  reboot_required   = $rebootRequired
  last_search_time  = $lastSearch
  last_install_time = $lastInstall
  updates           = @($updates)
}
`

// wuInstallScript searches, accepts the EULAs, downloads and installs.
//
// Updates that can ask the user something are skipped rather than installed:
// the agent runs as LocalSystem in session 0, so nobody would ever see the
// prompt and the install would sit there until the timeout killed it.
//
// The installer is only ever handed updates that are actually downloaded —
// Install() fails the whole batch otherwise, which would turn one machine's
// failed download into "no updates installed at all".
const wuInstallScript = `
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$found = $searcher.Search($CRITERIA)

$selected = New-Object -ComObject Microsoft.Update.UpdateColl
$skippedInteractive = 0
foreach ($u in $found.Updates) {
  if ($u.InstallationBehavior.CanRequestUserInput) { $skippedInteractive++; continue }
  if (-not $u.EulaAccepted) { try { $u.AcceptEula() } catch { continue } }
  $selected.Add($u) | Out-Null
}

$toDownload = New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($u in $selected) { if (-not $u.IsDownloaded) { $toDownload.Add($u) | Out-Null } }
if ($toDownload.Count -gt 0) {
  $downloader = $session.CreateUpdateDownloader()
  $downloader.Updates = $toDownload
  $downloader.Download() | Out-Null
}

$toInstall = New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($u in $selected) { if ($u.IsDownloaded) { $toInstall.Add($u) | Out-Null } }

$results = @()
$rebootRequired = $false
$resultCode = 2
if ($toInstall.Count -gt 0) {
  $installer = $session.CreateUpdateInstaller()
  $installer.Updates = $toInstall
  $outcome = $installer.Install()
  $rebootRequired = [bool]$outcome.RebootRequired
  $resultCode = [int]$outcome.ResultCode
  for ($i = 0; $i -lt $toInstall.Count; $i++) {
    $u = $toInstall.Item($i)
    $r = $outcome.GetUpdateResult($i)
    $kbs = @()
    foreach ($k in $u.KBArticleIDs) { $kbs += [string]$k }
    $results += @{
      title          = [string]$u.Title
      kb_article_ids = @($kbs)
      result_code    = [int]$r.ResultCode
      hresult        = [int]$r.HResult
    }
  }
}

# Re-read after installing: an update that needs a restart only says so now.
try { $rebootRequired = $rebootRequired -or [bool](New-Object -ComObject Microsoft.Update.SystemInfo).RebootRequired } catch { }

@{
  selected            = $selected.Count
  skipped_interactive = $skippedInteractive
  installed           = $toInstall.Count
  result_code         = $resultCode
  reboot_required     = $rebootRequired
  updates             = @($results)
}
`

// buildWUScript substitutes the search criteria into a script.
//
// The only value that ever varies, and it is built here from a bool — never
// taken from the network. The wire still carries a command *type* and nothing
// else, which is the whole security model of the command catalogue.
//
// The quotes are doubled, which is PowerShell's escape inside a single-quoted
// string, because the criteria itself contains them: Type='Software'. Pasted in
// raw it closes the literal mid-string and the script does not parse at all —
// on the *driver-excluding* variant, which is the one wu_install uses.
func buildWUScript(script string, includeDrivers bool) string {
	criteria := strings.ReplaceAll(wuSearchCriteria(includeDrivers), "'", "''")
	return strings.ReplaceAll(script, "$CRITERIA", "'"+criteria+"'")
}

// --- Parsing the collection -------------------------------------------------

// rawWUUpdate is one update as the script reports it.
type rawWUUpdate struct {
	UpdateID     string   `json:"update_id"`
	Revision     int      `json:"revision"`
	Title        string   `json:"title"`
	Severity     string   `json:"severity"`
	TypeID       int      `json:"type_id"`
	Categories   []string `json:"categories"`
	KBArticleIDs []string `json:"kb_article_ids"`
	IsDownloaded bool     `json:"is_downloaded"`
	SizeBytes    float64  `json:"size_bytes"`
}

// rawWUState is the collection script's output.
//
// The two dates are strings, not time.Time: a value the script could not make
// sense of must cost that one field, not the whole pending list to an unmarshal
// error. Same spirit as the backend's degrade-don't-422 fields.
type rawWUState struct {
	RebootRequired  bool          `json:"reboot_required"`
	LastSearchTime  string        `json:"last_search_time"`
	LastInstallTime string        `json:"last_install_time"`
	Updates         []rawWUUpdate `json:"updates"`
}

// parseWUState turns the collection script's JSON into the wire block.
func parseWUState(data []byte) (*models.WUState, error) {
	var raw rawWUState
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse windows update state: %w", err)
	}

	// Never nil: an empty list is the report of a fully patched machine, and the
	// server replaces its stored set with it.
	pending := make([]models.PendingUpdate, 0, len(raw.Updates))
	for _, u := range raw.Updates {
		if strings.TrimSpace(u.UpdateID) == "" {
			// Nothing for the server to key on, and nothing we could install.
			continue
		}
		pending = append(pending, models.PendingUpdate{
			UpdateID:     updateKey(u.UpdateID, u.Revision),
			KB:           formatKB(u.KBArticleIDs),
			Title:        strings.TrimSpace(u.Title),
			Severity:     normalizeSeverity(u.Severity),
			Type:         mapUpdateType(u.TypeID, u.Categories),
			Categories:   trimStrings(u.Categories),
			IsDownloaded: u.IsDownloaded,
			SizeMB:       bytesToMB(u.SizeBytes),
		})
	}

	return &models.WUState{
		RebootRequired:  raw.RebootRequired,
		LastSearchTime:  parseWUTime(raw.LastSearchTime),
		LastInstallTime: parseWUTime(raw.LastInstallTime),
		Pending:         pending,
	}, nil
}

// updateKey combines WUA's UpdateID with its revision number.
//
// Microsoft revises an update in place, keeping the UpdateID: the revised one is
// a different thing to install, so collapsing the two onto one server-side row
// would silently hide the revision. A missing revision degrades to the bare id
// rather than to a misleading ".0".
func updateKey(id string, revision int) string {
	id = strings.TrimSpace(id)
	if revision <= 0 {
		return id
	}
	return fmt.Sprintf("%s.%d", id, revision)
}

// formatKB renders the KB article the console displays.
//
// WUA reports the bare digits ("5063878") in a list that is usually one entry
// and occasionally none — most drivers carry no KB at all. The rare multi-KB
// update reports them all, comma-separated, rather than losing the extras: the
// value is read by a human looking a number up, not parsed.
func formatKB(ids []string) string {
	kbs := make([]string, 0, len(ids))
	for _, id := range ids {
		id = strings.TrimSpace(id)
		if id == "" {
			continue
		}
		if !strings.HasPrefix(strings.ToUpper(id), "KB") {
			id = "KB" + id
		}
		kbs = append(kbs, strings.ToUpper(id))
	}
	return strings.Join(kbs, ", ")
}

// normalizeSeverity lowercases the MSRC rating (Critical / Important /
// Moderate / Low), which is what the console colours by. Unrated updates —
// most of them — report an empty string, and that is reported as-is rather than
// invented into a "low".
func normalizeSeverity(severity string) string {
	return strings.ToLower(strings.TrimSpace(severity))
}

// mapUpdateType tells a driver from a software update.
//
// IUpdate.Type is the authoritative signal and is checked first. The category
// fallback exists for the machines where the property comes back as 0 — an
// older WUA, or a COM shim that did not marshal the enum — and it matters:
// installing drivers is the one thing the two install variants differ on, so
// mislabelling one puts it in the wrong bucket in the console.
func mapUpdateType(typeID int, categories []string) string {
	switch typeID {
	case wuTypeIDDriver:
		return updateTypeDriver
	case wuTypeIDSoftware:
		return updateTypeSoftware
	}
	for _, c := range categories {
		if strings.EqualFold(strings.TrimSpace(c), "Drivers") {
			return updateTypeDriver
		}
	}
	return updateTypeSoftware
}

// maxPlausibleDownloadBytes is where a reported size stops meaning anything.
//
// MaxDownloadSize is a *ceiling*, not a measurement: WUA sums every payload the
// update could conceivably need — full package and express/delta variants, each
// architecture, each language — where exactly one of them is ever fetched. On a
// driver, which ships a single payload, that ceiling is the size, which is why
// those read true. On a cumulative update it is not: KB5121003 reports
// 97 304 266 124 bytes — ninety gigabytes — for a download of about one.
//
// So a bound, above which the figure carries no information at all and a dash is
// the more honest answer. Ten gibibytes leaves an order of magnitude over the
// largest download Windows legitimately ships (a feature update, four to six),
// and still catches the values that were destroying trust in the column.
//
// It does not, and cannot, rescue a ceiling that is merely inflated rather than
// absurd — a Defender definition update reporting 1.4 GiB for some 150 MB. That
// is why the console labels the column a maximum instead of a size.
const maxPlausibleDownloadBytes = 10 * 1024 * 1024 * 1024

// bytesToMB converts WUA's MaxDownloadSize, rounded to a tenth of a mebibyte.
//
// Three ends, all deliberate. Zero means "WUA reported no size", which is nil —
// not a claim that the update is empty. A real but tiny download (many driver
// extensions are tens of kilobytes) floors at 0.1 rather than rounding to 0.0,
// which the console would render as "0 Mio" next to an update that plainly has
// something to fetch. And anything past maxPlausibleDownloadBytes is nil too:
// see there.
func bytesToMB(size float64) *float64 {
	if size <= 0 || size > maxPlausibleDownloadBytes {
		return nil
	}
	mb := float64(int64(size/(1024*1024)*10+0.5)) / 10
	if mb == 0 {
		mb = 0.1
	}
	return &mb
}

// trimStrings cleans the category names, dropping empties. Returns nil for an
// empty result so the field is simply omitted from the payload.
func trimStrings(values []string) []string {
	out := make([]string, 0, len(values))
	for _, v := range values {
		if v = strings.TrimSpace(v); v != "" {
			out = append(out, v)
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

// parseWUTime reads a timestamp the script formatted as UTC ISO 8601. Anything
// else — absent, empty, or unparseable — is nil: the console renders a dash,
// which is honest, where a zero time would read as January 1st year one.
func parseWUTime(value string) *time.Time {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil
	}
	t, err := time.Parse(time.RFC3339, value)
	if err != nil || t.IsZero() {
		return nil
	}
	utc := t.UTC()
	return &utc
}

// --- Reading an install -----------------------------------------------------

// rawWUInstallUpdate is one update's outcome.
type rawWUInstallUpdate struct {
	Title        string   `json:"title"`
	KBArticleIDs []string `json:"kb_article_ids"`
	ResultCode   int      `json:"result_code"`
	HResult      int      `json:"hresult"`
}

// rawWUInstall is the install script's output.
type rawWUInstall struct {
	Selected           int                  `json:"selected"`
	SkippedInteractive int                  `json:"skipped_interactive"`
	Installed          int                  `json:"installed"`
	ResultCode         int                  `json:"result_code"`
	RebootRequired     bool                 `json:"reboot_required"`
	Updates            []rawWUInstallUpdate `json:"updates"`
}

// wuResultLabel names an OperationResultCode in the console's language.
func wuResultLabel(code int) string {
	switch code {
	case wuResultSucceeded:
		return "installée"
	case wuResultSucceededWithErrors:
		return "installée avec des erreurs"
	case wuResultFailed:
		return "échec"
	case wuResultAborted:
		return "abandonnée"
	case wuResultInProgress:
		return "encore en cours"
	default:
		return "non démarrée"
	}
}

// wuResultOK reports whether a code counts as applied. Succeeded-with-errors
// counts: the update *is* installed, and a side effect that failed is worth
// showing without turning the whole command red.
func wuResultOK(code int) bool {
	return code == wuResultSucceeded || code == wuResultSucceededWithErrors
}

// summarizeInstall turns the install script's JSON into what the console shows.
//
// The output is built in both outcomes, success and failure alike: for these
// operations the per-KB breakdown *is* the useful part, and an error with no
// list behind it would send an administrator to the machine's own WU log — the
// thing this feature exists to avoid.
func summarizeInstall(data []byte) (string, error) {
	var raw rawWUInstall
	if err := json.Unmarshal(data, &raw); err != nil {
		return "", fmt.Errorf("parse windows update install result: %w", err)
	}

	var lines []string
	switch {
	case raw.Selected == 0 && raw.SkippedInteractive == 0:
		// A success, not a failure: the machine is up to date, which is exactly
		// what the command was asked to achieve.
		lines = append(lines, "Aucune mise à jour applicable : le poste est à jour.")
	case raw.Selected == 0:
		lines = append(lines, "Aucune mise à jour installable sans intervention sur le poste.")
	default:
		lines = append(lines, fmt.Sprintf("%d mise(s) à jour retenue(s), %d installée(s).",
			raw.Selected, raw.Installed))
	}
	if raw.SkippedInteractive > 0 {
		lines = append(lines, fmt.Sprintf(
			"%d ignorée(s) : elles réclament une interaction utilisateur, impossible depuis un service.",
			raw.SkippedInteractive))
	}

	failed := 0
	for _, u := range raw.Updates {
		if !wuResultOK(u.ResultCode) {
			failed++
		}
		lines = append(lines, formatInstalledUpdate(u))
	}
	// Retained but never handed to the installer: their download is what failed.
	// Counted separately because WUA reports no per-update result for them —
	// they would otherwise vanish from the summary entirely.
	if missing := raw.Selected - raw.Installed; missing > 0 {
		failed += missing
		lines = append(lines, fmt.Sprintf(
			"%d mise(s) à jour n'ont pas pu être téléchargée(s), et n'ont donc pas été installée(s).",
			missing))
	}

	if raw.RebootRequired {
		lines = append(lines,
			"", "Redémarrage requis pour finaliser l'installation (commande « Redémarrer »).")
	}

	output := strings.Join(lines, "\n")
	if failed > 0 {
		return output, fmt.Errorf("%d mise(s) à jour sur %d n'ont pas été installées",
			failed, raw.Selected)
	}
	// The global code is checked last: it can report an overall failure even
	// when every individual update went through (an aborted batch, typically).
	if raw.Installed > 0 && !wuResultOK(raw.ResultCode) {
		return output, fmt.Errorf("installation %s (code %d)",
			wuResultLabel(raw.ResultCode), raw.ResultCode)
	}
	return output, nil
}

// formatInstalledUpdate renders one update's outcome: "KB5063878 — Titre :
// installée". The HRESULT is shown in hex only when something went wrong —
// 0x8007000d is searchable, 134217741 is not — and never on a success, where it
// is always zero and only adds noise.
func formatInstalledUpdate(u rawWUInstallUpdate) string {
	name := formatKB(u.KBArticleIDs)
	title := strings.TrimSpace(u.Title)
	switch {
	case name == "":
		name = title
	case title != "":
		name = name + " — " + title
	}
	if wuResultOK(u.ResultCode) && u.HResult == 0 {
		return fmt.Sprintf("%s : %s", name, wuResultLabel(u.ResultCode))
	}
	return fmt.Sprintf("%s : %s (0x%08x)", name, wuResultLabel(u.ResultCode), uint32(u.HResult))
}

// --- Diagnosing a failure ---------------------------------------------------

// wuErrorHints maps the Windows Update result codes an administrator actually
// meets in a managed parc to a sentence that says what to *do*. WUA's own
// message says "Exception from HRESULT: 0x8024402C" and stops there.
//
// Only documented codes are translated, like the maintenance verdicts: anything
// else is reported raw rather than guessed at, because a confidently wrong
// diagnosis on a console screen costs more than a bare number.
var wuErrorHints = []struct {
	code string
	hint string
}{
	{"0x80070422", "le service Windows Update (wuauserv) est désactivé sur ce poste"},
	{"0x8024402c", "la source de mises à jour est injoignable : le poste ne résout pas le nom de son serveur WSUS (ou de Windows Update)"},
	{"0x80072ee2", "délai dépassé en joignant la source de mises à jour : réseau, proxy ou serveur WSUS indisponible"},
	{"0x8024002e", "l'accès à Windows Update est interdit par stratégie : ce poste doit passer par son serveur WSUS"},
	{"0x80248014", "service de mises à jour inconnu : la configuration WSUS du poste pointe vers un service qui n'existe pas"},
	{"0x80244022", "le serveur de mises à jour a répondu « service indisponible » (HTTP 503)"},
	{"0x80240016", "une autre installation est déjà en cours (TrustedInstaller occupé) : réessayer plus tard"},
	{"0x80240438", "aucune source de mises à jour n'est configurée sur ce poste"},
}

// wuErrorHint returns an actionable sentence for a known WU failure, or "".
func wuErrorHint(message string) string {
	lower := strings.ToLower(message)
	for _, h := range wuErrorHints {
		if strings.Contains(lower, h.code) {
			return h.hint
		}
	}
	return ""
}

// wrapWUError adds the hint above to a raw WUA failure, keeping the original
// message: the hint is a reading of the code, not a replacement for it.
func wrapWUError(err error) error {
	if err == nil {
		return nil
	}
	if hint := wuErrorHint(err.Error()); hint != "" {
		return fmt.Errorf("%s (%w)", hint, err)
	}
	return err
}

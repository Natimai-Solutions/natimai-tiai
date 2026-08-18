package collector

import (
	"strings"

	"tiai/agent/internal/models"
)

// The Windows Security Center (WMI namespace root\SecurityCenter2, class
// AntiVirusProduct) is the only place a *third-party* antivirus is visible:
// MSFT_MpComputerStatus describes Defender and nothing else, so a machine
// guarded by ESET or Bitdefender reads there as "Defender off" and nowhere as
// "protected". Every antivirus that wants Windows to stop nagging the user
// registers here, which makes this registry authoritative for the one question
// the console asks: which product guards this machine, and is it running.
//
// Two things it deliberately does not give us, which is why the scope stops at
// read-only: no signature *version* or date (vendors expose none through the
// Security Center, only a freshness bit), and no way to drive an update.

// rawAVProduct is one registered product as read from AntiVirusProduct. Kept out
// of the //go:build windows file so the decoding and the election stay
// compilable — and unit-testable — off Windows, like rawSession and rawAddress.
type rawAVProduct struct {
	Name         string // displayName, e.g. "ESET Endpoint Security"
	State        uint32 // productState bitfield, see decodeProductState
	InstanceGUID string // instanceGuid; Defender's is well-known
	ProductExe   string // pathToSignedProductExe; a URI for Defender
}

// productState is an undocumented three-byte field, 0xTTRRSS, that every
// registered product fills in: TT flags the product type, RR the real-time
// protection state, SS the signature freshness. Microsoft documents the layout
// nowhere — the supported reading is the wscapi COM API, which a WMI query
// cannot reach — so only the values actually observed in the field are decoded,
// and anything else is reported as *unknown* rather than guessed at. A wrongly
// asserted "protection disabled" on a console screen is worse than a dash.
const (
	avStateRTPShift = 8
	avStateByteMask = 0xff
)

// decodeProductState reads the real-time-protection and signature bytes of
// productState. Both results are tri-state: nil means the product reported a
// value we do not know how to read.
func decodeProductState(state uint32) (enabled, signaturesUpToDate *bool) {
	// 0x10 / 0x11: protection running. 0x00 / 0x01: stopped.
	switch (state >> avStateRTPShift) & avStateByteMask {
	case 0x10, 0x11:
		enabled = boolPtr(true)
	case 0x00, 0x01:
		enabled = boolPtr(false)
	}
	// 0x00: definitions current. 0x10: out of date. Vendors are uneven about
	// refreshing this byte, which is why the server treats an unknown freshness
	// as acceptable and only an explicit "out of date" as a problem.
	switch state & avStateByteMask {
	case 0x00:
		signaturesUpToDate = boolPtr(true)
	case 0x10:
		signaturesUpToDate = boolPtr(false)
	}
	return enabled, signaturesUpToDate
}

// buildAVProductState turns the registered products into the wire block.
//
// An empty list yields an empty — but non-nil — block: "no antivirus registered
// at all" is a real state, worth storing and worth showing. The caller
// distinguishes it from "the agent could not look" by returning nil there
// instead, which leaves the server's last known value alone.
func buildAVProductState(products []rawAVProduct) *models.AVProductState {
	elected := electAVProduct(products)
	if elected == nil {
		return &models.AVProductState{}
	}
	enabled, upToDate := decodeProductState(elected.State)
	return &models.AVProductState{
		Name:               strings.TrimSpace(elected.Name),
		Enabled:            enabled,
		SignaturesUpToDate: upToDate,
		IsDefender:         isDefenderProduct(*elected),
	}
}

// electAVProduct picks the product to report. Nameless entries are skipped:
// there is nothing to display and nothing to search on.
func electAVProduct(products []rawAVProduct) *rawAVProduct {
	var best *rawAVProduct
	for i := range products {
		p := &products[i]
		if strings.TrimSpace(p.Name) == "" {
			continue
		}
		if best == nil || betterAVProduct(*p, *best) {
			best = p
		}
	}
	return best
}

// betterAVProduct reports whether a outranks b. Several registered products is
// the normal case, not the exception: Defender stays registered next to the
// third-party antivirus that pushed it into passive mode. Criteria, most
// significant first:
//
//  1. a running product before a stopped one — what protects the machine *now*
//     is the question being asked. An unknown state ranks between the two: it
//     may well be running, and a product whose bitfield we cannot read should
//     not lose to one that is explicitly off.
//  2. a third party before Defender — when both are running, Windows has handed
//     protection to the third party and Defender is passive. Defender's own WMI
//     class still reports itself as enabled in that situation, which is exactly
//     the trap this collector exists to sidestep.
//  3. lowest name — an arbitrary but *stable* tie-break, so a machine with two
//     third-party antivirus products installed (pathological, and real) does not
//     flap between them from one poll to the next.
func betterAVProduct(a, b rawAVProduct) bool {
	aEnabled, _ := decodeProductState(a.State)
	bEnabled, _ := decodeProductState(b.State)
	if ra, rb := enabledRank(aEnabled), enabledRank(bEnabled); ra != rb {
		return ra > rb
	}
	if ad, bd := isDefenderProduct(a), isDefenderProduct(b); ad != bd {
		return !ad
	}
	return a.Name < b.Name
}

// enabledRank orders the tri-state protection flag: running, unknown, stopped.
func enabledRank(enabled *bool) int {
	switch {
	case enabled == nil:
		return 1
	case *enabled:
		return 2
	default:
		return 0
	}
}

// defenderInstanceGUID is the instanceGuid Microsoft Defender has registered
// under since Windows 8 — stable across releases and languages, unlike anything
// user-facing.
const defenderInstanceGUID = "{d68ddc3a-831f-4fae-9e44-da132c1acf46}"

// isDefenderProduct tells Defender's own entry from a third party's. The answer
// travels to the server rather than being re-derived there: matching product
// names in the backend would be brittle, and the agent is where the evidence
// sits. Three signals, most reliable first — any one match is enough, and the
// worst case of a miss is a machine labelled with Defender's name where it could
// have said "no third-party antivirus".
func isDefenderProduct(p rawAVProduct) bool {
	if strings.EqualFold(strings.TrimSpace(p.InstanceGUID), defenderInstanceGUID) {
		return true
	}
	// Not a path but a URI scheme: Defender is in-box, so the Security Center
	// has no executable of its own to launch and registers "windowsdefender://".
	if strings.HasPrefix(strings.ToLower(strings.TrimSpace(p.ProductExe)), "windowsdefender:") {
		return true
	}
	// Last resort, should a future build change either of the above. Matched on
	// the *qualified* names Microsoft has shipped, never on a bare "defender":
	// "Bitdefender" contains it, and misreading a third-party antivirus as
	// Defender is precisely the failure this collector must not make. The vendor
	// prefix stays untranslated in displayName on a localized Windows, unlike
	// every other string the Security Center exposes.
	name := strings.ToLower(p.Name)
	return strings.Contains(name, "windows defender") ||
		strings.Contains(name, "microsoft defender")
}

// boolPtr lifts a bool into the tri-state pointers the wire types use, where nil
// means "not reported" rather than false.
func boolPtr(v bool) *bool { return &v }

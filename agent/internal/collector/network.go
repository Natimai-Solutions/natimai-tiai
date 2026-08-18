package collector

import (
	"bytes"
	"net"
)

// rawAddress is one unicast address of one adapter, carried with the two
// adapter-level facts the election needs: whether that adapter reaches a
// network at all (it has a default gateway) and how Windows itself ranks it
// (interface metric). Kept out of the //go:build windows file so the election
// stays compilable — and unit-testable — off Windows, like rawSession.
type rawAddress struct {
	IP         net.IP
	IfIndex    uint32 // adapter index; tie-break only, meaningless on its own
	Metric     uint32 // route metric of the owning adapter, for this IP family
	HasGateway bool   // the adapter has a default gateway
}

// usableAddress rejects the addresses that never identify a machine on the
// network:
//
//   - loopback (127.0.0.0/8, ::1) — every machine has one, it designates none;
//   - link-local: 169.254.0.0/16, the address Windows gives itself when the
//     DHCP lease fails (APIPA) and which reaches nothing outside its own
//     network segment, plus its IPv6 counterpart fe80::/10;
//   - the unspecified address (0.0.0.0, ::), reported by an adapter that holds
//     no address yet.
func usableAddress(ip net.IP) bool {
	if ip == nil || ip.IsUnspecified() {
		return false
	}
	return !ip.IsLoopback() && !ip.IsLinkLocalUnicast() && !ip.IsMulticast()
}

// electAddress picks the single address to report when a machine has several —
// a laptop docked *and* on Wi-Fi, a server with two NICs, a workstation running
// Hyper-V, WSL or VirtualBox. It returns "" when no address qualifies, which
// the caller reports as "no address" rather than as an error.
func electAddress(addrs []rawAddress) string {
	var best *rawAddress
	for i := range addrs {
		a := &addrs[i]
		if !usableAddress(a.IP) {
			continue
		}
		if best == nil || betterAddress(*a, *best) {
			best = a
		}
	}
	if best == nil {
		return ""
	}
	return best.IP.String()
}

// betterAddress reports whether a outranks b. Criteria, most significant first:
//
//  1. IPv4 before IPv6 — the parc is addressed in v4 and that is the address an
//     admin will ping or RDP; an IPv6 is reported only for a machine that has
//     no v4 at all.
//  2. an adapter with a default gateway before one without — this is what
//     separates the real NIC from the host-only virtual switches (Hyper-V
//     vEthernet, WSL, VirtualBox, VMware) which carry an address but reach no
//     network, and which no name-based heuristic would catch reliably.
//  3. lowest interface metric — Windows' own routing preference, so a docked
//     Ethernet wins over the Wi-Fi that is still associated.
//  4. lowest interface index, then lowest address: an arbitrary but *stable*
//     tie-break, so the reported address doesn't flap from one poll to the next
//     on a machine where two adapters are genuinely equivalent.
func betterAddress(a, b rawAddress) bool {
	if av4, bv4 := a.IP.To4() != nil, b.IP.To4() != nil; av4 != bv4 {
		return av4
	}
	if a.HasGateway != b.HasGateway {
		return a.HasGateway
	}
	if a.Metric != b.Metric {
		return a.Metric < b.Metric
	}
	if a.IfIndex != b.IfIndex {
		return a.IfIndex < b.IfIndex
	}
	// To16 on both sides: comparing a 4-byte and a 16-byte form would order on
	// length rather than on value.
	return bytes.Compare(a.IP.To16(), b.IP.To16()) < 0
}

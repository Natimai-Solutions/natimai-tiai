package collector

import (
	"bytes"
	"fmt"
	"net"
	"strings"
)

// rawAddress is one unicast address of one adapter, carried with the
// adapter-level facts the election needs: whether that adapter reaches a
// network at all (it has a default gateway), how Windows itself ranks it
// (interface metric), and the hardware address it is bound to. Kept out of the
// //go:build windows file so the election stays compilable — and unit-testable
// — off Windows, like rawSession.
type rawAddress struct {
	IP  net.IP
	MAC net.HardwareAddr // adapter's physical address; nil when it has none
	// PrefixLen is the on-link prefix length Windows holds for this address —
	// the mask, in other words. 0 means the API did not fill it in.
	PrefixLen  uint8
	IfIndex    uint32 // adapter index; tie-break only, meaningless on its own
	Metric     uint32 // route metric of the owning adapter, for this IP family
	HasGateway bool   // the adapter has a default gateway
}

// NetworkInfo is what one poll reports about this machine's place on the
// network: the address an administrator would reach it at, and the hardware
// address of the adapter holding it.
//
// The two travel together rather than being read by two independent collectors,
// and that is the whole point: a Wake-on-LAN packet is aimed at a MAC *and*
// broadcast on the subnet of an IP, so a MAC belonging to a different adapter
// than the reported address would send the server shouting on the wrong
// network. Electing once and reading both off the winner makes that
// disagreement unrepresentable.
//
// PrefixLength is the mask that goes with IP, and it is here for the same
// reason: it is the poste's *own* network that the packet has to be broadcast
// on. The server used to assume /24 from a setting, which is wrong on every parc
// addressed in /16 or /22 and right by accident on the others — whereas Windows
// has known the answer all along.
//
// Any field may be empty — an adapter with no usable address, a MAC the API
// reports as blank, a prefix it did not fill in — and empty means "nothing to
// report", never "none". Zero is the empty value for the prefix: a /0 is not a
// mask a machine holds.
type NetworkInfo struct {
	IP           string
	MAC          string
	PrefixLength int
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

// elect picks the single address to report when a machine has several — a
// laptop docked *and* on Wi-Fi, a server with two NICs, a workstation running
// Hyper-V, WSL or VirtualBox — and returns it with the MAC of the adapter that
// holds it. The zero NetworkInfo means no address qualified, which the caller
// reports as "no address" rather than as an error.
func elect(addrs []rawAddress) NetworkInfo {
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
		return NetworkInfo{}
	}
	return NetworkInfo{
		IP:           best.IP.String(),
		MAC:          formatMAC(best.MAC),
		PrefixLength: usablePrefixLength(best.IP, best.PrefixLen),
	}
}

// usablePrefixLength keeps a prefix that can describe a network, and returns 0
// for anything else.
//
// Bounded against the address family rather than trusted: Windows before Vista
// left the field at zero, and an adapter can report a value that makes no sense
// for the address it sits on. A /0 is refused too — its broadcast address is
// 255.255.255.255, which from the server would reach the whole world or nothing
// at all, and never the poste. A rejected prefix costs the mask and not the
// address: the server falls back on its configured default, which is exactly
// what it did before this field existed.
func usablePrefixLength(ip net.IP, prefix uint8) int {
	max := uint8(128)
	if ip.To4() != nil {
		max = 32
	}
	if prefix == 0 || prefix > max {
		return 0
	}
	return int(prefix)
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

// macLength is the length of an EUI-48 hardware address — the only kind a
// Wake-on-LAN magic packet can carry, since the pattern the NIC watches for is
// six times the target MAC repeated sixteen times.
const macLength = 6

// formatMAC renders an adapter's physical address as the server expects it, and
// returns "" for anything that is not a wakeable Ethernet/Wi-Fi address.
//
// Three rejections, all of them things GetAdaptersAddresses genuinely returns:
// an empty address (a PPP or tunnel pseudo-adapter has none), an address that
// is not six bytes (an InfiniBand adapter reports twenty), and the all-zero
// address some virtual adapters report in place of nothing. None of the three
// is a MAC a magic packet could wake, and sending one anyway would have the
// console offer a wake that silently does nothing.
//
// Upper case with colons: this is read by an administrator next to the IP
// address, and it is the form Windows itself shows in ipconfig /all (bar the
// hyphens). The server re-normalises whatever arrives, so this is a courtesy,
// not a contract.
func formatMAC(mac net.HardwareAddr) string {
	if len(mac) != macLength {
		return ""
	}
	if bytes.Equal(mac, make([]byte, macLength)) {
		return ""
	}
	parts := make([]string, 0, macLength)
	for _, b := range mac {
		parts = append(parts, fmt.Sprintf("%02X", b))
	}
	return strings.Join(parts, ":")
}

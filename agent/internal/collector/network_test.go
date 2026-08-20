package collector

import (
	"net"
	"testing"
)

func TestUsableAddress(t *testing.T) {
	tests := []struct {
		ip   string
		want bool
	}{
		{"192.168.1.10", true},
		{"10.0.0.5", true},
		{"172.16.4.9", true},
		{"2001:db8::1", true},
		// Every machine has one; it designates none.
		{"127.0.0.1", false},
		{"127.0.0.53", false},
		{"::1", false},
		// APIPA: the DHCP lease failed. Reaches nothing, names nobody.
		{"169.254.10.5", false},
		{"169.254.255.255", false},
		{"fe80::1c2d:3e4f", false},
		// An adapter that holds no address yet.
		{"0.0.0.0", false},
		{"::", false},
	}
	for _, tc := range tests {
		ip := net.ParseIP(tc.ip)
		if ip == nil {
			t.Fatalf("bad fixture %q", tc.ip)
		}
		if got := usableAddress(ip); got != tc.want {
			t.Errorf("usableAddress(%s) = %v, want %v", tc.ip, got, tc.want)
		}
	}
	if usableAddress(nil) {
		t.Error("usableAddress(nil) = true, want false")
	}
}

func TestElectAddress(t *testing.T) {
	addr := func(ip string, index, metric uint32, gw bool) rawAddress {
		return rawAddress{IP: net.ParseIP(ip), IfIndex: index, Metric: metric, HasGateway: gw}
	}

	tests := []struct {
		name  string
		addrs []rawAddress
		want  string
	}{
		{
			name: "no adapter at all",
			want: "",
		},
		{
			name:  "the ordinary case: a single address",
			addrs: []rawAddress{addr("192.168.1.10", 12, 25, true)},
			want:  "192.168.1.10",
		},
		{
			// The exclusions, verified end to end: a machine that has only a
			// loopback and a failed DHCP lease reports nothing.
			name: "loopback and APIPA leave nothing to report",
			addrs: []rawAddress{
				addr("127.0.0.1", 1, 75, false),
				addr("169.254.7.3", 12, 25, false),
			},
			want: "",
		},
		{
			// The reason the metric alone can't decide: the APIPA address sits
			// on the *best* adapter here.
			name: "APIPA is skipped even on the best-ranked adapter",
			addrs: []rawAddress{
				addr("169.254.7.3", 12, 5, true),
				addr("10.0.0.20", 18, 40, true),
			},
			want: "10.0.0.20",
		},
		{
			name: "IPv4 wins over IPv6 on the same adapter",
			addrs: []rawAddress{
				addr("2001:db8::20", 12, 25, true),
				addr("192.168.1.10", 12, 25, true),
			},
			want: "192.168.1.10",
		},
		{
			name:  "IPv6 is reported when there is no IPv4",
			addrs: []rawAddress{addr("2001:db8::20", 12, 25, true)},
			want:  "2001:db8::20",
		},
		{
			// Hyper-V / WSL / VirtualBox: an address on a switch that reaches
			// no network, and often a better metric than the real NIC.
			name: "a gateway beats a host-only virtual switch",
			addrs: []rawAddress{
				addr("172.28.144.1", 40, 5, false),
				addr("192.168.1.10", 12, 25, true),
			},
			want: "192.168.1.10",
		},
		{
			// Docked laptop: Ethernet and Wi-Fi both up and both routed.
			name: "lowest metric wins between two routed adapters",
			addrs: []rawAddress{
				addr("192.168.1.50", 18, 45, true), // Wi-Fi
				addr("192.168.1.10", 12, 25, true), // Ethernet, docked
			},
			want: "192.168.1.10",
		},
		{
			// Stability across polls matters more than which one we pick.
			name: "equivalent adapters break the tie on the interface index",
			addrs: []rawAddress{
				addr("192.168.1.50", 18, 25, true),
				addr("192.168.1.10", 12, 25, true),
			},
			want: "192.168.1.10",
		},
		{
			name: "two addresses on one adapter break the tie on the address",
			addrs: []rawAddress{
				addr("192.168.1.50", 12, 25, true),
				addr("192.168.1.10", 12, 25, true),
			},
			want: "192.168.1.10",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := elect(tc.addrs).IP; got != tc.want {
				t.Errorf("elect().IP = %q, want %q", got, tc.want)
			}
		})
	}
}

// --- The MAC that travels with the elected address -------------------------

// The election reports one adapter, not a machine-wide summary: the MAC has to
// be the one of the adapter actually holding the reported address, or a
// Wake-on-LAN packet would be broadcast on the subnet of one NIC while naming
// another.
func TestElectReportsTheMACOfTheWinningAdapter(t *testing.T) {
	ethernet := net.HardwareAddr{0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33}
	wifi := net.HardwareAddr{0x00, 0x1A, 0x2B, 0x3C, 0x4D, 0x5E}
	virtual := net.HardwareAddr{0x00, 0x15, 0x5D, 0x01, 0x02, 0x03}

	got := elect([]rawAddress{
		// Hyper-V switch: best metric, no gateway — loses, and its MAC with it.
		{IP: net.ParseIP("172.28.144.1"), MAC: virtual, IfIndex: 40, Metric: 5},
		{IP: net.ParseIP("192.168.1.50"), MAC: wifi, IfIndex: 18, Metric: 45, HasGateway: true},
		{IP: net.ParseIP("192.168.1.10"), MAC: ethernet, IfIndex: 12, Metric: 25, HasGateway: true},
	})
	if got.IP != "192.168.1.10" {
		t.Fatalf("elect().IP = %q, want the docked Ethernet address", got.IP)
	}
	if got.MAC != "AA:BB:CC:11:22:33" {
		t.Errorf("elect().MAC = %q, want the Ethernet adapter's own address", got.MAC)
	}
}

// The mask travels with the address for the same reason the MAC does: the packet
// is broadcast on the poste's own subnet, and only the poste knows whether that
// is a /16 or a /24. Guessing it server-side was right by accident on a flat
// /24 parc and wrong everywhere else.
func TestElectReportsThePrefixOfTheWinningAddress(t *testing.T) {
	got := elect([]rawAddress{
		// A /24 on the virtual switch that loses: its mask must not be the one
		// reported, or the packet goes out on a subnet the poste is not on.
		{IP: net.ParseIP("172.28.144.1"), PrefixLen: 24, IfIndex: 40, Metric: 5},
		{
			IP: net.ParseIP("10.4.7.9"), PrefixLen: 16,
			IfIndex: 12, Metric: 25, HasGateway: true,
		},
	})
	if got.IP != "10.4.7.9" {
		t.Fatalf("elect().IP = %q, want the routed address", got.IP)
	}
	if got.PrefixLength != 16 {
		t.Errorf("elect().PrefixLength = %d, want 16", got.PrefixLength)
	}
}

// What the server may be handed as a mask. A rejected prefix costs the mask and
// not the address: the server then falls back on its configured default, which
// is what it did before this field existed.
func TestUsablePrefixLength(t *testing.T) {
	v4 := net.ParseIP("192.168.1.10")
	v6 := net.ParseIP("2001:db8::20")

	tests := []struct {
		name   string
		ip     net.IP
		prefix uint8
		want   int
	}{
		{name: "the ordinary /24", ip: v4, prefix: 24, want: 24},
		{name: "a /16 parc, which is the case that motivated this", ip: v4, prefix: 16, want: 16},
		{name: "a /22, since masks are not all round numbers", ip: v4, prefix: 22, want: 22},
		{
			// A VPN or point-to-point adapter. No broadcast domain to speak of,
			// and the server turns it into a unicast — the honest answer.
			name: "a /32 host route is a mask like any other", ip: v4, prefix: 32, want: 32,
		},
		{name: "an IPv6 prefix is bounded at 128", ip: v6, prefix: 64, want: 64},
		{
			// Zero is both "Windows did not fill the field in" — it never did
			// before Vista, and some adapters still do not — and "/0", whose
			// broadcast address is 255.255.255.255: the whole world, or nothing
			// at all, and never the poste. Neither reading is a usable mask.
			name: "not reported, or a /0", ip: v4, prefix: 0, want: 0,
		},
		{name: "nonsense for the family", ip: v4, prefix: 64, want: 0},
		{name: "beyond any family", ip: v6, prefix: 200, want: 0},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := usablePrefixLength(tc.ip, tc.prefix); got != tc.want {
				t.Errorf("usablePrefixLength(%s, %d) = %d, want %d",
					tc.ip, tc.prefix, got, tc.want)
			}
		})
	}
}

// An adapter can hold a usable address and still have no hardware address worth
// waking. The address is reported all the same — losing the IP because the MAC
// was unreadable would trade a working feature for a missing one.
func TestElectReportsAnAddressWithoutAMAC(t *testing.T) {
	got := elect([]rawAddress{
		{IP: net.ParseIP("10.8.0.6"), IfIndex: 22, Metric: 25, HasGateway: true},
	})
	if got.IP != "10.8.0.6" {
		t.Errorf("elect().IP = %q, want the address anyway", got.IP)
	}
	if got.MAC != "" {
		t.Errorf("elect().MAC = %q, want empty", got.MAC)
	}
	// Same contract on the mask: an unreported prefix is a zero the server reads
	// as "fall back on the configured default", not as a /0.
	if got.PrefixLength != 0 {
		t.Errorf("elect().PrefixLength = %d, want 0", got.PrefixLength)
	}
}

func TestElectReportsNothingWithoutAnAddress(t *testing.T) {
	if got := elect(nil); got != (NetworkInfo{}) {
		t.Errorf("elect(nil) = %+v, want the zero value", got)
	}
}

// What the server may be handed as a wake target. Everything that is not a
// six-byte EUI-48 is dropped rather than forwarded: a magic packet is six times
// the MAC repeated sixteen times, so a twenty-byte InfiniBand address or a
// blank one cannot produce a packet that wakes anything — and a console
// offering a wake that silently does nothing is worse than one not offering it.
func TestFormatMAC(t *testing.T) {
	tests := []struct {
		name string
		mac  net.HardwareAddr
		want string
	}{
		{
			name: "an ordinary Ethernet address, upper case with colons",
			mac:  net.HardwareAddr{0x00, 0x1a, 0x2b, 0x3c, 0x4d, 0x5e},
			want: "00:1A:2B:3C:4D:5E",
		},
		{
			name: "a PPP or tunnel adapter has no hardware address at all",
			mac:  nil,
			want: "",
		},
		{
			name: "InfiniBand reports twenty bytes, which no magic packet carries",
			mac:  make(net.HardwareAddr, 20),
			want: "",
		},
		{
			// Reported by some virtual adapters in place of nothing. It is a
			// valid six-byte string and a meaningless wake target.
			name: "the all-zero address is not an address",
			mac:  make(net.HardwareAddr, 6),
			want: "",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := formatMAC(tc.mac); got != tc.want {
				t.Errorf("formatMAC(%v) = %q, want %q", tc.mac, got, tc.want)
			}
		})
	}
}

// The election must not depend on the order GetAdaptersAddresses happens to
// enumerate adapters in — that order is not contractual, and a reported address
// that flips between two polls would show up as a machine "moving" in the
// console.
func TestElectAddressIsOrderIndependent(t *testing.T) {
	addrs := []rawAddress{
		{IP: net.ParseIP("127.0.0.1"), IfIndex: 1, Metric: 75},
		{IP: net.ParseIP("172.28.144.1"), IfIndex: 40, Metric: 5},
		{IP: net.ParseIP("2001:db8::20"), IfIndex: 12, Metric: 25, HasGateway: true},
		{IP: net.ParseIP("192.168.1.10"), IfIndex: 12, Metric: 25, HasGateway: true},
		{IP: net.ParseIP("192.168.1.50"), IfIndex: 18, Metric: 45, HasGateway: true},
	}
	const want = "192.168.1.10"

	for i := range addrs {
		rotated := append(append([]rawAddress{}, addrs[i:]...), addrs[:i]...)
		if got := elect(rotated).IP; got != want {
			t.Errorf("elect().IP = %q from rotation %d, want %q", got, i, want)
		}
	}
}

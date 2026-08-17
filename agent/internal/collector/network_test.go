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
			if got := electAddress(tc.addrs); got != tc.want {
				t.Errorf("electAddress() = %q, want %q", got, tc.want)
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
		if got := electAddress(rotated); got != want {
			t.Errorf("electAddress() = %q from rotation %d, want %q", got, i, want)
		}
	}
}

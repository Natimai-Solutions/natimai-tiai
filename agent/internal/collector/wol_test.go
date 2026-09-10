package collector

import (
	"bytes"
	"context"
	"errors"
	"net"
	"strings"
	"testing"
)

// The frame is asserted byte for byte: nothing downstream will ever say it was
// wrong, since Wake-on-LAN acknowledges nothing.
func TestMagicPacketIsSixFFThenTheMACSixteenTimes(t *testing.T) {
	hw, err := parseWakeMAC("AA:BB:CC:DD:EE:FF")
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	pkt := magicPacket(hw)
	if len(pkt) != 6+16*6 {
		t.Fatalf("packet length = %d, want 102", len(pkt))
	}
	if !bytes.Equal(pkt[:6], bytes.Repeat([]byte{0xFF}, 6)) {
		t.Errorf("sync stream = % X", pkt[:6])
	}
	if !bytes.Equal(pkt[6:], bytes.Repeat(hw, 16)) {
		t.Errorf("body is not the MAC sixteen times")
	}
}

// Every notation an administrator or a server might write, and the strings
// that are six bytes long and still not a wake target.
func TestParseWakeMAC(t *testing.T) {
	for _, ok := range []string{
		"AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AABB.CCDD.EEFF", "aabbccddeeff", "  AA:BB:CC:DD:EE:FF ",
	} {
		hw, err := parseWakeMAC(ok)
		if err != nil {
			t.Errorf("%q: unexpected error %v", ok, err)
			continue
		}
		if hw.String() != "aa:bb:cc:dd:ee:ff" {
			t.Errorf("%q parsed as %s", ok, hw)
		}
	}
	for _, bad := range []string{
		"", "not a mac", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:FF:00", "GG:BB:CC:DD:EE:FF",
		"00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF",
		// Nothing but hex reaches the parser: a shell metacharacter or a path
		// is refused as "not a MAC", never interpreted.
		"AA:BB:CC:DD:EE:FF; rm -rf /", "C:\\Windows\\x",
	} {
		if _, err := parseWakeMAC(bad); err == nil {
			t.Errorf("%q: expected a refusal", bad)
		}
	}
}

func cidr(t *testing.T, s string) *net.IPNet {
	t.Helper()
	ip, n, err := net.ParseCIDR(s)
	if err != nil {
		t.Fatalf("ParseCIDR(%q): %v", s, err)
	}
	// ParseCIDR zeroes the host bits in n.IP; keep the adapter's own address,
	// which is what iface.Addrs() hands back.
	n.IP = ip
	return n
}

// The destinations are this poste's own subnets and nothing else — the bound
// that makes an argument-carrying command acceptable in the catalogue.
func TestBroadcastAddressesAreThePostesOwnSubnets(t *testing.T) {
	got := broadcastAddresses([]*net.IPNet{
		cidr(t, "192.168.1.42/24"),
		cidr(t, "10.4.7.9/16"),
		cidr(t, "10.4.8.1/16"),    // same subnet as the previous one: one destination
		cidr(t, "127.0.0.1/8"),    // loopback
		cidr(t, "169.254.3.4/16"), // APIPA
		cidr(t, "172.16.0.1/32"),  // no broadcast address at all
		cidr(t, "172.16.0.2/31"),  // nor here
		cidr(t, "2001:db8::1/64"), // IPv6 has no broadcast
	})
	var s []string
	for _, ip := range got {
		s = append(s, ip.String())
	}
	if strings.Join(s, ",") != "192.168.1.255,10.4.255.255" {
		t.Errorf("destinations = %v", s)
	}
}

// RelayWake end to end, with the two seams pinned: what would go on the wire,
// and where.
func TestRelayWakeEmitsOnEachSubnetAndSaysSo(t *testing.T) {
	wolLocalSubnets = func() ([]*net.IPNet, error) {
		return []*net.IPNet{cidr(t, "192.168.1.42/24"), cidr(t, "10.4.7.9/16")}, nil
	}
	defer func() { wolLocalSubnets = localIPv4Subnets }()
	var sentTo []string
	var sentPayload []byte
	var sentCount int
	wolSend = func(_ context.Context, dests []net.IP, port int, payload []byte, count int) error {
		for _, d := range dests {
			sentTo = append(sentTo, d.String())
		}
		sentPayload, sentCount = payload, count
		if port != 9 {
			t.Errorf("port = %d, want 9", port)
		}
		return nil
	}
	defer func() { wolSend = sendDatagrams }()

	out, err := RelayWake(context.Background(), "aa-bb-cc-dd-ee-ff")
	if err != nil {
		t.Fatalf("RelayWake: %v", err)
	}
	if strings.Join(sentTo, ",") != "192.168.1.255,10.4.255.255" {
		t.Errorf("sent to %v", sentTo)
	}
	if sentCount != wolCopies {
		t.Errorf("copies = %d, want %d", sentCount, wolCopies)
	}
	hw, _ := parseWakeMAC("AA:BB:CC:DD:EE:FF")
	if !bytes.Equal(sentPayload, magicPacket(hw)) {
		t.Errorf("payload is not the magic packet")
	}
	// The verdict names the MAC and each destination: an administrator whose
	// poste did not come back reads it to know which wire the frame went on.
	for _, want := range []string{"AA:BB:CC:DD:EE:FF", "192.168.1.255:9", "10.4.255.255:9"} {
		if !strings.Contains(out, want) {
			t.Errorf("output lacks %q:\n%s", want, out)
		}
	}
}

func TestRelayWakeRefusesWithoutASubnetOrWithABadMAC(t *testing.T) {
	wolLocalSubnets = func() ([]*net.IPNet, error) { return nil, nil }
	defer func() { wolLocalSubnets = localIPv4Subnets }()
	sent := false
	wolSend = func(context.Context, []net.IP, int, []byte, int) error { sent = true; return nil }
	defer func() { wolSend = sendDatagrams }()

	if _, err := RelayWake(context.Background(), "AA:BB:CC:DD:EE:FF"); err == nil {
		t.Error("expected a refusal with no IPv4 subnet")
	}
	if _, err := RelayWake(context.Background(), "00:00:00:00:00:00"); err == nil {
		t.Error("expected a refusal on the all-zero MAC")
	}
	if sent {
		t.Error("nothing must be sent on a refusal")
	}
}

func TestRelayWakeReportsASendFailure(t *testing.T) {
	wolLocalSubnets = func() ([]*net.IPNet, error) { return []*net.IPNet{cidr(t, "192.168.1.42/24")}, nil }
	defer func() { wolLocalSubnets = localIPv4Subnets }()
	wolSend = func(context.Context, []net.IP, int, []byte, int) error { return errors.New("network is unreachable") }
	defer func() { wolSend = sendDatagrams }()

	_, err := RelayWake(context.Background(), "AA:BB:CC:DD:EE:FF")
	if err == nil || !strings.Contains(err.Error(), "network is unreachable") {
		t.Errorf("expected the send error to surface, got %v", err)
	}
}

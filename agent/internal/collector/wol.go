package collector

import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"strings"
)

// Relaying a Wake-on-LAN from a poste that is on, for a poste that is off.
//
// The server normally emits the magic packet itself, and can only do so from a
// host on the same broadcast domain as the sleeping machine. A server hosted
// elsewhere — another site, a data centre — has no such host, but the parc
// does: every poste still running on the site is one. So the server may hand a
// `wake_on_lan` to *this* agent, naming the MAC to wake, and this agent puts
// the frame on its own wire.
//
// This is the one command in the catalogue that carries an argument, and the
// bounds below are what make that acceptable (agent/README.md, « Commandes de
// maintenance à distance »):
//
//   - the argument is parsed as an EUI-48 and nothing else. Not a string that
//     reaches a shell, a file or the registry: six bytes, or a refusal;
//   - the destination is never taken from the server. The packet is broadcast
//     on the IPv4 subnets this poste is itself attached to, on UDP/9, and
//     nowhere else — a compromised server cannot aim this agent at an address
//     of its choosing;
//   - the effect is bounded by construction: the worst a forged command can do
//     is wake machines on this segment, which is the feature.

const (
	// wolPort is UDP/9 (discard), the convention. Immaterial to the hardware —
	// a NIC in standby matches the magic pattern anywhere in the frame — so it
	// is a constant rather than a setting the server could vary.
	wolPort = 9
	// wolCopies: a broadcast is unacknowledged and dropped without notice;
	// three copies cost three datagrams and remove the single-loss case. The
	// same count as the server's own default.
	wolCopies = 3
)

// The frame the NIC watches for: six 0xFF bytes, then the target MAC sixteen
// times over (AMD's Magic Packet specification).
var wolSyncStream = bytes.Repeat([]byte{0xFF}, 6)

const wolMACRepeats = 16

// Seams for tests: enumerating this poste's subnets and putting datagrams on
// the wire are the two things a unit test must not do.
var (
	wolLocalSubnets = localIPv4Subnets
	wolSend         = sendDatagrams
)

// RelayWake emits the magic packet for mac on every IPv4 subnet this poste is
// attached to, and says where it went. The text is read by an administrator in
// the command history, so it is in French like the maintenance verdicts, and
// it names the destinations rather than the rule.
//
// A success means the datagrams left this poste, nothing more: Wake-on-LAN is
// unacknowledged, and the poste that never wakes looks exactly like the one
// that does.
func RelayWake(ctx context.Context, mac string) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	hw, err := parseWakeMAC(mac)
	if err != nil {
		return "", err
	}
	subnets, err := wolLocalSubnets()
	if err != nil {
		return "", fmt.Errorf("lecture des cartes réseau de ce poste : %w", err)
	}
	destinations := broadcastAddresses(subnets)
	if len(destinations) == 0 {
		return "", errors.New(
			"ce poste n'a aucun sous-réseau IPv4 sur lequel diffuser le paquet magique")
	}
	payload := magicPacket(hw)
	if err := wolSend(ctx, destinations, wolPort, payload, wolCopies); err != nil {
		return "", fmt.Errorf("émission du paquet magique impossible : %w", err)
	}
	targets := make([]string, 0, len(destinations))
	for _, d := range destinations {
		targets = append(targets, fmt.Sprintf("%s:%d", d, wolPort))
	}
	return fmt.Sprintf(
		"Paquet magique émis vers %s depuis ce poste — %d copie(s) sur %s.\n"+
			"L'émission ne prouve pas le réveil : le protocole n'accuse rien, et le "+
			"poste visé ne réapparaîtra dans la console qu'à la remontée de son agent.",
		formatMAC(hw), wolCopies, strings.Join(targets, ", ")), nil
}

// parseWakeMAC accepts the notations a MAC is written in — colons (what the
// server sends), hyphens (ipconfig), dots (Cisco), nothing — and refuses
// everything that is not a wakeable EUI-48: the wrong length, the all-zero
// address some virtual adapters report in place of nothing, and the Ethernet
// broadcast address. A refusal is a `failed` in the console, worded for the
// administrator who will read it there.
func parseWakeMAC(value string) (net.HardwareAddr, error) {
	cleaned := strings.NewReplacer(":", "", "-", "", ".", "", " ", "").Replace(strings.TrimSpace(value))
	if len(cleaned) != macLength*2 {
		return nil, fmt.Errorf("adresse MAC à réveiller invalide : %q", value)
	}
	raw, err := hex.DecodeString(cleaned)
	if err != nil {
		return nil, fmt.Errorf("adresse MAC à réveiller invalide : %q", value)
	}
	hw := net.HardwareAddr(raw)
	if bytes.Equal(hw, make([]byte, macLength)) || bytes.Equal(hw, bytes.Repeat([]byte{0xFF}, macLength)) {
		return nil, fmt.Errorf("adresse MAC à réveiller invalide : %q", value)
	}
	return hw, nil
}

// magicPacket builds the frame for a parsed MAC.
func magicPacket(hw net.HardwareAddr) []byte {
	return append(append([]byte{}, wolSyncStream...), bytes.Repeat(hw, wolMACRepeats)...)
}

// broadcastAddresses derives one directed-broadcast address per usable IPv4
// subnet, de-duplicated. Loopback and link-local (APIPA) subnets carry no
// poste worth waking; a /31 or /32 has no broadcast address at all. Two
// adapters on the same subnet (a docked laptop still associated to Wi-Fi)
// yield one destination, not two.
func broadcastAddresses(subnets []*net.IPNet) []net.IP {
	var out []net.IP
	seen := map[string]bool{}
	for _, n := range subnets {
		ip := n.IP.To4()
		if ip == nil || !usableAddress(ip) {
			continue
		}
		ones, bits := n.Mask.Size()
		if bits != 32 || ones >= 31 || ones == 0 {
			continue
		}
		bcast := make(net.IP, 4)
		for i := range bcast {
			bcast[i] = ip[i] | ^n.Mask[i]
		}
		if key := bcast.String(); !seen[key] {
			seen[key] = true
			out = append(out, bcast)
		}
	}
	return out
}

// localIPv4Subnets lists the IPv4 subnets of every adapter that is up.
//
// net.Interfaces() rather than GetAdaptersAddresses here, unlike the address
// election: the question is not "which address names this poste" but "which
// wires is it on", and every one of them is a candidate — the standard library
// answers that on Windows and elsewhere alike, which also keeps this testable
// off Windows.
func localIPv4Subnets() ([]*net.IPNet, error) {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil, err
	}
	var out []*net.IPNet
	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, a := range addrs {
			if n, ok := a.(*net.IPNet); ok && n.IP.To4() != nil {
				out = append(out, n)
			}
		}
	}
	return out, nil
}

// sendDatagrams sends count copies of payload to every destination on port.
// One socket for all of them: the kernel routes each directed broadcast out of
// the adapter that holds the matching subnet, and the standard library opens
// UDP sockets with SO_BROADCAST already set on every platform.
func sendDatagrams(ctx context.Context, destinations []net.IP, port int, payload []byte, count int) error {
	conn, err := net.ListenUDP("udp4", nil)
	if err != nil {
		return err
	}
	defer conn.Close()
	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetWriteDeadline(deadline)
	}
	for range count {
		for _, d := range destinations {
			if err := ctx.Err(); err != nil {
				return err
			}
			if _, err := conn.WriteToUDP(payload, &net.UDPAddr{IP: d, Port: port}); err != nil {
				return fmt.Errorf("vers %s : %w", d, err)
			}
		}
	}
	return nil
}

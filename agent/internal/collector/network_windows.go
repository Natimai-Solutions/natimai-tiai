package collector

import (
	"context"
	"errors"
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
)

// gaaFlags: gateways are the one extra we ask for — they are what tells a real
// NIC from a host-only virtual switch (see betterAddress). Everything we don't
// read is skipped, which is both cheaper and a smaller buffer to size.
const gaaFlags = windows.GAA_FLAG_INCLUDE_GATEWAYS |
	windows.GAA_FLAG_SKIP_ANYCAST |
	windows.GAA_FLAG_SKIP_MULTICAST |
	windows.GAA_FLAG_SKIP_DNS_SERVER |
	windows.GAA_FLAG_SKIP_FRIENDLY_NAME

const (
	// initialAdapterBufSize is the 15 KB starting size MSDN recommends for
	// GetAdaptersAddresses: sizing with a first, bufferless call costs a second
	// enumeration and still races the adapter list, so we start big instead.
	initialAdapterBufSize = 15 * 1024
	// adapterBufAttempts bounds the grow-and-retry loop. Two would do in
	// practice; the extra rounds cover an adapter appearing between two calls.
	adapterBufAttempts = 4
)

// ReadIPAddress returns the machine's primary IP address, or "" when it has
// none worth reporting (see usableAddress).
//
// Read on every heartbeat rather than cached at start-up like sysinfo: a DHCP
// renewal, a docking station or a VPN changes the address while the agent keeps
// running, and an address that is a week stale is worse than none.
func ReadIPAddress(ctx context.Context) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	addrs, err := enumerateAddresses()
	if err != nil {
		return "", err
	}
	return electAddress(addrs), nil
}

// enumerateAddresses lists the unicast addresses of every operational adapter.
//
// GetAdaptersAddresses, not net.Interfaces(): the stdlib exposes neither the
// interface metric nor the presence of a default gateway, which are precisely
// what makes the choice between several addresses deterministic instead of
// heuristic (plan: no name-matching on "vEthernet").
func enumerateAddresses() ([]rawAddress, error) {
	size := uint32(initialAdapterBufSize)
	for range adapterBufAttempts {
		// Allocated as a slice of the struct, not of bytes: a []byte would be
		// correctly aligned for these 64-bit fields only by luck of the
		// allocator. The API writes into memory we own, so the linked list
		// below — and the net.IP slices pointing into it — stay valid for as
		// long as the GC sees them referenced. Nothing to free.
		buf := make([]windows.IpAdapterAddresses,
			size/uint32(unsafe.Sizeof(windows.IpAdapterAddresses{}))+1)
		head := &buf[0]

		err := windows.GetAdaptersAddresses(windows.AF_UNSPEC, gaaFlags, 0, head, &size)
		switch {
		case err == nil:
			return collectAddresses(head), nil
		case errors.Is(err, windows.ERROR_NO_DATA):
			// No adapter matches — a machine with every NIC disabled. Empty,
			// not an error.
			return nil, nil
		case !errors.Is(err, windows.ERROR_BUFFER_OVERFLOW):
			return nil, fmt.Errorf("GetAdaptersAddresses: %w", err)
		}
		// size now holds the length the API wants; grow and retry. A loop
		// rather than a single retry: an adapter appearing in between (a VPN
		// coming up, a dock being plugged) can push the requirement up again.
	}
	return nil, fmt.Errorf(
		"GetAdaptersAddresses: buffer still too small after %d attempts", adapterBufAttempts)
}

// collectAddresses walks the adapter list and keeps the addresses of the
// adapters that can carry traffic.
func collectAddresses(head *windows.IpAdapterAddresses) []rawAddress {
	var out []rawAddress
	for ad := head; ad != nil; ad = ad.Next {
		// Only adapters that are actually up: a disconnected NIC keeps its
		// static address and a disabled one its last DHCP lease, and reporting
		// either would name the machine by an address nobody can reach.
		if ad.OperStatus != windows.IfOperStatusUp {
			continue
		}
		// Loopback is filtered by address anyway; tunnel pseudo-interfaces
		// (Teredo, ISATAP, 6to4) are dropped whole — they carry addresses that
		// designate nothing on the LAN.
		if ad.IfType == windows.IF_TYPE_SOFTWARE_LOOPBACK || ad.IfType == windows.IF_TYPE_TUNNEL {
			continue
		}
		hasGateway := ad.FirstGatewayAddress != nil

		for ua := ad.FirstUnicastAddress; ua != nil; ua = ua.Next {
			ip := ua.Address.IP()
			if ip == nil {
				continue // neither AF_INET nor AF_INET6
			}
			// Metric and interface index are per-family on an adapter.
			metric, index := ad.Ipv4Metric, ad.IfIndex
			if ip.To4() == nil {
				metric, index = ad.Ipv6Metric, ad.Ipv6IfIndex
			}
			out = append(out, rawAddress{
				IP:         ip,
				IfIndex:    index,
				Metric:     metric,
				HasGateway: hasGateway,
			})
		}
	}
	return out
}

package sysinfo

import (
	"fmt"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

var (
	netapi32                  = windows.NewLazySystemDLL("netapi32.dll")
	procNetGetJoinInformation = netapi32.NewProc("NetGetJoinInformation")
	procNetApiBufferFree      = netapi32.NewProc("NetApiBufferFree")
)

// NETSETUP_JOIN_STATUS value for a domain-joined machine.
const netSetupDomainName = 3

// domain returns the AD domain name when the machine is domain-joined, or ""
// for a workgroup / unjoined machine (which has no AD domain).
func domain() string {
	var nameBuf *uint16
	var joinStatus uint32
	r, _, _ := procNetGetJoinInformation.Call(
		0,
		uintptr(unsafe.Pointer(&nameBuf)),
		uintptr(unsafe.Pointer(&joinStatus)),
	)
	if r != 0 || nameBuf == nil {
		return ""
	}
	defer procNetApiBufferFree.Call(uintptr(unsafe.Pointer(nameBuf))) //nolint:errcheck
	if joinStatus != netSetupDomainName {
		return ""
	}
	return windows.UTF16PtrToString(nameBuf)
}

// osVersion composes a human-readable OS string from the registry, e.g.
// "Windows 11 Pro 23H2 (Build 22631)".
func osVersion() string {
	k, err := registry.OpenKey(
		registry.LOCAL_MACHINE,
		`SOFTWARE\Microsoft\Windows NT\CurrentVersion`,
		registry.QUERY_VALUE,
	)
	if err != nil {
		return ""
	}
	defer k.Close()

	product, _, _ := k.GetStringValue("ProductName")
	display, _, _ := k.GetStringValue("DisplayVersion")
	build, _, _ := k.GetStringValue("CurrentBuild")
	product = fixProductName(product, build)

	var parts []string
	if product != "" {
		parts = append(parts, product)
	}
	if display != "" {
		parts = append(parts, display)
	}
	out := strings.Join(parts, " ")
	if build != "" {
		out = strings.TrimSpace(fmt.Sprintf("%s (Build %s)", out, build))
	}
	return strings.TrimSpace(out)
}

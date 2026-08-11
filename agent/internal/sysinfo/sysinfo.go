// Package sysinfo reports the host attributes the server stores alongside a
// machine: hostname, AD domain, and OS version. These are plain attributes
// (plan §2.3) — they may change without affecting the machine's identity.
package sysinfo

import (
	"os"
	"strconv"
	"strings"
)

// Info is the host descriptor sent on enroll and heartbeat.
type Info struct {
	Hostname  string
	Domain    string
	OSVersion string
}

// Collect reads the current host attributes. Best-effort: missing values are
// returned empty rather than failing.
func Collect() Info {
	h, _ := os.Hostname()
	return Info{
		Hostname:  h,
		Domain:    domain(),
		OSVersion: osVersion(),
	}
}

// firstWindows11Build is the first Windows 11 build number (21H2).
const firstWindows11Build = 22000

// fixProductName works around Windows 11 reporting itself as Windows 10:
// Microsoft never updated the registry `ProductName`, which still reads
// "Windows 10 Pro" on an 11. The build number is the reliable discriminator.
//
// Only names starting with "Windows 10" are rewritten, so Server SKUs — whose
// ProductName is already correct, and where 2025 (build 26100) sits above the
// threshold — are left untouched.
func fixProductName(product, build string) string {
	if !strings.HasPrefix(product, "Windows 10") {
		return product
	}
	n, err := strconv.Atoi(strings.TrimSpace(build))
	if err != nil || n < firstWindows11Build {
		return product
	}
	return "Windows 11" + strings.TrimPrefix(product, "Windows 10")
}

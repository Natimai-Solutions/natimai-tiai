//go:build windows

package collector

import (
	"bytes"
	"context"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"

	"tiai/agent/internal/deploy"
	"tiai/agent/internal/logging"
	"tiai/agent/internal/models"
)

// --- Firewall ------------------------------------------------------------------

// The three profiles, as the local store and the GPO store name them: the
// local store still calls the private profile "Standard".
var firewallProfiles = [3]struct{ local, policy string }{
	{`DomainProfile`, `DomainProfile`},
	{`StandardProfile`, `PrivateProfile`},
	{`PublicProfile`, `PublicProfile`},
}

const (
	firewallLocalKey  = `SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\`
	firewallPolicyKey = `SOFTWARE\Policies\Microsoft\WindowsFirewall\`
)

// readFirewall reads EnableFirewall for each profile, the GPO's value first.
// The registry and not the firewall's COM API: one value per profile, the
// same precedence the service applies, and no COM apartment to set up on the
// inventory's goroutine.
func readFirewall() *models.FirewallState {
	var got [3]*bool
	found := false
	for i, p := range firewallProfiles {
		got[i] = EffectiveFirewall(
			readDWORD(firewallPolicyKey+p.policy, "EnableFirewall"),
			readDWORD(firewallLocalKey+p.local, "EnableFirewall"),
		)
		found = found || got[i] != nil
	}
	if !found {
		return nil
	}
	return &models.FirewallState{Domain: got[0], Private: got[1], Public: got[2]}
}

func readDWORD(path, name string) *uint32 {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, path, registry.QUERY_VALUE|registry.WOW64_64KEY)
	if err != nil {
		return nil
	}
	defer k.Close()
	v, _, err := k.GetIntegerValue(name)
	if err != nil {
		return nil
	}
	u := uint32(v)
	return &u
}

// --- Local Administrators --------------------------------------------------------

var (
	netapi32                    = windows.NewLazySystemDLL("netapi32.dll")
	procNetLocalGroupGetMembers = netapi32.NewProc("NetLocalGroupGetMembers")
)

// localGroupMembersInfo2 is LOCALGROUP_MEMBERS_INFO_2.
type localGroupMembersInfo2 struct {
	sid           *windows.SID
	sidUsage      uint32
	domainAndName *uint16
}

const maxPreferredLength = 0xFFFFFFFF

// readLocalAdmins lists the Administrators group. The group is found by its
// well-known SID (S-1-5-32-544): its name is « Administrateurs » on a French
// Windows. nil when the group could not be read.
func readLocalAdmins() *[]models.LocalAdmin {
	sid, err := windows.CreateWellKnownSid(windows.WinBuiltinAdministratorsSid)
	if err != nil {
		logging.Debugf("agent: inventory: administrators sid: %v", err)
		return nil
	}
	group, _, _, err := sid.LookupAccount("")
	if err != nil {
		logging.Debugf("agent: inventory: administrators name: %v", err)
		return nil
	}
	groupPtr, err := windows.UTF16PtrFromString(group)
	if err != nil {
		return nil
	}
	var buf *byte
	var read, total uint32
	var resume uintptr
	rc, _, _ := procNetLocalGroupGetMembers.Call(
		0,
		uintptr(unsafe.Pointer(groupPtr)),
		2,
		uintptr(unsafe.Pointer(&buf)),
		maxPreferredLength,
		uintptr(unsafe.Pointer(&read)),
		uintptr(unsafe.Pointer(&total)),
		uintptr(unsafe.Pointer(&resume)),
	)
	if rc != 0 {
		logging.Debugf("agent: inventory: NetLocalGroupGetMembers: %d", rc)
		return nil
	}
	defer windows.NetApiBufferFree(buf)
	members := []models.LocalAdmin{}
	if read == 0 || buf == nil {
		return &members
	}
	rows := unsafe.Slice((*localGroupMembersInfo2)(unsafe.Pointer(buf)), read)
	for _, r := range rows {
		m := models.LocalAdmin{Name: windows.UTF16PtrToString(r.domainAndName)}
		if r.sid != nil {
			m.SID = r.sid.String()
		}
		members = append(members, m)
	}
	return &members
}

// --- winget ----------------------------------------------------------------------

// wingetListTimeout bounds `winget list`: it refreshes its source index first,
// which is a download on a cold cache.
const wingetListTimeout = 3 * time.Minute

// readWingetPackages runs `winget list --source winget` as SYSTEM, from the
// same winget.exe the deployments use. nil when winget is missing or failed.
func readWingetPackages(ctx context.Context) *[]models.WingetPackage {
	exe, err := (&deploy.SystemEnv{}).WingetPath()
	if err != nil {
		logging.Debugf("agent: inventory: winget: %v", err)
		return nil
	}
	ctx, cancel := context.WithTimeout(ctx, wingetListTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, exe, "list", "--source", "winget",
		"--accept-source-agreements", "--disable-interactivity")
	cmd.Dir = filepath.Dir(exe)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	var out bytes.Buffer
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		logging.Debugf("agent: inventory: winget list: %v", err)
		return nil
	}
	pkgs := ParseWingetList(out.String())
	if pkgs == nil {
		logging.Debugf("agent: inventory: winget list: no table in its output")
		return nil
	}
	return &pkgs
}

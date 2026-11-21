package collector

import (
	"encoding/json"
	"errors"
	"regexp"
	"sort"
	"strings"

	"tiai/agent/internal/models"
)

// Reading the directory for the others (dev/plan-lecture-annuaire.md, mode
// relay): a poste the console designated reads the computer objects of its
// own domain with its machine account, and the server files and checks the
// postes by that reading. Pure here — the names accepted, the LDAP filters,
// the script, the parsing — so it is testable off Windows; the PowerShell
// run is in directoryread_windows.go.

// directoryName is a computer name as the server may ask for it: nothing an
// LDAP filter or a PowerShell single-quoted string would need to escape.
var directoryName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,62}$`)

// directoryBatch is the names per LDAP filter: one search per batch keeps a
// filter well under the size a domain controller accepts.
const directoryBatch = 200

// maxDirectoryNames bounds what one reading asks the directory for.
const maxDirectoryNames = 20000

// DirectoryFilters turns the names into LDAP filters on sAMAccountName, the
// names the server should not have sent dropped, duplicates collapsed.
func DirectoryFilters(names []string) []string {
	seen := map[string]bool{}
	var clean []string
	for _, n := range names {
		n = strings.ToUpper(strings.TrimSpace(n))
		if !directoryName.MatchString(n) || seen[n] {
			continue
		}
		seen[n] = true
		clean = append(clean, n)
		if len(clean) == maxDirectoryNames {
			break
		}
	}
	sort.Strings(clean)
	var filters []string
	for start := 0; start < len(clean); start += directoryBatch {
		end := min(start+directoryBatch, len(clean))
		var b strings.Builder
		b.WriteString("(&(objectCategory=computer)(|")
		for _, n := range clean[start:end] {
			b.WriteString("(sAMAccountName=" + n + "$)")
		}
		b.WriteString("))")
		filters = append(filters, b.String())
	}
	return filters
}

// directoryScript is the PowerShell that reads the domain, as the machine
// account (the agent runs as LocalSystem): the domain's DNS name, NetBIOS
// name and SID, the computer objects the filters name, the subnets and their
// sites. Read only, through System.DirectoryServices — what [adsisearcher]
// is — paged, its result one object for ConvertTo-Json.
func directoryScript(filters []string) string {
	quoted := make([]string, len(filters))
	for i, f := range filters {
		quoted[i] = "'" + f + "'"
	}
	return `
$root = [ADSI]'LDAP://RootDSE'
$nc = [string]$root.defaultNamingContext
$cfg = [string]$root.configurationNamingContext
$dom = [ADSI]('LDAP://' + $nc)
$sid = (New-Object System.Security.Principal.SecurityIdentifier ($dom.objectSid[0], 0)).Value
$dns = ($nc -replace '^DC=', '') -replace ',DC=', '.'
$part = New-Object System.DirectoryServices.DirectorySearcher ([ADSI]('LDAP://CN=Partitions,' + $cfg)), ('(&(objectClass=crossRef)(nCName=' + $nc + '))')
[void]$part.PropertiesToLoad.Add('netbiosname')
$netbios = [string]$part.FindOne().Properties['netbiosname'][0]
$objects = New-Object System.Collections.ArrayList
foreach ($f in @(` + strings.Join(quoted, ",") + `)) {
  $s = New-Object System.DirectoryServices.DirectorySearcher $dom, $f
  $s.PageSize = 500
  foreach ($a in 'samaccountname','dnshostname','objectguid','distinguishedname','location','useraccountcontrol') { [void]$s.PropertiesToLoad.Add($a) }
  foreach ($r in $s.FindAll()) {
    $p = $r.Properties
    [void]$objects.Add([pscustomobject]@{
      object_guid = (New-Object Guid (,[byte[]]$p['objectguid'][0])).ToString()
      sam_account_name = [string]$p['samaccountname'][0]
      dns_host_name = if ($p['dnshostname'].Count) { [string]$p['dnshostname'][0] } else { '' }
      distinguished_name = [string]$p['distinguishedname'][0]
      location = if ($p['location'].Count) { [string]$p['location'][0] } else { '' }
      disabled = [bool]([int]$p['useraccountcontrol'][0] -band 2)
    })
  }
}
$subnets = New-Object System.Collections.ArrayList
try {
  $ss = New-Object System.DirectoryServices.DirectorySearcher ([ADSI]('LDAP://CN=Subnets,CN=Sites,' + $cfg)), '(objectClass=subnet)'
  $ss.PageSize = 500
  foreach ($a in 'cn','siteobject') { [void]$ss.PropertiesToLoad.Add($a) }
  foreach ($r in $ss.FindAll()) {
    $site = ''
    if ($r.Properties['siteobject'].Count) { $site = (([string]$r.Properties['siteobject'][0]).Split(',')[0]) -replace '^CN=', '' }
    [void]$subnets.Add([pscustomobject]@{ subnet = [string]$r.Properties['cn'][0]; site = $site })
  }
} catch { }
[pscustomobject]@{
  domain = [pscustomobject]@{ name = $dns; netbios_name = $netbios; sid = $sid }
  objects = @($objects)
  subnets = @($subnets)
}`
}

// ParseDirectoryReading reads the script's JSON. A reading without its
// domain's identity is refused: the server could not tell whose it is.
func ParseDirectoryReading(raw []byte) (*models.DirectoryReading, error) {
	var r models.DirectoryReading
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil, err
	}
	if r.Domain.SID == "" || r.Domain.NetBIOSName == "" {
		return nil, errors.New("directory: no domain identity in the reading")
	}
	if r.Objects == nil {
		r.Objects = []models.DirectoryObject{}
	}
	if r.Subnets == nil {
		r.Subnets = []models.DirectorySubnet{}
	}
	return &r, nil
}

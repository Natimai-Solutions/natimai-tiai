package collector

import (
	"regexp"
	"sort"
	"strings"

	"tiai/agent/internal/models"
)

// The C5 readings: the firewall's three profiles, the local Administrators,
// and what winget would upgrade. Pure here — the precedence rule, the table
// parser, the ordering — so they are testable off Windows; the registry,
// netapi32 and winget.exe calls live in compliance_windows.go.

// InventoryOptions are the parts of the inventory a switch decides.
type InventoryOptions struct {
	// The installed programs (ReportSoftware, on by default).
	Software bool
	// The members of the local Administrators group (ReportLocalAdmins, off by
	// default: account names).
	LocalAdmins bool
	// `winget list` (ReportWingetPackages, off by default).
	WingetPackages bool
}

// EffectiveFirewall is a profile's state as Windows applies it: a value
// pushed by Group Policy wins over the local one, as in the firewall itself.
// nil when neither could be read.
func EffectiveFirewall(policy, local *uint32) *bool {
	v := local
	if policy != nil {
		v = policy
	}
	if v == nil {
		return nil
	}
	on := *v != 0
	return &on
}

var (
	wingetDashes  = regexp.MustCompile(`^-{8,}\s*$`)
	wingetIDShape = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}$`)
)

// wingetSources are the values the Source column carries; a fourth column
// holding one of them is that column, not the Available one.
var wingetSources = map[string]bool{"winget": true, "msstore": true}

// ParseWingetList reads the table `winget list` prints.
//
// winget has no machine-readable output for this, so the table is read the
// way it is drawn: the line of dashes under the header, and the header's
// words for where each column starts. The header's words are in the poste's
// language, so only their positions are used; the columns come in a fixed
// order — name, id, version, then available and source when shown.
//
// Defensive throughout, since this is another program's display: a progress
// spinner rewritten with carriage returns is reduced to what it left last, a
// row whose id is not an id (cut by winget with an ellipsis on a narrow
// table, a footer line) is skipped, and a table never found yields nil.
func ParseWingetList(out string) []models.WingetPackage {
	lines := strings.Split(strings.ReplaceAll(out, "\r\n", "\n"), "\n")
	for i := range lines {
		if j := strings.LastIndex(lines[i], "\r"); j >= 0 {
			lines[i] = lines[i][j+1:]
		}
	}
	header := -1
	for i := 1; i < len(lines); i++ {
		if wingetDashes.MatchString(lines[i]) && strings.TrimSpace(lines[i-1]) != "" {
			header = i - 1
			break
		}
	}
	if header < 0 {
		return nil
	}
	starts := columnStarts([]rune(lines[header]))
	if len(starts) < 3 {
		return nil
	}
	packages := []models.WingetPackage{}
	for _, line := range lines[header+2:] {
		if strings.TrimSpace(line) == "" {
			break
		}
		cells := cutColumns([]rune(line), starts)
		id := cells[1]
		if !wingetIDShape.MatchString(id) {
			continue
		}
		p := models.WingetPackage{ID: id, Name: cells[0], Version: cells[2]}
		switch len(cells) {
		case 4:
			if !wingetSources[strings.ToLower(cells[3])] {
				p.Available = cells[3]
			}
		default:
			if len(cells) >= 5 {
				p.Available = cells[3]
			}
		}
		packages = append(packages, p)
	}
	return packages
}

// columnStarts is where each word of the header begins.
func columnStarts(header []rune) []int {
	var starts []int
	for i, r := range header {
		if r != ' ' && (i == 0 || header[i-1] == ' ') {
			starts = append(starts, i)
		}
	}
	return starts
}

// cutColumns splits a row at the header's positions, trimming each cell.
func cutColumns(row []rune, starts []int) []string {
	cells := make([]string, len(starts))
	for k, from := range starts {
		to := len(row)
		if k+1 < len(starts) && starts[k+1] < to {
			to = starts[k+1]
		}
		if from < len(row) {
			cells[k] = strings.TrimSpace(string(row[from:to]))
		}
	}
	return cells
}

// sortCompliance orders the two lists the hash covers.
func sortCompliance(inv *models.InventoryState) {
	if inv.LocalAdmins != nil {
		admins := *inv.LocalAdmins
		sort.Slice(admins, func(i, j int) bool { return admins[i].Name < admins[j].Name })
	}
	if inv.WingetPackages != nil {
		pkgs := *inv.WingetPackages
		sort.Slice(pkgs, func(i, j int) bool { return pkgs[i].ID < pkgs[j].ID })
	}
}

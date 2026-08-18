package collector

import (
	"context"
	"fmt"

	"tiai/agent/internal/models"
)

// securityCenterNamespace holds the Security Center's product registry. It
// exists on client SKUs only — Windows Server ships no Security Center — so the
// query below fails there, permanently. See ReadAVProduct for what that means.
const securityCenterNamespace = `root\SecurityCenter2`

// antiVirusProduct mirrors the AntiVirusProduct properties we read. The class
// carries a handful more (pathToSignedReportingExe, timestamp) that say nothing
// the console shows: the timestamp is the last state change, not the signature
// date, and vendors disagree on what it means.
type antiVirusProduct struct {
	DisplayName            string
	ProductState           uint32
	InstanceGuid           string
	PathToSignedProductExe string
}

// ReadAVProduct returns the antivirus the Windows Security Center considers
// active on this machine, third-party products included.
//
// Three outcomes, all meaningful and all distinct:
//
//   - a named product — reported as-is, with its protection and freshness bits;
//   - an empty block, no error — the registry is readable and empty: no
//     antivirus at all is registered, and the server stores exactly that;
//   - an error — the registry could not be read. The caller omits the block and
//     the server keeps what it had. This is the permanent outcome on Windows
//     Server, where the namespace does not exist, hence the caller's once-only
//     logging.
func ReadAVProduct(ctx context.Context) (*models.AVProductState, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	var rows []antiVirusProduct
	if err := queryNamespace(
		"SELECT * FROM AntiVirusProduct", &rows, securityCenterNamespace); err != nil {
		return nil, fmt.Errorf("query AntiVirusProduct: %w", err)
	}
	products := make([]rawAVProduct, 0, len(rows))
	for _, r := range rows {
		products = append(products, rawAVProduct{
			Name:         r.DisplayName,
			State:        r.ProductState,
			InstanceGUID: r.InstanceGuid,
			ProductExe:   r.PathToSignedProductExe,
		})
	}
	return buildAVProductState(products), nil
}

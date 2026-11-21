package agent

import (
	"context"

	"tiai/agent/internal/collector"
	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// readDirectory is the directory reading, behind a variable so a test can
// stand in for ADSI.
var readDirectory = collector.ReadDirectoryObjects

// runDirectoryRead reads the objects the server named and posts the reading,
// then reports how many were read; the server answers in the same exchange
// whether it took it (a poste no longer a reader, another domain: refused).
func (a *Agent) runDirectoryRead(ctx context.Context, commandID string, request *models.DirectoryRequest) (msg.Message, error) {
	if request == nil || len(request.Names) == 0 {
		return msg.Message{}, msg.Err("directory.read.no_names", nil)
	}
	reading, err := readDirectory(ctx, request.Names)
	if err != nil {
		return msg.Message{}, err
	}
	if err := a.client.PostDirectory(ctx, commandID, *reading); err != nil {
		return msg.Message{}, msg.Wrap("directory.read.refused", nil, err)
	}
	return msg.New("directory.read.done", msg.Params{
		"objects": len(reading.Objects),
		"asked":   len(request.Names),
		"domain":  reading.Domain.Name,
	}), nil
}

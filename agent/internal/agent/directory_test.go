package agent

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"tiai/agent/internal/api"
	"tiai/agent/internal/config"
	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

func stubDirectory(t *testing.T, reading *models.DirectoryReading, err error) *[]string {
	t.Helper()
	var asked []string
	orig := readDirectory
	t.Cleanup(func() { readDirectory = orig })
	readDirectory = func(_ context.Context, names []string) (*models.DirectoryReading, error) {
		asked = names
		return reading, err
	}
	return &asked
}

func TestDirectoryReadPostsTheReadingThenSaysWhatWasRead(t *testing.T) {
	reading := &models.DirectoryReading{
		Domain:  models.DirectoryDomain{Name: "lycee.local", NetBIOSName: "LYCEE", SID: "S-1-5-21-1-2-3"},
		Objects: []models.DirectoryObject{{ObjectGUID: "g", SAMAccountName: "PC-01$"}},
		Subnets: []models.DirectorySubnet{},
	}
	asked := stubDirectory(t, reading, nil)
	var path string
	var posted models.DirectoryReading
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &posted)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	}))
	defer srv.Close()
	a := &Agent{cfg: config.DefaultConfig(), client: api.New(srv.URL, "tok", 5*time.Second, nil)}

	m, err := a.runDirectoryRead(context.Background(), "cmd-1", &models.DirectoryRequest{Names: []string{"PC-01", "PC-02"}})
	if err != nil {
		t.Fatal(err)
	}
	if path != "/api/v1/agent/directory/cmd-1" || posted.Domain.SID != "S-1-5-21-1-2-3" {
		t.Fatalf("posted %q %+v", path, posted)
	}
	if len(*asked) != 2 {
		t.Fatalf("asked %v", *asked)
	}
	if m.Code != "directory.read.done" || m.Params["objects"] != 1 || m.Params["asked"] != 2 {
		t.Fatalf("message %+v", m)
	}
}

func TestDirectoryReadRefusedByTheServer(t *testing.T) {
	stubDirectory(t, &models.DirectoryReading{}, nil)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error":{"code":"directory.reading_refused"}}`))
	}))
	defer srv.Close()
	a := &Agent{cfg: config.DefaultConfig(), client: api.New(srv.URL, "tok", 5*time.Second, nil)}
	_, err := a.runDirectoryRead(context.Background(), "cmd-1", &models.DirectoryRequest{Names: []string{"PC-01"}})
	if code, _ := msg.Of(err); code != "directory.read.refused" {
		t.Fatalf("got %v (%s)", err, code)
	}
}

func TestDirectoryReadWithoutNamesReadsNothing(t *testing.T) {
	asked := stubDirectory(t, nil, nil)
	a := &Agent{cfg: config.DefaultConfig()}
	_, err := a.runDirectoryRead(context.Background(), "cmd-1", nil)
	if code, _ := msg.Of(err); code != "directory.read.no_names" || *asked != nil {
		t.Fatalf("got %v, asked %v", err, *asked)
	}
}

func TestDirectoryReadIsAKnownType(t *testing.T) {
	a := &Agent{cfg: config.DefaultConfig()}
	if _, _, ok := a.resolve(models.Command{ID: "1", Type: "directory_read"}); !ok {
		t.Fatal("directory_read must be a known type")
	}
}

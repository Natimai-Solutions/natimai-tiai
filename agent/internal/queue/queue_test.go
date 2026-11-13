package queue

import (
	"bytes"
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"tiai/agent/internal/models"
)

func TestEnqueuePeekRemoveFIFO(t *testing.T) {
	q, err := New(t.TempDir(), 10)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	if q.Depth() != 0 {
		t.Fatalf("expected empty queue, got depth %d", q.Depth())
	}

	for _, id := range []string{"a", "b", "c"} {
		if err := q.Enqueue(Item{CommandID: id, Result: models.CommandResult{Status: "succeeded"}}); err != nil {
			t.Fatalf("Enqueue %s: %v", id, err)
		}
	}
	if q.Depth() != 3 {
		t.Fatalf("expected depth 3, got %d", q.Depth())
	}

	// FIFO: oldest ("a") comes out first.
	item, path, err := q.Peek()
	if err != nil || item == nil {
		t.Fatalf("Peek: item=%v err=%v", item, err)
	}
	if item.CommandID != "a" {
		t.Fatalf("expected oldest 'a', got %q", item.CommandID)
	}
	if err := q.Remove(path); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	if q.Depth() != 2 {
		t.Fatalf("expected depth 2 after remove, got %d", q.Depth())
	}
}

func TestEnqueueDropsOldestWhenFull(t *testing.T) {
	q, err := New(t.TempDir(), 2)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	for _, id := range []string{"a", "b", "c"} {
		if err := q.Enqueue(Item{CommandID: id}); err != nil {
			t.Fatalf("Enqueue %s: %v", id, err)
		}
	}
	if q.Depth() != 2 {
		t.Fatalf("expected cap at 2, got %d", q.Depth())
	}
	// "a" should have been dropped; oldest remaining is "b".
	item, _, err := q.Peek()
	if err != nil || item == nil {
		t.Fatalf("Peek: item=%v err=%v", item, err)
	}
	if item.CommandID != "b" {
		t.Fatalf("expected 'b' after dropping oldest, got %q", item.CommandID)
	}
}

func TestPeekEmpty(t *testing.T) {
	q, _ := New(t.TempDir(), 10)
	item, path, err := q.Peek()
	if err != nil {
		t.Fatalf("Peek empty: %v", err)
	}
	if item != nil || path != "" {
		t.Fatalf("expected nil item/empty path, got %v %q", item, path)
	}
}

// A command id names a file in the queue directory: one that is not a plain
// token must never reach filepath.Join, or a full backlog writes wherever the
// server's string points (same class as audit S01).
func TestEnqueueRefusesAnIDThatIsAPath(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "a", "b", "queue")
	q, err := New(dir, 10)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	for _, id := range []string{"../../../escaped", `..\..\escaped`, "a/b", "x.y", "", "c:evil",
		strings.Repeat("a", 65)} {
		if err := q.Enqueue(Item{CommandID: id}); err == nil {
			t.Errorf("Enqueue accepted %q", id)
		}
	}
	if q.Depth() != 0 {
		t.Errorf("depth = %d, want nothing written", q.Depth())
	}
	var stray []string
	_ = filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err == nil && !info.IsDir() {
			stray = append(stray, path)
		}
		return nil
	})
	if len(stray) != 0 {
		t.Errorf("files written: %v", stray)
	}
	// A server id (UUID, either case) still goes in.
	for _, id := range []string{"3f1c2a4e-9b7d-4c1e-8a2f-0d5e6b7c8a9f", "3F1C2A4E-9B7D-4C1E-8A2F-0D5E6B7C8A9F"} {
		if err := q.Enqueue(Item{CommandID: id}); err != nil {
			t.Errorf("Enqueue %q: %v", id, err)
		}
	}
}

// Dropping a verdict when the queue is full is said, with the command it
// concerned: the console will show that command expired, and the log is the
// only place telling why.
func TestEnqueueLogsTheDroppedVerdict(t *testing.T) {
	var buf bytes.Buffer
	orig := log.Writer()
	log.SetOutput(&buf)
	t.Cleanup(func() { log.SetOutput(orig) })

	q, err := New(t.TempDir(), 2)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	for _, id := range []string{"first", "second", "third"} {
		if err := q.Enqueue(Item{CommandID: id}); err != nil {
			t.Fatalf("Enqueue %s: %v", id, err)
		}
	}
	if !strings.Contains(buf.String(), "for command first") {
		t.Errorf("drop not logged with its command id: %q", buf.String())
	}
}

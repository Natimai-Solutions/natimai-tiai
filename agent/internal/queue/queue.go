// Package queue is a tiny durable file-backed FIFO for outbound items the agent
// must not lose when the server is unreachable (plan §2.9). It holds command
// results: a finished scan whose result couldn't be posted is replayed on the
// next successful contact. Defender state and threats are NOT queued — they are
// re-derived on every heartbeat, so a missed report self-heals.
package queue

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"tiai/agent/internal/models"
)

// Item is a pending command result awaiting delivery.
type Item struct {
	CommandID string               `json:"command_id"`
	Result    models.CommandResult `json:"result"`
	CreatedAt time.Time            `json:"created_at"`
}

// Queue is a directory of JSON files, one per item, ordered by filename
// (timestamp-prefixed) so the oldest is replayed first.
type Queue struct {
	mu       sync.Mutex
	dir      string
	maxItems int
}

// New opens (creating if needed) a queue under dir, capped at maxItems.
func New(dir string, maxItems int) (*Queue, error) {
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return nil, fmt.Errorf("create queue dir: %w", err)
	}
	if maxItems <= 0 {
		maxItems = 1000
	}
	return &Queue{dir: dir, maxItems: maxItems}, nil
}

// safeCommandID is what a command id must look like to name a file here: the
// server's ids are UUIDs, and anything carrying a separator or a dot could put
// the file outside the queue directory (the class of audit S01). The agent
// already refuses such a command on arrival; this is the second lock.
var safeCommandID = regexp.MustCompile(`^[0-9A-Za-z-]{1,64}$`)

// Enqueue appends an item, dropping the oldest when the queue is full.
func (q *Queue) Enqueue(item Item) error {
	if !safeCommandID.MatchString(item.CommandID) {
		return fmt.Errorf("queue: command id %q refused (not a plain token)", item.CommandID)
	}

	q.mu.Lock()
	defer q.mu.Unlock()

	if files, _ := q.listFiles(); len(files) >= q.maxItems {
		// Said, with the command it concerns: that verdict will never reach
		// the server, which expires the command on its own clock instead.
		log.Printf("queue: full (%d items), dropping the oldest verdict, for command %s",
			q.maxItems, commandIDOf(files[0]))
		_ = os.Remove(files[0])
	}

	if item.CreatedAt.IsZero() {
		item.CreatedAt = time.Now().UTC()
	}
	data, err := json.Marshal(item)
	if err != nil {
		return fmt.Errorf("marshal queue item: %w", err)
	}
	name := fmt.Sprintf("%s_%s.json", item.CreatedAt.UTC().Format("20060102-150405.000000"), item.CommandID)
	tmp := filepath.Join(q.dir, name+".tmp")
	final := filepath.Join(q.dir, name)
	if err := os.WriteFile(tmp, data, 0o640); err != nil {
		return fmt.Errorf("write queue item: %w", err)
	}
	return os.Rename(tmp, final)
}

// Peek returns the oldest item and its on-disk path, or (nil, "", nil) if empty.
// A corrupt item is removed and skipped.
func (q *Queue) Peek() (*Item, string, error) {
	q.mu.Lock()
	defer q.mu.Unlock()

	files, err := q.listFiles()
	if err != nil {
		return nil, "", err
	}
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, "", fmt.Errorf("read queue item: %w", err)
		}
		var item Item
		if err := json.Unmarshal(data, &item); err != nil {
			_ = os.Remove(path) // drop corrupt entry
			continue
		}
		return &item, path, nil
	}
	return nil, "", nil
}

// Remove deletes a delivered item by its path.
func (q *Queue) Remove(path string) error {
	q.mu.Lock()
	defer q.mu.Unlock()
	return os.Remove(path)
}

// Depth returns the number of queued items.
func (q *Queue) Depth() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	files, _ := q.listFiles()
	return len(files)
}

// commandIDOf reads the command id back from an item's file name,
// <timestamp>_<id>.json.
func commandIDOf(path string) string {
	name := strings.TrimSuffix(filepath.Base(path), ".json")
	if _, id, ok := strings.Cut(name, "_"); ok {
		return id
	}
	return name
}

func (q *Queue) listFiles() ([]string, error) {
	entries, err := os.ReadDir(q.dir)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, e := range entries {
		if !e.IsDir() && filepath.Ext(e.Name()) == ".json" {
			files = append(files, filepath.Join(q.dir, e.Name()))
		}
	}
	sort.Strings(files)
	return files, nil
}

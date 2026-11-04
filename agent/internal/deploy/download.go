package deploy

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"time"
)

// Fetcher streams one package file from the server, from offset, into f. When
// the server ignores the range and sends the whole file, the fetcher truncates
// f itself. A *RetryLater error asks to come back after a while: the server
// is busy, or the network dropped.
type Fetcher interface {
	FetchPackageFile(ctx context.Context, packageID, sha256 string, offset int64, f *os.File) error
}

// RetryLater is a transient failure, worth retrying after Wait.
type RetryLater struct {
	Wait time.Duration
	Err  error
}

func (e *RetryLater) Error() string { return e.Err.Error() }
func (e *RetryLater) Unwrap() error { return e.Err }

const (
	downloadAttempts = 20
	fileBudget       = 2 * time.Hour
)

// Download fetches f into dest, resuming whatever a previous attempt left,
// and returns only once dest has the size and the SHA-256 the manifest names.
// sleep waits between attempts (time-based in production, instant in tests).
func Download(ctx context.Context, fetch Fetcher, packageID string, f FileRef, dest string, sleep func(context.Context, time.Duration) error) error {
	ctx, cancel := context.WithTimeout(ctx, fileBudget)
	defer cancel()

	if ok, _ := hashMatches(dest, f); ok {
		return nil
	}
	backoff := 5 * time.Second
	for attempt := 1; ; attempt++ {
		err := fetchOnce(ctx, fetch, packageID, f, dest)
		if err == nil {
			break
		}
		var later *RetryLater
		if !errors.As(err, &later) || attempt >= downloadAttempts {
			return err
		}
		wait := later.Wait
		if wait <= 0 {
			wait = backoff
			backoff = min(backoff*2, 5*time.Minute)
		}
		if serr := sleep(ctx, wait); serr != nil {
			return serr
		}
	}
	ok, err := hashMatches(dest, f)
	if err != nil {
		return err
	}
	if !ok {
		_ = os.Remove(dest)
		return errors.New("empreinte SHA-256 différente de celle du manifeste : fichier rejeté")
	}
	return nil
}

func fetchOnce(ctx context.Context, fetch Fetcher, packageID string, f FileRef, dest string) error {
	file, err := os.OpenFile(dest, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return err
	}
	offset := info.Size()
	if offset > f.Size {
		// Longer than it should ever be: start over.
		if err := file.Truncate(0); err != nil {
			return err
		}
		offset = 0
	}
	if offset == f.Size {
		return nil
	}
	if _, err := file.Seek(offset, io.SeekStart); err != nil {
		return err
	}
	if err := fetch.FetchPackageFile(ctx, packageID, f.SHA256, offset, file); err != nil {
		return err
	}
	info, err = file.Stat()
	if err != nil {
		return err
	}
	if info.Size() != f.Size {
		return &RetryLater{Err: fmt.Errorf("transfert incomplet (%d/%d octets)", info.Size(), f.Size)}
	}
	return nil
}

func hashMatches(path string, f FileRef) (bool, error) {
	file, err := os.Open(path)
	if err != nil {
		return false, nil
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || info.Size() != f.Size {
		return false, nil
	}
	h := sha256.New()
	if _, err := io.Copy(h, file); err != nil {
		return false, err
	}
	return hex.EncodeToString(h.Sum(nil)) == f.SHA256, nil
}

// SleepContext waits d, or until ctx ends.
func SleepContext(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

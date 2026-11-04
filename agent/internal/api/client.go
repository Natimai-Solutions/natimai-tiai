// Package api is the HTTP client to the Tiai server.
//
// Under Windows, Go's HTTP client uses the system certificate store, so a
// certificate issued by the internal CA validates without extra config.
package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"sync"
	"time"

	"tiai/agent/internal/deploy"
	"tiai/agent/internal/models"
)

// StatusError is a non-2xx response from the server, kept typed so the agent
// can react to a *specific* status: a 401 on the heartbeat means the stored
// token is no longer honoured (revocation, an admin's allow-reenroll, a
// database restored from before our enrollment), and the recovery is to drop
// the token and re-enroll — which needs the status, not an error string.
type StatusError struct {
	StatusCode int
	Body       string
}

func (e *StatusError) Error() string {
	return fmt.Sprintf("status %d: %s", e.StatusCode, e.Body)
}

// Client talks to the Tiai API.
type Client struct {
	baseURL string
	timeout time.Duration
	http    *http.Client

	// The bearer token changes under a running agent — at enrollment, and on
	// every rotation — from the polling loop, while the command worker posts
	// results from its own goroutine. Each request reads it once, under the
	// lock, so it carries either the old token or the new one, never a torn
	// value.
	mu    sync.RWMutex
	token string
}

// New builds a client with the given per-request timeout, reaching the server
// through proxy — nil for a direct connection (see ParseProxy).
//
// The budget lives on the *request* (a context deadline in do) and not on the
// http.Client, and that is deliberate: http.Client.Timeout caps every request
// at the same value whatever context it is handed, which would put the
// heartbeat that carries an inventory — the largest thing the agent ever sends,
// and the heaviest write the server ever does — on the same ten seconds as an
// empty one. Applied per request, a caller can hand in a context that already
// carries a wider deadline for that one case (see the agent's poll loop) and
// everything else keeps the configured timeout.
func New(baseURL, token string, timeout time.Duration, proxy Proxy) *Client {
	// A clone of the default transport rather than a bare one: it keeps the
	// dial and TLS handshake timeouts, the connection pool and the system
	// certificate store the agent has always relied on. Only the proxy choice
	// changes, and it is ours rather than the environment's.
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = proxy
	return &Client{
		baseURL: baseURL,
		token:   token,
		timeout: timeout,
		http:    &http.Client{Transport: transport},
	}
}

// SetToken updates the bearer token (after enrollment or a rotation). Requests
// already in flight keep the token they were built with.
func (c *Client) SetToken(token string) {
	c.mu.Lock()
	c.token = token
	c.mu.Unlock()
}

// Token is the bearer token the next request will carry.
func (c *Client) Token() string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.token
}

// Enroll registers the machine and returns its per-machine token.
func (c *Client) Enroll(ctx context.Context, secret string, req models.EnrollRequest) (*models.EnrollResponse, error) {
	var out models.EnrollResponse
	if err := c.do(ctx, http.MethodPost, "/api/v1/agent/enroll", map[string]string{
		"X-Enrollment-Secret": secret,
	}, req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Heartbeat reports state and returns pending commands.
func (c *Client) Heartbeat(ctx context.Context, req models.HeartbeatRequest) (*models.HeartbeatResponse, error) {
	var out models.HeartbeatResponse
	if err := c.do(ctx, http.MethodPost, "/api/v1/agent/heartbeat", c.authHeader(), req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// PostResult reports a command's execution outcome.
func (c *Client) PostResult(ctx context.Context, commandID string, res models.CommandResult) error {
	path := fmt.Sprintf("/api/v1/agent/commands/%s/result", commandID)
	return c.do(ctx, http.MethodPost, path, c.authHeader(), res, nil)
}

func (c *Client) authHeader() map[string]string {
	return map[string]string{"Authorization": "Bearer " + c.Token()}
}

func (c *Client) do(ctx context.Context, method, path string, headers map[string]string, body, out any) error {
	// The caller's deadline wins when it set one; otherwise the configured
	// timeout applies. Nothing in the agent runs without a context, so this is
	// the only place a request can be bounded. A non-positive timeout means
	// "unbounded", as it did on http.Client — never "already expired".
	if _, ok := ctx.Deadline(); !ok && c.timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, c.timeout)
		defer cancel()
	}

	var reader io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("marshal request: %w", err)
		}
		reader = bytes.NewReader(data)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("%s %s: %w", method, path,
			&StatusError{StatusCode: resp.StatusCode, Body: string(b)})
	}
	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}

// FetchPackageFile streams a package file into f from offset — a Range
// request when resuming. Implements deploy.Fetcher: a 429 (the server is
// serving its quota of downloads) and network failures come back as
// *deploy.RetryLater, never as a failed command.
func (c *Client) FetchPackageFile(ctx context.Context, packageID, sha256 string, offset int64, f *os.File) error {
	path := fmt.Sprintf("/api/v1/agent/packages/%s/files/%s", url.PathEscape(packageID), url.PathEscape(sha256))
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.Token())
	if offset > 0 {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return &deploy.RetryLater{Err: fmt.Errorf("GET %s: %w", path, err)}
	}
	defer resp.Body.Close()
	switch {
	case resp.StatusCode == http.StatusOK:
		// The whole file, range or not: start the local copy over.
		if offset > 0 {
			if err := f.Truncate(0); err != nil {
				return err
			}
			if _, err := f.Seek(0, io.SeekStart); err != nil {
				return err
			}
		}
	case resp.StatusCode == http.StatusPartialContent && offset > 0:
	case resp.StatusCode == http.StatusRequestedRangeNotSatisfiable:
		if err := f.Truncate(0); err != nil {
			return err
		}
		return &deploy.RetryLater{Wait: time.Second, Err: errors.New("reprise refusée, nouveau départ")}
	case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
		wait := time.Minute
		if s, err := strconv.Atoi(resp.Header.Get("Retry-After")); err == nil && s > 0 {
			wait = time.Duration(s) * time.Second
		}
		return &deploy.RetryLater{Wait: wait, Err: fmt.Errorf("serveur occupé (%d)", resp.StatusCode)}
	default:
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("GET %s: %w", path, &StatusError{StatusCode: resp.StatusCode, Body: string(b)})
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		return &deploy.RetryLater{Err: fmt.Errorf("transfert interrompu : %w", err)}
	}
	return nil
}

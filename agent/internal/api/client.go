// Package api is the HTTP client to the Tiai server.
//
// Under Windows, Go's HTTP client uses the system certificate store, so a
// certificate issued by the internal CA validates without extra config.
package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

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
	token   string
	timeout time.Duration
	http    *http.Client
}

// New builds a client with the given per-request timeout.
//
// The budget lives on the *request* (a context deadline in do) and not on the
// http.Client, and that is deliberate: http.Client.Timeout caps every request
// at the same value whatever context it is handed, which would put the
// heartbeat that carries an inventory — the largest thing the agent ever sends,
// and the heaviest write the server ever does — on the same ten seconds as an
// empty one. Applied per request, a caller can hand in a context that already
// carries a wider deadline for that one case (see the agent's poll loop) and
// everything else keeps the configured timeout.
func New(baseURL, token string, timeout time.Duration) *Client {
	return &Client{
		baseURL: baseURL,
		token:   token,
		timeout: timeout,
		http:    &http.Client{},
	}
}

// SetToken updates the bearer token (after enrollment).
func (c *Client) SetToken(token string) { c.token = token }

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
	return map[string]string{"Authorization": "Bearer " + c.token}
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

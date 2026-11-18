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
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"tiai/agent/internal/deploy"
	"tiai/agent/internal/models"
	"tiai/agent/internal/msg"
)

// StatusError is a non-2xx response from the server, kept typed so the agent
// can react to a *specific* status: a 401 on the heartbeat means the stored
// token is no longer honoured (revocation, an admin's allow-reenroll, a
// database restored from before our enrollment), and the recovery is to drop
// the token and re-enroll — which needs the status, not an error string.
type StatusError struct {
	StatusCode int
	Body       string
	// RetryAfter is the wait the answer's Retry-After header asks for; zero
	// when there is none, or none in seconds (see retryAfter).
	RetryAfter time.Duration
}

// Error renders the body on one line: an error ends up in the agent's log, and
// in a verdict, and the body is whatever answered — the server, or anything
// that stood in for it. With its line breaks it could write lines of its own
// there. Body itself is left as received, for whoever reads it (a code in it).
func (e *StatusError) Error() string {
	return fmt.Sprintf("status %d: %s", e.StatusCode, singleLine(e.Body))
}

// singleLine replaces every control character, and the two Unicode line
// separators, with a space.
func singleLine(s string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsControl(r) || r == '\u2028' || r == '\u2029' {
			return ' '
		}
		return r
	}, s)
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

// maxErrorBody bounds what an error response may put in an error, and so in
// the log.
const maxErrorBody = 4096

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
		http: &http.Client{
			Transport: transport,
			// Never follow a redirect: Go would resend the custom
			// X-Enrollment-Secret header to wherever it points (audit S22).
			// A 3xx is an answer, reported as such.
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
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
		reader = bytes.NewReader(stripControlEscapes(data))
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
		// Bounded: the body goes into the error, and the error into the log
		// on every failed tick (audit S23).
		b, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBody))
		return fmt.Errorf("%s %s: %w", method, path, &StatusError{
			StatusCode: resp.StatusCode, Body: string(b), RetryAfter: retryAfter(resp.Header)})
	}
	if out != nil {
		if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}

// maxRetryAfter bounds what a Retry-After header is read as. Far above any
// wait the agent agrees to — each caller applies its own bound — and what
// keeps the conversion to a duration from overflowing.
const maxRetryAfter = 24 * time.Hour

// retryAfter reads a Retry-After header in its seconds form, the one the
// server sends with a 429 (the length of the limiter's window). The HTTP-date
// form is not read: it would be compared with this poste's clock, and nothing
// the agent talks to sends it. Zero when the header is absent or unusable.
func retryAfter(h http.Header) time.Duration {
	s, err := strconv.ParseInt(strings.TrimSpace(h.Get("Retry-After")), 10, 64)
	if err != nil || s <= 0 {
		return 0
	}
	if s > int64(maxRetryAfter/time.Second) {
		return maxRetryAfter
	}
	return time.Duration(s) * time.Second
}

// stripControlEscapes removes from a JSON document every C0 control character
// a string carries, except tab, line feed and carriage return.
//
// Done here, on what every request sends — enrollment, heartbeat, verdict — so
// that no field escapes it: a NUL in a command's output (a tool writing
// UTF-16 into a pipe), in a program name read from the registry or in an
// update title is accepted by Go and refused by the server's database, which
// answers 500. A verdict refused that way stayed at the head of the local
// queue and held back every verdict behind it; a heartbeat refused that way
// would take the poste offline. Nothing the agent reports means anything by
// those characters.
//
// encoding/json writes every control character inside a string as an escape
// — \u0000 … \u001f, or a two-byte escape for those that have one: \n \r \t,
// and \b \f since Go 1.22 — and a backslash anywhere in its output starts an
// escape: a literal backslash is "\\". So the document is walked escape by
// escape, and the escapes of the stripped characters dropped: \b, \f, and the
// \u00XX of a C0 character.
func stripControlEscapes(data []byte) []byte {
	if bytes.IndexByte(data, '\\') < 0 {
		return data
	}
	out := make([]byte, 0, len(data))
	for i := 0; i < len(data); i++ {
		if data[i] != '\\' || i+1 >= len(data) {
			out = append(out, data[i])
			continue
		}
		if data[i+1] == 'b' || data[i+1] == 'f' {
			i++
			continue
		}
		if data[i+1] == 'u' && i+5 < len(data) && isStrippedControl(data[i+2:i+6]) {
			i += 5
			continue
		}
		// Any other escape is copied whole, so that the backslash of "\\"
		// is never read as the start of the next one.
		out = append(out, data[i], data[i+1])
		i++
	}
	return out
}

// isStrippedControl tells whether the four hex digits of a \u escape name a C0
// control character other than tab, line feed and carriage return.
func isStrippedControl(hex []byte) bool {
	if hex[0] != '0' || hex[1] != '0' || (hex[2] != '0' && hex[2] != '1') {
		return false
	}
	v, err := strconv.ParseUint(string(hex[2:]), 16, 8)
	if err != nil {
		return false
	}
	return v != '\t' && v != '\n' && v != '\r'
}

// FetchPackageFile streams a package file into f from offset — a Range
// request when resuming. Implements deploy.Fetcher: a 429 (the server is
// serving its quota of downloads) and network failures come back as
// *deploy.RetryLater, never as a failed command.
func (c *Client) FetchPackageFile(ctx context.Context, packageID, sha256 string, offset, size int64, f *os.File) error {
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
		return &deploy.RetryLater{Wait: time.Second, Err: msg.Err("deploy.download.restart", nil)}
	case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
		wait := time.Minute
		if s, err := strconv.Atoi(resp.Header.Get("Retry-After")); err == nil && s > 0 {
			wait = time.Duration(s) * time.Second
		}
		return &deploy.RetryLater{Wait: wait, Err: msg.Err("deploy.download.busy", msg.Params{"status": resp.StatusCode})}
	default:
		b, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBody))
		return fmt.Errorf("GET %s: %w", path, &StatusError{StatusCode: resp.StatusCode, Body: string(b)})
	}
	// Never more than the manifest announced: a server sending without end
	// must not fill the system volume, as SYSTEM, before the size is checked
	// (audit S24). One byte more than what remains tells « too long » apart.
	remaining := size - offset
	if resp.ContentLength > 0 && resp.StatusCode == http.StatusPartialContent && resp.ContentLength > remaining {
		return msg.Err("deploy.download.size_announced", msg.Params{"path": path, "announced": resp.ContentLength, "expected": remaining})
	}
	if resp.StatusCode == http.StatusOK && resp.ContentLength > size {
		return msg.Err("deploy.download.size_announced", msg.Params{"path": path, "announced": resp.ContentLength, "expected": size})
	}
	limit := remaining
	if resp.StatusCode == http.StatusOK {
		limit = size
	}
	n, err := io.Copy(f, io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return &deploy.RetryLater{Err: msg.Wrap("deploy.download.interrupted", nil, err)}
	}
	if n > limit {
		return msg.Err("deploy.download.too_long", msg.Params{"path": path, "size": size})
	}
	return nil
}

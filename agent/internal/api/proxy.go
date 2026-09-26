package api

import (
	"fmt"
	"net/http"
	"net/url"
	"strings"
)

// Proxy decides how a request reaches the server: the http.Transport.Proxy
// contract. nil means a direct connection.
type Proxy = func(*http.Request) (*url.URL, error)

// Setting values for proxy_url that are not a URL.
const (
	// ProxyDirect connects to the server directly, whatever the poste's
	// environment says. The default, and the empty string means the same.
	ProxyDirect = "direct"
	// ProxyEnvironment honours HTTP_PROXY / HTTPS_PROXY / NO_PROXY, the way
	// every Go program does when told nothing — and the way this agent did
	// before the setting existed.
	ProxyEnvironment = "environment"
)

// ParseProxy turns the proxy_url setting into a Proxy.
//
// The default is a *direct* connection, not the environment, and that is the
// whole reason the setting exists. Go's HTTP client only ever looks at the
// HTTP_PROXY / HTTPS_PROXY / NO_PROXY variables: it knows nothing of the
// Windows proxy settings (Internet Options, `netsh winhttp`), so an exclusion
// list written there is never seen. A parc that pushes HTTPS_PROXY as a
// *system* variable — the one a LocalSystem service inherits — therefore sent
// every heartbeat to the establishment's proxy, which answered 407 Proxy
// Authentication Required to an agent that has no credentials to give, and no
// poste enrolled. The server is on the local network; a direct connection is
// what every deployment so far meant.
//
// Accepted values, case-insensitive for the keywords:
//   - "" or "direct": no proxy.
//   - "environment": HTTP_PROXY / HTTPS_PROXY / NO_PROXY, as before.
//   - a URL (http://proxy:3128, http://user:pass@proxy:3128, socks5://…): that
//     proxy, for every request.
func ParseProxy(setting string) (Proxy, error) {
	s := strings.TrimSpace(setting)
	switch strings.ToLower(s) {
	case "", ProxyDirect, "none":
		return nil, nil
	case ProxyEnvironment, "env":
		return http.ProxyFromEnvironment, nil
	}
	u, err := url.Parse(s)
	if err != nil {
		return nil, fmt.Errorf("proxy_url %q: %w", s, err)
	}
	switch u.Scheme {
	case "http", "https", "socks5", "socks5h":
	default:
		return nil, fmt.Errorf("proxy_url %q: expected %q, %q or a http://, https:// or socks5:// URL",
			s, ProxyDirect, ProxyEnvironment)
	}
	if u.Host == "" {
		return nil, fmt.Errorf("proxy_url %q: no host", s)
	}
	return http.ProxyURL(u), nil
}

// DescribeProxy is the setting as it goes to the log: the keyword, or the
// proxy URL with any password redacted.
func DescribeProxy(setting string) string {
	s := strings.TrimSpace(setting)
	switch strings.ToLower(s) {
	case "", ProxyDirect, "none":
		return ProxyDirect
	case ProxyEnvironment, "env":
		return ProxyEnvironment
	}
	if u, err := url.Parse(s); err == nil {
		return u.Redacted()
	}
	return s
}

package tests

import (
	"bytes"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Run with: CADDY_BIN=/path/to/custom/caddy go test ./tests/romm_test.go
// Requires the same Caddy modules as the Dockerfile, but no live upstreams.
func TestRomMRouting(t *testing.T) {
	binary := os.Getenv("CADDY_BIN")
	if binary == "" {
		binary = "caddy"
	}
	root, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	config, err := os.ReadFile(filepath.Join(root, "Caddyfile"))
	if err != nil {
		t.Fatal(err)
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, r.URL.RequestURI())
	}))
	defer upstream.Close()

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	// Exercise the real routes over local HTTP without requesting certificates.
	localConfig := strings.NewReplacer(
		"newyork.welch.io {", fmt.Sprintf("http://newyork.welch.io:%d {", port),
		"romm.welch.io {", fmt.Sprintf("http://romm.welch.io:%d {", port),
		"rope.local:7676", strings.TrimPrefix(upstream.URL, "http://"),
		"/srv/themes", filepath.Join(root, "themes"),
	).Replace(string(config))
	path := filepath.Join(t.TempDir(), "Caddyfile")
	if err := os.WriteFile(path, []byte(localConfig), 0600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(binary, "run", "--config", path, "--adapter", "caddyfile")
	cmd.Env = append(os.Environ(), "OAUTH_CLIENT_ID=dummy", "OAUTH_CLIENT_SECRET=dummy",
		"OAUTH_AUTH_URL=https://newyork.welch.io/auth/oauth2/github", "JWT_SHARED_KEY=dummy",
		"XDG_DATA_HOME="+t.TempDir(), "XDG_CONFIG_HOME="+t.TempDir())
	var logs bytes.Buffer
	cmd.Stdout, cmd.Stderr = &logs, &logs
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		cmd.Process.Kill()
		cmd.Wait()
		if t.Failed() {
			t.Log(logs.String())
		}
	}()
	client := &http.Client{Timeout: time.Second, CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}
	request := func(host, path string) (*http.Response, error) {
		req, err := http.NewRequest("GET", fmt.Sprintf("http://127.0.0.1:%d%s", port, path), nil)
		if err != nil {
			return nil, err
		}
		req.Host = host
		return client.Do(req)
	}
	deadline := time.Now().Add(15 * time.Second)
	for {
		resp, err := request("newyork.welch.io", "/healthz")
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				break
			}
		}
		if time.Now().After(deadline) {
			t.Fatal("Caddy did not become ready")
		}
		time.Sleep(50 * time.Millisecond)
	}
	for _, path := range []string{"/", "/assets/index.js", "/api/heartbeat?check=1"} {
		t.Run("proxy"+path, func(t *testing.T) {
			resp, err := request("romm.welch.io", path)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				t.Fatal(err)
			}
			if resp.StatusCode != 200 || string(body) != path {
				t.Errorf("want unchanged upstream path %q and HTTP 200; got HTTP %d, %q", path, resp.StatusCode, body)
			}
		})
	}
	for _, tc := range []struct{ path, location string }{
		{"/romm", "https://romm.welch.io/"},
		{"/romm/", "https://romm.welch.io/"},
		{"/romm/rom/123?tab=files", "https://romm.welch.io/rom/123?tab=files"},
	} {
		t.Run("redirect"+tc.path, func(t *testing.T) {
			resp, err := request("newyork.welch.io", tc.path)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusMovedPermanently || resp.Header.Get("Location") != tc.location {
				t.Errorf("want 301 to %q; got %d to %q", tc.location, resp.StatusCode, resp.Header.Get("Location"))
			}
		})
	}
}

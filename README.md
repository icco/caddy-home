# caddy-home

The Caddyfile that sits in front of my home network.

NOTE: currently the docker-compose is broken, so while it gives a rough idea of how to use this image, it does not work exactly.

## OpenCode web protection

The `opencode-web` snippet is imported by OpenCode's Docker label on mist. It
keeps OpenCode's native authentication at `opencode.natwelch.com` and adds:

- An exact Origin check before proxying, including WebSocket upgrades. Clients
  without Origin headers (CLI/API clients) still use native authentication.
- Anti-framing, base-URI and form-action CSP directives in a **second** policy,
  preserving OpenCode's own script hashes and WebAssembly policy.
- HSTS, nosniff, no-referrer and no-store responses for API/authentication routes.
- A named `http.log.access.opencode` logger retaining client IP, method, hostname
  and status for Fail2Ban. Request URLs/headers and response headers are omitted
  because pairing links, query credentials and terminal tickets contain secrets.
  The matching runtime error logger is filtered too, including upstream failures.

The host configuration and secret-rotation steps live in
[icco.me/mist/opencode](https://github.com/icco/icco.me/tree/main/mist/opencode).
Publish this image before deploying the Compose label change. The web UI and
API share one origin; third-party hosted UIs are deliberately rejected by this
route. Keep debug logging off for production credentials.

With a Caddy binary built using this Dockerfile's modules, run:

```sh
CADDY=/path/to/caddy python3 tests/test-opencode-web.py
```

The test provisions both the base Caddyfile and imported route, then checks
authentication passthrough, CSP/header behavior, foreign-origin rejection,
event streams, WebSocket upgrades, and redaction on successful/failed requests.

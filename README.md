# caddy-home

The Caddyfile that sits in front of my home network.

NOTE: currently the docker-compose is broken, so while it gives a rough idea of how to use this image, it does not work exactly.

## OpenCode GitHub login

OpenCode at `opencode.newyork.welch.io` reuses the existing GitHub app and
`newyork.welch.io/auth` portal. The portal's `Domain=newyork.welch.io` cookie
already covers this subdomain, so an existing login works for both sites. The
OAuth callback stays on the parent domain; no new GitHub app is needed.

The OpenCode service imports the `opencode-github` snippet via its Docker label.
Its stricter policy accepts only `authp/admin`, which the portal grants only to
`github.com/icco`. It does not reuse the home policy's general `authp/user` role
or metrics bypasses. All OpenCode paths, including native `/auth` endpoints,
event streams and terminals, require this check.

Cookies are Secure, HttpOnly and SameSite=Lax, retaining the existing shared
cookie scope and session lifetime. Foreign Origin headers are rejected before
proxying, including WebSocket handshakes from other `welch.io` services. Caddy
then replaces upstream Authorization and strips browser cookies. There are no
Basic Auth, bearer-header or query-token bypasses.

Set `OPENCODE_BACKEND_AUTH` on Caddy to base64 of `opencode:<backend password>`.
The existing `JWT_SHARED_KEY` and `OAUTH_CLIENT_SECRET` must come from private
deployment configuration; rotate the previously committed values before enabling
OpenCode. Rotating the shared signing key signs existing portal sessions out.

Deployment, secret generation and rollback are documented in
[icco.me/mist/opencode](https://github.com/icco/icco.me/tree/main/mist/opencode).
Publish this image before merging that repo's activation change. That PR adds
the subdomain's DNS record and redirects the old OpenCode hostname. No new
container or Caddy module is needed.

### Authentication regression checks

With a Caddy binary built using the versions/modules in `Dockerfile`:

```sh
CADDY=/path/to/caddy python3 tests/test-opencode-auth.py
```

This validates the base config and imported route and runs the actual proxy against a local
mock backend with disposable keys. It checks denied paths, credentials, token
expiry, foreign origins and WebSocket handshakes. Completing GitHub login still
requires the deployed OAuth app and a browser.

# caddy-home

The Caddyfile that sits in front of my home network.

NOTE: currently the docker-compose is broken, so while it gives a rough idea of how to use this image, it does not work exactly.

## OpenCode GitHub login

OpenCode uses the existing `caddy-security` module, with a separate GitHub OAuth
app and signing key. Only `github.com/icco` receives the `opencode/user` role;
ordinary GitHub users and the home portal's tokens cannot access the backend.
The one-hour cookies are Secure, HttpOnly, SameSite=Lax and host-only, with
`__Host-` names. Requests with a foreign Origin are rejected before proxying,
including WebSocket handshakes from sibling sites.

This is opt-in: the current deployment can run the new image before activation.
Set `OPENCODE_AUTH_CONFIG=/srv/opencode-auth.caddy` and these secret environment
variables on Caddy:

- `OPENCODE_OAUTH_CLIENT_ID` and `OPENCODE_OAUTH_CLIENT_SECRET`: a dedicated GitHub
  OAuth app, with callback
  `https://opencode.natwelch.com/_auth/oauth2/opencode-github/authorization-code-callback`.
- `OPENCODE_JWT_SHARED_KEY`: a new random signing key, independent of `JWT_SHARED_KEY`.
- `OPENCODE_BACKEND_AUTH`: base64 of `opencode:<backend password>`.

The OpenCode service imports the `opencode-github` snippet via its Docker label.
It routes `/_auth` to the portal and requires the dedicated role for every other
path, including the API, native pairing endpoints, event streams and terminals.
Caddy replaces upstream Authorization after that check and strips browser cookies.
There are no metrics, health, Basic Auth or query-token bypasses in this policy.

Deployment, secret generation and rollback are documented in
[icco.me/mist/opencode](https://github.com/icco/icco.me/tree/main/mist/opencode).
Publish this image before merging that repo's activation change. No new DNS,
container or Caddy module is needed.

### Authentication regression checks

With a Caddy binary built using the versions/modules in `Dockerfile`:

```sh
CADDY=/path/to/caddy python3 tests/test-opencode-auth.py
```

This validates both deployment modes and runs the actual proxy against a local
mock backend with disposable keys. It checks denied paths, credentials, token
expiry, foreign origins and WebSocket handshakes. Completing GitHub login still
requires the deployed OAuth app and a browser.

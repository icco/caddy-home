#!/usr/bin/env python3
"""Exercise the real Caddy auth boundary with disposable keys and a mock backend.

Run: CADDY=/path/to/custom/caddy python3 tests/test-opencode-auth.py
Requires the same modules as Dockerfile. No Docker daemon or GitHub login needed.
"""

import base64
import hashlib
import hmac
import http.client
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
CADDY = os.environ.get("CADDY", "caddy")
KEY = "test-only-shared-portal-signing-key-not-for-production"
BACKEND_AUTH = "Basic " + base64.b64encode(b"opencode:test-backend-password").decode()


def token(role="authp/admin", key=KEY, expiry=3600):
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    now = int(time.time())
    claims = {"sub": "github.com/icco", "roles": [role], "iat": now,
              "nbf": now - 1, "exp": now + expiry, "jti": os.urandom(16).hex()}
    data = encode(b'{"alg":"HS256","typ":"JWT"}') + "." + encode(json.dumps(claims).encode())
    return data + "." + encode(hmac.new(key.encode(), data.encode(), hashlib.sha256).digest())


class Backend(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers["Sec-WebSocket-Key"]
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            return
        body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *_):
        pass


class AuthBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        work = Path(cls.tmp.name)
        env = {**os.environ, "OAUTH_CLIENT_ID": "test", "OAUTH_CLIENT_SECRET": "test",
               "OAUTH_AUTH_URL": "https://newyork.welch.io/auth/oauth2/github", "JWT_SHARED_KEY": KEY,
               "OPENCODE_BACKEND_AUTH": BACKEND_AUTH.split()[1]}
        config = work / "Caddyfile"
        source = (ROOT / "Caddyfile").read_text().replace("/srv/themes", str(ROOT / "themes"))
        config.write_text(source)

        def run(*args):
            result = subprocess.run([CADDY, *args], env=env, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return result.stdout

        # Both pre-activation and activated deployments must provision cleanly.
        run("validate", "--config", str(config))
        config.write_text(source + "\nopencode.newyork.welch.io {\n import opencode-github\n}\n")
        run("validate", "--config", str(config))
        adapted = json.loads(run("adapt", "--config", str(config)))

        cls.backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        cls.addClassCleanup(cls.backend.server_close)
        cls.addClassCleanup(cls.backend.shutdown)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]

        # Retain the production route and policy; replace only listeners/upstream.
        routes = [route for server in adapted["apps"]["http"]["servers"].values()
                  for route in server["routes"]
                  if any(set(match.get("host", [])) & {"opencode.newyork.welch.io", "newyork.welch.io"}
                         for match in route.get("match", []))]
        assert len(routes) == 2, "expected OpenCode and the existing home portal"
        adapted["apps"]["http"]["servers"] = {"test": {
            "listen": [f"127.0.0.1:{cls.port}"], "routes": routes, "automatic_https": {"disable": True}}}
        adapted["apps"].pop("tls", None)
        adapted["storage"] = {"module": "file_system", "root": str(work / "storage")}
        adapted = json.loads(json.dumps(adapted).replace("opencode:4096", f"127.0.0.1:{cls.backend.server_port}"))
        runtime = work / "runtime.json"
        runtime.write_text(json.dumps(adapted))
        cls.log = (work / "caddy.log").open("w+")
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen([CADDY, "run", "--config", str(runtime)], env=env,
                                       stdout=cls.log, stderr=cls.log)

        def stop():
            cls.process.terminate()
            cls.process.wait(timeout=10)

        cls.addClassCleanup(stop)
        for _ in range(100):
            if cls.process.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            try:
                cls.request("/")
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Caddy did not start")

    @classmethod
    def request(cls, path, headers=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)
        try:
            conn.request(method, path, headers={"Host": "opencode.newyork.welch.io", **(headers or {})})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_every_backend_path_requires_gateway_login(self):
        for path in ["/", "/api/info", "/api/event", "/api/pty/test/connect", "/metrics",
                     "/healthz", "/auth/connect/test", "/_auth-other"]:
            for headers in [{}, {"Authorization": BACKEND_AUTH}, {"X-WEBAUTH-USER": "github.com/icco"}]:
                with self.subTest(path=path, headers=headers):
                    status, response, _ = self.request(path, headers)
                    self.assertIn(status, [302, 303, 307])
                    self.assertTrue(response["Location"].startswith("https://newyork.welch.io/auth/oauth2/github"))

    def test_authorized_request_replaces_credentials_and_strips_cookies(self):
        status, _, body = self.request("/api/info", {
            "Cookie": "AUTHP_ACCESS_TOKEN=" + token(), "Authorization": "Basic attacker"})
        self.assertEqual(status, 200, body)
        headers = json.loads(body)
        self.assertEqual(headers["Authorization"], BACKEND_AUTH)
        self.assertNotIn("Cookie", headers)

    def test_wrong_role_key_and_expired_tokens_are_denied(self):
        for value in [token(role="authp/user"), token(role="opencode/user"),
                      token(key="test-retired-key"), token(expiry=-60)]:
            with self.subTest(token=value):
                status, _, _ = self.request("/api/info", {"Cookie": "AUTHP_ACCESS_TOKEN=" + value})
                self.assertNotEqual(status, 200)

    def test_bearer_and_query_tokens_are_not_login_bypasses(self):
        value = token()
        for path, headers in [("/api/info", {"Authorization": "Bearer " + value}),
                              ("/api/info?access_token=" + value, {})]:
            status, _, _ = self.request(path, headers)
            self.assertIn(status, [302, 303, 307])

    def test_foreign_origins_are_denied_including_sibling_sites(self):
        for origin in ["https://evil.example", "https://other.newyork.welch.io", "https://newyork.welch.io", "null"]:
            for method in ["GET", "POST"]:
                with self.subTest(origin=origin, method=method):
                    status, _, _ = self.request("/api/info", {
                        "Cookie": "AUTHP_ACCESS_TOKEN=" + token(), "Origin": origin}, method)
                    self.assertEqual(status, 403)
        status, _, _ = self.request("/api/info", {
            "Cookie": "AUTHP_ACCESS_TOKEN=" + token(),
            "Origin": "https://opencode.newyork.welch.io"}, "POST")
        self.assertEqual(status, 200)

    def test_websocket_handshake_requires_cookie_and_same_origin(self):
        headers = {"Connection": "Upgrade", "Upgrade": "websocket",
                   "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                   "Origin": "https://opencode.newyork.welch.io"}
        status, _, _ = self.request("/api/pty/test/connect", headers)
        self.assertIn(status, [302, 303, 307])
        headers["Cookie"] = "AUTHP_ACCESS_TOKEN=" + token()
        status, response, _ = self.request("/api/pty/test/connect", headers)
        self.assertEqual(status, 101)
        self.assertEqual({key.lower(): value for key, value in response.items()}["sec-websocket-accept"],
                         "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")
        headers["Origin"] = "https://other.newyork.welch.io"
        status, _, _ = self.request("/api/pty/test/connect", headers)
        self.assertEqual(status, 403)

    def test_oauth_start_reuses_existing_app_and_shared_secure_cookie(self):
        status, headers, _ = self.request("/auth/oauth2/github", {"Host": "newyork.welch.io"})
        self.assertIn(status, [302, 303, 307])
        location = urllib.parse.urlparse(headers["Location"])
        self.assertEqual(location.netloc, "github.com")
        query = urllib.parse.parse_qs(location.query)
        self.assertEqual(query["client_id"], ["test"])
        callback = urllib.parse.urlparse(query["redirect_uri"][0])
        self.assertEqual(callback.netloc, "newyork.welch.io")
        self.assertEqual(callback.path, "/auth/oauth2/github/authorization-code-callback")
        cookie = headers["Set-Cookie"]
        self.assertIn("AUTHP_", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Domain=newyork.welch.io", cookie)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Run the production Caddy snippet with a local authenticated mock backend.

Usage: CADDY=/path/to/custom/caddy python3 tests/test-opencode-web.py
"""

import base64
import hashlib
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

ROOT = Path(__file__).resolve().parents[1]
AUTH = "Basic " + base64.b64encode(b"opencode:disposable-test-password").decode()


class Backend(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/auth/connect/error-"):
            self.close_connection = True
            return
        if self.headers.get("Authorization") != AUTH:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Secure Area"')
            self.end_headers()
            return
        if self.headers.get("Upgrade", "").lower() == "websocket":
            accept = base64.b64encode(hashlib.sha1(
                (self.headers["Sec-WebSocket-Key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            return
        body = b"data: test-event\n\n" if self.path == "/api/event" else b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if self.path == "/api/event" else "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "script-src 'self' 'wasm-unsafe-eval'")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Location", "/auth/connect/response-secret-marker")
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, *_):
        pass


class WebBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        work = Path(cls.tmp.name)
        caddy = os.environ.get("CADDY", "caddy")
        env = {**os.environ, "OAUTH_CLIENT_ID": "test", "OAUTH_CLIENT_SECRET": "test",
               "OAUTH_AUTH_URL": "https://newyork.welch.io/auth", "JWT_SHARED_KEY": "test-only"}
        config = work / "Caddyfile"
        source = (ROOT / "Caddyfile").read_text().replace("/srv/themes", str(ROOT / "themes"))

        def run(*args):
            result = subprocess.run([caddy, *args], env=env, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return result.stdout

        config.write_text(source)
        run("validate", "--config", str(config))
        config.write_text(source + "\nopencode.natwelch.com {\n import opencode-web\n}\n")
        run("validate", "--config", str(config))
        adapted = json.loads(run("adapt", "--config", str(config)))
        cls.backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        cls.addClassCleanup(cls.backend.server_close)
        cls.addClassCleanup(cls.backend.shutdown)
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        servers = adapted["apps"]["http"]["servers"]
        server = next(server for server in servers.values() if any(
            "opencode.natwelch.com" in match.get("host", [])
            for route in server["routes"] for match in route.get("match", [])))
        server["routes"] = [route for route in server["routes"] if any(
            "opencode.natwelch.com" in match.get("host", []) for match in route.get("match", []))]
        server["listen"] = [f"127.0.0.1:{cls.port}"]
        server["automatic_https"] = {"disable": True}
        server.pop("tls_connection_policies", None)
        adapted["apps"]["http"]["servers"] = {"test": server}
        adapted["apps"].pop("tls", None)
        adapted["storage"] = {"module": "file_system", "root": str(work / "storage")}
        runtime = work / "runtime.json"
        runtime.write_text(json.dumps(adapted).replace("opencode:4096", f"127.0.0.1:{cls.backend.server_port}"))
        cls.log = (work / "caddy.log").open("w+")
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen([caddy, "run", "--config", str(runtime)], env=env,
                                       stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop)
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
    def stop(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
            cls.process.wait(timeout=10)

    @classmethod
    def request(cls, path, headers=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=5)
        try:
            conn.request(method, path, headers={"Host": "opencode.natwelch.com", **(headers or {})})
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def test_authentication_is_still_enforced_upstream(self):
        for path in ["/api/info", "/api/session", "/api/event", "/openapi.json"]:
            for headers in [{}, {"Authorization": "Basic invalid"}]:
                status, response, _ = self.request(path, headers)
                self.assertEqual(status, 401)
                self.assertIn("Basic", response["WWW-Authenticate"])
                self.assertEqual(response["X-Frame-Options"], "DENY")
                self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(self.request("/api/info", {"Authorization": AUTH})[0], 200)

    def test_security_headers_preserve_the_app_csp(self):
        status, headers, _ = self.request("/api/info", {"Authorization": AUTH})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        policies = headers.get_all("Content-Security-Policy")
        self.assertIn("script-src 'self' 'wasm-unsafe-eval'", policies)
        self.assertIn("frame-ancestors 'none'; base-uri 'self'; form-action 'self'", policies)
        # Static assets can still be cached normally.
        self.assertEqual(self.request("/_assets/app.js", {"Authorization": AUTH})[1]["Cache-Control"],
                         "public, max-age=3600")

    def test_foreign_origins_are_rejected_before_authenticated_requests(self):
        for origin in ["https://untrusted.example", "https://art.natwelch.com", "null"]:
            for method in ["GET", "POST", "OPTIONS"]:
                status, _, _ = self.request("/api/info", {"Authorization": AUTH, "Origin": origin}, method)
                self.assertEqual(status, 403)
        self.assertEqual(self.request("/api/info", {
            "Authorization": AUTH, "Origin": "https://opencode.natwelch.com"}, "POST")[0], 200)

    def test_streams_and_websocket_upgrades(self):
        status, headers, body = self.request("/api/event", {"Authorization": AUTH})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertEqual(body, b"data: test-event\n\n")
        headers = {"Authorization": AUTH, "Connection": "Upgrade", "Upgrade": "websocket",
                   "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                   "Origin": "https://opencode.natwelch.com"}
        self.assertEqual(self.request("/api/pty/test/connect", headers)[0], 101)
        headers["Origin"] = "https://untrusted.example"
        self.assertEqual(self.request("/api/pty/test/connect", headers)[0], 403)

    def test_z_credentials_are_redacted_from_access_and_error_logs(self):
        headers = {"Authorization": AUTH, "Cookie": "opencode_session=cookie-secret-marker",
                   "Referer": "https://opencode.natwelch.com/?auth_token=referer-secret-marker"}
        self.request("/auth/connect/pairing-secret-marker?auth_token=query-secret-marker", headers)
        self.assertEqual(self.request("/auth/connect/error-secret-marker", headers)[0], 502)
        self.stop()
        self.log.seek(0)
        text = self.log.read()
        for secret in [AUTH, "pairing-secret-marker", "query-secret-marker", "referer-secret-marker",
                       "cookie-secret-marker", "response-secret-marker", "error-secret-marker"]:
            self.assertNotIn(secret, text)
        records = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        access = [r for r in records if r.get("logger") == "http.log.access.opencode"]
        errors = [r for r in records if r.get("logger") == "http.log.error.opencode"]
        self.assertTrue(access)
        self.assertTrue(errors)
        self.assertTrue(any(r["status"] == 401 for r in access))
        for record in access + errors:
            self.assertEqual(record["request"]["host"], "opencode.natwelch.com")
            self.assertIn("client_ip", record["request"])
            self.assertNotIn("uri", record["request"])
            self.assertNotIn("headers", record["request"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

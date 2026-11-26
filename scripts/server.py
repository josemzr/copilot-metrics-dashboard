"""Only the dashboard, validated snapshots and collection status are served."""
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse

from snapshot import read_snapshot, with_center_labels
from pricing import STORE as PRICES

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # URLs can contain untrusted strings; do not log request data.
        pass

    def send_body(self, code, body, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src data: blob:; base-uri 'none'; "
                         "object-src 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json_body(self, code, value):
        self.send_body(code, json.dumps(value, allow_nan=False).encode())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        host = self.headers.get("Host", "").split(":")[0]
        if host not in ("localhost", "127.0.0.1"):
            self.json_body(403, dict(error="Use the local dashboard address"))
            return
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/" and not url.query:
            body = (ROOT / "web/dist/index.html").read_bytes()
            if os.environ.get("DATA_MODE") == "MANUAL":
                body = body.replace(b'<html lang="en">', b'<html lang="en" data-mode="manual">', 1)
            self.send_body(200, body, "text/html; charset=utf-8")
        elif url.path == "/healthz" and not url.query:
            self.json_body(200, dict(status="alive"))
        elif url.path == "/api/pricing" and not url.query:
            self.json_body(200, PRICES.get())
        elif url.path == "/api/status" and not url.query:
            if os.environ.get("DATA_MODE") == "MANUAL":
                self.json_body(200, dict(state="manual", lastAttempt=None,
                                         lastSuccess=None, lastError=None))
                return
            path = Path(os.environ.get("DATA_DIR", "/data")) / "status.json"
            try:
                with path.open("rb") as stream:
                    body = stream.read(8193)
                if len(body) > 8192:
                    raise ValueError
                status = json.loads(body)
                allowed = {"state", "lastAttempt", "lastSuccess", "lastError"}
                if not isinstance(status, dict) or set(status) - allowed:
                    raise ValueError
                self.json_body(200, status)
            except FileNotFoundError:
                self.json_body(200, dict(state="disabled", lastAttempt=None,
                                         lastSuccess=None, lastError=None))
            except (ValueError, OSError):
                self.json_body(503, dict(state="error", lastError="Collection status is unavailable"))
        elif url.path == "/api/dataset":
            params = urllib.parse.parse_qs(url.query, keep_blank_values=True)
            if params not in ({"mode": ["SAMPLE"]}, {"mode": ["REAL"]}):
                self.json_body(400, dict(error="Select mode=SAMPLE or mode=REAL"))
                return
            mode = params["mode"][0]
            if mode == "REAL" and os.environ.get("DATA_MODE") == "MANUAL":
                self.json_body(503, dict(error="Manual mode: import your local dataset.json in the browser"))
                return
            path = (ROOT / "data/sample/dataset.json" if mode == "SAMPLE"
                    else Path(os.environ.get("DATA_DIR", "/data")) / "dataset.json")
            try:
                self.json_body(200, with_center_labels(read_snapshot(path, mode)))
            except FileNotFoundError:
                self.json_body(503, dict(error="No valid REAL snapshot yet. Enable and configure the collector."))
            except (ValueError, KeyError, TypeError, OSError):
                self.json_body(503, dict(error="Stored snapshot is invalid or unavailable"))
        else:
            self.json_body(404, dict(error="Not found"))


def main():
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

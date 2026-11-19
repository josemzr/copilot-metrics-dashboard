from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect
from collect import Client, ContractError
from make_sample import make_sample
import server
from snapshot import atomic_json, read_snapshot, validate
import worker


class FixtureAPI(BaseHTTPRequestHandler):
    failure = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        if type(self).failure:
            self.send_response(403)
            self.end_headers()
            return
        url = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(url.query)
        if url.path.endswith("/cost-centers"):
            value = {"costCenters": []}
        elif url.path.endswith("/budgets"):
            value = {"budgets": [], "has_next_page": False}
        elif url.path.endswith("/users-1-day"):
            value = {"report_day": params["day"][0],
                     "download_links": ["https://reports.example.test/part"]}
        else:
            value = {"timePeriod": {name: int(params[name][0]) for name in ("year", "month", "day")},
                     "usageItems": []}
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = make_sample()[0]

    def test_collection_http_failure_preserves_last_valid_snapshot_and_reports_error(self):
        api = ThreadingHTTPServer(("127.0.0.1", 0), FixtureAPI)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        fixture_base = f"http://127.0.0.1:{api.server_port}"

        class FixtureOpener:
            def open(self, request, timeout):
                path = request.full_url.removeprefix(collect.API_BASE)
                return urllib.request.urlopen(fixture_base + path, timeout=timeout)

        def client_factory():
            client = Client(collect.API_BASE, collect.API_VERSION, "fixture-not-a-token")
            client.opener = FixtureOpener()
            return client

        config = dict(enterprise="example", collect_days=1, countries={},
                      telemetry_assignments=[], billing_users=[], collect_licenses=False)
        try:
            with tempfile.TemporaryDirectory() as directory:
                # Only the download transport is stubbed; API requests hit the authorized fixture server.
                with patch("collect.download_url", return_value=b""):
                    FixtureAPI.failure = False
                    self.assertTrue(worker.run_once(config, directory, client_factory))
                    original = (Path(directory) / "dataset.json").read_bytes()
                    self.assertEqual(read_snapshot(Path(directory) / "dataset.json", "REAL")["Info"][0]["Mode"], "REAL")
                    FixtureAPI.failure = True
                    self.assertFalse(worker.run_once(config, directory, client_factory))
                    self.assertEqual((Path(directory) / "dataset.json").read_bytes(), original)
                    status = json.loads((Path(directory) / "status.json").read_text())
                    self.assertEqual(status["state"], "error")
                    self.assertIsNotNone(status["lastSuccess"])
                    self.assertIn("unchanged", status["lastError"])
        finally:
            FixtureAPI.failure = False
            api.shutdown()
            api.server_close()
            thread.join()

    def test_invalid_candidate_does_not_replace_valid_snapshot(self):
        data = deepcopy(self.sample)
        data["Info"][0]["Mode"] = "REAL"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset.json"
            atomic_json(path, data)
            original = path.read_bytes()
            config = dict(collect_days=1)
            with patch("worker.collect", return_value={}), patch("worker.normalize", return_value={"Info": []}):
                self.assertFalse(worker.run_once(config, directory, lambda: object()))
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_downloads_have_no_authorization_and_reject_redirect_or_nonpublic_hosts(self):
        class Response(io.BytesIO):
            pass

        class Opener:
            def open(inner, request, timeout):
                self.assertIsNone(request.get_header("Authorization"))
                self.assertEqual(request.full_url, "https://reports.example.test/part")
                return Response(b'{"day":"2026-11-01"}\n')

        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with patch("collect.socket.getaddrinfo", return_value=public), patch(
                "collect.urllib.request.build_opener", return_value=Opener()):
            self.assertIn(b"day", collect.download_url("https://reports.example.test/part"))
        for link in ("http://example.test/part", "https://user:pass@example.test/part",
                     "https://example.test:444/part"):
            with self.assertRaises(ContractError):
                collect.download_url(link)
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch("collect.socket.getaddrinfo", return_value=private):
            with self.assertRaisesRegex(ContractError, "public HTTPS"):
                collect.download_url("https://example.test/part")
        with self.assertRaises(ContractError):
            collect.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.test")

    def test_report_part_limits_dates_and_ndjson_are_enforced(self):
        client = Client(collect.API_BASE, collect.API_VERSION, "unused")
        metadata = dict(report_day="2026-11-01", download_links=["https://reports.example.test/part"])
        client.get = lambda *a, **k: metadata
        with patch("collect.download_url", return_value=b'{"day":"2026-11-01"}\n[{"day":"2026-11-01"}]\n'):
            self.assertEqual(len(client.report("/report", "2026-11-01")), 2)
        metadata["download_links"] *= 33
        with self.assertRaisesRegex(ContractError, "part count"):
            client.report("/report", "2026-11-01")
        metadata["download_links"] = ["https://reports.example.test/part"]
        with patch("collect.download_url", return_value=b"not-json"):
            with self.assertRaisesRegex(ContractError, "invalid NDJSON"):
                client.report("/report", "2026-11-01")
        with self.assertRaisesRegex(ContractError, "metadata"):
            client.report("/report", "2026-11-02")

    def test_pagination_rate_limit_and_size_budgets_are_bounded(self):
        class Endless:
            def get(self, *args, **kwargs):
                return {"rows": [1], "has_next_page": True}
        with patch("collect.MAX_PAGES", 2):
            with self.assertRaisesRegex(ContractError, "terminate"):
                collect.paged(Endless(), "/rows", "rows")
        with self.assertRaisesRegex(ContractError, "size limit"):
            collect.bounded_json(io.BytesIO(b" " * 20), limit=10)
        client = Client(collect.API_BASE, collect.API_VERSION, "unused")
        error = urllib.error.HTTPError(collect.API_BASE, 429, "", {"Retry-After": "1000"}, None)
        with patch.object(client.opener, "open", side_effect=error) as opened, patch("collect.time.sleep") as sleep:
            with self.assertRaisesRegex(ContractError, "HTTP 429"):
                client.get("/test")
            self.assertEqual(opened.call_count, 3)
            self.assertTrue(all(call.args[0] <= 30 for call in sleep.call_args_list))
        client.requests = 5000
        with self.assertRaisesRegex(ContractError, "budget"):
            client.get("/test")

    def test_snapshot_rejects_bad_provenance_scalars_and_nonfinite_values(self):
        for change in (
            lambda d: d["Info"][0].update(Mode="UNKNOWN"),
            lambda d: d["Metrics"][0].update(Generations=float("nan")),
            lambda d: d["Metrics"][0].update(Generations={}),
            lambda d: d["Metrics"][0].update(__proto__="bad"),
            lambda d: d["Centers"][0].update(Country=8),
            lambda d: d["Metrics"][0].pop("Day"),
        ):
            data = deepcopy(self.sample)
            change(data)
            with self.assertRaises((ContractError, ValueError)):
                validate(data)
        with self.assertRaises(ContractError):
            validate(self.sample, "REAL")

    def test_app_signing_uses_ephemeral_rsa_key_and_short_lived_installation_token(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        captured = []

        class FakeClient:
            def __init__(self, base, version, token):
                captured.append(token)

            def request(self, path, method, body):
                self_case.assertEqual(path, "/app/installations/000000/access_tokens")
                self_case.assertEqual(method, "POST")
                self_case.assertEqual(body, b"{}")
                return {"token": "fixture-installation-value"}

        self_case = self
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ephemeral-signing-fixture"
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                               serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            path.chmod(0o600)
            with patch("collect.Client", FakeClient), patch("collect.time.time", return_value=1800000000):
                collect.app_client("000000", "000000", path)
        header, payload, signature = captured[0].split(".")
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        claims = json.loads(decode(payload))
        self.assertEqual(claims["iss"], "000000")
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)
        key.public_key().verify(decode(signature), (header + "." + payload).encode(),
                                padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(captured[1], "fixture-installation-value")

    def test_private_key_permission_error_is_actionable_without_exposing_its_path(self):
        with tempfile.TemporaryDirectory() as directory:
            def denied():
                raise PermissionError("fixture path must not enter status")
            self.assertFalse(worker.run_once(dict(collect_days=1), directory, denied))
            status = json.loads((Path(directory) / "status.json").read_text())
            self.assertIn("COLLECTOR_UID", status["lastError"])
            self.assertNotIn("fixture path", status["lastError"])

    def test_optional_curl_header_helper_requires_explicit_flag_and_app_environment(self):
        output = io.StringIO()
        env = dict(GITHUB_APP_ID="000000", GITHUB_INSTALLATION_ID="000000",
                   GITHUB_APP_PRIVATE_KEY_FILE="/outside/project/fixture-key")
        with patch.dict("os.environ", env), patch("collect.app_client", return_value=SimpleNamespace(
                token="fixture-installation-value")), patch("sys.stdout", output):
            self.assertEqual(collect.main(["--authorization-header"]), 0)
        self.assertEqual(output.getvalue(), "Authorization: Bearer fixture-installation-value\n")
        with patch.dict("os.environ", {}, clear=True), patch("sys.stderr", io.StringIO()):
            self.assertEqual(collect.main(["--authorization-header"]), 1)

    def test_server_returns_real_unavailable_without_serving_sample_as_real(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"DATA_DIR": directory}):
            http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{http.server_port}"
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(base + "/api/dataset?mode=REAL")
                self.assertEqual(caught.exception.code, 503)
                self.assertIn("No valid REAL", json.load(caught.exception)["error"])
                caught.exception.close()
                with urllib.request.urlopen(base + "/api/status") as response:
                    self.assertEqual(json.load(response)["state"], "disabled")
                for path in ("/.env", "/.git/config", "/%2e%2e/.env", "/admin/.secrets/key"):
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(base + path)
                    self.assertEqual(denied.exception.code, 404)
                    denied.exception.close()
            finally:
                http.shutdown()
                http.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()

from copy import deepcopy
import datetime as dt
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from collect import ContractError
from download_local import AccountClient, DownloadError, ScopeCapture, account_client, configuration, download, main
from make_sample import make_sample
from snapshot import TABLES, atomic_json, read_snapshot
from kit.build_local_kit import build as build_kit
from server import Handler

NO_TOKEN_OVERRIDES = {name: "" for name in (
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
)}


class FixtureAPI:
    def __init__(self):
        self.data, self.raw, self.mapping = make_sample()
        self.calls, self.reports = [], []
        self.failure = None
        self.denied_suffix = None
        self.oauth_scopes = "gist, manage_billing:enterprise, read:org, repo, workflow"

    def page(self, rows, params, key):
        size = min(params.get("per_page", 100), 3)
        page = params.get("page", 1)
        values = rows[(page - 1) * size:page * size]
        return {key: deepcopy(values), "has_next_page": page * size < len(rows)}

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "/user":
            return {"login": "example-user"}
        if self.denied_suffix and path.endswith(self.denied_suffix):
            raise ContractError("GitHub HTTP 403; response body must not be logged")
        if self.failure == "permission":
            raise ContractError("GitHub HTTP 403; fixture-only")
        if path.endswith("/cost-centers"):
            return self.page(self.raw["cost_centers"], params, "costCenters")
        if "/cost-centers/" in path:
            center = deepcopy(next(c for c in self.raw["cost_centers"] if path.endswith("/" + c["id"])))
            page = self.page(center["resources"], params, "resources")
            return dict(center, **page)
        if path.endswith("/budgets"):
            return self.page(self.raw["budgets"], params, "budgets")
        if path.endswith("/seats"):
            return self.page(self.raw["license_snapshot"]["seats"], params, "seats")
        if path.endswith("/users-1-day"):
            return {"report_day": params["day"], "download_links": ["https://reports.example.test/part"]}
        day = dt.date(params["year"], params["month"], params["day"]).isoformat()
        group = next((g for g in self.raw["billing"] if g["day"] == day
                      and g["cost_center_id"] == params["cost_center_id"]), None)
        empty = dict(timePeriod={key: params[key] for key in ("year", "month", "day")},
                     costCenter={"id": params["cost_center_id"]}, usageItems=[])
        if group is None:
            return empty
        if "user" not in params:
            return deepcopy(group["total"])
        detail = next((d for d in group["details"] if d["user"] == params["user"]), None)
        result = deepcopy(detail["response"]) if detail else empty
        if self.failure == "overcount" and result["usageItems"]:
            result["usageItems"][0]["grossQuantity"] += 1000000
        return result

    def report(self, path, day):
        self.reports.append(day)
        return deepcopy([r for r in self.raw["users"] if r["day"] == day])


class ManualDownloadTests(unittest.TestCase):
    def setUp(self):
        self.api = FixtureAPI()
        self.config = configuration("example-enterprise", "2026-11-14", "2026-11-16",
                                    dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc))

    def test_selected_identity_is_checked_without_token_arguments_or_auth_mutation(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            self.assertTrue(kwargs["capture_output"])
            return SimpleNamespace(returncode=0, stdout="fixture-only-token\n", stderr="")
        def factory(base, version, token):
            self.assertEqual(token, "fixture-only-token")
            return SimpleNamespace(get=lambda path: {"login": "Example-User"},
                                   oauth_scopes="repo, read:enterprise, manage_billing:enterprise")
        with patch.dict(os.environ, {}, clear=True):
            account_client("example-user", runner=runner, client_factory=factory)
        self.assertEqual(calls, [["gh", "auth", "token", "--hostname", "github.com", "--user", "example-user"]])
        self.assertNotIn("fixture-only-token", str(calls))

    def test_auth_failures_and_environment_overrides_never_fall_back(self):
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout="fixture-only-token", stderr="")
        for login, scopes in (("other-user", "read:enterprise, manage_billing:enterprise"),
                              (None, "repo")):
            factory = lambda *a, login=login, scopes=scopes: SimpleNamespace(
                get=lambda path: {"login": login}, oauth_scopes=scopes)
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(DownloadError):
                account_client("example-user", runner=runner, client_factory=factory)
        with patch.dict(os.environ, {"GH_TOKEN": "fixture-only-override"}, clear=True), self.assertRaises(DownloadError):
            account_client("example-user", runner=lambda *a, **k: self.fail("Must not read another credential"))
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(DownloadError) as failure:
            account_client("example-user", runner=lambda *a, **k: SimpleNamespace(
                returncode=1, stdout="fixture-sensitive-output", stderr="fixture-sensitive-output"))
        self.assertNotIn("fixture-sensitive-output", str(failure.exception))

    def test_normalized_enterprise_billing_consent_passes_when_all_five_sources_authorize(self):
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout="fixture-only-token", stderr="")
        loader = lambda login: account_client(login, runner=runner, client_factory=lambda *a: self.api)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, NO_TOKEN_OVERRIDES):
            data = download(directory, self.config, "example-user", client_loader=loader)
        self.assertEqual(self.api.oauth_scopes, "gist, manage_billing:enterprise, read:org, repo, workflow")
        self.assertEqual(set(data), TABLES)
        self.assertEqual(data["Info"][0]["Mode"], "REAL")
        for suffix in ("/cost-centers", "/budgets", "/seats", "/ai_credit/usage", "/users-1-day"):
            self.assertTrue(any(path.endswith(suffix) for path, _ in self.api.calls))
        self.assertEqual(len(self.api.reports), 3)

    def test_partial_consent_with_source_403_is_rejected_before_reports_and_preserves_last_good(self):
        self.api.oauth_scopes = "repo"
        self.api.denied_suffix = "/budgets"
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout="fixture-only-token", stderr="")
        loader = lambda login: account_client(login, runner=runner, client_factory=lambda *a: self.api)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, NO_TOKEN_OVERRIDES):
            path = Path(directory) / "dataset.json"
            atomic_json(path, self.api.data)
            before = path.read_bytes()
            with self.assertRaises(DownloadError) as failure:
                download(directory, self.config, "example-user", client_loader=loader)
            self.assertIn("Budgets", str(failure.exception))
            self.assertIn("HTTP 403", str(failure.exception))
            self.assertNotIn("response body", str(failure.exception))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.api.reports, [])

    def test_oauth_scope_capture_and_account_client_get_only_guard(self):
        capture = ScopeCapture()
        response = SimpleNamespace(headers={"X-OAuth-Scopes": "read:enterprise,manage_billing:enterprise"})
        self.assertIs(capture.https_response(urllib.request.Request("https://api.github.com/user"), response), response)
        self.assertEqual(capture.scopes, response.headers["X-OAuth-Scopes"])
        client = AccountClient("https://api.github.com", "2026-03-10", "fixture-only")
        with self.assertRaisesRegex(DownloadError, "GET-only"):
            client.request("/fixture", method="POST", body=b"{}")

    def test_explicit_dates_have_no_hidden_two_day_lag(self):
        now = dt.datetime(2026, 11, 19, 12, tzinfo=dt.timezone.utc)
        config = configuration("example-enterprise", "2026-11-18", "2026-11-18", now)
        self.assertEqual((config["start_day"], config["end_day"]), ("2026-11-18", "2026-11-18"))
        for start, end in (("2026-11-19", "2026-11-19"), ("2026-11-18", "2026-11-17"),
                           ("2026-10-01", "2026-11-18"), ("20261118", "2026-11-18")):
            with self.assertRaises((ContractError, ValueError)):
                configuration("example-enterprise", start, end, now)

    def test_all_sources_and_pagination_produce_one_complete_normalized_dataset(self):
        with tempfile.TemporaryDirectory(prefix="manual data ") as directory:
            data = download(directory, self.config, "example-user", client_loader=lambda user: self.api)
            loaded = read_snapshot(Path(directory) / "dataset.json", "REAL")
            self.assertEqual(data, loaded)
            self.assertEqual(set(data), TABLES)
            self.assertEqual(len(data["Licenses"]), 22)
            self.assertEqual(len(data["Budgets"]), 6)
            self.assertEqual(len(data["Metrics"]), 66)
            self.assertEqual(self.api.reports, ["2026-11-14", "2026-11-15", "2026-11-16"])
            self.assertTrue(any(p.endswith("/budgets") and q["page"] > 1 for p, q in self.api.calls if "page" in q))
            self.assertTrue(any(p.endswith("/seats") and q["page"] > 1 for p, q in self.api.calls if "page" in q))
            self.assertTrue(any("/cost-centers/" in p and q["page"] > 1 for p, q in self.api.calls if "page" in q))
            self.assertTrue(all(r["CenterId"] == "unattributed-history" for r in data["Metrics"]))
            self.assertFalse(any(r["HistoricalRosterComplete"] for r in data["LicenseCoverage"]))
            self.assertNotIn("fixture-only-token", (Path(directory) / "dataset.json").read_text())

    def test_permission_and_reconciliation_failures_preserve_last_good_file(self):
        for failure in ("permission", "overcount"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "dataset.json"
                atomic_json(path, self.api.data)
                previous = path.read_bytes()
                self.api.failure = failure
                self.api.reports = []
                with self.assertRaises(DownloadError):
                    download(directory, self.config, "example-user", client_loader=lambda user: self.api)
                self.assertEqual(path.read_bytes(), previous)
                self.assertEqual(json.loads((Path(directory) / "download-status.json").read_text())["state"], "error")
                if failure == "permission":
                    self.assertEqual(self.api.reports, [])

    def test_sample_will_not_overwrite_real_and_errors_do_not_echo_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            data = deepcopy(self.api.data)
            data["Info"][0]["Mode"] = "REAL"
            path = Path(directory) / "dataset.json"
            atomic_json(path, data)
            previous = path.read_bytes()
            with patch("sys.stderr", io.StringIO()) as stderr:
                self.assertEqual(main(["--sample", "--output-directory", directory]), 1)
            self.assertIn("will not overwrite", stderr.getvalue())
            self.assertEqual(path.read_bytes(), previous)


class PortableKitTests(unittest.TestCase):
    def test_manual_server_does_not_read_an_accidental_real_snapshot_or_run_a_collector(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"DATA_MODE": "MANUAL", "DATA_DIR": directory}):
            data = make_sample()[0]
            data["Info"][0]["Mode"] = "REAL"
            atomic_json(Path(directory) / "dataset.json", data)
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/api/status") as response:
                    self.assertEqual(json.load(response)["state"], "manual")
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(base + "/api/dataset?mode=REAL")
                self.assertEqual(failure.exception.code, 503)
                self.assertIn("import your local", json.load(failure.exception)["error"])
                failure.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_stdlib_sample_and_ready_to_open_allowlisted_sample_kit(self):
        with tempfile.TemporaryDirectory(prefix="portable kit ") as directory:
            output = Path(directory) / "local kit.zip"
            names = build_kit(output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(names), set(archive.namelist()))
                self.assertIn("powerbi/CopilotMetrics.pbip", names)
                self.assertIn("scripts/download.ps1", names)
                self.assertIn("compose.manual.yaml", names)
                bundled_mix = json.loads(archive.read("projections/mixes.json"))
                contract = json.loads(archive.read("projections/contract.json"))
                self.assertEqual(bundled_mix, contract["mixes"])
                self.assertFalse(any(n.startswith((".git/", "cloud/", "data/real/")) or n.endswith(".pem") for n in names))
                folder = Path(directory) / "unpacked kit with spaces"
                archive.extractall(folder)
            target = Path(directory) / "private sample with spaces"
            run = subprocess.run([sys.executable, "-S", str(folder / "scripts/download_local.py"),
                                  "--sample", "--output-directory", str(target)],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(read_snapshot(target / "dataset.json", "SAMPLE"), make_sample()[0])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required for the portable entrypoint check")
    def test_powershell_sample_from_an_unpacked_kit_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="PowerShell kit ") as directory:
            package = Path(directory) / "kit.zip"
            build_kit(package)
            folder = Path(directory) / "kit with spaces"
            with zipfile.ZipFile(package) as archive:
                archive.extractall(folder)
            target = Path(directory) / "private JSON with spaces"
            run = subprocess.run(["pwsh", "-NoLogo", "-NoProfile", "-File", str(folder / "scripts/download.ps1"),
                                  "-Sample", "-OutputDirectory", str(target)],
                                 capture_output=True, text=True, timeout=60, cwd=folder)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(read_snapshot(target / "dataset.json", "SAMPLE"), make_sample()[0])
            previous = (target / "dataset.json").read_bytes()
            failed = subprocess.run([
                "pwsh", "-NoLogo", "-NoProfile", "-File", str(folder / "scripts/download.ps1"),
                "-GitHubUser", "example-user", "-Enterprise", "example-enterprise",
                "-StartDay", "2026-11-14", "-EndDay", "2026-11-16", "-OutputDirectory", str(target)],
                env=dict(os.environ, GH_TOKEN="fixture-only-not-a-real-token"),
                capture_output=True, text=True, timeout=60, cwd=folder)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("token environment overrides", failed.stderr)
            self.assertNotIn("fixture-only-not-a-real-token", failed.stdout + failed.stderr)
            self.assertEqual((target / "dataset.json").read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()

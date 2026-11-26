from copy import deepcopy
import datetime as dt
import io
import inspect
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "cloud/app"), str(ROOT / "cloud")]
from collect import ContractError, app_client
from make_sample import make_sample
from pipeline import CollectionFailed, DATASET, STATUS, SUCCESS, configuration, dataset_content, execute
from build_package import build
import powerbi as cloud_powerbi


def real_fixture():
    data = make_sample()[0]
    data["Info"][0]["Mode"] = "REAL"
    data["Info"][0]["Label"] = "Synthetic REAL cloud test fixture"
    return data


class CloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = real_fixture()
        cls.settings = dict(GITHUB_APP_ID="000000", GITHUB_INSTALLATION_ID="000000",
                            GITHUB_ENTERPRISE="example-enterprise", COLLECT_DAYS="16",
                            GITHUB_KEY_SECRET_NAME="fixture-key")
        cls.now = dt.datetime(2026, 11, 18, 20, tzinfo=dt.timezone.utc)

    def test_collection_reuses_memory_key_and_publishes_validated_real_blob(self):
        blobs, calls = {}, []
        def client_factory(app, installation, **kwargs):
            self.assertEqual(kwargs, {"key_bytes": b"fixture-only"})
            return object()
        def write(name, payload, metadata):
            calls.append(name)
            blobs[name] = payload
        receipt = execute(self.settings, lambda name: "fixture-only", blobs.get, write,
                          now=self.now, client_factory=client_factory,
                          collector=lambda *args: {}, normalizer=lambda *args: self.real)
        self.assertEqual(calls, [STATUS, DATASET, SUCCESS, STATUS])
        self.assertEqual(receipt["mode"], "REAL")
        self.assertEqual(json.loads(blobs[STATUS])["state"], "ready")
        self.assertEqual(json.loads(blobs[DATASET])["SourceCoverage"], self.real["SourceCoverage"])
        self.assertEqual(dataset_content(blobs[DATASET]), blobs[DATASET])

    def test_source_error_preserves_last_good_blob_and_reports_only_error_type(self):
        original = b"previous validated snapshot"
        blobs = {DATASET: original, SUCCESS: json.dumps({"asOf": "2026-11-17T00:00:00Z"}).encode()}
        def fail(*args):
            raise ContractError("private diagnostic must not enter status")
        def write(name, payload, metadata):
            blobs[name] = payload
        with self.assertRaises(CollectionFailed) as failure:
            execute(self.settings, lambda name: "fixture-only", blobs.get, write,
                    now=self.now, client_factory=lambda *a, **k: object(), collector=fail)
        self.assertEqual(failure.exception.stage, "github-read")
        self.assertEqual(blobs[DATASET], original)
        status = json.loads(blobs[STATUS])
        self.assertEqual(status["lastSuccess"], "2026-11-17T00:00:00Z")
        self.assertEqual(status["errorType"], "ContractError")
        self.assertNotIn("private diagnostic", blobs[STATUS].decode())
        self.assertFalse(status["datasetCommitted"])

    def test_wrong_mode_window_or_bad_scalars_cannot_replace_blob(self):
        for change in (
            lambda d: d["Info"][0].update(Mode="SAMPLE"),
            lambda d: d["Info"][0].update(EndDay="2026-11-17"),
            lambda d: d["Metrics"][0].update(Generations="not a number"),
        ):
            candidate = deepcopy(self.real)
            change(candidate)
            blobs = {DATASET: b"old"}
            with self.assertRaises(CollectionFailed):
                execute(self.settings, lambda name: "fixture-only", blobs.get,
                        lambda name, value, metadata: blobs.update({name: value}),
                        now=self.now, client_factory=lambda *a, **k: object(),
                        collector=lambda *a: {}, normalizer=lambda *a: candidate)
            self.assertEqual(blobs[DATASET], b"old")

    def test_window_is_utc_minus_two_and_governed_mapping_does_not_invent_history(self):
        settings = dict(self.settings, COLLECT_DAYS="3",
                        COLLECTOR_CONFIG_JSON='{"countries":{"example-center":"Example region"}}')
        config = configuration(settings, dt.datetime(2026, 11, 19, 1, tzinfo=dt.timezone.utc))
        self.assertEqual((config["start_day"], config["end_day"]), ("2026-11-15", "2026-11-17"))
        self.assertEqual(config["telemetry_assignments"], [])
        self.assertEqual(config["license_history"], [])
        for invalid in (
            dict(settings, COLLECT_DAYS="0"),
            dict(settings, ALLOW_MISSING_METRICS="yes"),
            dict(settings, COLLECTOR_CONFIG_JSON='{"start_day":"2026-01-01"}'),
        ):
            with self.assertRaises(ContractError):
                configuration(invalid, self.now)

    def test_status_commit_failure_is_not_reported_as_success(self):
        calls = []
        def write(name, payload, metadata):
            calls.append(name)
            if name == SUCCESS:
                raise OSError("fixture-only failure")
        with self.assertRaises(CollectionFailed) as failure:
            execute(self.settings, lambda name: "fixture-only", lambda name: None, write,
                    now=self.now, client_factory=lambda *a, **k: object(),
                    collector=lambda *a: {}, normalizer=lambda *a: self.real)
        self.assertTrue(failure.exception.dataset_committed)
        self.assertEqual(calls[-1], STATUS)

    def test_key_bytes_sign_without_a_file_and_are_bounded_and_exclusive(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        class FakeClient:
            def __init__(self, base, version, token):
                self.token = token
            def request(self, *args, **kwargs):
                return {"token": "fixture-installation-value"}
        with patch("collect.Client", FakeClient):
            self.assertEqual(app_client("000000", "000000", key_bytes=pem).token, "fixture-installation-value")
        for kwargs in ({}, {"key_bytes": b""}, {"key_bytes": b"x" * 65537},
                       {"key_bytes": "not bytes"}, {"key_bytes": pem, "key_path": Path("unused")}):
            with self.assertRaises(ContractError):
                app_client("000000", "000000", **kwargs)

    def test_source_package_is_an_exact_allowlist_with_shared_public_core(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "function-source.zip"
            build(output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {
                    "function_app.py", "pipeline.py", "host.json", "collect.py",
                    "normalize.py", "snapshot.py", "requirements.txt",
                })
                self.assertEqual(archive.read("collect.py"), (ROOT / "scripts/collect.py").read_bytes())
                self.assertEqual(archive.read("normalize.py"), (ROOT / "scripts/normalize.py").read_bytes())
                self.assertEqual(archive.read("snapshot.py"), (ROOT / "scripts/snapshot.py").read_bytes())
                self.assertNotIn("settings.example.json", archive.namelist())
                self.assertNotIn(".env", archive.namelist())
                self.assertNotIn(".python_packages", archive.namelist())
                self.assertIn(b"cryptography==", archive.read("requirements.txt"))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_cloud_model_has_a_static_full_url_no_embedded_data_and_plan_writes_nothing(self):
        url = "https://example-metrics.azurewebsites.net/api/dataset"
        database = cloud_powerbi.cloud_model(url)
        expressions = database["model"]["expressions"]
        self.assertNotIn("DataMode", [e["name"] for e in expressions])
        self.assertNotIn("DataRootPath", [e["name"] for e in expressions])
        self.assertNotIn("ProjectionMixFile", [e["name"] for e in expressions])
        mix = next(e["expression"] for e in expressions if e["name"] == "ProjectionMixJSON")
        self.assertIn("Binary.FromText", mix)
        self.assertNotIn("File.Contents", mix)
        self.assertIn("IsParameterQuery=true", mix)
        self.assertIn("ProjectionPricing", [e["name"] for e in expressions])
        text = "\n".join(expressions[0]["expression"])
        self.assertIn(f'Web.Contents("{url}", [ApiKeyName="code"])', text)
        self.assertNotIn("Binary.FromText", text)
        for invalid in (url + "?code=fixture", "http://example.test/api/dataset",
                        "https://user:pass@example.azurewebsites.net/api/dataset"):
            with self.assertRaises(ValueError):
                cloud_powerbi.expression(invalid)
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdout", io.StringIO()) as output:
            target = Path(directory) / "generated"
            cloud_powerbi.main(["--dataset-url", url, "--output", str(target)])
            self.assertFalse(target.exists())
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["authMode"], "function-key")
            self.assertIn("Desktop/Excel", plan["credential"])
            self.assertIsNone(plan["refreshScheduleExampleUTC"])
            cloud_powerbi.main(["--dataset-url", url, "--output", str(target), "--execute"])
            self.assertEqual(set(p.name for p in target.iterdir()), {"model.bim", "definition.pbism"})

    def test_basic_gateway_model_uses_plain_web_contents_and_mode_specific_url(self):
        url = "https://example-metrics.azure-api.net/api/dataset"
        database = cloud_powerbi.cloud_model(url, auth_mode="basic-gateway")
        text = "\n".join(database["model"]["expressions"][0]["expression"])
        self.assertIn(f'Web.Contents("{url}")', text)
        for forbidden in ("ApiKeyName", "Headers", "Authorization", "x-functions-key", "Binary.FromText"):
            self.assertNotIn(forbidden, text)
        for invalid in (
            "https://example-metrics.azurewebsites.net/api/dataset",
            "http://example-metrics.azure-api.net/api/dataset",
            "https://user:pass@example-metrics.azure-api.net/api/dataset",
            url + "?code=fixture", url + "#fragment",
        ):
            with self.assertRaises(ValueError):
                cloud_powerbi.expression(invalid, auth_mode="basic-gateway")
        with self.assertRaises(ValueError):
            cloud_powerbi.expression(url)
        with self.assertRaises(ValueError):
            cloud_powerbi.expression(url, auth_mode="unknown")

    def test_basic_gateway_plan_and_execute_only_generate_private_local_files(self):
        url = "https://example-metrics.azure-api.net/api/dataset"
        with tempfile.TemporaryDirectory() as directory, patch(
                "socket.create_connection", side_effect=AssertionError("Must remain offline")):
            target = Path(directory) / "generated"
            args = ["--auth-mode", "basic-gateway", "--dataset-url", url, "--output", str(target)]
            with patch("sys.stdout", io.StringIO()) as output:
                cloud_powerbi.main(args)
            plan = json.loads(output.getvalue())
            self.assertFalse(target.exists())
            self.assertFalse(plan["networkCalls"])
            self.assertEqual(plan["authMode"], "basic-gateway")
            self.assertIn("Basic", plan["credential"])
            self.assertEqual(plan["credentialUsername"], "dataset")
            self.assertIn("dataset-only Function key", plan["credentialPasswordSource"])
            with patch("sys.stdout", io.StringIO()):
                cloud_powerbi.main(args + ["--execute"])
            self.assertEqual(set(p.name for p in target.iterdir()), {"model.bim", "definition.pbism"})
            generated = json.loads((target / "model.bim").read_text())
            self.assertEqual(generated, cloud_powerbi.cloud_model(url, auth_mode="basic-gateway"))


class FunctionBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import function_app
        cls.module = function_app
        cls.functions = {f.get_function_name(): f for f in function_app.app.get_functions()}
        cls.real = real_fixture()

    def test_python_parameters_match_all_sdk_input_bindings(self):
        for name, function in self.functions.items():
            with self.subTest(function=name):
                bindings = json.loads(function.get_function_json())["bindings"]
                inputs = {binding["name"] for binding in bindings
                          if binding["direction"].casefold() in ("in", "inout")
                          and binding["name"] != "$return"}
                parameters = set(inspect.signature(function.get_user_function()).parameters)
                self.assertEqual(parameters, inputs)

    def test_read_endpoint_is_function_authenticated_get_and_never_collects(self):
        import azure.functions as func
        function = self.functions["dataset"]
        bindings = json.loads(function.get_function_json())["bindings"]
        trigger = next(b for b in bindings if b["type"] == "httpTrigger")
        self.assertEqual(trigger["authLevel"].casefold(), "function")
        self.assertEqual(trigger["methods"], ["GET"])
        data = deepcopy(self.real)
        payload = json.dumps(data).encode()
        requested = []
        class Context:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        class Service(Context):
            def get_blob_client(self, container, name):
                requested.append((container, name))
                return self
            def download_blob(self, **kwargs):
                self_case.assertLessEqual(kwargs["length"], 16 * 1024 * 1024 + 1)
                return SimpleNamespace(readall=lambda: payload)
        self_case = self
        env = dict(DATA_BLOB_ACCOUNT_URL="https://exampledata.blob.core.windows.net/",
                   DATA_CONTAINER="metrics")
        with patch.dict("os.environ", env), patch.object(self.module, "ManagedIdentityCredential", return_value=Context()), patch.object(
                self.module, "BlobServiceClient", return_value=Service()), patch.object(
                self.module, "execute", side_effect=AssertionError("GET must never collect")):
            request = func.HttpRequest("GET", "https://example.azurewebsites.net/api/dataset?blob=other", body=b"")
            response = function.get_user_function()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(requested, [("metrics", DATASET)])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_read_errors_are_explicit_and_never_expose_exception_messages(self):
        import azure.functions as func
        from azure.core.exceptions import AzureError
        with patch.object(self.module, "ManagedIdentityCredential", side_effect=AzureError("private value")), self.assertLogs(level="ERROR") as logs:
            response = self.functions["dataset"].get_user_function()(
                func.HttpRequest("GET", "https://example.azurewebsites.net/api/dataset", body=b""))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private value", response.get_body().decode() + "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()

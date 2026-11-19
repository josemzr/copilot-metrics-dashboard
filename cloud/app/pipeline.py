"""Cloud adapter around the same collector, normalizer and validator used by Docker."""
import datetime as dt
import hashlib
import json

from collect import ContractError, MAX_BYTES, MAX_KEY_BYTES, app_client, collect
from normalize import normalize
from snapshot import validate

DATASET = "latest/dataset.json"
STATUS = "latest/status.json"
SUCCESS = "latest/last-success.json"
MAPPING_FIELDS = {
    "countries", "billing_users", "telemetry_assignments", "license_history",
    "license_history_coverage", "user_classifications",
}


class CollectionFailed(RuntimeError):
    def __init__(self, stage, error_type, dataset_committed=False):
        super().__init__("Cloud collection failed; inspect authenticated status and monitoring")
        self.stage, self.error_type, self.dataset_committed = stage, error_type, dataset_committed


def configuration(settings, now):
    count = int(settings.get("COLLECT_DAYS", "3"))
    allow_missing = settings.get("ALLOW_MISSING_METRICS", "false")
    if not 1 <= count <= 31 or allow_missing not in ("true", "false"):
        raise ContractError("Invalid collection window or missing-report setting")
    raw = settings.get("COLLECTOR_CONFIG_JSON", "{}")
    if len(raw.encode()) > 1024 * 1024:
        raise ContractError("Attribution configuration exceeds 1 MiB")
    mappings = json.loads(raw)
    if not isinstance(mappings, dict) or set(mappings) - MAPPING_FIELDS:
        raise ContractError("Unexpected attribution configuration field")
    end = now.astimezone(dt.timezone.utc).date() - dt.timedelta(days=2)
    config = dict(enterprise=settings["GITHUB_ENTERPRISE"],
                  start_day=(end - dt.timedelta(days=count - 1)).isoformat(),
                  end_day=end.isoformat(), collect_licenses=True,
                  allow_missing_metrics=allow_missing == "true",
                  countries={}, billing_users=[], telemetry_assignments=[],
                  license_history=[], license_history_coverage=[])
    config.update(mappings)
    return config


def encode(value):
    result = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    if len(result) > MAX_BYTES:
        raise ContractError("Cloud snapshot exceeds 16 MiB")
    return result


def execute(settings, secret_reader, blob_reader, blob_writer, *, now=None,
            client_factory=app_client, collector=collect, normalizer=normalize):
    """Ports use bytes. blob_reader returns None only when the fixed blob is absent."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stage, committed = "configuration", False
    status = dict(state="collecting", lastAttempt=now.isoformat(), lastSuccess=None, lastError=None)
    # Import here so configuration and package inspection do not create Azure clients.
    from azure.core.exceptions import AzureError
    from cryptography.exceptions import UnsupportedAlgorithm
    errors = (AzureError, ContractError, KeyError, ValueError, TypeError, OSError, UnsupportedAlgorithm)
    try:
        config = configuration(settings, now)
        previous = blob_reader(SUCCESS)
        if previous is not None:
            if len(previous) > 8192:
                raise ContractError("Last-success metadata exceeds 8 KiB")
            status["lastSuccess"] = json.loads(previous)["asOf"]
        blob_writer(STATUS, encode(status), None)
        stage = "key-vault"
        material = secret_reader(settings["GITHUB_KEY_SECRET_NAME"])
        if not isinstance(material, str) or not 1 <= len(material.encode()) <= MAX_KEY_BYTES:
            raise ContractError("Key Vault key exceeds the supported size")
        stage = "github-auth"
        client = client_factory(settings["GITHUB_APP_ID"], settings["GITHUB_INSTALLATION_ID"],
                                key_bytes=material.encode())
        material = None
        stage = "github-read"
        raw = collector(config, client)
        stage = "validation"
        data = validate(normalizer(raw, config, "REAL"), "REAL")
        if (data["Info"][0]["StartDay"], data["Info"][0]["EndDay"]) != (
                config["start_day"], config["end_day"]):
            raise ContractError("Collected snapshot window differs from the requested window")
        payload = encode(data)
        receipt = dict(asOf=data["Info"][0]["AsOf"], startDay=config["start_day"],
                       endDay=config["end_day"], sha256=hashlib.sha256(payload).hexdigest(),
                       mode="REAL", metricsRows=len(data["Metrics"]), billingRows=len(data["Billing"]))
        stage = "blob-commit"
        blob_writer(DATASET, payload, {"sha256": receipt["sha256"]})
        committed = True
        blob_writer(SUCCESS, encode(receipt), None)
        status.update(state="ready", lastSuccess=receipt["asOf"])
        blob_writer(STATUS, encode(status), None)
        return receipt
    except errors as error:
        status.update(state="error", lastError="Collection failed; inspect the stage and error type.",
                      stage=stage, errorType=type(error).__name__, datasetCommitted=committed)
        failure = CollectionFailed(stage, type(error).__name__, committed)
        try:
            blob_writer(STATUS, encode(status), None)
        except errors as status_error:
            raise CollectionFailed("status-write", type(status_error).__name__, committed) from None
        raise failure from None


def dataset_content(content):
    if len(content) > MAX_BYTES:
        raise ContractError("Stored dataset exceeds 16 MiB")
    validate(json.loads(content), "REAL")
    return content

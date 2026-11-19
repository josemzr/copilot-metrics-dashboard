"""Scheduled collection into a private volume; failed runs retain the last valid data."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time

from collect import ContractError, app_client, collect
from normalize import normalize
from snapshot import atomic_json, read_snapshot, validate


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def settings():
    days = int(os.environ.get("COLLECT_DAYS", "7"))
    interval = int(os.environ.get("COLLECT_INTERVAL_SECONDS", "86400"))
    if not 1 <= days <= 31 or not 300 <= interval <= 604800:
        raise ContractError("COLLECT_DAYS must be 1..31; collection interval must be 300..604800 seconds")
    allow_missing = os.environ.get("ALLOW_MISSING_METRICS", "false")
    if allow_missing not in ("true", "false"):
        raise ContractError("ALLOW_MISSING_METRICS must be true or false")
    config = dict(enterprise=os.environ.get("GITHUB_ENTERPRISE", ""),
                  app_id=os.environ.get("GITHUB_APP_ID", ""),
                  installation_id=os.environ.get("GITHUB_INSTALLATION_ID", ""),
                  key_path=Path("/run/secrets/github_app_key"),
                  collect_days=days, interval=interval, collect_licenses=True,
                  allow_missing_metrics=allow_missing == "true",
                  billing_users=[], countries={}, telemetry_assignments=[],
                  license_history=[], license_history_coverage=[])
    mapping = os.environ.get("ATTRIBUTION_FILE")
    if mapping:
        # Optional governed mappings live in a separate read-only mount, never in the image.
        with Path(mapping).open("rb") as stream:
            content = stream.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ContractError("Attribution file exceeds 1 MiB")
        supplied = json.loads(content)
        allowed = {"countries", "telemetry_assignments", "license_history",
                   "license_history_coverage", "user_classifications", "billing_users"}
        if not isinstance(supplied, dict) or set(supplied) - allowed:
            raise ContractError("Unexpected attribution configuration field")
        config.update(supplied)
    return config


def run_once(config, output, client_factory=None):
    output = Path(output)
    previous_asof = None
    try:
        previous_asof = read_snapshot(output / "dataset.json", "REAL")["Info"][0]["AsOf"]
    except FileNotFoundError:
        pass
    except (ValueError, KeyError, TypeError):
        # Invalid stored content is never served; a new successful collection may replace it.
        print("Stored snapshot is invalid; awaiting a successful collection", file=sys.stderr)
    status = dict(state="collecting", lastAttempt=utc_now(), lastSuccess=previous_asof, lastError=None)
    atomic_json(output / "status.json", status)
    try:
        today = dt.datetime.now(dt.timezone.utc).date()
        end = today - dt.timedelta(days=2)
        start = end - dt.timedelta(days=config["collect_days"] - 1)
        config = dict(config, start_day=start.isoformat(), end_day=end.isoformat())
        factory = client_factory or (
            lambda: app_client(config["app_id"], config["installation_id"], config["key_path"]))
        dataset = validate(normalize(collect(config, factory()), config, "REAL"), "REAL")
        atomic_json(output / "dataset.json", dataset)
        status.update(state="ready", lastSuccess=dataset["Info"][0]["AsOf"], lastError=None)
        success = True
    except (ContractError, ValueError, KeyError, TypeError, OSError) as error:
        # API bodies, keys, signed URLs and exception values never enter public status or logs.
        reason = ("Private key or data volume is not readable/writable by the collector UID. "
                  "Check COLLECTOR_UID and file ownership; keep the key mode 0600. "
                  if isinstance(error, PermissionError) else
                  "Collection failed. Check App configuration, permissions, source availability "
                  "and collection limits. ")
        status.update(state="error", lastError=reason + "The last valid snapshot is unchanged.")
        print(f"Collection failed ({type(error).__name__}); last valid snapshot retained", file=sys.stderr)
        success = False
    atomic_json(output / "status.json", status)
    return success


def main():
    output = Path(os.environ.get("DATA_DIR", "/data"))
    output.mkdir(parents=True, exist_ok=True)
    try:
        config = settings()
    except (ValueError, OSError, TypeError) as error:
        atomic_json(output / "status.json", dict(
            state="error", lastAttempt=utc_now(), lastSuccess=None,
            lastError="Invalid collector configuration. Check the server-side settings."))
        print(f"Collector configuration rejected ({type(error).__name__})", file=sys.stderr)
        return 2
    while True:
        success = run_once(config, output)
        if "--once" in sys.argv:
            return 0 if success else 1
        time.sleep(config["interval"])


if __name__ == "__main__":
    raise SystemExit(main())

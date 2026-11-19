"""Validation shared by the collector and the fixed-route HTTP server."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import tempfile

from collect import ContractError, MAX_BYTES, MAX_RECORDS

TABLES = {
    "Info", "Centers", "Dates", "Users", "Models", "Billing", "Metrics",
    "ModelFeatures", "ClientModels", "IDEs", "Languages", "Pools", "Budgets",
    "Memberships", "Features", "CLI", "Licenses", "LicensedDays", "LicenseCoverage",
    "Periods14", "SourceCoverage",
}
COUNTERS = {
    "Interactions", "Generations", "Acceptances", "LinesAdded", "LinesDeleted",
    "LinesSuggested", "LinesSuggestedDelete", "TelemetryCredits", "Requests", "Prompts",
    "Sessions", "PromptTokens", "OutputTokens", "RequirementsMet", "RequirementsUnmet",
    "RequirementsUnknown", "grossQuantity", "grossAmount", "discountQuantity",
    "discountAmount", "netQuantity", "netAmount", "PricePerUnit", "MissingMetricsDays",
}
FLAGS = {
    "ActivityObserved", "TelemetryPresent", "IsResidual", "HistoricalRosterComplete",
    "PoolEnabled", "CustomModel", "HardStop", "MetricsAvailable", "BillingAvailable",
}
TEXT_FIELDS = {
    "User", "CenterId", "Center", "Country", "State", "Model", "Feature", "Client",
    "IDE", "Language", "Mode", "Label", "Coverage", "Enterprise", "SKU", "Product",
    "UnitType", "Attribution", "UnitStatus", "Scope", "Entity", "ProductSKU",
    "BudgetId", "BudgetType", "Plan", "Organization", "SelectionMode", "ResourceType",
    "ResourceName", "LicenseRosterStatus", "HistoricalLicenseCoverage", "Stack",
    "ClassificationSource", "MetricsStatus", "BillingStatus", "MetricsCoverageStatus",
}
DAY_FIELDS = {"Day", "StartDay", "EndDay", "WeekStart", "WeekEnd", "MetricsStartDay",
              "MetricsEndDay", "BillingStartDay", "BillingEndDay"}
DAILY_TABLES = {
    "Dates", "Billing", "Metrics", "ModelFeatures", "ClientModels", "Features",
    "CLI", "LicensedDays", "LicenseCoverage", "SourceCoverage", "IDEs", "Languages",
}
PERSON_TABLES = {"Users", "Licenses", "LicensedDays", "Metrics", "ModelFeatures",
                 "ClientModels", "Features", "CLI"}


def is_day(value):
    return isinstance(value, str) and dt.date.fromisoformat(value).isoformat() == value


def validate(data, mode=None):
    if not isinstance(data, dict) or set(data) - TABLES:
        raise ContractError("Snapshot must contain only known tables")
    required = ("Info", "Centers", "Dates", "Users", "Billing", "Metrics")
    if any(not isinstance(data.get(table), list) for table in required):
        raise ContractError("Required snapshot table is missing")
    count = 0
    for table, rows in data.items():
        if not isinstance(rows, list):
            raise ContractError("Snapshot tables must be arrays")
        count += len(rows)
        if count > MAX_RECORDS:
            raise ContractError("Snapshot exceeds the row limit")
        for row in rows:
            if not isinstance(row, dict):
                raise ContractError("Snapshot row must be an object")
            if table in DAILY_TABLES and not is_day(row.get("Day")):
                raise ContractError("Daily snapshot row requires an ISO Day")
            if table in PERSON_TABLES and (not isinstance(row.get("User"), str) or not row["User"]):
                raise ContractError("Person snapshot row requires a User")
            if table == "Centers" and any(not isinstance(row.get(key), str) for key in ("CenterId", "Center", "Country")):
                raise ContractError("Center row requires CenterId, Center and Country")
            for key, value in row.items():
                if key in ("__proto__", "constructor", "prototype"):
                    raise ContractError("Unsafe snapshot field")
                if value is not None and type(value) not in (str, int, float, bool):
                    raise ContractError("Snapshot values must be scalar")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ContractError("Snapshot contains a non-finite value")
                if isinstance(value, str) and len(value) > 8192:
                    raise ContractError("Snapshot string exceeds the length limit")
                if key in TEXT_FIELDS and value is not None and not isinstance(value, str):
                    raise ContractError("Snapshot text field must be a string or null")
                if key in COUNTERS and value is not None and (
                        type(value) not in (int, float) or value < 0):
                    raise ContractError("Snapshot counter must be a non-negative number or null")
                if (key in FLAGS or key.startswith("Used")) and value is not None and type(value) is not bool:
                    raise ContractError("Snapshot flag must be boolean or null")
                if key in DAY_FIELDS and value is not None and not is_day(value):
                    raise ContractError("Snapshot contains an invalid ISO day")
    if len(data["Info"]) != 1:
        raise ContractError("Snapshot requires exactly one Info row")
    info = data["Info"][0]
    if info.get("Mode") not in ("SAMPLE", "REAL") or mode and info["Mode"] != mode:
        raise ContractError("Snapshot provenance does not match the requested mode")
    start, end = (dt.date.fromisoformat(info[field]) for field in ("StartDay", "EndDay"))
    if start > end or (end - start).days > 3660:
        raise ContractError("Invalid snapshot window")
    dt.datetime.fromisoformat(info["AsOf"].replace("Z", "+00:00"))
    if not isinstance(info.get("Label"), str) or not info["Label"].strip():
        raise ContractError("Snapshot label is missing")
    for table, field in (("Centers", "CenterId"), ("Dates", "Day"), ("Users", "User"), ("Models", "Model")):
        identifiers = [row[field] for row in data.get(table, [])]
        if any(not isinstance(value, str) or not value for value in identifiers) or len(identifiers) != len(set(identifiers)):
            raise ContractError("Snapshot dimension keys must be unique nonempty strings")
    centers = {row["CenterId"] for row in data["Centers"]}
    users = {row["User"] for row in data["Users"]}
    for table, rows in data.items():
        for row in rows:
            if "CenterId" in row and row["CenterId"] not in centers:
                raise ContractError("Snapshot row references an unknown center")
            if "User" in row and row["User"] not in users:
                raise ContractError("Snapshot row references an unknown user")
            if "Day" in row and not start.isoformat() <= row["Day"] <= end.isoformat():
                raise ContractError("Snapshot row is outside the declared window")
    if "SourceCoverage" in data:
        covered = [r["Day"] for r in data["SourceCoverage"]]
        expected = {r["Day"] for r in data["Dates"]}
        if len(covered) != len(set(covered)) or set(covered) != expected:
            raise ContractError("Source coverage must identify every dataset day exactly once")
    return data


def read_snapshot(path, mode):
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ContractError("Snapshot exceeds 16 MiB")
    return validate(json.loads(content), mode)


def atomic_json(path, data, *, file_mode=0o640):
    path = Path(path)
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    if len(payload) > MAX_BYTES:
        raise ContractError("Snapshot exceeds 16 MiB")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name + ".",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, file_mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

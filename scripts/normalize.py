"""Strict normalization: billing attribution != current cost-center membership."""
from collections import defaultdict
import datetime as dt
from decimal import Decimal
import json
from pathlib import Path

from collect import ContractError

NO_CENTER = "none"
UNKNOWN_CENTER = "unattributed-history"
UNKNOWN_SNAPSHOT_CENTER = "unattributed-snapshot"
RESIDUAL_USER = "(no user detail)"
NUMBERS = ("grossQuantity", "grossAmount", "discountQuantity", "discountAmount",
           "netQuantity", "netAmount")


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n")
    temporary.replace(path)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"Expected numeric API value, got {type(value).__name__}")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ContractError("Non-finite quantity")
    return result


def billing_items(response, day, center, user=None):
    date = dt.date.fromisoformat(day)
    period = response["timePeriod"]
    if (period["year"], period.get("month"), period.get("day")) != (
            date.year, date.month, date.day):
        raise ContractError("Billing response is not the exact requested day")
    if response.get("costCenter", {}).get("id", center) != center:
        raise ContractError("Billing response center differs from query")
    if user and response.get("user", user).lower() != user.lower():
        raise ContractError("Billing response user differs from query")
    result = {}
    for item in response["usageItems"]:
        unit = item["unitType"]
        if unit != "ai-credits":
            raise ContractError(f"Unexpected AI credit unit: {unit}; do not convert requests")
        key = (item["product"], item["sku"], item["model"], unit,
               str(number(item["pricePerUnit"])))
        if key in result:
            raise ContractError("Duplicate billing item at expected model/SKU/price grain")
        result[key] = {field: number(item[field]) for field in NUMBERS}
    return result


def billing_rows(groups):
    rows = []
    seen = set()
    for group in groups:
        day, center = group["day"], group["cost_center_id"]
        if (day, center) in seen:
            raise ContractError("Repeated daily cost-center extract")
        seen.add((day, center))
        totals = billing_items(group["total"], day, center)
        accumulated = defaultdict(lambda: {field: Decimal(0) for field in NUMBERS})
        users = set()
        for detail in group["details"]:
            user = detail["user"].lower()
            if user in users or user == RESIDUAL_USER:
                raise ContractError("Repeated or reserved billing user")
            users.add(user)
            items = billing_items(detail["response"], day, center, user)
            for key, values in items.items():
                if key not in totals:
                    raise ContractError("User billing item absent from canonical center total")
                if any(values.values()):
                    rows.append(billing_row(day, center, user, key, values, "API user filter"))
                for field in NUMBERS:
                    accumulated[key][field] += values[field]
        for key, total in totals.items():
            residual = {f: total[f] - accumulated[key][f] for f in NUMBERS}
            # Financial rounding tolerance only; negative source adjustments remain valid.
            for field in NUMBERS:
                if total[field] >= 0 and residual[field] < Decimal("-0.000001"):
                    raise ContractError("User details exceed center total; inconsistent snapshot")
                if abs(residual[field]) <= Decimal("0.000001"):
                    residual[field] = Decimal(0)
            if any(residual.values()):
                rows.append(billing_row(day, center, RESIDUAL_USER, key, residual,
                                        "Center total minus available user detail"))
    return rows


def billing_row(day, center, user, key, values, attribution):
    product, sku, model, unit, price = key
    return dict(Day=day, CenterId=center, User=user, Model=model, Product=product,
                SKU=sku, UnitType=unit, PricePerUnit=float(price),
                Attribution=attribution, **{k: float(v) for k, v in values.items()})


def historical_center(user_id, login, day, assignments):
    matches = [
        row for row in assignments
        if (str(row.get("user_id", "")) == str(user_id)
            if row.get("user_id") is not None
            else row.get("user_login", "").lower() == login.lower())
        and row["valid_from"] <= day < row["valid_to_exclusive"]
    ]
    if len(matches) > 1:
        raise ContractError("Overlapping historical telemetry assignments")
    if matches and not matches[0].get("evidence"):
        raise ContractError("Historical assignment requires evidence")
    return matches[0]["cost_center_id"] if matches else UNKNOWN_CENTER


def metric_value(record, key):
    value = record.get(key)
    return float(number(value)) if value is not None else None


FLAGS = {
    "UsedChat": "used_chat", "UsedAgent": "used_agent", "UsedCLI": "used_cli",
    "UsedCopilotApp": "used_copilot_app", "UsedCloudAgent": "used_copilot_cloud_agent",
    "UsedCodeReviewActive": "used_copilot_code_review_active",
    "UsedCodeReviewPassive": "used_copilot_code_review_passive",
    "UsedVSCodeAgent": "used_vscode_agent", "UsedLocalBYOK": "used_local_byok",
}
COUNTS = {
    "Interactions": "user_initiated_interaction_count",
    "Generations": "code_generation_activity_count",
    "Acceptances": "code_acceptance_activity_count",
    "LinesAdded": "loc_added_sum", "LinesDeleted": "loc_deleted_sum",
    "LinesSuggested": "loc_suggested_to_add_sum",
    "LinesSuggestedDelete": "loc_suggested_to_delete_sum",
}


def boolean_value(record, key):
    value = record.get(key)
    if value is not None and not isinstance(value, bool):
        raise ContractError("Expected boolean or null for " + key)
    return value


def activity_observed(record):
    """Local positive-signal definition, not an asserted copy of GitHub's DAU."""
    counts = [metric_value(record, key) for key in COUNTS.values()]
    flags = {name: boolean_value(record, key) for name, key in FLAGS.items()}
    if flags["UsedCloudAgent"] is None:
        flags["UsedCloudAgent"] = boolean_value(record, "used_copilot_coding_agent")
    requests = [
        metric_value(record.get(key) or {}, "request_count")
        for key in ("totals_by_cli", "totals_by_copilot_app")
    ] + [metric_value(client, "request_count") for client in record.get("totals_by_client", [])]
    if (any(value is not None and value > 0 for value in counts + requests)
            or any(value is True for key, value in flags.items() if key != "UsedCodeReviewPassive")):
        return True
    core = [metric_value(record, COUNTS[key]) for key in ("Interactions", "Generations", "Acceptances")]
    core_flags = [flags[key] for key in ("UsedChat", "UsedAgent", "UsedCLI",
                                        "UsedCopilotApp", "UsedCloudAgent")]
    return False if all(value == 0 for value in core) and all(
        value is False for value in core_flags) else None


def license_tables(raw, config, requested_days, centers):
    snapshot = raw.get("license_snapshot")
    rows = []
    if snapshot:
        if snapshot.get("complete") is not True:
            raise ContractError("License snapshot is not explicitly complete")
        grouped, identities = {}, {}
        for seat in snapshot["seats"]:
            assignee = seat["assignee"]
            if not assignee:
                raise ContractError("License assignee missing; cannot claim complete roster")
            login, uid = assignee["login"].lower(), str(assignee["id"])
            if login in identities and identities[login] != uid:
                raise ContractError("License login reused by different user IDs")
            identities[login] = uid
            grouped.setdefault(login, []).append(seat)
        for login, seats in sorted(grouped.items()):
            direct = {center["id"] for center in raw["cost_centers"] for resource in center["resources"]
                      if resource["type"].lower() == "user" and resource["name"].lower() == login}
            if len(direct) > 1:
                raise ContractError("User directly assigned to multiple cost centers")
            active_dates = [seat["last_activity_at"] for seat in seats if seat.get("last_activity_at")]
            cancellations = [seat.get("pending_cancellation_date") for seat in seats]
            rows.append(dict(
                User=login, UserId=identities[login],
                CenterId=next(iter(direct), UNKNOWN_SNAPSHOT_CENTER),
                Plan=" | ".join(sorted({seat.get("plan_type", "unknown") for seat in seats})),
                Organization=" | ".join(sorted({
                    (seat.get("organization") or {}).get("login", "Direct enterprise")
                    for seat in seats})),
                AsOf=snapshot["as_of"], LastActivityAt=max(active_dates) if active_dates else None,
                PendingCancellation=max(cancellations) if all(cancellations) else None))
    historical, coverage = [], []
    histories = config.get("license_history", [])
    ranges = config.get("license_history_coverage", [])
    for item in histories + ranges:
        if (not item.get("evidence") or dt.date.fromisoformat(item["valid_from"])
                >= dt.date.fromisoformat(item["valid_to_exclusive"])):
            raise ContractError("License history requires valid interval and audit evidence")
    seen = set()
    for day in requested_days:
        complete = any(item["valid_from"] <= day < item["valid_to_exclusive"] for item in ranges)
        coverage.append(dict(Day=day, HistoricalRosterComplete=complete))
        for item in histories:
            if not item["valid_from"] <= day < item["valid_to_exclusive"]:
                continue
            user = item["user_login"].lower()
            if (day, user) in seen:
                raise ContractError("Overlapping historical license assignments")
            seen.add((day, user))
            center = historical_center(item.get("user_id"), user, day, config["telemetry_assignments"])
            if center not in centers:
                raise ContractError("Unknown historical license center")
            historical.append(dict(Day=day, User=user, CenterId=center))
    return rows, historical, coverage


def normalize(raw, config, mode="REAL"):
    requested_days = sorted(set(raw["requested_days"]))
    if len(requested_days) != len(raw["requested_days"]):
        raise ContractError("Repeated requested day")
    coverage_raw = raw.get("source_coverage", [
        dict(day=day, metrics_status="available", billing_status="available_snapshot")
        for day in requested_days])
    if len(coverage_raw) != len(requested_days) or {r["day"] for r in coverage_raw} != set(requested_days):
        raise ContractError("Source coverage must contain exactly every requested day")
    source_coverage = []
    for row in coverage_raw:
        if row["metrics_status"] not in ("available", "unavailable_empty_response"):
            raise ContractError("Unknown metrics availability status")
        if row["billing_status"] != "available_snapshot":
            raise ContractError("Billing export incomplete; cannot publish a success-shaped snapshot")
        source_coverage.append(dict(
            Day=row["day"], MetricsAvailable=row["metrics_status"] == "available",
            BillingAvailable=True, MetricsStatus=row["metrics_status"],
            BillingStatus=row["billing_status"]))
    available_metrics_days = {r["Day"] for r in source_coverage if r["MetricsAvailable"]}
    center_rows = [
        dict(CenterId=c["id"], Center=c["name"],
             Country=config["countries"].get(c["id"], "Unmapped region"),
             State=c.get("state", "unknown"))
        for c in raw["cost_centers"]
    ] + [
        dict(CenterId=NO_CENTER, Center="Enterprise only / no center",
             Country="No region", State="virtual"),
        dict(CenterId=UNKNOWN_CENTER, Center="No verified historical attribution",
             Country="No region", State="virtual"),
        dict(CenterId=UNKNOWN_SNAPSHOT_CENTER, Center="Unverified current attribution",
             Country="No region", State="virtual"),
    ]
    centers = {r["CenterId"] for r in center_rows}
    if len(centers) != len(center_rows):
        raise ContractError("Duplicate cost-center ID")
    billing = billing_rows(raw["billing"])
    metrics, features, clients, ides, languages, feature_totals, cli = [], [], [], [], [], [], []
    seen, user_ids, logins = set(), {}, {}
    for record in raw["users"]:
        login = record["user_login"].lower()
        uid, day = str(record["user_id"]), record["day"]
        if day not in requested_days:
            raise ContractError("Metric day outside the requested report window")
        if day not in available_metrics_days:
            raise ContractError("Metrics record present on a day marked unavailable")
        if (day, uid) in seen:
            raise ContractError("Duplicate user-day: do not append overlapping 28-day exports")
        if uid in user_ids and user_ids[uid] != login:
            raise ContractError("Login changed inside extract; supply explicit identity handling")
        if login in logins and logins[login] != uid:
            raise ContractError("Login reused by different numeric user IDs")
        seen.add((day, uid))
        user_ids[uid], logins[login] = login, uid
        center = historical_center(uid, login, day, config["telemetry_assignments"])
        if center not in centers:
            raise ContractError("Unknown historical cost-center ID")
        common = dict(Day=day, User=login, UserId=uid, CenterId=center)
        flags = {name: boolean_value(record, key) for name, key in FLAGS.items()}
        if flags["UsedCloudAgent"] is None:
            flags["UsedCloudAgent"] = boolean_value(record, "used_copilot_coding_agent")
        requirements = record.get("usage_metrics_requirements")
        metrics.append(dict(
            **common, Interactions=metric_value(record, "user_initiated_interaction_count"),
            Generations=metric_value(record, "code_generation_activity_count"),
            Acceptances=metric_value(record, "code_acceptance_activity_count"),
            LinesAdded=metric_value(record, "loc_added_sum"),
            LinesSuggested=metric_value(record, "loc_suggested_to_add_sum"),
            LinesDeleted=metric_value(record, "loc_deleted_sum"),
            LinesSuggestedDelete=metric_value(record, "loc_suggested_to_delete_sum"),
            TelemetryCredits=metric_value(record, "ai_credits_used"),
            TelemetryPresent=boolean_value(record, "client_telemetry_present"),
            ActivityObserved=activity_observed(record), **flags,
            RequirementsMet=len(requirements["met"]) if requirements is not None else None,
            RequirementsUnmet=len(requirements["unmet"]) if requirements is not None else None,
            RequirementsUnknown=len(requirements["unknown"]) if requirements is not None else None,
        ))
        for item in record.get("totals_by_feature", []):
            feature_totals.append(dict(**common, Feature=item["feature"],
                                       **{name: metric_value(item, key) for name, key in COUNTS.items()}))
        for item in record.get("totals_by_model_feature", []):
            features.append(dict(**common, Model=item["model"], Feature=item["feature"],
                                 Interactions=metric_value(item, "user_initiated_interaction_count"),
                                 Generations=metric_value(item, "code_generation_activity_count"),
                                 Acceptances=metric_value(item, "code_acceptance_activity_count"),
                                 **{name: metric_value(item, key) for name, key in COUNTS.items()
                                    if name.startswith("Lines")}))
        for client in record.get("totals_by_client", []):
            for item in client.get("totals_by_model", []):
                token = item.get("token_usage") or {}
                clients.append(dict(
                    **common, Client=client["client"], Model=item["model"],
                    SelectionMode=item.get("model_selection_mode", "unknown"),
                    CustomModel=item.get("is_custom_enterprise_model"),
                    Requests=metric_value(item, "request_count"),
                    PromptTokens=metric_value(token, "prompt_tokens_sum"),
                    OutputTokens=metric_value(token, "output_tokens_sum")))
        for item in record.get("totals_by_ide", []):
            ides.append(dict(**common, IDE=item["ide"],
                             Interactions=metric_value(item, "user_initiated_interaction_count"),
                             Generations=metric_value(item, "code_generation_activity_count"),
                             Acceptances=metric_value(item, "code_acceptance_activity_count"),
                             **{name: metric_value(item, key) for name, key in COUNTS.items()
                                if name.startswith("Lines")}))
        for item in record.get("totals_by_language_feature", []):
            languages.append(dict(**common, Language=item["language"], Feature=item["feature"],
                                  Generations=metric_value(item, "code_generation_activity_count"),
                                  Acceptances=metric_value(item, "code_acceptance_activity_count"),
                                  **{name: metric_value(item, key) for name, key in COUNTS.items()
                                     if name.startswith("Lines")}))
        if record.get("totals_by_cli") is not None:
            item = record["totals_by_cli"]
            tokens = item.get("token_usage") or {}
            cli.append(dict(**common, Prompts=metric_value(item, "prompt_count"),
                            Requests=metric_value(item, "request_count"),
                            Sessions=metric_value(item, "session_count"),
                            PromptTokens=metric_value(tokens, "prompt_tokens_sum"),
                            OutputTokens=metric_value(tokens, "output_tokens_sum")))
    if any(row["CenterId"] not in centers for row in billing):
        raise ContractError("Billing center absent from center dimension")
    licenses, licensed_days, license_coverage = license_tables(raw, config, requested_days, centers)
    for row in licenses:
        if row["User"] in logins and logins[row["User"]] != row["UserId"]:
            raise ContractError("License and metrics identity mismatch")
        logins[row["User"]] = row["UserId"]
    users = sorted({r["User"] for r in billing + metrics + licenses + licensed_days})
    models = sorted({r["Model"] for r in billing + features + clients})
    snapshots = [
        dict(CenterId=c["id"], AsOf=raw["collected_at"],
             PoolEnabled=c.get("ai_credit_pool_enabled"),
             TargetRaw=(c.get("ai_credit_pool_state") or {}).get("target_amount"),
             CurrentRaw=(c.get("ai_credit_pool_state") or {}).get("current_amount"),
             UnitStatus="Amount unit not defined by the REST contract; balance N/D")
        for c in raw["cost_centers"]
    ]
    memberships = [
        dict(CenterId=c["id"], ResourceType=r["type"], ResourceName=r["name"],
             AsOf=raw["collected_at"])
        for c in raw["cost_centers"] for r in c["resources"]
    ]
    def budget_center(budget):
        if budget["budget_scope"] not in ("cost_center", "multi_user_cost_center"):
            return NO_CENTER
        entity = budget["budget_entity_name"]
        if entity in centers:
            return entity
        # Observed GET response uses the name even though POST expects a UUID.
        matches = [c["CenterId"] for c in center_rows if c["Center"] == entity]
        if len(matches) != 1:
            raise ContractError("Budget center name has no unique match in this snapshot")
        return matches[0]

    budgets = [
        dict(BudgetId=b["id"], Scope=b["budget_scope"],
             Entity=b.get("budget_entity_name", ""), ProductSKU=b["budget_product_sku"],
             BudgetType=b["budget_type"], BudgetAmount=b["budget_amount"],
             ConsumedAmount=b.get("consumed_amount"), HardStop=b["prevent_further_usage"],
             CenterId=budget_center(b),
             AsOf=raw["collected_at"])
        for b in raw["budgets"]
    ]
    unknown_budgets = {b["CenterId"] for b in budgets} - centers
    if unknown_budgets:
        raise ContractError("Budget references unknown cost center")
    user_rows = []
    for user in users:
        classification = config.get("user_classifications", {}).get(user)
        if classification and (not classification.get("evidence") or not classification.get("as_of")
                               or not classification.get("stack")):
            raise ContractError("External stack classification requires stack, date and evidence")
        user_rows.append(dict(
            User=user, UserId=logins.get(user, ""), IsResidual=user == RESIDUAL_USER,
            Stack=classification["stack"] if classification else "Unclassified",
            ClassificationSource=classification["evidence"] if classification else None,
            ClassificationAsOf=classification["as_of"] if classification else None))
    date_rows = []
    for day in requested_days:
        date = dt.date.fromisoformat(day)
        monday = date - dt.timedelta(days=date.weekday())
        date_rows.append(dict(Day=day, Month=day[:7], WeekStart=monday.isoformat(),
                              WeekEnd=(monday + dt.timedelta(days=6)).isoformat()))
    snapshot = raw.get("license_snapshot")
    return dict(
        Info=[dict(Mode=mode, Label=(
            "SYNTHETIC SAMPLE - NOT REAL USAGE" if mode == "SAMPLE"
            else "REAL DATA - PRIVATE SNAPSHOT") +
            f" | Billing: {min(raw['requested_days'])} to {max(raw['requested_days'])}" +
            (" | Metrics PARTIAL" if len(available_metrics_days) < len(requested_days)
             else " | Metrics complete"),
                   AsOf=raw["collected_at"], StartDay=min(raw["requested_days"]),
                   EndDay=max(raw["requested_days"]), Enterprise=raw["enterprise"],
                   Coverage="Partial user billing: explicit residual; telemetry is not billing",
                   SchemaVersion="2.0",
                   LicenseSnapshotAsOf=snapshot["as_of"] if snapshot else None,
                   LicenseRosterStatus="Complete snapshot, not historical" if snapshot else "Unavailable",
                   HistoricalLicenseCoverage="Audited roster intervals" if config.get(
                       "license_history_coverage") else "No historical roster: adoption and inactivity N/D",
                   MetricsStartDay=min(available_metrics_days) if available_metrics_days else None,
                   MetricsEndDay=max(available_metrics_days) if available_metrics_days else None,
                   BillingStartDay=min(requested_days), BillingEndDay=max(requested_days),
                   MissingMetricsDays=len(requested_days) - len(available_metrics_days),
                   MetricsCoverageStatus="Complete" if len(available_metrics_days) == len(requested_days)
                   else "PARTIAL: missing metrics days; do not infer inactivity")],
        Centers=center_rows, Dates=date_rows, Users=user_rows,
        Models=[dict(Model=m) for m in models],
        Billing=billing, Metrics=metrics, ModelFeatures=features, ClientModels=clients,
        IDEs=ides, Languages=languages, Pools=snapshots, Budgets=budgets,
        Memberships=memberships, Features=feature_totals, CLI=cli,
        Licenses=licenses, LicensedDays=licensed_days, LicenseCoverage=license_coverage,
        Periods14=[dict(BlockIndex=index, BlockLabel=f"B{index + 1:02}") for index in range(28)],
        SourceCoverage=source_coverage,
    )

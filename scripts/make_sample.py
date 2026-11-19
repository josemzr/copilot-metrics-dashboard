#!/usr/bin/env python3
"""Reproducible, entirely fictional data. No credentials or API calls."""
from collections import defaultdict
import datetime as dt
from pathlib import Path
import random

from normalize import NUMBERS, normalize, write_json

ROOT = Path(__file__).resolve().parents[1]


def make_sample():
    randomizer = random.Random(20261118)
    centers, countries, assignments = [], {}, []
    for country in ("Region_A", "Region_B", "Region_C"):
        for suffix in ("", "_Copilot"):
            center_id = "sample-" + country.lower() + (suffix.lower() or "-base")
            countries[center_id] = country
            centers.append(dict(
                id=center_id, name=country + suffix, state="active", resources=[],
                ai_credit_pool_enabled=bool(suffix),
                ai_credit_pool_state={"target_amount": 200 if suffix else None,
                                      "current_amount": 84 if suffix else None}))
    dates = [(dt.date(2026, 11, 1) + dt.timedelta(days=i)).isoformat() for i in range(16)]
    users = []
    for index in range(18):
        user = f"demo-user-{index + 1:02}"
        center = centers[index // 3]["id"]
        users.append((user, center))
        centers[index // 3]["resources"].append(dict(type="User", name=user))
        assignments.append(dict(
            user_id=index + 1, cost_center_id=center, valid_from="2026-11-01",
            valid_to_exclusive="2026-12-01", evidence="SYNTHETIC SCENARIO ONLY"))
    models = ("Model Alpha", "Model Beta", "Model Gamma")
    billing_groups, telemetry = [], []
    for day_index, day in enumerate(dates):
        for center in centers:
            details, totals = [], {}
            for index, (user, cid) in enumerate(users):
                if cid != center["id"]:
                    continue
                items = []
                model_features, client_models = [], []
                interactions = 0
                for model_index, model in enumerate(models):
                    quantity = randomizer.randint(8, 100) * (model_index + 1)
                    discount = round(quantity * (0.6 if "_Copilot" in center["name"] else 0.2), 2)
                    # The 0.01 denomination is documented; these usage/discount inputs are fictional.
                    item = dict(product="Copilot", sku="Copilot AI Credits", model=model,
                                unitType="ai-credits", pricePerUnit=0.01,
                                grossQuantity=quantity, grossAmount=quantity / 100,
                                discountQuantity=discount, discountAmount=discount / 100,
                                netQuantity=round(quantity - discount, 2),
                                netAmount=round((quantity - discount) / 100, 4))
                    items.append(item)
                    if model not in totals:
                        totals[model] = {k: item[k] for k in ("product", "sku", "model",
                                                           "unitType", "pricePerUnit")}
                        totals[model].update({k: 0 for k in NUMBERS})
                    for field in NUMBERS:
                        totals[model][field] = round(totals[model][field] + item[field], 6)
                    count = randomizer.randint(2, 20)
                    interactions += count
                    model_features.append(dict(
                        model=model, feature="agent" if model_index else "chat",
                        user_initiated_interaction_count=count,
                        code_generation_activity_count=count * 2,
                        code_acceptance_activity_count=count))
                    client_models.append(dict(
                        model=model, model_selection_mode="user_selected",
                        is_custom_enterprise_model=False, request_count=count * 3,
                        token_usage=dict(prompt_tokens_sum=count * 500,
                                         output_tokens_sum=count * 120)))
                response = dict(timePeriod=dict(year=2026, month=11, day=int(day[-2:])),
                                costCenter=dict(id=cid, name=center["name"]),
                                user=user, usageItems=items)
                # Intentionally omit some user billing detail, retaining the canonical total.
                if index != 2:
                    details.append(dict(user=user, response=response))
                # Different adoption rhythms are fictional, independent of billing coverage.
                if index > 2 and (day_index + index) % (2 + index % 4) != 0:
                    continue
                inline = dict(
                    feature="code_completion", user_initiated_interaction_count=0,
                    code_generation_activity_count=interactions,
                    code_acceptance_activity_count=interactions // 2,
                    loc_added_sum=interactions * 3, loc_deleted_sum=0,
                    loc_suggested_to_add_sum=interactions * 12, loc_suggested_to_delete_sum=0)
                agent = dict(
                    feature="agent_edit", user_initiated_interaction_count=interactions,
                    code_generation_activity_count=interactions,
                    code_acceptance_activity_count=interactions - interactions // 2,
                    loc_added_sum=interactions * 6, loc_deleted_sum=interactions * 3,
                    loc_suggested_to_add_sum=0, loc_suggested_to_delete_sum=0)
                telemetry.append(dict(
                    day=day, user_login=user, user_id=index + 1,
                    user_initiated_interaction_count=interactions,
                    code_generation_activity_count=interactions * 2,
                    code_acceptance_activity_count=interactions,
                    loc_added_sum=interactions * 9, loc_deleted_sum=interactions * 3,
                    loc_suggested_to_add_sum=interactions * 12, loc_suggested_to_delete_sum=0,
                    ai_credits_used=sum(item["grossQuantity"] for item in items),
                    client_telemetry_present=index % 5 != 0,
                    used_chat=index % 3 != 0, used_agent=index % 2 == 0,
                    used_cli=index % 2 == 0, used_copilot_app=index % 4 == 0,
                    used_copilot_cloud_agent=False, used_copilot_coding_agent=False,
                    used_copilot_code_review_active=False,
                    used_copilot_code_review_passive=None,
                    used_vscode_agent=False, used_local_byok=False,
                    usage_metrics_requirements=dict(
                        met=["vscode"] if index % 6 else [],
                        unmet=[] if index % 6 else ["vscode"], unknown=[]),
                    totals_by_feature=[inline, agent],
                    totals_by_cli=dict(prompt_count=interactions, request_count=interactions * 2,
                                       session_count=2, token_usage=dict(
                                           prompt_tokens_sum=interactions * 200,
                                           output_tokens_sum=interactions * 80)) if index % 2 == 0 else None,
                    totals_by_model_feature=model_features,
                    totals_by_client=[dict(client="vscode" if index % 2 else "copilot_cli",
                                           totals_by_model=client_models)],
                    totals_by_ide=[dict(ide="vscode" if index % 2 else "jetbrains",
                                       user_initiated_interaction_count=interactions,
                                       code_generation_activity_count=interactions * 2)],
                    totals_by_language_feature=[dict(
                        language=("python", "typescript", "csharp")[index % 3],
                        feature="agent_edit", code_generation_activity_count=interactions * 2,
                        code_acceptance_activity_count=interactions,
                        loc_added_sum=interactions * 9, loc_deleted_sum=interactions * 3,
                        loc_suggested_to_add_sum=interactions * 12,
                        loc_suggested_to_delete_sum=0)]))
            billing_groups.append(dict(
                day=day, cost_center_id=center["id"], details=details,
                total=dict(timePeriod=dict(year=2026, month=11, day=int(day[-2:])),
                           costCenter=dict(id=center["id"], name=center["name"]),
                           usageItems=list(totals.values()))))
    spending = defaultdict(float)
    for group in billing_groups:
        spending[group["cost_center_id"]] += sum(i["netAmount"] for i in group["total"]["usageItems"])
    budgets = [dict(
        id="sample-budget-" + c["id"], budget_scope="cost_center", budget_entity_name=c["id"],
        budget_type="BundlePricing", budget_product_sku="ai_credits", budget_amount=300,
        consumed_amount=round(spending[c["id"]], 4), prevent_further_usage=True)
        for c in centers]
    licenses, history, classifications = [], [], {}
    for index in range(22):
        user = f"demo-user-{index + 1:02}"
        licenses.append(dict(assignee=dict(login=user, id=index + 1), plan_type="business",
                             organization=None, pending_cancellation_date=None,
                             last_activity_at=dates[-1] + "T12:00:00Z" if index < 18 else None))
        history.append(dict(user_login=user, user_id=index + 1, valid_from=dates[0],
                            valid_to_exclusive="2026-12-01", evidence="SYNTHETIC COMPLETE ROSTER"))
        if index >= 18:
            centers[index % 6]["resources"].append(dict(type="User", name=user))
            assignments.append(dict(user_id=index + 1, cost_center_id=centers[index % 6]["id"],
                                    valid_from=dates[0], valid_to_exclusive="2026-12-01",
                                    evidence="SYNTHETIC SCENARIO ONLY"))
        classifications[user] = dict(stack=("Backend", "Data", "Platform")[index % 3],
                                     as_of="2026-11-18", evidence="SYNTHETIC EXTERNAL MAPPING")
    observed = {(row["day"], row["user_login"]) for row in telemetry}
    for day in dates:
        for index in range(22):
            user = f"demo-user-{index + 1:02}"
            if (day, user) in observed:
                continue
            telemetry.append(dict(
                day=day, user_login=user, user_id=index + 1,
                user_initiated_interaction_count=0, code_generation_activity_count=0,
                code_acceptance_activity_count=0, loc_added_sum=0, loc_deleted_sum=0,
                loc_suggested_to_add_sum=0, loc_suggested_to_delete_sum=0,
                ai_credits_used=0, client_telemetry_present=True,
                used_chat=False, used_agent=False, used_cli=False, used_copilot_app=False,
                used_copilot_cloud_agent=False, used_copilot_coding_agent=False,
                used_copilot_code_review_active=False, used_copilot_code_review_passive=False,
                used_vscode_agent=False, used_local_byok=False,
                usage_metrics_requirements=dict(met=["vscode"], unmet=[], unknown=[]),
                totals_by_feature=[], totals_by_model_feature=[], totals_by_client=[],
                totals_by_ide=[], totals_by_language_feature=[]))
    raw = dict(collected_at="2026-11-18T17:00:00+00:00", enterprise="synthetic-example",
               requested_days=dates, cost_centers=centers, budgets=budgets,
               users=telemetry, billing=billing_groups,
               license_snapshot=dict(as_of="2026-11-18T17:00:00+00:00", complete=True, seats=licenses))
    config = dict(countries=countries, telemetry_assignments=assignments,
                  user_classifications=classifications, license_history=history,
                  license_history_coverage=[dict(valid_from=dates[0], valid_to_exclusive="2026-12-01",
                                                 evidence="SYNTHETIC COMPLETE ROSTER")])
    return normalize(raw, config, "SAMPLE"), raw, config


if __name__ == "__main__":
    dataset, _, _ = make_sample()
    (ROOT / "data/sample").mkdir(parents=True, exist_ok=True)
    write_json(ROOT / "data/sample/dataset.json", dataset)
    print("SAMPLE dataset regenerated (deterministic; fictional)")

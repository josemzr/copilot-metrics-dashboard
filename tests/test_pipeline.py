from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import Client, ContractError, center_snapshots, days, paged
from make_sample import make_sample
from normalize import billing_rows, historical_center, normalize, RESIDUAL_USER


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset, cls.raw, cls.config = make_sample()

    def test_user_details_and_residual_reconcile_exact_center_model_totals(self):
        rows = billing_rows(self.raw["billing"][:1])
        total = self.raw["billing"][0]["total"]["usageItems"]
        for item in total:
            for field in ("grossQuantity", "grossAmount", "netQuantity", "netAmount",
                          "discountQuantity", "discountAmount"):
                self.assertAlmostEqual(sum(r[field] for r in rows if r["Model"] == item["model"]),
                                       item[field], places=6)
        self.assertTrue(any(r["User"] == RESIDUAL_USER for r in rows))

    def test_no_current_membership_applied_to_past_telemetry(self):
        assignment = dict(user_id=99, cost_center_id="new", valid_from="2026-11-10",
                          valid_to_exclusive="2026-12-01", evidence="audited event")
        self.assertEqual(historical_center("99", "renamed", "2026-11-09", [assignment]),
                         "unattributed-history")
        self.assertEqual(historical_center("99", "renamed", "2026-11-10", [assignment]), "new")
        self.assertEqual(historical_center("99", "renamed", "2026-12-01", [assignment]),
                         "unattributed-history")

    def test_unconfigured_region_uses_exact_client_center_name_without_changing_facts(self):
        raw = deepcopy(self.raw)
        raw["cost_centers"][0]["name"] = "North_West Business_Copilot"
        configured = normalize(raw, self.config, "REAL")
        names = normalize(raw, dict(self.config, countries={}), "REAL")
        for center in raw["cost_centers"]:
            self.assertEqual(next(r["Country"] for r in names["Centers"] if r["CenterId"] == center["id"]),
                             center["name"])
        first = raw["cost_centers"][0]["id"]
        self.assertEqual(next(r["Country"] for r in configured["Centers"] if r["CenterId"] == first),
                         self.config["countries"][first])
        self.assertEqual(next(r["Country"] for r in names["Centers"] if r["CenterId"] == "none"), "No region")
        for table in names:
            if table != "Centers":
                self.assertEqual(names[table], configured[table])

    def test_ambiguous_history_fails(self):
        assignment = self.config["telemetry_assignments"][0]
        with self.assertRaisesRegex(ContractError, "Overlapping"):
            historical_center(1, "demo-user-01", "2026-11-01", [assignment, assignment])

    def test_current_snapshot_does_not_become_credit_balance(self):
        pool = self.dataset["Pools"][0]
        self.assertNotIn("RemainingCredits", pool)
        self.assertIn("not defined", pool["UnitStatus"])
        self.assertNotIn("Day", pool)
        self.assertNotIn("Day", self.dataset["Budgets"][0])

    def test_duplicate_day_and_premium_request_units_rejected(self):
        group = deepcopy(self.raw["billing"][0])
        with self.assertRaisesRegex(ContractError, "Repeated daily"):
            billing_rows([group, group])
        group["total"]["usageItems"][0]["unitType"] = "requests"
        with self.assertRaisesRegex(ContractError, "unit"):
            billing_rows([group])

    def test_contradictory_user_billing_fails_instead_of_double_counting(self):
        group = deepcopy(self.raw["billing"][0])
        group["details"][0]["response"]["usageItems"][0]["grossQuantity"] = 10000000
        with self.assertRaisesRegex(ContractError, "exceed"):
            billing_rows([group])

    def test_non_numeric_missing_and_wrong_period_billing_fail(self):
        for value in (None, True, "100"):
            group = deepcopy(self.raw["billing"][0])
            group["total"]["usageItems"][0]["netAmount"] = value
            with self.assertRaises(ContractError):
                billing_rows([group])
        group = deepcopy(self.raw["billing"][0])
        del group["total"]["timePeriod"]["day"]
        with self.assertRaisesRegex(ContractError, "exact requested day"):
            billing_rows([group])

    def test_missing_telemetry_is_null_not_zero_and_real_never_sample(self):
        raw = deepcopy(self.raw)
        del raw["users"][0]["ai_credits_used"]
        dataset = normalize(raw, self.config)
        self.assertIsNone(dataset["Metrics"][0]["TelemetryCredits"])
        self.assertEqual(dataset["Info"][0]["Mode"], "REAL")
        self.assertNotIn("SYNTHETIC", dataset["Info"][0]["Label"])

    def test_overlapping_report_windows_rejected(self):
        raw = deepcopy(self.raw)
        raw["users"].append(raw["users"][0])
        with self.assertRaisesRegex(ContractError, "Duplicate user-day"):
            normalize(raw, self.config)

    def test_login_reuse_rejected(self):
        raw = deepcopy(self.raw)
        raw["users"][1]["user_login"] = raw["users"][0]["user_login"]
        with self.assertRaisesRegex(ContractError, "reused"):
            normalize(raw, self.config)

    def test_budget_pagination_not_first_ten_only(self):
        class Fake:
            def get(self, path, **params):
                page = params["page"]
                return {"budgets": [page], "has_next_page": page < 3}
        self.assertEqual(paged(Fake(), "/budgets", "budgets"), [1, 2, 3])

    def test_center_memberships_are_paginated_in_current_snapshot(self):
        class Fake:
            def get(self, path, **params):
                if path == "/billing/cost-centers":
                    return {"costCenters": [{"id": "c1", "resources": []}]}
                page = params["page"]
                return {"id": "c1", "resources": [{"type": "User", "name": f"user-{page}"}],
                        "has_next_page": page < 2}
        self.assertEqual(len(center_snapshots(Fake(), "/billing")[0]["resources"]), 2)

    def test_budget_get_name_resolves_only_against_unique_current_snapshot(self):
        raw = deepcopy(self.raw)
        raw["budgets"][0]["budget_entity_name"] = raw["cost_centers"][0]["name"]
        dataset = normalize(raw, self.config)
        self.assertEqual(dataset["Budgets"][0]["CenterId"], raw["cost_centers"][0]["id"])
        raw["cost_centers"][1]["name"] = raw["cost_centers"][0]["name"]
        with self.assertRaisesRegex(ContractError, "no unique match"):
            normalize(raw, self.config)

    def test_api_empty_string_is_not_zero_usage(self):
        client = Client("https://api.github.com", "2026-03-10", "unused")
        client.get = lambda *a, **k: ""
        with self.assertRaisesRegex(ContractError, "not zero usage"):
            client.report("/copilot/metrics/reports/users-1-day", "2026-11-01")

    def test_no_accidental_credential_exfiltration_or_bad_dates(self):
        with self.assertRaisesRegex(ContractError, "api.github.com"):
            Client("https://example.com", "2026-03-10", "never-send-this")
        self.assertEqual(list(days("2026-11-01", "2026-11-02")),
                         ["2026-11-01", "2026-11-02"])
        with self.assertRaises(ContractError):
            list(days("2026-11-02", "2026-11-01"))


if __name__ == "__main__":
    unittest.main()

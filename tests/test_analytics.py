from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import ContractError, ReportUnavailable, collect, license_snapshot
from make_sample import make_sample
from normalize import activity_observed, normalize


class AnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset, cls.raw, cls.config = make_sample()

    def test_activity_unknown_is_not_inactive_and_passive_review_alone_is_not_active(self):
        self.assertIsNone(activity_observed({}))
        core = dict(user_initiated_interaction_count=0, code_generation_activity_count=0,
                    code_acceptance_activity_count=0, used_chat=False, used_agent=False,
                    used_cli=False, used_copilot_app=False, used_copilot_cloud_agent=False)
        self.assertIs(activity_observed(core), False)
        self.assertIs(activity_observed(dict(core, used_copilot_code_review_passive=True)), False)
        self.assertIs(activity_observed(dict(core, used_cli=True)), True)
        self.assertIs(activity_observed(dict(core, totals_by_client=[
            dict(request_count=1)])), True)
        with self.assertRaises(ContractError):
            activity_observed(dict(core, used_chat="false"))

    def test_features_are_independent_and_inline_acceptance_is_not_all_added_lines(self):
        row = self.dataset["Metrics"][0]
        features = [f for f in self.dataset["Features"]
                    if (f["Day"], f["User"]) == (row["Day"], row["User"])]
        self.assertEqual(sum(f["LinesAdded"] for f in features), row["LinesAdded"])
        self.assertEqual(sum(f["LinesDeleted"] for f in features), row["LinesDeleted"])
        inline = next(f for f in features if f["Feature"] == "code_completion")
        self.assertLess(inline["LinesAdded"], row["LinesAdded"])
        self.assertLess(row["LinesAdded"] - row["LinesDeleted"],
                        row["LinesAdded"] + row["LinesDeleted"])

    def test_license_snapshot_is_deduplicated_and_never_becomes_historical_roster(self):
        raw = deepcopy(self.raw)
        raw["license_snapshot"]["seats"].append(raw["license_snapshot"]["seats"][0])
        config = dict(self.config, license_history=[], license_history_coverage=[])
        dataset = normalize(raw, config)
        self.assertEqual(len(dataset["Licenses"]), 22)
        self.assertEqual(dataset["LicensedDays"], [])
        self.assertTrue(all(not r["HistoricalRosterComplete"] for r in dataset["LicenseCoverage"]))
        self.assertEqual(dataset["Info"][0]["LicenseSnapshotAsOf"], raw["license_snapshot"]["as_of"])

    def test_historical_roster_includes_inactive_and_requires_audited_full_coverage(self):
        self.assertEqual(len(self.dataset["LicensedDays"]), 22 * 16)
        self.assertEqual(len({r["User"] for r in self.dataset["Metrics"]
                              if r["ActivityObserved"] is True}), 18)
        self.assertEqual(len(self.dataset["Metrics"]), 22 * 16)
        self.assertEqual(sum(r["ActivityObserved"] is False for r in self.dataset["Metrics"]), 226)
        self.assertTrue(all(r["HistoricalRosterComplete"] for r in self.dataset["LicenseCoverage"]))
        config = deepcopy(self.config)
        config["license_history"][0]["evidence"] = ""
        with self.assertRaisesRegex(ContractError, "audit evidence"):
            normalize(self.raw, config)
        config = deepcopy(self.config)
        config["license_history"].append(config["license_history"][0])
        with self.assertRaisesRegex(ContractError, "Overlapping"):
            normalize(self.raw, config)

    def test_iso_week_and_external_stack_missing_stay_explicit(self):
        self.assertEqual(self.dataset["Dates"][0]["WeekStart"], "2026-10-26")
        self.assertEqual(self.dataset["Dates"][1]["WeekStart"], "2026-11-02")
        config = dict(self.config, user_classifications={})
        dataset = normalize(self.raw, config)
        self.assertTrue(all(r["Stack"] == "Unclassified" for r in dataset["Users"]))
        self.assertTrue(all(r["ClassificationSource"] is None for r in dataset["Users"]))
        raw = deepcopy(self.raw)
        del raw["users"][0]["loc_deleted_sum"]
        del raw["users"][0]["used_chat"]
        del raw["users"][0]["usage_metrics_requirements"]
        row = normalize(raw, config)["Metrics"][0]
        self.assertIsNone(row["LinesDeleted"])
        self.assertIsNone(row["UsedChat"])
        self.assertIsNone(row["RequirementsUnmet"])

    def test_license_collection_paginates_without_exporting_email_or_profile(self):
        class Fake:
            def get(self, path, **params):
                page = params["page"]
                return {"seats": [{
                    "assignee": {"login": f"user-{page}", "id": page, "email": "not-exported"},
                    "organization": None, "plan_type": "business", "last_activity_at": None,
                }], "has_next_page": page < 2}
        snapshot = license_snapshot(Fake(), "/enterprises/test")
        self.assertEqual(len(snapshot["seats"]), 2)
        self.assertNotIn("email", snapshot["seats"][0]["assignee"])
        self.assertTrue(snapshot["complete"])

    def test_partial_metrics_export_is_opt_in_and_does_not_hide_api_failures(self):
        class Fake:
            failure = ReportUnavailable("known empty response")

            def get(self, path, **params):
                if path.endswith("/cost-centers"):
                    return {"costCenters": []}
                if path.endswith("/budgets"):
                    return {"budgets": [], "has_next_page": False}
                return {"timePeriod": {"year": 2026, "month": 11, "day": params["day"]},
                        "usageItems": []}

            def report(self, path, day):
                if day == "2026-11-02":
                    raise self.failure
                return []

        config = dict(enterprise="test", start_day="2026-11-01", end_day="2026-11-02",
                      billing_users=[], collect_licenses=False)
        fake = Fake()
        with self.assertRaises(ReportUnavailable):
            collect(config, fake)
        config["allow_missing_metrics"] = True
        raw = collect(config, fake)
        self.assertEqual(raw["users"], [])
        self.assertEqual(raw["source_coverage"][1]["metrics_status"], "unavailable_empty_response")
        for error in (ContractError("HTTP 403"), ContractError("HTTP 404"),
                      ContractError("HTTP 500"), ContractError("Invalid contract")):
            fake.failure = error
            with self.assertRaises(ContractError) as caught:
                collect(config, fake)
            self.assertIs(caught.exception, error)

    def test_missing_source_day_has_no_fabricated_zero_rows(self):
        raw = deepcopy(self.raw)
        day = raw["requested_days"][-1]
        raw["users"] = [row for row in raw["users"] if row["day"] != day]
        raw["source_coverage"] = [
            dict(day=d, metrics_status="unavailable_empty_response" if d == day else "available",
                 billing_status="available_snapshot") for d in raw["requested_days"]]
        dataset = normalize(raw, self.config)
        self.assertFalse(any(row["Day"] == day for row in dataset["Metrics"]))
        self.assertTrue(any(row["Day"] == day for row in dataset["Billing"]))
        self.assertEqual(dataset["Info"][0]["MissingMetricsDays"], 1)
        self.assertIn("PARTIAL", dataset["Info"][0]["Label"])
        self.assertFalse(dataset["SourceCoverage"][-1]["MetricsAvailable"])
        self.assertEqual(dataset["Info"][0]["BillingEndDay"], day)


if __name__ == "__main__":
    unittest.main()

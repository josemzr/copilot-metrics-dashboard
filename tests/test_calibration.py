from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_powerbi import model
from make_sample import make_sample
from projection_powerbi import MEASURES, patch_model


class CalibrationModelTests(unittest.TestCase):
    def test_generated_dax_variables_avoid_the_reserved_rows_identifier(self):
        for name, (expression, _) in MEASURES.items():
            with self.subTest(measure=name):
                variables = re.findall(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)", expression, re.I)
                self.assertNotIn("rows", {variable.casefold() for variable in variables})

    def test_existing_model_patch_keeps_all_original_sources_measures_and_relationships(self):
        current = json.loads(subprocess.check_output(
            ["git", "show", "HEAD:powerbi/CopilotMetrics.SemanticModel/model.bim"], cwd=ROOT))
        original = deepcopy(current)
        patched = patch_model(current)["model"]
        old = original["model"]
        for before in old["tables"]:
            if before["name"].startswith("Projection"):
                continue
            after = next(t for t in patched["tables"] if t["name"] == before["name"])
            for key in ("columns", "partitions", "hierarchies"):
                self.assertEqual(after.get(key), before.get(key))
            existing = {m["name"]: m for m in after.get("measures", [])}
            for measure in before.get("measures", []):
                if not measure["name"].startswith("Projection "):
                    self.assertEqual(existing[measure["name"]], measure)
        prior_sources = [e for e in old["expressions"] if not e["name"].startswith(("Projection", "Projections"))]
        self.assertEqual([e for e in patched["expressions"] if not e["name"].startswith(("Projection", "Projections"))],
                         prior_sources)
        self.assertEqual(patched["relationships"][:37], old["relationships"][:37])
        self.assertEqual(patch_model(deepcopy(current)), current)

    def test_bucket_and_replacement_tables_are_separate_from_universe_and_numeric_anchors(self):
        database = model(make_sample()[0])["model"]
        tables = {t["name"]: t for t in database["tables"]}
        self.assertIn("ProjectionBuckets", tables)
        self.assertIn("ProjectionReplaceSource", tables)
        self.assertNotIn("ProjectionReplaceSource", {r["fromTable"] for r in database["relationships"]})
        self.assertNotIn("ProjectionReplaceSource", {r["toTable"] for r in database["relationships"]})
        for name, field in (("Projection Baseline Credits", "ReportedCredits"), ("Projection Baseline USD", "ReportedUSD")):
            text = MEASURES[name][0]
            self.assertIn("Projection Partial Reported", text)
            partial = "Projection Partial Reported Credits" if field == "ReportedCredits" else "Projection Partial Reported USD"
            self.assertIn(f"SUM(ProjectionBuckets[{field}])", MEASURES[partial][0])
            self.assertNotIn("Projection Ready", text)
            self.assertNotIn("*100", text)
        for name in ("Projection Scenario Credits", "Projection Scenario USD"):
            self.assertIn("[Projection Unresolved Change Rows]=0", MEASURES[name][0])
            self.assertIn("[Projection No Changes]=1", MEASURES[name][0])
            self.assertNotIn("[Projection Numeric Total Error]", MEASURES[name][0])
        self.assertNotIn("Scenario Credits", MEASURES["Projection Unresolved Change Rows"][0])
        self.assertNotIn("Scenario USD", MEASURES["Projection Unresolved Change Rows"][0])
        self.assertIn("[Projection Bucket Change Requested]=0,1", MEASURES["Projection Bucket Ratio"][0])
        self.assertIn("Source>0", MEASURES["Projection Bucket Ratio"][0])
        self.assertIn("Target==0 && Credits==0 && USD==0", MEASURES["Projection Bucket Ratio"][0])
        self.assertIn("Volume=1", MEASURES["Projection Bucket Change Requested"][0])
        self.assertIn("Projection Token Diagnostic Baseline USD", MEASURES)

    def test_calibrated_deltas_reference_each_primary_value_only_once(self):
        for name, baseline, scenario in (
            ("Projection Delta Credits", "Projection Baseline Credits", "Projection Scenario Credits"),
            ("Projection Delta Cost USD", "Projection Baseline USD", "Projection Scenario USD"),
        ):
            text = MEASURES[name][0]
            self.assertEqual(text.count("[" + baseline + "]"), 1)
            self.assertEqual(text.count("[" + scenario + "]"), 1)

    def test_no_change_fast_paths_do_not_treat_blank_replacement_as_zero(self):
        for name in ("Projection No Changes", "Projection Bucket Change Requested"):
            with self.subTest(measure=name):
                text = MEASURES[name][0]
                self.assertRegex(text, r"\bP\s*==\s*0\b")
                self.assertNotRegex(text, r"\bP\s*=\s*0\b")

    def test_m_aggregates_complete_token_buckets_before_view_filters_with_explicit_missingness(self):
        text = (ROOT / "projections/usage.pq").read_text()
        self.assertIn('Table.Group(CopilotBills,{"Day","User","SourceKey","CenterId"}', text)
        self.assertIn('Table.Group(Usage,{"Day","User","SourceKey"}', text)
        self.assertIn('SumComplete(bills,"grossQuantity")', text)
        self.assertIn('SumComplete(bills,"grossAmount")', text)
        self.assertIn("List.AnyTrue", text)
        self.assertIn("Incomplete/ambiguous token center attribution", text)
        self.assertIn("No complete token bucket", text)
        self.assertNotIn("Dataset[Memberships]", text)
        self.assertNotIn("ProjectionPricing", text)
        self.assertNotIn("Web.Contents", text)


if __name__ == "__main__":
    unittest.main()

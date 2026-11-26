import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_powerbi as pbi
from make_sample import make_sample


class PowerBIReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.report = Path(cls.temporary.name) / "Report"
        (cls.report / "definition").mkdir(parents=True)
        with patch.object(pbi, "REPORT", cls.report):
            pbi.build_report()
        cls.database = pbi.model(make_sample()[0])["model"]
        cls.measures = {measure["name"]: measure for table in cls.database["tables"]
                        for measure in table.get("measures", [])}

    def visuals(self, page):
        return [json.loads(path.read_text())["visual"]
                for path in (self.report / "definition/pages" / page / "visuals").glob("*/visual.json")]

    def test_overview_keeps_fully_discounted_models_visible_without_activity_only_rows(self):
        tables = [visual for visual in self.visuals("overview") if visual["visualType"] == "tableEx"]
        self.assertEqual(len(tables), 1)
        projections = tables[0]["query"]["queryState"]["Values"]["projections"]
        self.assertEqual([item["queryRef"] for item in projections], [
            "Models.Model", "Info.Gross amount USD", "Info.Discounts USD", "Info.Net cost USD",
        ])
        for name, column in (("Gross amount USD", "grossAmount"), ("Discounts USD", "discountAmount"),
                             ("Net cost USD", "netAmount")):
            expression = self.measures[name]["expression"]
            self.assertEqual(expression,
                             f'CALCULATE(SUM(Billing[{column}]), KEEPFILTERS(Billing[UnitType] = "ai-credits"))')
            self.assertNotIn("COALESCE", expression)
        self.assertFalse(any(visual["visualType"] == "clusteredBarChart"
                             for visual in self.visuals("overview")))

    def test_fourteen_day_stacked_columns_are_native_and_keep_all_dynamic_roles(self):
        matches = [visual for visual in self.visuals("models14")
                   if "Series" in visual["query"]["queryState"]
                   and visual["query"]["queryState"]["Y"]["projections"][0]["queryRef"] == "Info.Block14 credits"]
        self.assertEqual(len(matches), 1)
        visual = matches[0]
        self.assertEqual(visual["visualType"], "columnChart")
        query = visual["query"]["queryState"]
        self.assertEqual(query["Category"]["projections"][0]["queryRef"], "Periods14.BlockLabel")
        self.assertEqual(query["Series"]["projections"][0]["queryRef"], "Models.Model")
        self.assertEqual([item["queryRef"] for item in query["Tooltips"]["projections"]],
                         ["Info.Block14 start", "Info.Block14 end"])

    def test_empty_residual_and_diagnostic_counts_have_coverage_qualified_zero(self):
        for name in ("Unattributed user credits", "Unknown activity rows", "Telemetry present rows",
                     "Telemetry absent rows", "Unknown telemetry rows", "Unmet requirements rows"):
            with self.subTest(measure=name):
                expression = self.measures[name]["expression"]
                self.assertIn("ISBLANK(", expression)
                self.assertIn("SourceCoverage[BillingAvailable]" if name == "Unattributed user credits"
                              else "[Complete metrics coverage]", expression)
                self.assertIn("0", expression)
        for name in ("Telemetry absent rows", "Users without client telemetry"):
            self.assertIn("NOT ISBLANK(Metrics[TelemetryPresent])", self.measures[name]["expression"])

    def test_telemetry_present_rate_uses_known_user_day_rows_and_not_distinct_users(self):
        expression = self.measures["Known telemetry coverage"]["expression"]
        self.assertEqual(expression,
                         "DIVIDE([Telemetry present rows], [Telemetry present rows] + [Telemetry absent rows])")
        self.assertNotIn("DISTINCTCOUNT", expression)
        matching = [visual for visual in self.visuals("diagnostics")
                    if "Known telemetry coverage" in visual["query"]["queryState"]["Values"]["projections"][0]["queryRef"]]
        self.assertEqual(len(matching), 1)
        title = matching[0]["visualContainerObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"]
        self.assertIn("Client telemetry present rate", title)
        self.assertIn("known-status user-day rows", title)

    def test_cards_show_nd_without_converting_numeric_graph_and_budget_measures(self):
        for name in ("Consumed budget USD", "Budget headroom USD", "Activity acceptance rate",
                     "Inline line acceptance rate", "Known telemetry coverage"):
            with self.subTest(measure=name):
                base = self.measures[name]
                self.assertNotIn("FORMAT(", base["expression"])
                self.assertNotIn("COALESCE", base["expression"])
                display = self.measures["Display " + name]
                self.assertTrue(display["isHidden"])
                self.assertIn(f"[{name}]", display["expression"])
                self.assertIn('ISBLANK(CardValue), "N/D"', display["expression"])
        self.assertIn("NOT ISBLANK([Consumed budget USD])", self.measures["Budget headroom USD"]["expression"])

    def test_full_public_model_avoids_reserved_value_and_rows_variable_names(self):
        for name, measure in self.measures.items():
            with self.subTest(measure=name):
                variables = re.findall(r"\bVAR\s+([A-Za-z_][A-Za-z0-9_]*)",
                                       measure["expression"], re.I)
                self.assertFalse({"value", "rows"} & {v.casefold() for v in variables})
        display = self.measures["Display Users with billing detail"]
        self.assertEqual(display["expression"],
                         'VAR CardValue = [Users with billing detail] RETURN '
                         'IF(ISBLANK(CardValue), "N/D", FORMAT(CardValue, "#,0", "en-US"))')

    def test_local_variable_fix_preserves_existing_calculations_formats_and_hidden_flags(self):
        root = Path(__file__).resolve().parents[1]
        original = json.loads(subprocess.check_output(
            ["git", "show", "HEAD:powerbi/CopilotMetrics.SemanticModel/model.bim"], cwd=root))
        for table in original["model"]["tables"]:
            for measure in table.get("measures", []):
                with self.subTest(measure=measure["name"]):
                    expected = dict(measure)
                    if expected["expression"].startswith("VAR Value = "):
                        variable = "CardValue" if measure["name"].startswith("Display ") else "CoveredValue"
                        expected["expression"] = re.sub(r"\bValue\b", variable, expected["expression"])
                    self.assertEqual(self.measures[measure["name"]], expected)

    def test_desktop_mix_file_is_optional_and_cloud_opt_out_keeps_embedded_mixes(self):
        expressions = {e["name"]: e["expression"] for e in self.database["expressions"]}
        self.assertTrue(expressions["ProjectionMixFile"].startswith('"" meta '))
        self.assertIn("IsParameterQueryRequired=false", expressions["ProjectionMixFile"])
        query = expressions["ProjectionMixJSON"]
        self.assertTrue(query.startswith(
            'if ProjectionMixFile = null or Text.Trim(ProjectionMixFile) = "" then '))
        self.assertIn("else Text.FromBinary(File.Contents(ProjectionMixFile),TextEncoding.Utf8)", query)
        self.assertNotIn("IsParameterQuery", query)
        self.assertNotIn("otherwise", query)
        cloud = pbi.model(make_sample()[0], mix_file_parameter=False)["model"]
        embedded = next(e["expression"] for e in cloud["expressions"] if e["name"] == "ProjectionMixJSON")
        self.assertNotIn("ProjectionMixFile", {e["name"] for e in cloud["expressions"]})
        self.assertIn(embedded.split(" meta ", 1)[0], query)
        self.assertIn("IsParameterQuery=true", embedded)
        self.assertNotIn("File.Contents", embedded)

    def test_overview_financial_cards_remain_numeric_for_classic_dashboard_alerts(self):
        cards = [visual for visual in self.visuals("overview") if visual["visualType"] == "card"]
        references = {visual["query"]["queryState"]["Values"]["projections"][0]["queryRef"]
                      for visual in cards}
        for name in ("Gross AI credits", "Net cost USD"):
            with self.subTest(measure=name):
                self.assertIn("Info." + name, references)
                self.assertNotIn("Display " + name, self.measures)
                self.assertNotIn("FORMAT(", self.measures[name]["expression"])

    def test_long_projection_page_uses_native_fit_to_width_without_changing_original_pages(self):
        for path in (self.report / "definition/pages").glob("*/page.json"):
            page = json.loads(path.read_text())
            self.assertEqual(page["displayOption"], "FitToWidth" if page["name"] == "projections" else "FitToPage")

    def test_only_numeric_cards_use_hidden_displays_and_all_other_visuals_keep_base_measures(self):
        used = set()
        for path in (self.report / "definition/pages").glob("*/visuals/*/visual.json"):
            visual = json.loads(path.read_text())["visual"]
            for role in visual["query"]["queryState"].values():
                for item in role["projections"]:
                    measure = item["field"].get("Measure", {}).get("Property")
                    if not measure:
                        continue
                    if measure.startswith("Display "):
                        self.assertEqual(visual["visualType"], "card")
                        used.add(measure)
                    if visual["visualType"] == "card" and measure in ("Data source", "Balance status"):
                        self.assertNotIn("Display ", measure)
        definitions = {name for name in self.measures if name.startswith("Display ")}
        self.assertEqual(definitions, used)
        for name in definitions:
            base = self.measures[name.removeprefix("Display ")]
            self.assertTrue(base.get("formatString"))
            self.assertNotEqual(base["formatString"], "yyyy-MM-dd")


if __name__ == "__main__":
    unittest.main()

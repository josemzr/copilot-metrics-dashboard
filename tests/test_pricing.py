import datetime as dt
import json
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pricing import CatalogStore, PricingError, SOURCES, parse_catalog, pricing_rows, public_source
from projection_powerbi import augment_model, patch_model
from projection_powerbi import MEASURES


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.prices = (ROOT / "projections/pricing-fixture.md").read_text()
        self.fusion = (ROOT / "projections/fusion-fixture.md").read_text()
        self.now = dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc)

    def test_exact_official_units_tiers_promotional_boundaries_and_na_write_are_preserved(self):
        catalog = parse_catalog(self.prices, self.fusion, self.now)
        self.assertEqual(catalog["creditsPerUSD"], 100)
        self.assertEqual(catalog["fusion"]["effectiveTo"], "2027-01-01")
        self.assertEqual(catalog["fusion"]["discount"], .3)
        self.assertEqual(len(catalog["sha256"]), 64)
        carbon = [r for r in catalog["rates"] if r["Model"] == "Gemini 4 Carbon"]
        self.assertEqual(len(carbon), 2)
        promo = next(r for r in carbon if r["Profile"] == "promotional")
        successor = next(r for r in carbon if r["Profile"] == "announced")
        self.assertEqual(promo["EffectiveTo"], successor["EffectiveFrom"])
        self.assertEqual(promo["CacheWriteStatus"], "not-applicable")
        self.assertIsNone(promo["CacheWriteUSD"])
        self.assertEqual(successor["InputUSD"], 4)
        self.assertEqual(successor["EffectiveFrom"], "2026-12-01")
        self.assertEqual(next(r for r in catalog["rates"] if r["Tier"] == "Long context")["Threshold"], "> 272K")

    def test_unknown_post_promo_prices_are_not_invented_and_units_or_schema_changes_fail(self):
        text = self.prices.split(" Starting December 1, 2026")[0]
        self.assertEqual(len([r for r in pricing_rows(text) if r["Model"] == "Gemini 4 Carbon"]), 1)
        for modified in (self.prices.replace("$0.01 USD", "$0.02 USD"),
                         self.prices.replace("$1.00", "unknown", 1),
                         self.prices.replace("until December 1, 2026", "while available")):
            with self.assertRaises(PricingError):
                parse_catalog(modified, self.fusion, self.now)

    def test_failure_retains_only_explicitly_stale_catalog_and_is_not_success_shaped(self):
        store = CatalogStore()
        sources = dict(zip(SOURCES, (self.prices, self.fusion)))
        first = store.get(fetch=sources.__getitem__, now=self.now)
        self.assertEqual(first["state"], "ready")
        def fail(url):
            raise PricingError("unavailable")
        result = store.get(fetch=fail, now=self.now + dt.timedelta(seconds=6))
        self.assertEqual(result["state"], "stale")
        self.assertEqual(result["catalog"], first["catalog"])
        self.assertIsNotNone(result["lastError"])
        self.assertEqual(CatalogStore().get(fetch=fail, now=self.now)["state"], "error")

    def test_public_price_transport_has_no_auth_and_never_accepts_arbitrary_urls(self):
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.full_url, SOURCES[0])
                self.assertIsNone(request.get_header("Authorization"))
                self.assertIsNone(request.data)
                self.assertEqual(timeout, 15)
                return io.BytesIO(self.prices.encode())
        with patch("pricing.urllib.request.build_opener", return_value=Opener()):
            self.assertEqual(public_source(SOURCES[0]), self.prices)
            for url in ("http://127.0.0.1/private", "https://api.github.com/user",
                        SOURCES[0] + "?token=fixture-only"):
                with self.assertRaises(PricingError):
                    public_source(url)

    def test_eager_scalar_fingerprint_step_keeps_standard_adler32_for_unicode_and_large_sources(self):
        body = (self.prices + "\n" + self.fusion).encode("utf-8")
        for content in (body, ("synthetic \u2264 context > 272K\n" * 3000).encode("utf-8")):
            a, b = 1, 0
            for byte in content:
                next_a = (a + byte) % 65521
                next_b = (b + next_a) % 65521
                self.assertGreaterEqual(next_a, 0)
                self.assertGreaterEqual(next_b, 0)
                a, b = next_a, next_b
            self.assertEqual(b * 65536 + a, zlib.adler32(content) & 0xFFFFFFFF)
        query = (ROOT / "projections/pricing.pq").read_text()
        self.assertIn("if a>=0 and b2>=0 then [A=a,B=b2]", query)
        self.assertEqual(query.count("IsRetry=true"), 2)
        self.assertEqual(query.count("ManualStatusHandling={408,429,503,504,509}"), 2)
        self.assertEqual(query.count('"Response.Status",200)<>200'), 2)

    def test_projection_adapter_preserves_every_original_table_measure_and_source(self):
        baseline = {"model": {"tables": [{"name": "Info", "measures": [{"name": "Numeric finance", "expression": "1"}]}],
                              "relationships": [], "expressions": [{"name": "Dataset", "expression": "private source"}]}}
        original = json.loads(json.dumps(baseline))
        augment_model(baseline)
        self.assertEqual(baseline["model"]["tables"][0]["measures"][0], original["model"]["tables"][0]["measures"][0])
        self.assertEqual(baseline["model"]["expressions"][0], original["model"]["expressions"][0])
        pricing = next(e for e in baseline["model"]["expressions"] if e["name"] == "ProjectionPricing")
        text = "\n".join(pricing["expression"])
        self.assertNotIn("Dataset", text)
        self.assertIn(SOURCES[0], text)
        self.assertIn(SOURCES[1], text)
        derived = next(e for e in baseline["model"]["expressions"] if e["name"] == "ProjectionDerived")
        self.assertNotIn("Web.Contents", "\n".join(derived["expression"]))
        with self.assertRaises(ValueError):
            augment_model(baseline)
        for name in ("Projection Baseline USD", "Projection Scenario USD", "Projection Delta Cost USD", "Projection Delta Cost Pct"):
            self.assertNotIn("FORMAT(", MEASURES[name][0])
            self.assertIn('"N/D"', MEASURES["Projection Display " + name.removeprefix("Projection ")][0])
        self.assertIn("FILTER(Targets,[_Weight]>0)", MEASURES["Projection Row Scenario USD"][0])
        self.assertIn("ISBLANK([_Weight])", MEASURES["Projection Option Error"][0])
        self.assertIn("ISBLANK([_Overhead])", MEASURES["Projection Option Error"][0])

    def test_calibrated_patch_preserves_original_objects_and_pricing_uses_no_private_source(self):
        from copy import deepcopy
        from build_powerbi import model
        from make_sample import make_sample
        database = model(make_sample()[0])
        before = deepcopy(database)
        patch_model(database)
        self.assertEqual(database, before)
        original_tables = [t for t in database["model"]["tables"] if not t["name"].startswith("Projection")]
        self.assertEqual(len(original_tables), 21)
        buckets = next(t for t in database["model"]["tables"] if t["name"] == "ProjectionBuckets")
        self.assertTrue({"ReportedCredits", "ReportedUSD", "CalibrationReason", "TokenRows"} <= {c["name"] for c in buckets["columns"]})
        self.assertIn("ProjectionReplaceSource", {t["name"] for t in database["model"]["tables"]})
        self.assertIn("[Projection Partial Reported Credits]", MEASURES["Projection Baseline Credits"][0])
        self.assertIn("[Projection Partial Reported USD]", MEASURES["Projection Baseline USD"][0])
        self.assertNotIn("*100", MEASURES["Projection Baseline Credits"][0])
        self.assertIn("[Projection Unresolved Change Rows]=0", MEASURES["Projection Scenario Credits"][0])
        self.assertIn("Source>0", MEASURES["Projection Bucket Ratio"][0])


if __name__ == "__main__":
    unittest.main()

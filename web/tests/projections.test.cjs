const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const P = require("../src/projections.js");
const contract = require("../../projections/contract.json");
const golden = require("../../projections/golden.json");
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
function fixture(model = "Fixture A") {
  const c = structuredClone(contract);
  c.models.push(...golden.rates.map(row => ({ model: row.Model, aliases: [] })));
  const data = { Info: [{ Mode: "REAL" }], Centers: [
    { CenterId: "unknown", State: "virtual" }, { CenterId: "c1", Country: "Region A", State: "active" },
    { CenterId: "c2", Country: "Region B", State: "active" }, { CenterId: "none", State: "virtual", Country: "No region" },
    { CenterId: "unattributed-history", State: "virtual", Country: "No region" }
  ], Billing: [], ClientModels: [{ Day: "2026-11-18", User: "u1", Model: model, CustomModel: false,
    CenterId: "unattributed-history", ...golden.volume }],
  SourceCoverage: [{ Day: "2026-11-18", MetricsAvailable: true }] };
  const pricing = { state: "ready", catalog: { version: contract.version, creditsPerUSD: 100,
    asOf: new Date(Date.now() - 1000).toISOString(), rates: structuredClone(golden.rates),
    fusion: { discount: .3, effectiveTo: "2999-01-01" } } };
  return { c, data, pricing };
}
test("eight independent synthetic oracle cases match JS using delta-cost sign, not invoice savings", () => {
  for (const item of golden.cases) {
    const { c, data, pricing } = fixture(item.source);
    if (item.promotionActive === false) pricing.catalog.fusion.effectiveTo = "2000-01-01";
    if (item.mix) c.mixes["fusion-high"] = item.mix;
    const result = P.simulate(data, c, pricing, item.options);
    near(result.baselineUSD, item.baselineUSD); near(result.targetUSD, item.scenarioUSD);
    near(result.deltaUSD, item.deltaCostUSD);
  }
  const { c, data, pricing } = fixture();
  const before = P.simulate(data, c, pricing).baselineUSD;
  data.ClientModels[0].Requests = 1000000000;
  assert.equal(P.simulate(data, c, pricing).baselineUSD, before, "Requests must never allocate token cost");
});
test("zero tokens and zero rates are valid while missing tokens/rates/custom models are excluded", () => {
  const { c, data, pricing } = fixture();
  const original = structuredClone(pricing.catalog.rates[0]);
  Object.assign(pricing.catalog.rates[0], { InputUSD: 0, CachedInputUSD: 0, CacheWriteUSD: 0, OutputUSD: 0 });
  assert.equal(P.simulate(data, c, pricing).baselineUSD, 0);
  pricing.catalog.rates[0] = original;
  data.ClientModels[0].PromptTokens = 0; data.ClientModels[0].OutputTokens = 0;
  assert.equal(P.simulate(data, c, pricing).baselineUSD, 0);
  assert.equal(P.simulate(data, c, pricing).deltaPct, null);
  data.ClientModels[0].PromptTokens = null;
  assert.equal(P.simulate(data, c, pricing).baselineUSD, null);
  data.ClientModels[0].PromptTokens = 100;
  data.ClientModels[0].CustomModel = true;
  assert.equal(P.simulate(data, c, pricing).eligibleRows, 0);
  data.ClientModels[0].CustomModel = false;
  delete pricing.catalog.rates[0].InputUSD;
  assert.equal(P.simulate(data, c, pricing).baselineUSD, null);
});
test("billing attribution precedes country/center filtering; ambiguous and roster-only assignments never backdate", () => {
  const { c, data, pricing } = fixture();
  const bill = { Day: "2026-11-18", User: "u1", Model: "Fixture A", CenterId: "c1", UnitType: "ai-credits", Attribution: "API user filter" };
  data.Billing.push(bill);
  assert.equal(P.simulate(data, c, pricing, {}, { country: "Region A", center: "c1" }).eligibleRows, 1);
  data.Billing.push({ ...bill, CenterId: "c2" });
  assert.equal(P.simulate(data, c, pricing, {}, { center: "c1" }).eligibleRows, 0);
  assert.equal(P.usage(data, c)[0].Attribution, "ambiguous-billing-centers");
  data.Billing = []; data.Memberships = [{ CenterId: "c1", ResourceName: "u1" }];
  assert.equal(P.simulate(data, c, pricing, {}, { center: "c1" }).eligibleRows, 0);
  data.Billing = [{ ...bill, CenterId: "none" }];
  assert.equal(P.simulate(data, c, pricing, {}, { center: "none" }).eligibleRows, 1);
  data.Billing = [{ ...bill, CenterId: "unattributed-history" }];
  assert.equal(P.usage(data, c)[0].Attribution, "unverified-center");
});
test("exact canonical aliases allow raw source filtering and Fusion billing labels do not infer routing", () => {
  const { c, data, pricing } = fixture();
  data.ClientModels[0].Model = "gpt-6-luna"; pricing.catalog.rates[0].Model = "GPT-6 Luna";
  data.Billing = [{ Day: "2026-11-18", User: "u1", Model: "Fusion (Standard): GPT-6 Luna",
    CenterId: "none", UnitType: "ai-credits", Attribution: "API user filter" }];
  assert.equal(P.simulate(data, c, pricing, {}, { model: "GPT-6 Luna", center: "none" }).eligibleRows, 1);
  data.ClientModels[0].Model = "GPT6LUNA";
  assert.equal(P.simulate(data, c, pricing).eligibleRows, 0);
});
test("invalid mixes/cache/tier, failed prices and future/invalid timestamps cannot silently estimate", () => {
  const { c, data, pricing } = fixture();
  assert.equal(P.simulate(data, c, pricing, { cacheRead: .9, cacheWrite: .2 }).state, "invalid");
  c.mixes.recommended.weights = [{ model: "Fixture A", weight: .7 }];
  assert.equal(P.simulate(data, c, pricing, { mode: "recommended" }).state, "invalid");
  assert.equal(P.simulate(data, c, pricing, { tier: "Long context" }).eligibleRows, 0);
  pricing.state = "stale";
  assert.equal(P.simulate(data, c, pricing).baselineUSD, null);
  assert.equal(P.simulate(data, c, pricing, { allowStale: true }).state, "explicit-stale");
  pricing.catalog.asOf = "2999-01-01T00:00:00Z";
  assert.equal(P.simulate(data, c, pricing, { allowStale: true }).baselineUSD, null);
  pricing.catalog.asOf = new Date(Date.now() - 1000).toISOString();
  assert.equal(P.simulate(data, c, pricing, { valuationDay: "2026-02-31" }).baselineUSD, null);
});
test("promo rates expire at exclusive boundaries; unknown successors are not inferred", () => {
  const { pricing } = fixture();
  const r = pricing.catalog.rates[0];
  r.EffectiveTo = "2026-12-01";
  assert.equal(P.findRate(pricing.catalog, "Fixture A", "Default", "2026-12-01"), null);
  pricing.catalog.rates.push({ ...r, EffectiveFrom: "2026-12-01", EffectiveTo: null, InputUSD: 20 });
  assert.equal(P.findRate(pricing.catalog, "Fixture A", "Default", "2026-12-01").InputUSD, 20);
});
test("eligible Fusion with missing/invalid published promotion terms is ND, never an assumed zero discount", () => {
  const { c, data, pricing } = fixture();
  c.mixes["fusion-high"] = { overhead: 1.2, weights: [{ model: "Fixture B", weight: 1 }] };
  for (const fusion of [{ discount: null, effectiveTo: "2027-01-01" },
                        { discount: .3, effectiveTo: null }, { discount: .3, effectiveTo: "2026-02-31" },
                        { discount: 2, effectiveTo: "2027-01-01" }]) {
    pricing.catalog.fusion = fusion;
    assert.equal(P.simulate(data, c, pricing, { mode: "fusion-high", fusionPromotionEligible: true }).baselineUSD, null);
    assert.equal(P.simulate(data, c, pricing, { mode: "fusion-high", fusionPromotionEligible: true, replacement: 0 }).deltaUSD, 0);
  }
});
test("zero-weight unpriced destinations do not require tariffs; null weights/overhead remain invalid", () => {
  const { c, data, pricing } = fixture();
  c.mixes.recommended = { overhead: 1, weights: [{ model: "Fixture B", weight: 1 }, { model: "Unpriced example", weight: 0 }] };
  near(P.simulate(data, c, pricing, { mode: "recommended" }).targetUSD, 2.8);
  c.mixes.recommended.weights[1].weight = null;
  assert.equal(P.simulate(data, c, pricing, { mode: "recommended" }).state, "invalid");
  c.mixes.recommended.weights[1].weight = 0;
  c.mixes.recommended.overhead = null;
  assert.equal(P.simulate(data, c, pricing, { mode: "recommended" }).state, "invalid");
});

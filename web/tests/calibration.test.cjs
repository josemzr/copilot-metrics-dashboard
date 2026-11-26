const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../src/projections.js");
const base = require("../../projections/contract.json");
const oracle = require("../../projections/calibrated-golden.json");
const theoretical = require("../../projections/golden.json");
const near = (a, b) => assert.ok(typeof a === "number" && Math.abs(a - b) < 1e-8, `${a} != ${b}`);
function fixture() {
  const contract = structuredClone(base);
  contract.models.push(...theoretical.rates.map(row => ({ model: row.Model, aliases: [] })));
  contract.mixes["fusion-high"] = structuredClone(oracle.mix);
  return { contract, data: structuredClone(oracle.data),
    pricing: { state: "ready", catalog: { version: contract.version, creditsPerUSD: 100,
      asOf: new Date(Date.now() - 1000).toISOString(), rates: structuredClone(theoretical.rates),
      fusion: { discount: .3, effectiveTo: "2999-01-01" } } } };
}
test("eleven independent Billing-anchored golden cases preserve actual baseline and calibrate only requested models", () => {
  for (const example of oracle.cases) {
    const { contract, data, pricing } = fixture();
    if (example.sourceUSDOverride) data.Billing[0].grossAmount = example.sourceUSDOverride;
    const result = P.calibrate(data, contract, example.pricesUnavailable ? null : pricing, example.options, example.filters);
    near(result.baselineCredits, example.baselineCredits); near(result.targetCredits, example.scenarioCredits);
    near(result.baselineUSD, example.baselineUSD); near(result.targetUSD, example.scenarioUSD);
    assert.equal(result.reportedNetUSD, 0, "Net invoice is never scaled into hypothetical cash savings");
  }
});
test("multiple client and Billing rows aggregate exactly once at complete bucket grain, independent of row order", () => {
  const { contract, data, pricing } = fixture();
  data.Billing[0].grossQuantity = 60; data.Billing[0].grossAmount = .6;
  data.Billing.push({ ...data.Billing[0], grossQuantity: 40, grossAmount: .4 });
  data.ClientModels[0].PromptTokens = 500000; data.ClientModels[0].OutputTokens = 100000;
  data.ClientModels.push({ ...data.ClientModels[0] });
  const options = { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" };
  const first = P.calibrate(data, contract, pricing, options);
  near(first.baselineCredits, 140); near(first.targetCredits, 60);
  assert.equal(first.rows.find(row => row.Model === "Fixture A").TokenRows, 2);
  data.Billing.reverse(); data.ClientModels.reverse();
  near(P.calibrate(data, contract, pricing, options).targetCredits, 60);
});
test("unpriced or tokenless Billing remains actual when untouched; requested changes are explicit ND, never dropped", () => {
  const { contract, data, pricing } = fixture();
  data.Billing.push({ ...data.Billing[0], Model: "Unknown exact model", grossQuantity: 30, grossAmount: .3 });
  const noop = P.calibrate(data, contract, null);
  near(noop.baselineCredits, 170); near(noop.targetCredits, 170); near(noop.unprojectedCredits, 170);
  near(P.calibrate(data, contract, pricing).unprojectedCredits, 30);
  const options = { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" };
  near(P.calibrate(data, contract, pricing, options).targetCredits, 90);
  const all = P.calibrate(data, contract, pricing, { ...options, replaceSourceModel: "" });
  assert.equal(all.baselineCredits, 170); assert.equal(all.targetCredits, null);
  assert.equal(all.unresolvedChangeCredits, 30); near(all.partialTargetCredits, 60);
  near(P.calibrate(data, contract, pricing, options, { model: "Fixture A" }).targetCredits, 20);
  data.ClientModels = data.ClientModels.filter(row => row.Model !== "Fixture B");
  near(P.calibrate(data, contract, pricing, options).targetCredits, 90, "B keeps actual40 without tokens");
});
test("any missing/custom/ambiguous token row prevents partial bucket calibration but keeps actual baseline", () => {
  for (const mutate of [
    d => d.ClientModels.push({ ...d.ClientModels[0], PromptTokens: null }),
    d => d.ClientModels.push({ ...d.ClientModels[0], CustomModel: true }),
    d => d.Billing.push({ ...d.Billing[0], CenterId: "c1", grossQuantity: 20, grossAmount: .2 }),
  ]) {
    const { contract, data, pricing } = fixture(); mutate(data);
    const result = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" });
    assert.ok(result.baselineCredits >= 140); assert.equal(result.targetCredits, null);
    assert.ok(result.unresolvedChangeCredits >= 100);
  }
});
test("current memberships and residual Billing cannot create a token bucket; source/center filters use original Billing scope", () => {
  const { contract, data, pricing } = fixture();
  data.Billing[0].Attribution = "Center total minus available user detail";
  data.Users[0].IsResidual = true;
  data.Memberships = [{ CenterId: "none", ResourceName: "fixture-user" }];
  const result = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" });
  assert.equal(result.baselineCredits, 140); assert.equal(result.targetCredits, null);
  data.Billing[0].Attribution = "API user filter"; data.Users[0].IsResidual = false;
  near(P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B" }, { center: "none" }).targetCredits, 60);
  assert.equal(P.calibrate(data, contract, pricing, {}, { center: "c1" }).baselineCredits, 0);
});
test("bad live pricing and zero theoretical denominator never erase actual consumption", () => {
  for (const prices of [null, { state: "error" }, { state: "stale" }]) {
    const { contract, data } = fixture();
    const result = P.calibrate(data, contract, prices, { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" });
    assert.equal(result.baselineCredits, 140); assert.equal(result.targetCredits, null);
    assert.equal(result.partialTargetCredits, 40);
  }
  const { contract, data, pricing } = fixture();
  Object.assign(pricing.catalog.rates[0], { InputUSD: 0, CachedInputUSD: 0, CacheWriteUSD: 0, OutputUSD: 0 });
  const result = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" });
  assert.equal(result.targetCredits, null); assert.equal(result.baselineCredits, 140);
  assert.match(result.rows[0].Reason, /Zero modeled source denominator/);
  assert.equal(P.calibrate(data, contract, null).deltaCredits, 0);
});
test("known zero and fully covered empty Billing differ from missing Billing coverage or invalid assumptions", () => {
  const { contract, data, pricing } = fixture();
  data.Billing = [];
  assert.equal(P.calibrate(data, contract, null).targetCredits, 0);
  data.SourceCoverage[0].BillingAvailable = false;
  assert.equal(P.calibrate(data, contract, null).baselineCredits, null);
  const full = fixture();
  const invalid = P.calibrate(full.data, full.contract, full.pricing, { mode: "recommended",
    mixes: { recommended: { overhead: 1, weights: [{ model: "Fixture B", weight: null }] } } });
  assert.equal(invalid.baselineCredits, 140); assert.equal(invalid.targetCredits, null);
  full.data.ClientModels[0].PromptTokens = 0; full.data.ClientModels[0].OutputTokens = 0;
  full.data.Billing[0].grossQuantity = 0; full.data.Billing[0].grossAmount = 0;
  near(P.calibrate(full.data, full.contract, full.pricing, { mode: "target", targetModel: "Fixture B" }).targetCredits, 40);
});
test("blank replacement is invalid for a requested change, while numeric zero and unchanged preserve actual Billing", () => {
  const { contract, data, pricing } = fixture();
  const options = { mode: "target", targetModel: "Fixture B", replacement: null };
  const invalid = P.calibrate(data, contract, pricing, options);
  near(invalid.baselineCredits, 140); near(invalid.baselineUSD, 1.4);
  assert.equal(invalid.targetCredits, null); assert.equal(invalid.targetUSD, null);
  assert.equal(invalid.deltaCredits, null); assert.equal(invalid.deltaUSD, null);
  const zero = P.calibrate(data, contract, null, { ...options, replacement: 0 });
  near(zero.targetCredits, 140); near(zero.targetUSD, 1.4);
  const unchanged = P.calibrate(data, contract, null, { ...options, mode: "unchanged" });
  near(unchanged.targetCredits, 140); near(unchanged.targetUSD, 1.4);
});
test("zero reported consumption cannot calibrate a free source to a positive-price target; non-finite ratios are explicit failures", () => {
  const { contract, data, pricing } = fixture();
  data.Billing[0].grossQuantity = 0; data.Billing[0].grossAmount = 0;
  Object.assign(pricing.catalog.rates[0], { InputUSD: 0, CachedInputUSD: 0, CacheWriteUSD: 0, OutputUSD: 0 });
  const options = { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" };
  const free = P.calibrate(data, contract, pricing, options);
  assert.equal(free.baselineCredits, 40); assert.equal(free.targetCredits, null);
  assert.match(free.rows[0].Reason, /Zero modeled source denominator/);
  data.ClientModels[0].PromptTokens = 1e308;
  pricing.catalog.rates[0].InputUSD = 10;
  const overflow = P.calibrate(data, contract, pricing, options);
  assert.equal(overflow.state, "partial"); assert.equal(overflow.targetCredits, null);
  assert.match(overflow.rows[0].Reason, /non-finite/);
  data.Billing[0].grossQuantity = 1e308;
  data.Billing.push({ ...data.Billing[0] });
  const actualOverflow = P.calibrate(data, contract, null);
  assert.equal(actualOverflow.baselineCredits, null);
  assert.notEqual(actualOverflow.state, "ready");
});
test("identity shortcut is not used when a target volume factor changes workload; credits and USD are independent", () => {
  const { contract, data, pricing } = fixture();
  data.Billing[0].grossAmount = 1.3;
  const result = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture A",
    replaceSourceModel: "Fixture A", targetVolumeFactor: 2 });
  near(result.targetCredits, 240); near(result.targetUSD, 3);
  assert.equal(P.calibrate(data, contract, null, { mode: "target", targetModel: "Fixture A",
    replaceSourceModel: "Fixture A", targetVolumeFactor: 2 }).targetCredits, null);
  data.Billing[0].grossAmount = 7; data.Billing[1].grossAmount = 3;
  const independent = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" });
  near(independent.baselineUSD, 10); near(independent.targetUSD, 4.4); near(independent.targetCredits, 60);
  near(independent.deltaUSDPct, -.56);
  near(independent.deltaPct, -80 / 140);
});
test("many complete buckets reuse one usage index and shared tariff kernel instead of rebuilding the dataset per bucket", () => {
  const { contract, data, pricing } = fixture();
  const bills = [], clients = [], users = [];
  for (let i = 0; i < 1000; i++) {
    const user = `synthetic-${i}`;
    users.push({ User: user, IsResidual: false });
    bills.push(...data.Billing.map(row => ({ ...row, User: user })));
    clients.push(...data.ClientModels.map(row => ({ ...row, User: user })));
  }
  data.ClientModels = clients; data.Users = users;
  let traversals = 0;
  const iterable = new Proxy(bills, { get(target, property) {
    if (property === Symbol.iterator) return function* () { traversals++; yield* target; };
    return Reflect.get(target, property);
  } });
  data.Billing = iterable;
  const result = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" });
  near(result.baselineCredits, 140000); near(result.targetCredits, 60000);
  assert.equal(result.rows.length, 2000);
  assert.equal(traversals, 2, "Exactly one Billing bridge pass and one bucket pass; no per-bucket rescan");
});
test("case-variant unknown Billing aliases retain independent actual buckets and collation-safe selection keys", () => {
  const { contract, data, pricing } = fixture();
  contract.models.find(row => row.model === "Fixture A").aliases.push("fixture-a");
  data.ClientModels[0].Model = "fixture-a";
  data.Billing.push({ ...data.Billing[0], Model: "FIXTURE A", grossQuantity: 30, grossAmount: .3 });
  const buckets = P.billingBuckets(data, contract);
  const keys = buckets.map(row => row.SourceKey.toLowerCase());
  const labels = buckets.map(row => row.SourceLabel.toLowerCase());
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(new Set(labels).size, labels.length);
  const unknown = buckets.find(row => row.SourceModel === "FIXTURE A");
  assert.equal(unknown.Model, null);
  assert.equal(P.calibrate(data, contract, null).baselineCredits, 170);
  const result = P.calibrate(data, contract, pricing, { mode: "target", targetModel: "Fixture B", replaceSourceKey: unknown.SourceKey });
  assert.equal(result.baselineCredits, 170); assert.equal(result.targetCredits, null);
  assert.equal(result.unresolvedChangeCredits, 30);
});
test("missing Billing amount pairs give ND totals but only explicit partial-known sums, never drop an unresolved bucket", () => {
  const { contract, data, pricing } = fixture();
  data.Billing[0].grossAmount = null;
  const options = { mode: "target", targetModel: "Fixture B", replaceSourceModel: "Fixture A" };
  const result = P.calibrate(data, contract, pricing, options);
  assert.equal(result.baselineCredits, null); assert.equal(result.baselineUSD, null);
  assert.equal(result.targetCredits, null); assert.equal(result.targetUSD, null);
  near(result.partialReportedCredits, 140); near(result.partialReportedUSD, .4);
  near(result.partialTargetCredits, 40); near(result.partialTargetUSD, .4);
  assert.equal(result.unresolvedChangeCredits, 100);
  data.Billing[0].grossAmount = 1; data.Billing[0].grossQuantity = null;
  const missingCredits = P.calibrate(data, contract, pricing, options);
  assert.equal(missingCredits.baselineCredits, null); assert.equal(missingCredits.baselineUSD, null);
  assert.equal(missingCredits.targetCredits, null);
  near(missingCredits.partialReportedCredits, 40); near(missingCredits.partialReportedUSD, 1.4);
  assert.equal(missingCredits.unresolvedChangeCredits, null, "Unknown credit quantity is not reported as zero");
  assert.equal(missingCredits.unresolvedRows, 1);
});

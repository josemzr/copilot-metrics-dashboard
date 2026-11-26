const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const P = require("../src/projections.js");
const contract = require("../../projections/contract.json");
const base = process.env.BASE_URL || "http://127.0.0.1:8080";
const root = path.resolve(__dirname, "../..");
const run = spawnSync(process.env.PYTHON || "python3", ["-c",
  "import sys,json;from pathlib import Path;sys.path.insert(0,'scripts');from pricing import parse_catalog;print(json.dumps(parse_catalog(Path('projections/pricing-fixture.md').read_text(),Path('projections/fusion-fixture.md').read_text())))"],
{ cwd: root, encoding: "utf8" });
assert.equal(run.status, 0, run.stderr);
const catalog = JSON.parse(run.stdout);
catalog.asOf = new Date(Date.now() - 1000).toISOString();
let failed = false, calls = 0;
const pricing = () => ({ state: failed ? "stale" : "ready", lastChecked: new Date().toISOString(),
  lastError: failed ? "Official pricing fixture unavailable" : null, catalog });
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage(), errors = [], external = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("request", r => { if (!r.url().startsWith(base) && !/^(data:|blob:)/.test(r.url())) external.push(r.url()); });
  await page.route("**/api/pricing", route => { calls++; return route.fulfill({ json: pricing() }); });
  try {
    await page.goto(base);
    await page.waitForSelector("#panel .kpi");
    const data = await (await page.request.get(base + "/api/dataset?mode=SAMPLE")).json();
    assert.equal(calls, 0);
    await page.locator("#tab-projections").click();
    await page.waitForFunction(() => document.getElementById("pricing-state").textContent.includes("Prices: ready"));
    assert.equal(calls, 1);
    await page.locator("#p-mode").selectOption("target");
    await page.locator("#p-target").selectOption("GPT-6.2 Sol");
    await page.locator("#p-replacement").fill("50"); await page.locator("#p-replacement").dispatchEvent("change");
    await page.locator("#p-read").fill("60"); await page.locator("#p-read").dispatchEvent("change");
    await page.locator("#p-write").fill("20"); await page.locator("#p-write").dispatchEvent("change");
    const expected = P.calibrate(data, contract, pricing(), { mode: "target", targetModel: "GPT-6.2 Sol", replacement: .5, cacheRead: .6, cacheWrite: .2 });
    const format = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });
    const fmt = value => value === null ? "N/D" : format.format(value);
    assert.equal(await page.locator(".kpi").filter({ hasText: "Estimated calibrated gross USD" }).locator(".kpi-number").textContent(), fmt(expected.targetUSD));
    assert.equal(await page.locator(".kpi").filter({ hasText: "Reported baseline AI credits" }).locator(".kpi-number").textContent(), fmt(expected.baselineCredits));
    await page.locator("#country").selectOption("Region_A");
    await page.locator("#center").selectOption(data.Centers.find(c => c.Country === "Region_A").CenterId);
    await page.locator("#model").selectOption("Model Alpha");
    await page.locator("#p-user").selectOption("demo-user-01");
    await page.locator("#start").fill("2026-11-02"); await page.locator("#start").dispatchEvent("change");
    await page.locator("#end").fill("2026-11-08"); await page.locator("#end").dispatchEvent("change");
    assert.equal(calls, 1, "Filters must not refetch tariffs");
    const scoped = P.calibrate(data, contract, pricing(), {
      mode: "target", targetModel: "GPT-6.2 Sol", replacement: .5, cacheRead: .6, cacheWrite: .2 },
    { country: "Region_A", center: data.Centers.find(c => c.Country === "Region_A").CenterId,
      model: "Model Alpha", user: "demo-user-01", start: "2026-11-02", end: "2026-11-08" });
    assert.equal(await page.getByRole("table", { name: "Complete Billing buckets and calibration coverage", exact: true }).locator("tbody tr").count(),
      scoped.rows.length);
    assert.equal(await page.locator(".kpi").filter({ hasText: "Estimated calibrated AI credits" }).locator(".kpi-number").textContent(), fmt(scoped.targetCredits));
    await page.locator("#reset").click();
    await page.locator("#p-replace-source").selectOption({ label: "GPT-6 Luna" });
    const selected = P.calibrate(data, contract, pricing(), {
      mode: "target", targetModel: "GPT-6.2 Sol", replaceSourceModel: "GPT-6 Luna",
      replacement: .5, cacheRead: .6, cacheWrite: .2 }, { user: "demo-user-01" });
    assert.equal(await page.locator(".kpi").filter({ hasText: "Estimated calibrated AI credits" }).locator(".kpi-number").textContent(), fmt(selected.targetCredits));
    const actualBeforeFailure = await page.locator(".kpi").filter({ hasText: "Reported baseline AI credits" }).locator(".kpi-number").textContent();
    await page.locator("#p-mode").selectOption("fusion-high");
    await page.locator("#p-promo").check();
    assert.equal(calls, 1);
    failed = true;
    await page.locator("#pricing-refresh").click();
    await page.locator("#pricing-state").filter({ hasText: "Prices: stale" }).waitFor();
    assert.equal(await page.locator(".kpi").filter({ hasText: "Estimated calibrated AI credits" }).locator(".kpi-number").textContent(), "N/D");
    assert.equal(await page.locator(".kpi").filter({ hasText: "Reported baseline AI credits" }).locator(".kpi-number").textContent(), actualBeforeFailure);
    await page.locator("#p-stale").check();
    assert.notEqual(await page.locator(".kpi").filter({ hasText: "Estimated calibrated AI credits" }).locator(".kpi-number").textContent(), "N/D");
    await page.locator("#p-read").fill("90"); await page.locator("#p-read").dispatchEvent("change");
    assert.equal(await page.locator(".kpi").filter({ hasText: "Estimated calibrated AI credits" }).locator(".kpi-number").textContent(), "N/D");
    await page.locator("#p-mode").selectOption("unchanged");
    assert.equal(await page.locator(".kpi").filter({ hasText: "Estimated calibrated AI credits" }).locator(".kpi-number").textContent(), actualBeforeFailure);
    await page.locator("#tab-overview").click();
    await page.waitForSelector("#panel .kpi");
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    console.log("PASS: Billing anchored baseline/no-op, separate replacement/source scope, calibrated controls, explicit stale opt-in, partialND without dropping actuals, no per-filter requests, original pages usable");
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });

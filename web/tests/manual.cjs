const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const D = require("../src/core.js");
const base = process.env.BASE_URL || "http://127.0.0.1:8081";

(async () => {
  const file = process.env.DATASET_PATH;
  assert.ok(file, "DATASET_PATH must identify a synthetic dataset produced by the kit");
  const bytes = await fs.readFile(file), data = D.parseDataset(bytes.toString());
  const expected = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(D.summarize(data).totals.Credits);
  const browser = await chromium.launch();
  const page = await browser.newPage(), requests = [], errors = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => requests.push(request.url()));
  await page.route("**/api/**", route => route.abort());
  await page.clock.install();
  try {
    await page.goto(base);
    await page.locator("#collector-status").filter({ hasText: "Manual mode:" }).waitFor();
    assert.equal((await page.request.get(base + "/api/status")).status(), 200);
    assert.equal((await page.request.get(base + "/api/dataset?mode=REAL")).status(), 503);
    const initialAPI = requests.filter(url => url.includes("/api/")).length;
    await page.locator("#file-input").setInputFiles(file);
    await page.locator("#notice").filter({ hasText: "loaded in memory only" }).waitFor();
    assert.equal(await page.locator("#mode-badge").textContent(), data.Info[0].Mode);
    assert.equal(await page.locator(".kpi").filter({ hasText: "Gross AI credits" }).locator(".kpi-number").textContent(), expected);
    await page.locator("#refresh").click();
    await page.locator("#notice").filter({ hasText: "JSON re-read locally" }).waitFor();
    await page.clock.fastForward(65000);
    assert.equal(requests.filter(url => url.includes("/api/")).length, initialAPI);
    const chooser = page.waitForEvent("filechooser");
    await page.locator("#real-mode").click();
    await (await chooser).setFiles(file);
    await page.locator("#notice").filter({ hasText: "loaded in memory only" }).waitFor();
    assert.equal(requests.filter(url => url.includes("/api/")).length, initialAPI);
    assert.ok(requests.every(url => url.startsWith(base) || /^(blob:|data:)/.test(url)));
    assert.deepEqual(errors, []);
    console.log("PASS: kit JSON imported, totals match, manual Refresh/file selection only; no polling, uploads or GitHub traffic");
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });

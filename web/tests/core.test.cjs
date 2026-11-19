const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const D = require("../src/core.js");

function fixture() {
  const days = D.daysBetween("2026-11-02", "2026-11-08");
  return D.validateDataset({
    Info: [{ Mode: "SAMPLE", Label: "Synthetic fixture", AsOf: "2026-11-09T00:00:00Z", StartDay: days[0], EndDay: days.at(-1), LicenseRosterStatus: "Complete snapshot, not historical" }],
    Centers: [{ CenterId: "es", Center: "Center A", Country: "Region A" }, { CenterId: "uk", Center: "Center B", Country: "UK" }],
    Dates: days.map(Day => ({ Day })),
    Users: [{ User: "u1" }, { User: "u2" }, { User: "residual", IsResidual: true }],
    Billing: [
      { Day: days[0], CenterId: "es", User: "u1", Model: "Model One", UnitType: "ai-credits", grossQuantity: 100 },
      { Day: days[0], CenterId: "es", User: "residual", Model: "Model One", UnitType: "ai-credits", grossQuantity: 20 },
      { Day: days[0], CenterId: "es", User: "u1", Model: "Model One", UnitType: "requests", grossQuantity: 999 },
      { Day: days[1], CenterId: "uk", User: "u2", Model: "Model Two", UnitType: "ai-credits", grossQuantity: 30 }
    ],
    Metrics: days.flatMap((Day, i) => [
      { Day, CenterId: "es", User: "u1", ActivityObserved: i < 3, Interactions: i < 3 ? 5 : 0, Generations: i < 3 ? 10 : 0, Acceptances: i < 3 ? 4 : 0, LinesAdded: i < 3 ? 20 : 0, LinesDeleted: i < 3 ? 6 : 0 },
      { Day, CenterId: "uk", User: "u2", ActivityObserved: false, Interactions: 0, Generations: 0, Acceptances: 0, LinesAdded: 0, LinesDeleted: 0 }
    ]),
    ModelFeatures: [{ Day: days[0], CenterId: "es", User: "u1", Model: "Model One", Feature: "chat", Generations: 7, Interactions: 4, Acceptances: 2 }],
    ClientModels: [{ Day: days[0], CenterId: "es", User: "u1", Model: "Model One", Requests: 50, PromptTokens: 200, OutputTokens: 100 }],
    Features: [{ Day: days[0], CenterId: "es", User: "u1", Feature: "code_completion", Generations: 8, Acceptances: 3, LinesAdded: 12, LinesSuggested: 48 }],
    Licenses: [{ User: "u1", CenterId: "es", AsOf: "2026-11-09T00:00:00Z" }, { User: "u2", CenterId: "uk", AsOf: "2026-11-09T00:00:00Z" }],
    LicensedDays: days.flatMap(Day => [{ Day, User: "u1", CenterId: "es" }, { Day, User: "u2", CenterId: "uk" }]),
    LicenseCoverage: days.map(Day => ({ Day, HistoricalRosterComplete: true })),
    Pools: [{ CenterId: "es", PoolEnabled: true, TargetRaw: 100, CurrentRaw: 80 }],
    Budgets: [{ CenterId: "es", BudgetAmount: 100, ConsumedAmount: 40 }]
  });
}

test("credits use only ai-credits grossQuantity and retain residual exactly once", () => {
  const s = D.summarize(fixture());
  assert.equal(s.totals.Credits, 150);
  assert.equal(s.residualCredits, 20);
  assert.equal(s.attributedCredits, 130);
  assert.equal(s.excludedBillingRows, 1);
  assert.equal(s.userRows.some(r => r.User === "residual"), false);
  assert.equal(s.activeCount, 1);
});
test("usage facts never add Metrics + ModelFeatures + ClientModels", () => {
  const s = D.summarize(fixture());
  assert.equal(s.totals.Generations, 30);
  assert.equal(s.totals.Interactions, 15);
  assert.equal(s.totals.Requests, 50);
  assert.equal(s.totals.Credits, 150);
});
test("country and center filters use facts, not present-day memberships or logins", () => {
  const d = fixture();
  d.Memberships = [{ CenterId: "uk", ResourceName: "u1", ResourceType: "User" }];
  const s = D.summarize(d, { country: "Region A" });
  assert.equal(s.totals.Credits, 120);
  assert.equal(s.totals.Generations, 30);
  assert.equal(s.licenseCount, 1);
  assert.equal(D.summarize(d, { country: "UK" }).totals.Generations, 0);
});
test("model filter uses the modeled grained facts and leaves snapshot totals alone", () => {
  const s = D.summarize(fixture(), { model: "Model One" });
  assert.equal(s.totals.Credits, 120);
  assert.equal(s.totals.Generations, 7);
  assert.equal(s.totals.LinesAdded, null);
  assert.equal(s.licenseCount, 2);
  assert.equal(s.pools.length, 1);
  assert.equal(s.budgets.length, 1);
  assert.equal(s.adoption, null);
  assert.equal(s.inactive, null);
});
test("complete historical roster and known activity enable adoption, not current licenses", () => {
  const d = fixture(), s = D.summarize(d);
  assert.equal(s.adoption, .5);
  assert.equal(s.inactive, 1);
  assert.equal(s.activityComplete, true);
  d.Licenses.push({ User: "snapshot-only", CenterId: "es" });
  const changed = D.summarize(d);
  assert.equal(changed.licenseCount, 3);
  assert.equal(changed.adoption, .5);
  assert.equal(changed.inactive, 1);
});
test("unknown licensed user-day activity disables adoption even with a complete historical roster", () => {
  const d = fixture();
  d.Metrics = d.Metrics.filter(r => !(r.User === "u2" && r.Day === "2026-11-08"));
  const s = D.summarize(d);
  assert.equal(s.adoption, null);
  assert.equal(s.inactive, null);
  assert.equal(s.licenseCount, 2);
});
test("one missing historical coverage day disables historical percentages", () => {
  const d = fixture();
  d.LicenseCoverage[3].HistoricalRosterComplete = false;
  assert.equal(D.summarize(d).adoption, null);
  assert.equal(D.summarize(d).inactive, null);
});
test("missing and null counters stay unknown, while documented zeros remain zero", () => {
  const d = fixture();
  d.Metrics[0].LinesDeleted = null;
  const s = D.summarize(d);
  assert.equal(s.totals.LinesDeleted, null);
  assert.equal(s.totals.NetLines, null);
  assert.equal(s.totals.EditedLines, null);
  assert.equal(D.sum([{ n: 0 }], "n"), 0);
  assert.equal(D.sum([], "n"), null);
  assert.equal(D.sum([{ n: 1 }, {}], "n"), null);
});
test("inline lines and acceptance ratios use matching feature scope", () => {
  const s = D.summarize(fixture());
  assert.equal(s.totals.LinesAccepted, 12);
  assert.equal(s.lineAcceptanceRate, .25);
  assert.equal(s.inlineAcceptanceRate, 3 / 8);
  assert.equal(s.acceptanceRate, .4);
  assert.equal(s.totals.NetLines, 42);
  assert.equal(s.totals.EditedLines, 78);
});
test("recurrence needs at least 3 distinct days in a fully selected ISO week", () => {
  const s = D.summarize(fixture());
  assert.equal(s.recurring, 1);
  assert.equal(s.recurringEligible, 1);
  assert.equal(s.activeInCompleteWeeks, 1);
  assert.deepEqual(s.weeks, ["2026-11-02"]);
  const partial = D.summarize(fixture(), { end: "2026-11-07" });
  assert.equal(partial.recurring, null);
  assert.equal(partial.recurringEligible, null);
});
test("recurrence denominator excludes users active only in a partial week", () => {
  const d = fixture();
  d.Info[0].StartDay = "2026-11-01";
  d.Metrics.push({ Day: "2026-11-01", User: "partial-only", CenterId: "es", ActivityObserved: true });
  const s = D.summarize(d);
  assert.equal(s.activeCount, 2);
  assert.equal(s.recurringEligible, 1);
});
test("DAU and active-day means include zero observed days", () => {
  const s = D.summarize(fixture());
  assert.equal(s.avgDAU, 3 / 7);
  assert.equal(s.avgActiveDays, 3);
  assert.equal(s.daily.at(-1).ActiveUsers, 0);
  assert.equal(s.peak.ActiveUsers, 1);
});
test("unknown signals never become inactive zero users", () => {
  const d = fixture();
  d.Metrics = [{ Day: "2026-11-02", User: "u1", CenterId: "es", ActivityObserved: null, Interactions: null, Generations: null }];
  d.ModelFeatures = []; d.Features = []; d.ClientModels = [];
  const s = D.summarize(d);
  assert.equal(s.activeCount, null);
  assert.equal(s.avgDAU, null);
  assert.equal(s.daily[0].ActiveUsers, null);
  assert.equal(s.userRows.find(r => r.User === "u1").ActiveDays, null);
});
test("per-source coverage allows fresh billing without fabricating missing Metrics or full-period rates", () => {
  const d = fixture();
  d.SourceCoverage = d.Dates.map(({ Day }) => ({ Day, MetricsAvailable: Day !== "2026-11-08", BillingAvailable: true,
    MetricsStatus: Day === "2026-11-08" ? "not_yet_available" : "available", BillingStatus: "available" }));
  d.Info[0].MetricsStartDay = "2026-11-02"; d.Info[0].MetricsEndDay = "2026-11-07";
  d.Info[0].BillingStartDay = "2026-11-02"; d.Info[0].BillingEndDay = "2026-11-08";
  d.Metrics = d.Metrics.filter(r => r.Day !== "2026-11-08");
  d.Billing.push({ Day: "2026-11-08", CenterId: "es", User: "u1", Model: "Model One", UnitType: "ai-credits", grossQuantity: 17 });
  const s = D.summarize(d);
  assert.equal(s.totals.Credits, 167);
  assert.equal(s.totals.Generations, 30);
  assert.equal(s.activeCount, 1);
  assert.equal(s.daily.at(-1).Credits, 17);
  assert.equal(s.daily.at(-1).ActiveUsers, null);
  assert.equal(s.daily.at(-1).Generations, null);
  for (const key of ["avgDAU", "peak", "avgActiveDays", "recurring", "recurringEligible", "adoption", "inactive"]) assert.equal(s[key], null, key);
  assert.deepEqual(s.metricsMissingDays, ["2026-11-08"]);
  const covered = D.summarize(d, { end: "2026-11-04" });
  assert.equal(covered.avgDAU, 1);
  assert.equal(covered.adoption, .5);
});
test("billing-only import keeps activity unknown, never inactive or zero", () => {
  const d = fixture();
  for (const table of ["Metrics", "ModelFeatures", "Features", "ClientModels", "CLI"]) d[table] = [];
  d.Info[0].MetricsStartDay = null; d.Info[0].MetricsEndDay = null;
  d.Info[0].MissingMetricsDays = 7;
  d.SourceCoverage = d.Dates.map(({ Day }) => ({ Day, MetricsAvailable: false, BillingAvailable: true }));
  const s = D.summarize(D.validateDataset(d));
  assert.equal(s.totals.Credits, 150);
  for (const key of ["activeCount", "avgDAU", "peak", "adoption", "inactive", "recurring", "chatUsers", "agentUsers"]) assert.equal(s[key], null, key);
  assert.ok(s.daily.every(row => row.ActiveUsers === null && row.Generations === null));
  assert.ok(s.userRows.every(row => row.Status === "No signal" && row.ActiveDays === null));
});
test("recurrence only requires coverage inside fully selected weeks, not a trailing partial week", () => {
  const d = fixture();
  d.Info[0].EndDay = "2026-11-09";
  d.SourceCoverage = D.daysBetween("2026-11-02", "2026-11-09").map(Day => ({ Day, MetricsAvailable: Day !== "2026-11-09", BillingAvailable: true }));
  const s = D.summarize(d);
  assert.equal(s.recurring, 1);
  assert.equal(s.recurringEligible, 1);
  assert.equal(s.avgDAU, null);
  assert.equal(s.adoption, null);
});
test("CLI/client positive requests count activity but do not inflate generation events", () => {
  const d = fixture();
  d.CLI = [{ Day: "2026-11-02", User: "u2", CenterId: "uk", Requests: 2, Sessions: 1, Prompts: 1 }];
  const s = D.summarize(d);
  assert.equal(s.activeCount, 2);
  assert.equal(s.totals.Generations, 30);
  assert.equal(s.totals.CLIRequests, 2);
  assert.equal(s.totals.Requests, 50);
});
test("explicit chat/agent flags take precedence over feature-derived fallback at user-day grain", () => {
  const d = fixture();
  d.Metrics[0].UsedChat = false;
  assert.equal(D.summarize(d).chatUsers, 0);
  delete d.Metrics[0].UsedChat;
  assert.equal(D.summarize(d).chatUsers, 1);
  d.Metrics[0].UsedChat = true;
  d.Features = [];
  d.ModelFeatures = [];
  assert.equal(D.summarize(d).chatUsers, 1);
});
test("14-day blocks anchor to selection start and use direct billing model values", () => {
  const d = fixture();
  d.Info[0].EndDay = "2026-11-20";
  d.Billing.push({ Day: "2026-11-16", User: "u1", CenterId: "es", Model: "Model One", UnitType: "ai-credits", grossQuantity: 77 });
  const s = D.summarize(d);
  assert.deepEqual(s.blocks.map(b => [b.start, b.end]), [["2026-11-02", "2026-11-15"], ["2026-11-16", "2026-11-20"]]);
  assert.equal(s.blocks[0].values.find(v => v.Model === "Model One").Credits, 120);
  assert.equal(s.blocks[1].values.find(v => v.Model === "Model One").Credits, 77);
});
test("model identity preserves case, spaces and punctuation with no heuristic cross-source aliases", () => {
  const d = fixture();
  d.Billing[0].Model = "gpt-5.6-sol";
  d.Billing[1].Model = "gpt56sol";
  d.ModelFeatures[0].Model = "GPT-5.6-SOL";
  d.ClientModels[0].Model = "gpt 5.6 sol";
  assert.notEqual(D.modelKey("gpt-5.6-sol"), D.modelKey("gpt56sol"));
  const s = D.summarize(d, { model: "gpt-5.6-sol" });
  assert.equal(s.totals.Credits, 100);
  assert.equal(s.totals.Generations, null);
  assert.equal(s.totals.Requests, null);
  const all = D.summarize(d).modelRows;
  for (const name of ["gpt-5.6-sol", "gpt56sol", "GPT-5.6-SOL", "gpt 5.6 sol"]) assert.ok(all.some(row => row.Model === name));
});
test("search is case-insensitive and export guards CSV formula injection", () => {
  assert.equal(D.searchRows([{ User: "Test", Credits: 8 }, { User: "Another" }], "test").length, 1);
  const csv = D.toCSV([{ User: "=HYPERLINK(\"bad\")", value: -2 }, { User: "\t +SUM(1,2)", value: null }], [{ key: "User", label: "User" }, { key: "value", label: "Value" }], { Mode: "SAMPLE" });
  assert.match(csv, /'=/);
  assert.match(csv, /'\t \+SUM/);
  assert.match(csv, /"-2"/);
  assert.match(csv, /"SAMPLE"/);
  assert.ok(csv.startsWith("\uFEFF"));
});
test("empty filters give no facts, no invented zeros, but retain relevant snapshot semantics", () => {
  const s = D.summarize(fixture(), { start: "2026-12-01", end: "2026-12-02" });
  assert.equal(s.empty, true);
  assert.equal(s.totals.Credits, null);
  assert.equal(s.activeCount, null);
  assert.equal(s.licenseCount, 2);
  assert.equal(s.pools.length, 1);
});
test("schema validation rejects malformed dates, booleans, numeric strings and prototype keys", () => {
  for (const change of [
    d => d.Metrics[0].Generations = "8",
    d => d.Metrics[0].UsedChat = "false",
    d => d.Metrics[0].Day = "2026-02-31",
    d => d.Info[0].AsOf = "tomorrow",
    d => d.Licenses[0].AsOf = 21,
    d => d.Billing[0].Model = 100
  ]) {
    const d = fixture(); change(d);
    assert.throws(() => D.validateDataset(d));
  }
  const text = JSON.stringify(fixture()).replace('"User":"u1"', '"User":"u1","__proto__":"bad"');
  assert.throws(() => D.parseDataset(text), /allowed/);
  assert.throws(() => D.parseDataset("{"), /valid JSON/);
});
test("license cancellation preserves the nullable ISO date returned by the real roster", () => {
  const d = fixture();
  d.Licenses[0].PendingCancellation = "2026-11-30";
  d.Licenses[1].PendingCancellation = null;
  assert.equal(D.validateDataset(d).Licenses[0].PendingCancellation, "2026-11-30");
  assert.equal(D.summarize(D.validateDataset(d)).licenseCount, 2);
  d.Licenses[0].PendingCancellation = "2026-11-31";
  assert.throws(() => D.validateDataset(d), /PendingCancellation/);
  d.Licenses[0].PendingCancellation = 1;
  assert.throws(() => D.validateDataset(d), /PendingCancellation/);
});
test("old arrays-only pipeline contract remains supported without fabricating a roster", () => {
  const d = fixture();
  for (const table of ["Licenses", "LicensedDays", "LicenseCoverage", "Features", "CLI"]) delete d[table];
  delete d.Info[0].LicenseRosterStatus;
  const s = D.summarize(D.validateDataset(d));
  assert.equal(s.licenseCount, null);
  assert.equal(s.adoption, null);
  assert.equal(s.totals.LinesAccepted, null);
  assert.equal(s.totals.Credits, 150);
});
test("current sample builds offline with no remote assets or REAL data", () => {
  const web = path.resolve(__dirname, "..");
  const run = spawnSync("python3", [path.join(web, "build.py")], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr);
  const html = fs.readFileSync(path.join(web, "dist/index.html"), "utf8");
  assert.doesNotMatch(html, /<(?:script|link)[^>]+(?:src|href)=["']https?:/);
  assert.match(html, /connect-src 'self'/);
  assert.match(html, /"Mode":"SAMPLE"/);
  assert.doesNotMatch(html, /"Mode":"REAL"/);
  assert.doesNotMatch(html, /__DATASET_JSON__|\/\*__CORE__\*\//);
});
test("default build refuses a REAL dataset rather than leaking it into dist", () => {
  const web = path.resolve(__dirname, "..");
  const run = spawnSync("python3", [path.join(web, "build.py"), "--dataset", path.resolve(web, "../data/real/dataset.json")], { encoding: "utf8" });
  assert.notEqual(run.status, 0);
  assert.match(run.stderr, /REAL requires/);
});

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CopilotData = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const TABLES = ["Info", "Centers", "Dates", "Users", "Models", "Billing", "Metrics",
    "ModelFeatures", "ClientModels", "IDEs", "Languages", "Pools", "Budgets", "Memberships",
    "Features", "Licenses", "LicensedDays", "LicenseCoverage", "CLI", "UserAttributes", "SourceCoverage"];
  const MAX_BYTES = 16 * 1024 * 1024;
  const MAX_ROWS = 150000;
  const DAY_MS = 86400000;
  const COUNTERS = ["Interactions", "Generations", "Acceptances", "LinesAdded",
    "LinesDeleted", "LinesSuggested", "LinesSuggestedDelete", "TelemetryCredits",
    "Requests", "Prompts", "Sessions", "PromptTokens", "OutputTokens",
    "RequirementsMet", "RequirementsUnmet", "RequirementsUnknown", "grossQuantity",
    "grossAmount", "discountQuantity", "discountAmount", "netQuantity", "netAmount", "PricePerUnit", "MissingMetricsDays"];
  const USED = ["UsedChat", "UsedAgent", "UsedCLI", "UsedCopilotApp", "UsedCloudAgent",
    "UsedCodeReviewActive", "UsedVSCodeAgent", "UsedLocalBYOK"];
  const FORBIDDEN = new Set(["__proto__", "constructor", "prototype"]);
  const TEXT_FIELDS = new Set(["User", "CenterId", "Center", "Country", "State", "Model", "Feature", "Client", "IDE", "Language",
    "Mode", "Label", "Coverage", "Enterprise", "SKU", "Product", "UnitType", "Attribution", "UnitStatus", "Scope",
    "Entity", "ProductSKU", "BudgetId", "BudgetType", "Plan", "Organization", "SelectionMode", "ResourceType",
    "ResourceName", "LicenseRosterStatus", "HistoricalLicenseCoverage", "Stack", "ClassificationSource",
    "MetricsStatus", "BillingStatus", "MetricsCoverageStatus"]);
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const num = v => typeof v === "number" && Number.isFinite(v);
  const dayTime = d => Date.parse(`${d}T00:00:00Z`);
  function isDay(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const time = dayTime(value);
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
  }
  function daysBetween(start, end) {
    if (!isDay(start) || !isDay(end) || start > end) return [];
    const count = Math.round((dayTime(end) - dayTime(start)) / DAY_MS) + 1;
    if (count > 3660) throw new Error("The date range cannot exceed ten years.");
    return Array.from({ length: count }, (_, i) => new Date(dayTime(start) + i * DAY_MS).toISOString().slice(0, 10));
  }
  function regionLabel(center) {
    if (center.State === "virtual" || ["none", "unattributed-history", "unattributed-snapshot"].includes(center.CenterId)) return "No region";
    return center.Center;
  }
  function validateDataset(input) {
    if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Expected a dataset JSON object.");
    for (const required of ["Info", "Centers", "Dates", "Users", "Billing", "Metrics"]) {
      if (!Array.isArray(input[required])) throw new Error(`Missing table ${required} (array).`);
    }
    let rows = 0;
    const data = {};
    for (const table of TABLES) {
      if (own(input, table) && !Array.isArray(input[table])) throw new Error(`${table} must be an array.`);
      data[table] = input[table] || [];
      rows += data[table].length;
      if (rows > MAX_ROWS) throw new Error(`Limit of ${MAX_ROWS.toLocaleString("en-US")} rows exceeded.`);
      for (const [index, row] of data[table].entries()) {
        if (!row || typeof row !== "object" || Array.isArray(row)) throw new Error(`${table}[${index}] is not a record.`);
        for (const [key, value] of Object.entries(row)) {
          if (FORBIDDEN.has(key)) throw new Error("JSON key not allowed.");
          if (value !== null && !["string", "number", "boolean"].includes(typeof value)) throw new Error(`${table}.${key}: only scalar values or null are allowed.`);
          if (typeof value === "string" && value.length > 8192) throw new Error(`${table}.${key}: text is too long.`);
          if (typeof value === "number" && !Number.isFinite(value)) throw new Error(`${table}.${key}: non-finite number.`);
          if (TEXT_FIELDS.has(key) && value !== null && typeof value !== "string") throw new Error(`${table}.${key}: text or null required.`);
          if (["AsOf", "LicenseSnapshotAsOf", "ClassificationAsOf", "LastActivityAt"].includes(key) && value !== null &&
              (typeof value !== "string" || !Number.isFinite(Date.parse(value)))) throw new Error(`${table}.${key}: invalid timestamp.`);
          if (COUNTERS.includes(key) && value !== null && (!num(value) || value < 0)) throw new Error(`${table}.${key}: non-negative counter or null required.`);
          if ((key.startsWith("Used") || ["ActivityObserved", "TelemetryPresent", "IsResidual", "HistoricalRosterComplete", "PoolEnabled", "CustomModel", "HardStop", "MetricsAvailable", "BillingAvailable"].includes(key)) &&
              value !== null && typeof value !== "boolean") throw new Error(`${table}.${key}: boolean or null required.`);
          if (key === "PendingCancellation" && value !== null && typeof value !== "boolean" && !isDay(value)) {
            throw new Error(`${table}.${key}: ISO date, legacy boolean or null required.`);
          }
          if (["Day", "StartDay", "EndDay", "WeekStart", "WeekEnd", "MetricsStartDay", "MetricsEndDay", "BillingStartDay", "BillingEndDay"].includes(key) && value !== null && !isDay(value)) throw new Error(`${table}.${key}: invalid ISO date.`);
        }
        if (["Dates", "Billing", "Metrics", "ModelFeatures", "ClientModels", "Features", "CLI", "LicensedDays", "LicenseCoverage", "SourceCoverage", "IDEs", "Languages"].includes(table) && !isDay(row.Day)) {
          throw new Error(`${table}[${index}]: Day required.`);
        }
        if (["Billing", "Metrics", "ModelFeatures", "ClientModels", "Features", "CLI", "LicensedDays", "Pools"].includes(table) && typeof row.CenterId !== "string") {
          throw new Error(`${table}[${index}]: CenterId required.`);
        }
        if (["Centers"].includes(table) && (typeof row.CenterId !== "string" || typeof row.Center !== "string")) {
          throw new Error("Centers requires CenterId and Center.");
        }
        if (["Users", "Licenses", "LicensedDays", "Metrics", "ModelFeatures", "ClientModels", "Features", "CLI"].includes(table) && (typeof row.User !== "string" || !row.User)) {
          throw new Error(`${table}[${index}]: User required.`);
        }
      }
    }
    if (data.Info.length !== 1) throw new Error("Info must contain exactly one record.");
    const info = data.Info[0];
    if (!["SAMPLE", "REAL"].includes(info.Mode)) throw new Error("Info.Mode must be SAMPLE or REAL.");
    if (typeof info.Label !== "string" || !info.Label.trim()) throw new Error("Info.Label required.");
    if (!isDay(info.StartDay) || !isDay(info.EndDay) || info.StartDay > info.EndDay) throw new Error("Invalid Info.StartDay/EndDay.");
    if (typeof info.AsOf !== "string" || !Number.isFinite(Date.parse(info.AsOf))) throw new Error("Info.AsOf must be a valid timestamp.");
    daysBetween(info.StartDay, info.EndDay);
    data.Centers = data.Centers.map(center => ({ ...center, Country: regionLabel(center) }));
    return data;
  }
  function parseDataset(text) {
    if (new TextEncoder().encode(text).length > MAX_BYTES) throw new Error("The file exceeds the 16 MiB limit.");
    let input;
    try { input = JSON.parse(text); } catch { throw new Error("The file does not contain valid JSON."); }
    return validateDataset(input);
  }
  function modelKey(value) { return typeof value === "string" ? value : ""; }
  function sum(rows, key) {
    if (!rows.length || rows.some(r => !num(r[key]))) return null;
    return rows.reduce((total, row) => total + row[key], 0);
  }
  function ratio(a, b) { return num(a) && num(b) && b > 0 ? a / b : null; }
  function residualSet(data) { return new Set(data.Users.filter(u => u.IsResidual === true).map(u => u.User)); }
  function isPerson(row, residual) { return Boolean(row.User) && row.IsResidual !== true && !residual.has(row.User) && row.User !== "(no user detail)"; }
  function centerMatch(row, filters, centers) {
    if (filters.center && row.CenterId !== filters.center) return false;
    if (filters.country && centers.get(row.CenterId)?.Country !== filters.country) return false;
    return true;
  }
  function matches(row, filters, centers, withModel = false) {
    return row.Day >= filters.start && row.Day <= filters.end && centerMatch(row, filters, centers) &&
      (!withModel || !filters.model || modelKey(row.Model) === modelKey(filters.model));
  }
  function activity(row) {
    if (row.ActivityObserved === true) return true;
    if (USED.some(k => row[k] === true) || ["Interactions", "Generations", "Acceptances", "LinesAdded", "LinesDeleted", "Requests", "Prompts"].some(k => num(row[k]) && row[k] > 0)) return true;
    if (row.ActivityObserved === false) return false;
    return null;
  }
  function monday(day) {
    const time = dayTime(day), weekday = new Date(time).getUTCDay();
    return new Date(time - ((weekday + 6) % 7) * DAY_MS).toISOString().slice(0, 10);
  }
  function completeWeeks(days) {
    const selected = new Set(days), weeks = new Set(days.map(monday));
    return [...weeks].filter(start => daysBetween(start, new Date(dayTime(start) + 6 * DAY_MS).toISOString().slice(0, 10)).every(d => selected.has(d)));
  }
  function by(rows, key) {
    const result = new Map();
    for (const row of rows) {
      const value = typeof key === "function" ? key(row) : row[key];
      if (!result.has(value)) result.set(value, []);
      result.get(value).push(row);
    }
    return result;
  }
  function featureUsers(metrics, features, usedKey, pattern) {
    const found = new Set(), knownPairs = new Set();
    let available = metrics.some(r => typeof r[usedKey] === "boolean") || features.length > 0;
    for (const row of metrics) {
      if (typeof row[usedKey] === "boolean") knownPairs.add(`${row.Day}\0${row.User}`);
      if (row[usedKey] === true) found.add(row.User);
    }
    for (const row of features) {
      if (!knownPairs.has(`${row.Day}\0${row.User}`) && pattern.test(row.Feature || "") && activity(row) === true) found.add(row.User);
    }
    return available ? found.size : null;
  }
  function summarize(data, inputFilters) {
    const info = data.Info[0];
    const filters = { start: info.StartDay, end: info.EndDay, country: "", center: "", model: "", ...inputFilters };
    const days = daysBetween(filters.start, filters.end);
    const centers = new Map(data.Centers.map(c => [c.CenterId, c]));
    const residual = residualSet(data);
    const sources = new Map(data.SourceCoverage.map(r => [r.Day, r]));
    const available = (day, source) => {
      if (sources.size) return sources.get(day)?.[`${source}Available`] === true;
      if (source === "Metrics" && info.MissingMetricsDays > 0) return false;
      const start = own(info, `${source}StartDay`) ? info[`${source}StartDay`] : info.StartDay;
      const end = own(info, `${source}EndDay`) ? info[`${source}EndDay`] : info.EndDay;
      return isDay(start) && isDay(end) && day >= start && day <= end;
    };
    const metricsMissingDays = days.filter(day => !available(day, "Metrics"));
    const billingMissingDays = days.filter(day => !available(day, "Billing"));
    const metricsComplete = days.length > 0 && metricsMissingDays.length === 0;
    const filter = (table, modeled = false) => data[table].filter(r =>
      matches(r, filters, centers, modeled) && (table === "LicensedDays" || available(r.Day, table === "Billing" ? "Billing" : "Metrics")));
    const metrics = filter("Metrics").filter(r => isPerson(r, residual));
    const mf = filter("ModelFeatures", true).filter(r => isPerson(r, residual));
    const clients = filter("ClientModels", true).filter(r => isPerson(r, residual));
    const cli = filters.model ? [] : filter("CLI").filter(r => isPerson(r, residual));
    const features = filters.model ? mf : filter("Features").filter(r => isPerson(r, residual));
    const usage = filters.model ? mf : metrics;
    const allBilling = filter("Billing", true);
    const billing = allBilling.filter(r => r.UnitType === "ai-credits");
    const activeDays = new Map(), signalsByDay = new Map();
    const signalRows = filters.model ? [...mf, ...clients] : [...metrics, ...mf, ...clients, ...cli, ...features];
    for (const row of signalRows) {
      if (!signalsByDay.has(row.Day)) signalsByDay.set(row.Day, []);
      signalsByDay.get(row.Day).push(row);
      if (activity(row) !== true) continue;
      if (!activeDays.has(row.User)) activeDays.set(row.User, new Set());
      activeDays.get(row.User).add(row.Day);
    }
    const activeUsers = new Set(activeDays.keys());
    const weeks = completeWeeks(days);
    const recurrenceCoverageComplete = weeks.length > 0 && weeks.every(start =>
      daysBetween(start, new Date(dayTime(start) + 6 * DAY_MS).toISOString().slice(0, 10)).every(day => available(day, "Metrics")));
    const activeInCompleteWeeks = new Set([...activeDays].filter(([, userDays]) =>
      [...userDays].some(day => weeks.includes(monday(day)))).map(([user]) => user));
    const recurring = recurrenceCoverageComplete ? [...activeDays.values()].filter(userDays =>
      weeks.some(start => [...userDays].filter(day => monday(day) === start).length >= 3)).length : null;
    const totals = {};
    for (const key of ["Interactions", "Generations", "Acceptances", "LinesAdded", "LinesDeleted", "LinesSuggested", "LinesSuggestedDelete", "RequirementsMet", "RequirementsUnmet", "RequirementsUnknown"]) totals[key] = sum(usage, key);
    const completion = features.filter(r => r.Feature === "code_completion");
    totals.LinesAccepted = sum(completion, "LinesAdded");
    totals.InlineLinesSuggested = sum(completion, "LinesSuggested");
    totals.InlineAcceptances = sum(completion, "Acceptances");
    totals.InlineGenerations = sum(completion, "Generations");
    totals.NetLines = num(totals.LinesAdded) && num(totals.LinesDeleted) ? totals.LinesAdded - totals.LinesDeleted : null;
    totals.EditedLines = num(totals.LinesAdded) && num(totals.LinesDeleted) ? totals.LinesAdded + totals.LinesDeleted : null;
    totals.Credits = sum(billing, "grossQuantity");
    totals.Requests = sum(clients, "Requests");
    totals.PromptTokens = sum(clients, "PromptTokens");
    totals.OutputTokens = sum(clients, "OutputTokens");
    totals.CLIRequests = sum(cli, "Requests");
    totals.CLISessions = sum(cli, "Sessions");
    totals.CLIPrompts = sum(cli, "Prompts");
    const snapshotLicenses = data.Licenses.filter(r => centerMatch(r, filters, centers) && isPerson(r, residual));
    const hasSnapshot = data.Licenses.length > 0 || /complete|available/i.test(info.LicenseRosterStatus || "") && !/incomplete|unavailable/i.test(info.LicenseRosterStatus || "");
    const licenseCount = hasSnapshot ? new Set(snapshotLicenses.map(r => r.User)).size : null;
    const coverage = new Map(data.LicenseCoverage.map(r => [r.Day, r.HistoricalRosterComplete]));
    const historicalComplete = days.length > 0 && days.every(day => coverage.get(day) === true);
    const licensedDays = filter("LicensedDays");
    const licensed = new Set(licensedDays.map(r => r.User));
    const knownUserDay = new Map();
    if (!filters.model) for (const row of metrics) {
      const key = `${row.Day}\0${row.User}`;
      const known = activity(row) !== null;
      knownUserDay.set(key, knownUserDay.get(key) || known);
    }
    const knownActivePairs = new Set();
    for (const [user, userDays] of activeDays) for (const day of userDays) knownActivePairs.add(`${day}\0${user}`);
    const activityComplete = historicalComplete && licensedDays.every(r =>
      knownUserDay.get(`${r.Day}\0${r.User}`) === true || knownActivePairs.has(`${r.Day}\0${r.User}`));
    const eligible = historicalComplete && activityComplete && metricsComplete && !filters.model;
    const activeLicensed = [...licensed].filter(user => activeUsers.has(user)).length;
    const inactive = eligible ? licensed.size - activeLicensed : null;
    const adoption = eligible ? ratio(activeLicensed, licensed.size) : null;
    const recurringEligible = recurrenceCoverageComplete ? ratio(recurring, activeInCompleteWeeks.size) : null;
    const daily = days.map(day => {
      const rows = usage.filter(r => r.Day === day), bills = billing.filter(r => r.Day === day);
      const dayUsers = [...activeDays.values()].filter(d => d.has(day)).length;
      const covered = available(day, "Metrics") && signalsByDay.get(day)?.some(r => activity(r) !== null);
      return { Day: day, ActiveUsers: covered ? dayUsers : null, Interactions: sum(rows, "Interactions"), Generations: sum(rows, "Generations"),
        Acceptances: sum(rows, "Acceptances"), Credits: sum(bills, "grossQuantity"), LinesAdded: sum(rows, "LinesAdded"), LinesDeleted: sum(rows, "LinesDeleted") };
    });
    const activeDayCount = [...activeDays.values()].reduce((total, set) => total + set.size, 0);
    const hasActivity = signalRows.some(r => activity(r) !== null);
    const avgDAU = hasActivity && metricsComplete ? activeDayCount / days.length : null;
    const peak = metricsComplete ? daily.filter(r => num(r.ActiveUsers)).sort((a, b) => b.ActiveUsers - a.ActiveUsers || a.Day.localeCompare(b.Day))[0] || null : null;
    const userNames = new Set([...metrics, ...mf, ...clients, ...cli, ...billing.filter(r => isPerson(r, residual))].map(r => r.User));
    for (const r of licensedDays) userNames.add(r.User);
    const userRows = [...userNames].filter(Boolean).map(user => {
      const um = usage.filter(r => r.User === user), ub = billing.filter(r => r.User === user);
      const uc = clients.filter(r => r.User === user);
      const daysUsed = activeDays.get(user)?.size || 0;
      const cids = [...new Set([...um, ...ub, ...uc].map(r => r.CenterId))];
      const observed = daysUsed > 0 || eligible && licensed.has(user) || metrics.some(r => r.User === user && activity(r) === false);
      return { User: user, Center: cids.map(c => centers.get(c)?.Center || c).join(" · ") || "Unattributed",
        ActiveDays: observed ? daysUsed : null, Status: daysUsed ? "Active" : eligible && licensed.has(user) ? "No use" : "No signal",
        Credits: sum(ub, "grossQuantity"), Generations: sum(um, "Generations"), Acceptances: sum(um, "Acceptances"),
        LinesAdded: sum(um, "LinesAdded"), LinesDeleted: sum(um, "LinesDeleted"), Requests: sum(uc, "Requests"),
        NetLines: num(sum(um, "LinesAdded")) && num(sum(um, "LinesDeleted")) ? sum(um, "LinesAdded") - sum(um, "LinesDeleted") : null };
    });
    const modelGroups = new Map();
    for (const row of [...billing, ...mf, ...clients]) {
      const key = modelKey(row.Model) || "unknown";
      if (!modelGroups.has(key)) modelGroups.set(key, row.Model || "No model");
    }
    const modelRows = [...modelGroups].map(([key, Model]) => {
      const b = billing.filter(r => (modelKey(r.Model) || "unknown") === key);
      const m = mf.filter(r => (modelKey(r.Model) || "unknown") === key);
      const c = clients.filter(r => (modelKey(r.Model) || "unknown") === key);
      return { Model, Credits: sum(b, "grossQuantity"), Generations: sum(m, "Generations"), Interactions: sum(m, "Interactions"),
        Acceptances: sum(m, "Acceptances"), Requests: sum(c, "Requests"), PromptTokens: sum(c, "PromptTokens"), OutputTokens: sum(c, "OutputTokens") };
    }).sort((a, b) => (b.Credits ?? -1) - (a.Credits ?? -1));
    const blocks = [];
    for (let i = 0; i < days.length; i += 14) {
      const start = days[i], end = days[Math.min(i + 13, days.length - 1)];
      const items = billing.filter(r => r.Day >= start && r.Day <= end);
      blocks.push({ start, end, values: [...modelGroups].map(([key, name]) => {
        const rows = items.filter(r => (modelKey(r.Model) || "unknown") === key);
        return { Model: name, Credits: rows.length ? sum(rows, "grossQuantity") : null };
      }) });
    }
    const pools = data.Pools.filter(r => centerMatch(r, filters, centers));
    const budgets = data.Budgets.filter(r => centerMatch(r, filters, centers));
    const residualBilling = billing.filter(r => !isPerson(r, residual));
    const residualCredits = residualBilling.length ? sum(residualBilling, "grossQuantity") : billing.length ? 0 : null;
    const attributedCredits = billing.filter(r => isPerson(r, residual));
    const attributed = attributedCredits.length ? sum(attributedCredits, "grossQuantity") : billing.length ? 0 : null;
    return { filters, days, info, metrics, usage, features, clients, cli, billing, totals, daily, userRows, modelRows, blocks, pools, budgets,
      activeCount: hasActivity ? activeUsers.size : null, avgDAU, peak, avgActiveDays: metricsComplete ? ratio(activeDayCount, activeUsers.size) : null,
      recurring, recurringEligible, activeInCompleteWeeks: activeInCompleteWeeks.size, weeks, licenseCount, snapshotLicenses, historicalComplete, activityComplete, inactive, adoption,
      chatUsers: featureUsers(filters.model ? [] : metrics, filters.model ? mf : [...features, ...mf], "UsedChat", /chat/i),
      agentUsers: featureUsers(filters.model ? [] : metrics, filters.model ? mf : [...features, ...mf], "UsedAgent", /agent/i),
      residualCredits, attributedCredits: attributed, excludedBillingRows: allBilling.length - billing.length,
      observedDays: daily.filter(r => r.ActiveUsers !== null).length,
      metricsComplete, metricsMissingDays, billingMissingDays, recurrenceCoverageComplete,
      sourceCoverage: days.map(Day => ({ Day, MetricsAvailable: available(Day, "Metrics"), BillingAvailable: available(Day, "Billing"),
        MetricsStatus: sources.get(Day)?.MetricsStatus || "Not declared", BillingStatus: sources.get(Day)?.BillingStatus || "Not declared" })),
      unknownActivityRows: metrics.filter(r => activity(r) === null).length,
      telemetryRows: metrics.filter(r => r.TelemetryPresent === true).length,
      empty: !usage.length && !billing.length && !clients.length && !cli.length,
      acceptanceRate: ratio(totals.Acceptances, totals.Generations),
      inlineAcceptanceRate: ratio(totals.InlineAcceptances, totals.InlineGenerations),
      lineAcceptanceRate: ratio(totals.LinesAccepted, totals.InlineLinesSuggested) };
  }
  function searchRows(rows, query) {
    const needle = query.trim().toLocaleLowerCase("en");
    return needle ? rows.filter(row => Object.values(row).some(value => String(value ?? "").toLocaleLowerCase("en").includes(needle))) : rows;
  }
  function csvCell(value) {
    let text = value === null || value === undefined ? "" : String(value);
    if (/^[\s\u0000-\u001f]*[=+\-@]/.test(text) && typeof value !== "number") text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  }
  function toCSV(rows, columns, context = {}) {
    const metadata = Object.keys(context).map(key => ({ key, label: key }));
    const headers = [...metadata, ...columns];
    return "\uFEFF" + headers.map(c => csvCell(c.label)).join(";") + "\r\n" +
      rows.map(row => headers.map(c => csvCell(own(context, c.key) ? context[c.key] : row[c.key])).join(";")).join("\r\n");
  }
  return { TABLES, MAX_BYTES, MAX_ROWS, isDay, daysBetween, parseDataset, validateDataset, modelKey, sum, ratio, activity,
    monday, completeWeeks, summarize, searchRows, csvCell, toCSV, num, by };
});

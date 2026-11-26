(function () {
  "use strict";
  const D = window.CopilotData, $ = id => document.getElementById(id);
  const P = window.CopilotProjections, projectionContract = JSON.parse($("projection-contract").textContent);
  let pricing = null, pricingBusy = false, projectionOptions = { ...projectionContract.defaults }, projectionUser = "", mixError = "";
  const projectionFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });
  const pfmt = value => D.num(value) ? projectionFormat.format(value) : "N/D";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const format = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
  const fmt = value => D.num(value) ? format.format(value) : "N/D";
  const pct = value => D.num(value) ? `${fmt(value * 100)}%` : "N/D";
  const stamp = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC") : "N/D";
  const manualStatusText = "Manual mode: import JSON. No background collection or automatic refresh.";
  const state = { tab: "overview", filters: {}, searches: {}, pages: {}, rank: "Credits", source: "SAMPLE", imported: false,
    manual: document.documentElement.dataset.mode === "manual" };
  let initial, data, summary, charts = new Map(), tables = {}, busy = false;
  try { initial = D.parseDataset($("embedded-dataset").textContent); data = initial; }
  catch (error) { $("notice").hidden = false; $("notice").textContent = `Dataset cannot be opened: ${error.message}`; return; }

  function message(text, error = false) {
    $("notice").hidden = false; $("notice").className = `notice${error ? " error" : ""}`;
    $("notice").textContent = text; $("announcement").textContent = text;
  }
  function options(values, all, selected = "") {
    return `<option value="">${esc(all)}</option>` + values.map(([value, name]) =>
      `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(name)}</option>`).join("");
  }
  function centers() {
    const values = data.Centers.filter(r => !state.filters.country || r.Country === state.filters.country);
    if (!values.some(r => r.CenterId === state.filters.center)) state.filters.center = "";
    $("center").innerHTML = options(values.map(r => [r.CenterId, r.Center]), "All centers", state.filters.center);
  }
  function populate(reset = true) {
    const info = data.Info[0];
    if (reset) {
      state.filters = { start: info.StartDay, end: info.EndDay, country: "", center: "", model: "" };
      state.pages = {}; state.searches = {};
    }
    $("start").value = state.filters.start; $("end").value = state.filters.end;
    const months = [...new Set(data.Dates.map(r => r.Day.slice(0, 7)))];
    $("month").innerHTML = options(months.map(m => [m, m]), "All months");
    $("country").innerHTML = options([...new Set(data.Centers.map(r => r.Country))].sort().map(v => [v, v]), "All regions / groups", state.filters.country);
    centers();
    const models = [...new Set([...data.Models, ...data.Billing, ...data.ModelFeatures, ...data.ClientModels].map(r => r.Model).filter(Boolean))].sort();
    $("model").innerHTML = options(models.map(v => [v, v]), "All models", state.filters.model);
    $("mode-badge").textContent = info.Mode;
    $("mode-badge").className = `badge${info.Mode === "REAL" ? " warning" : ""}`;
    $("dataset-label").textContent = info.Mode === "SAMPLE" ? "Synthetic sample - not real usage" : "REAL - private stored snapshot";
    $("dataset-label").title = info.Label;
    $("asof").textContent = `As of: ${stamp(info.AsOf)}`;
    $("coverage").textContent = `Coverage: ${info.StartDay} to ${info.EndDay}`;
    for (const mode of ["sample", "real"]) $(mode + "-mode").setAttribute("aria-pressed", String(info.Mode === mode.toUpperCase()));
  }
  function kpi(label, value, hint = "") {
    return `<article class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-number">${esc(value)}</div>${hint ? `<p class="kpi-hint">${esc(hint)}</p>` : ""}</article>`;
  }
  function heading(title) { return `<div class="section-heading"><h2>${esc(title)}</h2></div>`; }
  function card(title, body, id = "") {
    return `<section class="card">${`<div class="card-header"><h3>${esc(title)}</h3>${id ? `<div class="export-actions"><button data-chart="${id}" data-format="svg">SVG</button><button data-chart="${id}" data-format="png">PNG</button></div>` : ""}</div>`}${body}</section>`;
  }
  function chart(id, title, rows, series, label = "Day") {
    const values = rows.flatMap(r => series.map(s => r[s[0]])).filter(D.num);
    if (!values.length) return card(title, '<div class="empty">N/D - no data in this selection</div>');
    const w = 760, h = 240, left = 65, top = 14, pw = 670, ph = 175;
    const max = Math.max(1, ...values) * 1.08, colors = ["accent", "text-muted", "warning", "link", "text-soft", "border-strong"];
    let body = "";
    for (let i = 0; i <= 4; i++) {
      const y = top + ph * i / 4;
      body += `<line class="chart-gridline" x1="${left}" y1="${y}" x2="${left + pw}" y2="${y}"/><text x="${left - 8}" y="${y + 3}" text-anchor="end">${esc(fmt(max * (4 - i) / 4))}</text>`;
    }
    const x = i => left + (rows.length === 1 ? .5 : i / (rows.length - 1)) * pw;
    series.forEach(([key, name], index) => {
      const color = colors[index % colors.length];
      let segment = [];
      const finish = () => {
        if (segment.length > 1) body += `<polyline points="${segment.join(" ")}" fill="none" stroke="var(--cp-${color})" stroke-width="2.5"/>`;
        segment = [];
      };
      rows.forEach((row, i) => {
        if (!D.num(row[key])) { finish(); return; }
        const y = top + ph * (1 - row[key] / max);
        segment.push(`${x(i)},${y}`);
        body += `<circle cx="${x(i)}" cy="${y}" r="3" fill="var(--cp-${color})"><title>${esc(`${row[label]} - ${name}: ${fmt(row[key])}`)}</title></circle>`;
      });
      finish();
      body += `<text x="${left + index * 205}" y="232">${esc(name)}</text>`;
    });
    rows.forEach((row, i) => {
      if (i % Math.max(1, Math.ceil(rows.length / 5)) === 0 || i === rows.length - 1)
        body += `<text x="${x(i)}" y="211" text-anchor="middle">${esc(label === "Day" ? String(row[label]).slice(5) : row[label])}</text>`;
    });
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title>${body}</svg>`;
    charts.set(id, { svg, title });
    return card(title, `<div class="chart">${svg}</div>`, id);
  }
  const userCols = [["User", "User"], ["Center", "Cost center"], ["Status", "Activity"], ["ActiveDays", "Active days"], ["Credits", "AI credits"], ["Generations", "Generations"], ["Acceptances", "Acceptances"], ["LinesAdded", "Lines added"], ["LinesDeleted", "Lines deleted"], ["NetLines", "Net lines"], ["Requests", "Client requests"]];
  const dailyCols = [["Day", "Day"], ["ActiveUsers", "Observed active users"], ["Credits", "AI credits"], ["Interactions", "Interactions"], ["Generations", "Generations"], ["Acceptances", "Acceptances"], ["LinesAdded", "Lines added"], ["LinesDeleted", "Lines deleted"]];
  const modelCols = [["Model", "Model"], ["Credits", "AI credits"], ["Interactions", "Interactions"], ["Generations", "Generations"], ["Acceptances", "Acceptances"], ["Requests", "Client requests"], ["PromptTokens", "Input tokens"], ["OutputTokens", "Output tokens"]];
  function table(id, title, rows, pairs) {
    const columns = pairs.map(([key, label]) => ({ key, label }));
    tables[id] = { rows, columns, title };
    const filtered = D.searchRows(rows, state.searches[id] || "");
    const pages = Math.max(1, Math.ceil(filtered.length / 25));
    const page = state.pages[id] = Math.min(state.pages[id] || 0, pages - 1);
    const visible = filtered.slice(page * 25, page * 25 + 25);
    const cell = value => value === null || value === undefined ? "N/D" : typeof value === "number" ? fmt(value) : typeof value === "boolean" ? value ? "Yes" : "No" : value;
    return card(title, `<div class="toolbar"><input type="search" data-search="${id}" aria-label="Search ${esc(title)}" placeholder="Search this table" value="${esc(state.searches[id] || "")}"><div class="toolbar-actions"><span class="row-count">${filtered.length} of ${rows.length} rows</span><button data-csv="${id}">Export CSV</button></div></div>
      <div class="table-wrap"><table aria-label="${esc(title)}"><thead><tr>${columns.map(c => `<th scope="col">${esc(c.label)}</th>`).join("")}</tr></thead><tbody>${visible.length ? visible.map(row => `<tr>${columns.map(c => `<td${D.num(row[c.key]) ? ' class="numeric"' : ""}>${esc(cell(row[c.key]))}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${columns.length}">No matching rows</td></tr>`}</tbody></table></div>
      <div class="pagination"><span>Page ${page + 1} of ${pages}</span><button data-page="${id}" data-step="-1"${page ? "" : " disabled"} aria-label="Previous page">Previous</button><button data-page="${id}" data-step="1"${page === pages - 1 ? " disabled" : ""} aria-label="Next page">Next</button></div>`);
  }
  function dimension(tableName, dimension) {
    if (state.filters.model) return [];
    const centers = new Map(data.Centers.map(r => [r.CenterId, r]));
    const f = state.filters, available = new Set(summary.sourceCoverage.filter(r => r.MetricsAvailable).map(r => r.Day));
    const rows = data[tableName].filter(r => available.has(r.Day) && (!f.center || r.CenterId === f.center) && (!f.country || centers.get(r.CenterId)?.Country === f.country));
    return [...D.by(rows, dimension)].map(([Name, values]) => ({ Name, Generations: D.sum(values, "Generations") }));
  }
  function ranking() {
    const rows = summary.userRows.filter(r => D.num(r[state.rank])).sort((a, b) => b[state.rank] - a[state.rank] || a.User.localeCompare(b.User)).slice(0, 15);
    return `<div class="section-heading"><h2>Top 15 users</h2><div class="mini-tabs">${[["Credits", "AI credits"], ["Generations", "Generations"], ["NetLines", "Net lines"]].map(([key, name]) => `<button data-rank="${key}" aria-pressed="${state.rank === key}">${name}</button>`).join("")}</div></div>` +
      table("ranking", "Observed user activity", rows, [["User", "User"], [state.rank, state.rank === "Credits" ? "AI credits" : state.rank === "NetLines" ? "Net lines" : "Generations"]]);
  }
  function overview() {
    const s = summary, t = s.totals;
    return heading("Overview") + `<div class="kpi-grid">
      ${kpi("Licenses", fmt(s.licenseCount), `Snapshot: ${s.info.LicenseSnapshotAsOf?.slice(0, 10) || "N/D"}`)}
      ${kpi("Observed active users", fmt(s.activeCount))}
      ${kpi("Adoption", pct(s.adoption), s.adoption === null ? "Historical coverage required" : `${fmt(s.inactive)} licensed users without use`)}
      ${kpi("Recurring users", fmt(s.recurring), "3+ active days in a complete ISO week")}
      ${kpi("Mean active users / day", fmt(s.avgDAU), `Peak: ${fmt(s.peak?.ActiveUsers)}`)}
      ${kpi("Gross AI credits", fmt(t.Credits), "Billing - ai-credits")}</div>
      <div class="chart-grid">${chart("activity", "Daily activity", s.daily, [["Generations", "Generations"], ["Acceptances", "Acceptances"]])}${chart("dau", "Observed active users", s.daily, [["ActiveUsers", "Active users"]])}</div>` +
      heading("Activity") + `<div class="kpi-grid four">${kpi("Interactions", fmt(t.Interactions))}${kpi("Generations", fmt(t.Generations))}${kpi("Acceptances", fmt(t.Acceptances), pct(s.acceptanceRate))}${kpi("Active days / active user", fmt(s.avgActiveDays))}</div>` +
      heading("Lines of code") + `<div class="kpi-grid">${kpi("Suggested lines", fmt(t.LinesSuggested))}${kpi("Inline accepted lines", fmt(t.LinesAccepted), pct(s.lineAcceptanceRate))}${kpi("Lines added", fmt(t.LinesAdded))}${kpi("Lines deleted", fmt(t.LinesDeleted))}${kpi("Net lines", fmt(t.NetLines), "Added - deleted")}${kpi("Edited lines", fmt(t.EditedLines), "Added + deleted")}</div>` +
      ranking();
  }
  function usersView() {
    return heading("Users") + table("users", "User detail", summary.userRows, userCols) +
      `<div class="chart-grid equal">${table("ides", "Development environments", dimension("IDEs", "IDE"), [["Name", "IDE"], ["Generations", "Generations"]])}${table("languages", "Languages", dimension("Languages", "Language"), [["Name", "Language"], ["Generations", "Generations"]])}</div>`;
  }
  function dailyView() {
    return heading("Daily") + chart("daily", "Daily gross AI credits", summary.daily, [["Credits", "AI credits"]]) +
      `<div class="data-section">${table("daily", "Daily detail", summary.daily, dailyCols)}</div>`;
  }
  function modelsView() {
    const rows = summary.blocks.map(b => Object.assign({ Day: b.start }, ...b.values.map(v => ({ [v.Model]: v.Credits }))));
    const clients = [...D.by(summary.clients, r => JSON.stringify([r.Client, r.SelectionMode, r.CustomModel]))].map(([key, group]) => {
      const [Client, SelectionMode, CustomModel] = JSON.parse(key);
      return { Client, SelectionMode, CustomModel, Requests: D.sum(group, "Requests"), PromptTokens: D.sum(group, "PromptTokens"), OutputTokens: D.sum(group, "OutputTokens") };
    });
    const t = summary.totals;
    return heading("Models") + chart("models", "AI credits by model - consecutive 14-day blocks", rows, summary.modelRows.map(r => [r.Model, r.Model])) +
      `<div class="data-section">${table("models", "Exact model identifiers", summary.modelRows, modelCols)}</div>` +
      heading("CLI") + `<div class="kpi-grid four">${kpi("CLI prompts", fmt(t.CLIPrompts))}${kpi("CLI sessions", fmt(t.CLISessions))}${kpi("CLI requests", fmt(t.CLIRequests))}${kpi("Inline acceptance rate", pct(summary.inlineAcceptanceRate))}</div>` +
      `<div class="data-section">${table("clients", "Clients and model selection", clients, [["Client", "Client"], ["SelectionMode", "Selection"], ["CustomModel", "Custom model"], ["Requests", "Requests"], ["PromptTokens", "Input tokens"], ["OutputTokens", "Output tokens"]])}</div>`;
  }
  function qualityView() {
    const s = summary;
    const coverage = [
      { Field: "Mode", Value: s.info.Mode }, { Field: "Label", Value: s.info.Label },
      { Field: "As of", Value: s.info.AsOf }, { Field: "Declared coverage", Value: s.info.Coverage },
      { Field: "Current license roster", Value: s.info.LicenseRosterStatus || "N/D" },
      { Field: "Historical license coverage", Value: s.historicalComplete ? "Complete" : "Incomplete - adoption and inactivity N/D" },
      { Field: "Historical activity coverage", Value: s.activityComplete ? "Complete" : "Incomplete" },
      { Field: "Unknown activity rows", Value: s.unknownActivityRows },
      { Field: "Unattributed billing credits", Value: s.residualCredits },
      { Field: "Excluded billing unit rows", Value: s.excludedBillingRows }
    ];
    const flags = ["UsedChat", "UsedAgent", "UsedCLI", "UsedCopilotApp", "UsedCloudAgent", "UsedCodeReviewActive", "UsedCodeReviewPassive", "UsedVSCodeAgent", "UsedLocalBYOK"];
    const surfaces = flags.map(Surface => {
      const known = s.metrics.filter(r => typeof r[Surface] === "boolean");
      return { Surface, Users: known.length ? new Set(known.filter(r => r[Surface]).map(r => r.User)).size : null, KnownRows: known.length, UnknownRows: s.metrics.length - known.length };
    });
    return heading("Data quality") + table("coverage", "Snapshot coverage", coverage, [["Field", "Field"], ["Value", "Value"]]) +
      `<div class="data-section">${table("sources", "Source availability", s.sourceCoverage, [["Day", "Day"], ["MetricsAvailable", "Metrics available"], ["BillingAvailable", "Billing available"], ["MetricsStatus", "Metrics status"], ["BillingStatus", "Billing status"]])}</div>` +
      heading("Surfaces") + table("surfaces", "Surface coverage - all models", surfaces, [["Surface", "Surface"], ["Users", "Users with a positive signal"], ["KnownRows", "Known rows"], ["UnknownRows", "Unknown rows"]]) +
      heading("Telemetry requirements") + `<div class="kpi-grid four">${kpi("Requirements met", fmt(s.totals.RequirementsMet))}${kpi("Requirements unmet", fmt(s.totals.RequirementsUnmet))}${kpi("Requirements unknown", fmt(s.totals.RequirementsUnknown))}${kpi("Telemetry present rows", fmt(s.telemetryRows))}</div>` +
      heading("Pools - current snapshot") + table("pools", "Pools - balance N/D without a verified unit", s.pools, [["CenterId", "Center"], ["PoolEnabled", "Enabled"], ["TargetRaw", "Raw target"], ["CurrentRaw", "Raw current"], ["UnitStatus", "Unit status"], ["AsOf", "As of"]]) +
      heading("Budgets - current snapshot") + table("budgets", "Reported budgets", s.budgets, [["CenterId", "Center"], ["Scope", "Scope"], ["ProductSKU", "Product SKU"], ["BudgetAmount", "Raw budget"], ["ConsumedAmount", "Raw consumed"], ["HardStop", "Hard stop"], ["AsOf", "As of"]]);
  }
  function projectionsView() {
    const catalog = pricing?.catalog, o = projectionOptions, f = { ...state.filters, user: projectionUser };
    const result = P.calibrate(data, projectionContract, pricing,
      mixError ? { ...o, mode: "invalid-mix" } : o, f);
    const select = (id, label, values, value) => `<label>${label}<select id="${id}">${values.map(([key, text]) => `<option value="${esc(key)}"${value === key ? " selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
    const input = (id, label, value, max = 100) => `<label>${label}<input id="${id}" type="number" min="0" max="${max}" step="any" value="${esc(value)}"></label>`;
    const targetModels = [...new Set([...(catalog?.rates.map(row => row.Model) || []),
      ...P.billingBuckets(data, projectionContract).map(row => row.Model).filter(Boolean)])].sort();
    const aliases = P.aliases(projectionContract, data.Info[0].Mode === "SAMPLE", true);
    const centers = new Map(data.Centers.map(row => [row.CenterId, row]));
    const bills = data.Billing.filter(row => row.UnitType === "ai-credits" && row.Product === "Copilot" && row.Day >= f.start && row.Day <= f.end &&
      (!f.user || row.User === f.user) && (!f.center || row.CenterId === f.center) &&
      (!f.country || centers.get(row.CenterId)?.Country === f.country) &&
      (!f.model || (aliases.get(row.Model) || row.Model) === (aliases.get(f.model) || f.model)));
    const status = pricingBusy ? "Checking official public prices..." : pricing?.state || "not checked";
    const selectedMix = o.mixes || projectionContract.mixes;
    const sourceChoices = [...new Map(P.billingBuckets(data, projectionContract).map(row => [row.SourceKey, row.SourceLabel]))]
      .sort((a, b) => a[1].localeCompare(b[1]));
    const rows = result.rows.map(row => ({ ...row, BaselineUSD: pfmt(row.BaselineUSD), TargetUSD: pfmt(row.TargetUSD),
      BaselineCredits: pfmt(row.BaselineCredits), TargetCredits: pfmt(row.TargetCredits), Ratio: pfmt(row.Ratio) }));
    const coverage = ["PromptTokens", "OutputTokens", "Requests"].map(Field => {
      const known = result.rows.filter(row => D.num(row[Field]));
      const eligible = known.filter(row => !row.Reason);
      return { Field, Known: known.length ? known.reduce((n, row) => n + row[Field], 0) : null,
        Eligible: eligible.length ? eligible.reduce((n, row) => n + row[Field], 0) : null,
        MissingRows: result.rows.filter(row => !D.num(row[Field])).length };
    });
    const tariffs = (catalog?.rates || []).map(row => ({ ...row, InputUSD: pfmt(row.InputUSD),
      CachedInputUSD: pfmt(row.CachedInputUSD), OutputUSD: pfmt(row.OutputUSD),
      CacheWriteUSD: row.CacheWriteStatus === "not-applicable" ? "N/A: ordinary input" : pfmt(row.CacheWriteUSD) }));
    return heading("Projections - reported Billing baseline, calibrated alternatives") +
      `<div class="notice${result.error ? " error" : " subtle"}" id="calibration-state">${esc(mixError || result.error || "No changes equals the reported gross consumption. Alternatives are Billing-calibrated estimates, not guaranteed invoice savings.")}</div>` +
      `<div class="notice${result.error ? " error" : " subtle"}" role="status" id="pricing-state">Prices: ${esc(status)} | Checked: ${esc(stamp(pricing?.lastChecked))} | Verified: ${esc(stamp(catalog?.asOf))} | ${esc(catalog?.contentHash || "no verified fingerprint")}<br>${esc(pricing?.lastError || result.error || "Only public Copilot pricing is fetched. Filters do not query pricing or GitHub reports.")}</div>
      <div class="toolbar data-section"><button id="pricing-refresh" type="button"${pricingBusy ? " disabled" : ""}>Refresh official prices</button><label><input id="p-stale" type="checkbox"${o.allowStale ? " checked" : ""}${!catalog ? " disabled" : ""}> Explicitly accept last verified prices if stale (not latest)</label></div>
      <div class="filters" id="projection-controls">
      ${select("p-mode", "Scenario", [["unchanged", "No changes"], ["target", "Substitute target model"], ...Object.entries(projectionContract.mixes).map(([key, entry]) => [key, entry.label])], o.mode)}
      ${select("p-replace-source", "Models to replace (scenario, separate from source scope)", [["", "All source models in scope"], ...sourceChoices], o.replaceSourceKey || "")}
      ${select("p-target", "Target model (public tariff, not availability advice)", [["", "Choose target"], ...targetModels.map(m => [m, m])], o.targetModel || "")}
      ${select("p-user", "User", [["", "All users"], ...data.Users.filter(row => !row.IsResidual).map(row => [row.User, row.User])], projectionUser)}
      ${input("p-replacement", "Replacement %", o.replacement * 100)}
      ${select("p-tier", "Assumed context tier (not inferred)", [["Default", "Default"], ["Long context", "Long context"]], o.tier)}
      <label>Assumed rate valuation day<input id="p-day" type="date" value="${esc(o.valuationDay || catalog?.asOf?.slice(0, 10) || new Date().toISOString().slice(0, 10))}"></label>
      ${input("p-read", "Cached read % of total input", o.cacheRead * 100)}
      ${input("p-write", "Cache write % of total input", o.cacheWrite * 100)}
      ${input("p-volume", "Migrated token volume multiplier", o.targetVolumeFactor, 10)}
      ${input("p-extra", "Fusion extra multiplier", o.fusionExtraFactor, 10)}
      <label><input id="p-promo" type="checkbox"${o.fusionPromotionEligible ? " checked" : ""}> Paid-plan eligible: apply published Fusion promo within its dates</label>
      </div>
      <p class="caption">Primary baseline is reported Billing grossQuantity / grossAmount under the same filters, independently summed. No changes, 0% replacement and a same-model identity keep actual consumption, even without prices. For each requested bucket, the scenario/source token-price ratio multiplies that bucket's actual credits and USD separately; money is never divided among requests or token rows. Every token row in the complete bucket must be usable.</p>
      <p class="caption">Input is split into disjoint uncached / cached-read / cache-write buckets; N/A write is charged as ordinary input. Tier/cache split/volume are assumptions, not inferred request sizes. Missing aliases, tokens or trustworthy center evidence stay in the actual baseline; requested changes to them yield N/D total, with partial estimates clearly separated. No task-quality, equivalence or ROI claim.</p>
      <p class="caption">${data.Info[0].Mode === "SAMPLE" ? "SAMPLE volumes and model aliases are fictional demonstration mappings. " : ""}Fusion modes use editable EXAMPLE mixtures and token overhead, not a deterministic router. SelectionMode=auto never implies Fusion. Promotion requires explicit eligibility; after its published end no discount is applied.</p>
      <details class="data-section"><summary>Edit example mixes / weights / overhead (not recommendations)</summary><textarea id="p-mixes" rows="10" aria-label="Example mixes JSON">${esc(JSON.stringify(selectedMix, null, 2))}</textarea></details>
      <div class="kpi-grid four data-section">${kpi("Reported baseline AI credits", pfmt(result.baselineCredits))}${kpi("Estimated calibrated AI credits", pfmt(result.targetCredits))}${kpi("Delta AI credits", pfmt(result.deltaCredits), "Estimate - reported; not net invoice savings")}${kpi("Delta credits %", pct(result.deltaPct), "Zero reported denominator = N/D")}</div>
      <div class="kpi-grid four data-section">${kpi("Reported baseline gross USD", pfmt(result.baselineUSD))}${kpi("Estimated calibrated gross USD", pfmt(result.targetUSD))}${kpi("Unprojected reported AI credits", pfmt(result.unprojectedCredits), "Included if untouched; not silently dropped")}${kpi("Unresolved requested AI credits", pfmt(result.unresolvedChangeCredits), "If nonzero, full estimate is N/D")}</div>
      <div class="kpi-grid four data-section">${kpi("Unchanged reported AI credits", pfmt(result.unchangedCredits))}${kpi("Changed reported AI credits", pfmt(result.changedCredits))}${kpi("Partial estimate AI credits (NOT total)", pfmt(result.partialTargetCredits))}${kpi("Complete / selected Billing buckets", `${fmt(result.eligibleRows)} / ${fmt(result.selectedRows)}`, "Enterprise-only is not a country")}</div>
      <div class="kpi-grid four data-section">${kpi("Delta gross USD", pfmt(result.deltaUSD), "Estimated - reported gross, NOT net invoice")}${kpi("Delta gross USD %", pct(result.deltaUSDPct))}${kpi("Partial estimate gross USD (NOT total)", pfmt(result.partialTargetUSD))}${kpi("Unresolved requested buckets", fmt(result.unresolvedRows))}</div>
      <div class="chart-grid equal">${chart("projection-comparison", "Reported gross USD / calibrated estimate", [{ Side: "Reported", USD: result.baselineUSD }, { Side: "Estimate", USD: result.targetUSD }], [["USD", "Gross USD"]], "Side")}
      ${table("projection-excluded", "Exclusions / coverage", result.excluded || [], [["Reason", "Reason"], ["Rows", "Rows"]])}</div>
      <p class="caption">Rate valuation day: ${esc(result.valuationDay || "N/D")}. Prices determine only the relative token-workload estimate, not the primary reported spend. Partial reported amount: ${pfmt(result.partialReportedCredits)} credits / ${pfmt(result.partialReportedUSD)} USD. Missing source coverage keeps full totals N/D. No proportional allocation or unverified budget/pool units.</p>
      <div class="data-section">${table("projection-rows", "Complete Billing buckets and calibration coverage", rows, [["Day", "Day"], ["User", "User"], ["SourceLabel", "Source model (exact alias)"], ["CenterId", "Historical center"], ["BillingRows", "Billing rows"], ["TokenRows", "Token rows"], ["BaselineCredits", "Reported credits"], ["TargetCredits", "Estimated credits"], ["BaselineUSD", "Reported USD"], ["TargetUSD", "Estimated USD"], ["Ratio", "Whole bucket ratio"], ["CoverageReason", "Unprojected reason"], ["Reason", "Unresolved change"]])}</div>
      <div class="data-section">${table("projection-coverage", "SECONDARY complete token-bucket diagnostics (not actual spend)", coverage, [["Field", "Field"], ["Known", "Known bucket volume"], ["Eligible", "Volume used / unchanged"], ["MissingRows", "Unknown buckets"]])}</div>
      ${heading("REPORTED billing discounts and net - NOT estimated invoices")}<div class="kpi-grid four">${kpi("Reported gross USD", pfmt(D.sum(bills, "grossAmount")))}${kpi("Reported discounts USD", pfmt(D.sum(bills, "discountAmount")))}${kpi("Reported net USD", pfmt(D.sum(bills, "netAmount")), "May be zero; never scenario-scaled")}${kpi("Reported billing rows", fmt(bills.length))}</div>
      <div class="data-section">${table("projection-tariffs", "Verified catalog USD per 1M text tokens - check tier and effective dates", tariffs, [["Model", "Model"], ["Tier", "Tier"], ["Threshold", "Published threshold"], ["InputUSD", "Input USD"], ["CachedInputUSD", "Cached read USD"], ["CacheWriteUSD", "Cache write USD"], ["OutputUSD", "Output USD"], ["Profile", "Price profile"], ["EffectiveFrom", "Effective from"], ["EffectiveTo", "Effective to (exclusive)"]])}</div>
      <p class="caption">Official sources: ${projectionContract.sources.map(url => esc(url)).join(" | ")}. Alias contract ${esc(projectionContract.aliasesVersion)}; parser ${esc(projectionContract.pricingParserVersion)}. Cached prices are never silently presented as current.</p>`;
  }
  async function loadPricing() {
    if (pricingBusy) return;
    pricingBusy = true;
    if (state.tab === "projections") panel();
    try { pricing = await getJSON("/api/pricing"); }
    catch (error) { pricing = { state: pricing?.catalog ? "stale" : "error", catalog: pricing?.catalog || null, lastChecked: new Date().toISOString(), lastError: "Official pricing could not be checked. Use Docker with internet access for Projections." }; }
    finally { pricingBusy = false; if (state.tab === "projections") panel(); }
  }
  function panel() {
    charts = new Map(); tables = {};
    $("panel").innerHTML = ({ overview, users: usersView, daily: dailyView, models: modelsView, quality: qualityView, projections: projectionsView })[state.tab]();
    $("panel").setAttribute("aria-labelledby", `tab-${state.tab}`);
  }
  function render() {
    summary = D.summarize(data, state.filters);
    $("scope-summary").textContent = `${summary.days.length} days - ${state.filters.country || "All regions / groups"} - ${state.filters.center || "All centers"}`;
    $("source-notice").textContent = `Metrics: ${summary.days.length - summary.metricsMissingDays.length}/${summary.days.length} days | Billing: ${summary.days.length - summary.billingMissingDays.length}/${summary.days.length} days${summary.metricsMissingDays.length ? " | Partial activity coverage; full-period rates N/D" : ""}`;
    $("model-notice").hidden = !state.filters.model;
    panel();
  }
  function readFilters() {
    const start = $("start").value, end = $("end").value;
    if (!D.isDay(start) || !D.isDay(end) || start > end) { message("Select a valid start date on or before the end date.", true); return; }
    Object.assign(state.filters, { start, end, country: $("country").value, center: $("center").value, model: $("model").value });
    state.pages = {}; $("notice").hidden = true;
    try { render(); } catch (error) { message(error.message, true); }
  }
  function setTab(tab, focus = false) {
    const opening = state.tab !== "projections";
    state.tab = tab;
    document.querySelectorAll("[data-tab]").forEach(button => {
      const selected = button.dataset.tab === tab;
      button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    });
    panel();
    if (tab === "projections" && opening) loadPricing();
  }
  async function getJSON(path) {
    const response = await fetch(path, { cache: "no-store", credentials: "omit", redirect: "error" });
    const text = await response.text();
    if (new TextEncoder().encode(text).length > D.MAX_BYTES) throw new Error("Response exceeds 16 MiB.");
    if (!response.ok) throw new Error(JSON.parse(text).error || "Stored data unavailable.");
    return JSON.parse(text);
  }
  async function collectorStatus() {
    const status = await getJSON("/api/status");
    state.manual = status.state === "manual";
    $("collector-status").textContent = state.manual ? manualStatusText :
      `Collector: ${status.state} | Last attempt: ${stamp(status.lastAttempt)} | Last success: ${stamp(status.lastSuccess)}${status.lastError ? ` | ${status.lastError}` : ""}`;
    $("collector-status").className = `notice${status.state === "error" ? " error" : " subtle"}`;
    return status;
  }
  async function refresh(mode = state.source, reset = false) {
    if (busy) return;
    busy = true;
    try {
      if (location.protocol === "file:") throw new Error("Use Docker for automatic refresh. Local JSON import remains available.");
      await collectorStatus();
      const candidate = D.validateDataset(await getJSON(`/api/dataset?mode=${mode}`));
      if (candidate.Info[0].Mode !== mode) throw new Error("Dataset mode does not match the selected source.");
      const changed = candidate.Info[0].AsOf !== data.Info[0].AsOf;
      data = candidate; state.source = mode; state.imported = false;
      populate(reset || changed); render();
      $("refresh-status").textContent = `Stored snapshot checked: ${new Date().toLocaleTimeString("en-US")}`;
      $("notice").hidden = true;
    } catch (error) { message(`${error.message} The current ${data.Info[0].Mode} snapshot is unchanged.`, true); }
    finally { busy = false; }
  }
  function context() {
    return { Mode: data.Info[0].Mode, AsOf: data.Info[0].AsOf, From: state.filters.start, To: state.filters.end,
      Region: state.filters.country || "All", Center: state.filters.center || "All", Model: state.filters.model || "All",
      MissingMetricsDays: summary.metricsMissingDays.length, MissingBillingDays: summary.billingMissingDays.length };
  }
  function download(blob, name) {
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = name; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  async function exportChart(id, type) {
    try {
      const c = charts.get(id), css = getComputedStyle(document.documentElement);
      const doc = new DOMParser().parseFromString(c.svg, "image/svg+xml"), svg = doc.documentElement;
      const ns = svg.namespaceURI, style = doc.createElementNS(ns, "style");
      const tokens = ["surface", "text", "text-soft", "text-muted", "border", "accent", "warning", "link", "border-strong"];
      style.textContent = `svg{${tokens.map(n => `--cp-${n}:${css.getPropertyValue(`--cp-${n}`).trim()}`).join(";")}}text{font:10px Segoe UI,Aptos,Calibri,sans-serif;fill:var(--cp-text-soft)}.chart-gridline{stroke:var(--cp-border)}`;
      svg.prepend(style); svg.setAttribute("width", "760"); svg.setAttribute("height", "300"); svg.setAttribute("viewBox", "0 0 760 300");
      const bg = doc.createElementNS(ns, "rect"); bg.setAttribute("width", "760"); bg.setAttribute("height", "300"); bg.setAttribute("fill", "var(--cp-surface)");
      svg.insertBefore(bg, style.nextSibling);
      const group = doc.createElementNS(ns, "g"); group.setAttribute("transform", "translate(0 60)");
      [...svg.childNodes].filter(n => n !== bg && n !== style).forEach(n => group.append(n)); svg.append(group);
      const label = (text, y) => { const el = doc.createElementNS(ns, "text"); el.setAttribute("x", "14"); el.setAttribute("y", y); el.textContent = text; svg.append(el); };
      label(`Copilot Metrics - ${c.title}`, "16");
      label(`${data.Info[0].Mode} | ${state.filters.start} to ${state.filters.end} | AsOf ${data.Info[0].AsOf}`, "32");
      label(`${state.filters.country || "All regions / groups"} | ${state.filters.center || "All centers"} | ${state.filters.model || "All models"} | Missing M/B days ${summary.metricsMissingDays.length}/${summary.billingMissingDays.length}`, "48");
      const blob = new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml" });
      const name = `copilot-${data.Info[0].Mode.toLowerCase()}-${id}`;
      if (type === "svg") download(blob, `${name}.svg`);
      else {
        const url = URL.createObjectURL(blob);
        try {
          const image = new Image();
          await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error("Chart rasterization failed.")); image.src = url; });
          const canvas = document.createElement("canvas"); canvas.width = 1520; canvas.height = 600;
          const ctx = canvas.getContext("2d"); if (!ctx) throw new Error("Canvas is unavailable.");
          ctx.scale(2, 2); ctx.drawImage(image, 0, 0);
          const png = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
          if (!png) throw new Error("PNG export failed.");
          download(png, `${name}.png`);
        } finally { URL.revokeObjectURL(url); }
      }
      message(`Chart exported as ${type.toUpperCase()} with mode, dates and coverage.`);
    } catch (error) { message(error.message, true); }
  }
  $("filters").addEventListener("submit", event => { event.preventDefault(); readFilters(); });
  $("filters").addEventListener("change", event => {
    if (event.target.id === "country") { state.filters.country = $("country").value; centers(); }
    if (event.target.id === "month") {
      const month = $("month").value, info = data.Info[0];
      const end = month ? new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).toISOString().slice(0, 10) : info.EndDay;
      $("start").value = month ? [month + "-01", info.StartDay].sort().at(-1) : info.StartDay;
      $("end").value = [end, info.EndDay].sort()[0];
    } else if (["start", "end"].includes(event.target.id)) $("month").value = "";
    readFilters();
  });
  $("reset").onclick = () => { populate(); render(); };
  $("refresh").onclick = () => state.imported || state.manual ? (populate(false), render(), message("JSON re-read locally. Import a new file to update it.")) : refresh();
  $("real-mode").onclick = () => state.manual ? $("import-button").click() : refresh("REAL", true);
  $("sample-mode").onclick = () => { data = initial; state.source = "SAMPLE"; state.imported = false; populate(); render(); $("notice").hidden = true; };
  $("theme-toggle").onclick = () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; };
  document.querySelector(".tabs").onclick = event => { const tab = event.target.closest("[data-tab]"); if (tab) setTab(tab.dataset.tab); };
  document.querySelector(".tabs").onkeydown = event => {
    const tabs = [...document.querySelectorAll("[data-tab]")], index = tabs.indexOf(document.activeElement);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    setTab(tabs[next].dataset.tab, true);
  };
  $("panel").onclick = event => {
    if (event.target.closest("#pricing-refresh")) { loadPricing(); return; }
    const rank = event.target.closest("[data-rank]"); if (rank) { state.rank = rank.dataset.rank; panel(); }
    const page = event.target.closest("[data-page]"); if (page) { state.pages[page.dataset.page] += Number(page.dataset.step); panel(); }
    const csv = event.target.closest("[data-csv]");
    if (csv) {
      const t = tables[csv.dataset.csv], rows = D.searchRows(t.rows, state.searches[csv.dataset.csv] || "");
      download(new Blob([D.toCSV(rows, t.columns, context())], { type: "text/csv;charset=utf-8" }), `copilot-${data.Info[0].Mode.toLowerCase()}-${csv.dataset.csv}.csv`);
      message(`CSV exported: ${rows.length} filtered rows.`);
    }
    const c = event.target.closest("[data-chart]"); if (c) exportChart(c.dataset.chart, c.dataset.format);
  };
  $("panel").addEventListener("change", event => {
    if (!event.target.id.startsWith("p-")) return;
    projectionUser = $("p-user").value;
    const numeric = id => $(id).value.trim() === "" ? NaN : Number($(id).value);
    Object.assign(projectionOptions, { mode: $("p-mode").value, targetModel: $("p-target").value,
      replaceSourceKey: $("p-replace-source").value,
      replacement: numeric("p-replacement") / 100, cacheRead: numeric("p-read") / 100,
      cacheWrite: numeric("p-write") / 100, tier: $("p-tier").value,
      valuationDay: $("p-day").value,
      targetVolumeFactor: numeric("p-volume"), fusionExtraFactor: numeric("p-extra"),
      fusionPromotionEligible: $("p-promo").checked, allowStale: $("p-stale").checked });
    try { projectionOptions.mixes = JSON.parse($("p-mixes").value); mixError = ""; }
    catch { mixError = "Invalid example-mix JSON: projections are N/D."; }
    panel();
  });
  $("panel").oninput = event => {
    const id = event.target.dataset.search; if (!id) return;
    const value = event.target.value, position = event.target.selectionStart;
    state.searches[id] = value; state.pages[id] = 0; panel();
    const input = $("panel").querySelector(`[data-search="${id}"]`); input.focus(); input.setSelectionRange(position, position);
  };
  $("import-button").onclick = () => { $("file-input").value = ""; $("file-input").click(); };
  $("file-input").onchange = async () => {
    const file = $("file-input").files[0]; if (!file) return;
    try {
      if (file.size > D.MAX_BYTES) throw new Error("The file exceeds 16 MiB.");
      const candidate = D.parseDataset(await file.text());
      data = candidate; state.imported = true; state.source = candidate.Info[0].Mode;
      populate(); render(); message(`Validated ${state.source} JSON loaded in memory only. Nothing was uploaded or saved.`);
    } catch (error) { message(`Import rejected: ${error.message} The previous snapshot is unchanged.`, true); }
  };
  populate(); render();
  if (state.manual) $("collector-status").textContent = manualStatusText;
  if (location.protocol !== "file:" && !state.manual) {
    const poll = () => setInterval(() => {
        collectorStatus().catch(error => message(`Collector status unavailable: ${error.message}`, true));
        if (state.source === "REAL" && !state.imported) refresh();
      }, 60000);
    collectorStatus().then(status => {
      if (state.manual) return;
      if (status.state !== "disabled") refresh("REAL", true);
      poll();
    }).catch(error => { message(`Collector status unavailable: ${error.message}`, true); poll(); });
  }
})();

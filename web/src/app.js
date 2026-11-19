(function () {
  "use strict";
  const D = window.CopilotData, $ = id => document.getElementById(id);
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
    $("center").innerHTML = options(values.map(r => [r.CenterId, r.Center.replaceAll("_", " ")]), "All centers", state.filters.center);
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
    $("country").innerHTML = options([...new Set(data.Centers.map(r => r.Country))].sort().map(v => [v, v.replaceAll("_", " ")]), "All regions", state.filters.country);
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
        body += `<text x="${x(i)}" y="211" text-anchor="middle">${esc(String(row[label]).slice(5))}</text>`;
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
  function panel() {
    charts = new Map(); tables = {};
    $("panel").innerHTML = ({ overview, users: usersView, daily: dailyView, models: modelsView, quality: qualityView })[state.tab]();
    $("panel").setAttribute("aria-labelledby", `tab-${state.tab}`);
  }
  function render() {
    summary = D.summarize(data, state.filters);
    $("scope-summary").textContent = `${summary.days.length} days - ${state.filters.country || "All regions"} - ${state.filters.center || "All centers"}`;
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
    state.tab = tab;
    document.querySelectorAll("[data-tab]").forEach(button => {
      const selected = button.dataset.tab === tab;
      button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    });
    panel();
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
      label(`${state.filters.country || "All regions"} | ${state.filters.center || "All centers"} | ${state.filters.model || "All models"} | Missing M/B days ${summary.metricsMissingDays.length}/${summary.billingMissingDays.length}`, "48");
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

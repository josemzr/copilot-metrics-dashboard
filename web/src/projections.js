(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CopilotProjections = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const isDay = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  function aliases(contract, sample = false, billing = false) {
    const map = new Map();
    for (const entry of contract.models) {
      for (const name of [entry.model, ...entry.aliases]) {
        if (map.has(name) && map.get(name) !== entry.model) throw new Error("Ambiguous explicit model alias");
        map.set(name, entry.model);
      }
    }
    if (sample) for (const [name, model] of Object.entries(contract.sampleAliases)) map.set(name, model);
    if (billing) for (const [name, model] of Object.entries(contract.billingAliases)) map.set(name, model);
    return map;
  }
  function usage(data, contract) {
    const sample = data.Info[0].Mode === "SAMPLE", names = aliases(contract, sample), billed = aliases(contract, sample, true);
    const centers = new Map(data.Centers.map(row => [row.CenterId, row]));
    const bridge = new Map();
    for (const row of data.Billing) {
      if (row.Attribution !== "API user filter" || row.UnitType !== "ai-credits" || !billed.has(row.Model)) continue;
      const key = JSON.stringify([row.Day, row.User, billed.get(row.Model)]);
      if (!bridge.has(key)) bridge.set(key, new Set());
      if (centers.has(row.CenterId) && !["unattributed-history", "unattributed-snapshot"].includes(row.CenterId)) bridge.get(key).add(row.CenterId);
    }
    const covered = new Map(data.SourceCoverage.map(row => [row.Day, row.MetricsAvailable === true]));
    return data.ClientModels.map((row, index) => {
      const model = names.get(row.Model) || null, direct = centers.get(row.CenterId);
      const matches = bridge.get(JSON.stringify([row.Day, row.User, model])) || new Set();
      const verified = direct && direct.State !== "virtual";
      const center = verified ? row.CenterId : matches.size === 1 ? [...matches][0] : "unattributed-history";
      const reason = row.CustomModel !== false ? "Custom/BYOK or unknown hosting" : !model ? "Unknown exact model alias" :
        !number(row.PromptTokens) || !number(row.OutputTokens) ? "Missing/invalid token counters" :
          covered.get(row.Day) !== true ? "Metrics source unavailable" : "";
      return { RowId: index, Day: row.Day, User: row.User, RawModel: row.Model, Model: model, SourceModel: model || row.Model,
        CenterId: center, Country: centers.get(center)?.Country || null,
        Attribution: verified ? "verified-client-center" : matches.size === 1 ? "unique-api-user-billing" :
          matches.size > 1 ? "ambiguous-billing-centers" : "unverified-center",
        PromptTokens: row.PromptTokens, OutputTokens: row.OutputTokens, Requests: row.Requests,
        Reason: reason, SampleAlias: sample && Object.hasOwn(contract.sampleAliases, row.Model) };
    });
  }
  function assumptions(contract, input) {
    const value = { ...contract.defaults, ...input };
    if (!["unchanged", "target", ...Object.keys(contract.mixes)].includes(value.mode) ||
        !number(value.replacement) || value.replacement > 1 ||
        !number(value.cacheRead) || !number(value.cacheWrite) || value.cacheRead + value.cacheWrite > 1 ||
        !["Default", "Long context"].includes(value.tier) ||
        !number(value.targetVolumeFactor) || value.targetVolumeFactor > 10 ||
        !number(value.fusionExtraFactor) || value.fusionExtraFactor > 10 ||
        typeof value.fusionPromotionEligible !== "boolean") throw new Error("Invalid scenario assumptions");
    value.fusion = value.mode.startsWith("fusion-");
    value.weights = [];
    value.overhead = 1;
    if (value.mode !== "unchanged" && value.replacement > 0) {
      if (value.mode === "target") value.weights = [{ model: value.targetModel, weight: 1 }];
      else {
        const mix = (value.mixes || contract.mixes)[value.mode];
        if (!mix || !number(mix.overhead) || mix.overhead > 10 || !Array.isArray(mix.weights)) throw new Error("Invalid example mix");
        value.weights = mix.weights; value.overhead = mix.overhead;
      }
      if (!value.weights.length || value.weights.some(row => typeof row.model !== "string" || !number(row.weight)) ||
          Math.abs(value.weights.reduce((total, row) => total + row.weight, 0) - 1) > 1e-9) {
        throw new Error("Mix weights must be non-negative and sum to 1");
      }
    }
    return value;
  }
  function findRate(catalog, model, tier, day) {
    const rows = catalog.rates.filter(row => row.Model === model && row.Tier === tier &&
      (!row.EffectiveFrom || row.EffectiveFrom <= day) && (!row.EffectiveTo || day < row.EffectiveTo));
    if (rows.length !== 1) return null;
    const row = rows[0];
    return [row.InputUSD, row.CachedInputUSD, row.OutputUSD].every(number) &&
      (row.CacheWriteUSD === null || number(row.CacheWriteUSD)) ? row : null;
  }
  function cost(row, rate, options) {
    if (!rate || !["priced", "not-applicable"].includes(rate.CacheWriteStatus) ||
        rate.CacheWriteStatus === "priced" && !number(rate.CacheWriteUSD)) return null;
    const uncached = row.PromptTokens * (1 - options.cacheRead - options.cacheWrite);
    const read = row.PromptTokens * options.cacheRead, write = row.PromptTokens * options.cacheWrite;
    return (uncached * rate.InputUSD + read * rate.CachedInputUSD +
      write * (rate.CacheWriteStatus === "not-applicable" ? rate.InputUSD : rate.CacheWriteUSD) +
      row.OutputTokens * rate.OutputUSD) / 1000000;
  }
  function simulate(data, contract, pricing, input = {}, filters = {}) {
    let options;
    try { options = assumptions(contract, input); }
    catch (error) { return { state: "invalid", error: error.message, baselineUSD: null, targetUSD: null, deltaUSD: null, deltaPct: null, rows: [] }; }
    const catalog = pricing?.catalog, today = new Date().toISOString().slice(0, 10);
    const day = input.valuationDay || catalog?.asOf?.slice(0, 10) || today;
    const validDay = isDay(day);
    const age = catalog ? Date.now() - Date.parse(catalog.asOf) : NaN;
    const validStamp = Number.isFinite(age) && age >= 0 && new Date(catalog.asOf).toISOString().slice(0, 10) === catalog.asOf.slice(0, 10);
    const fresh = pricing?.state === "ready" && validStamp && age <= contract.maxAgeHours * 3600000;
    const usable = validDay && catalog && catalog.version === contract.version && catalog.creditsPerUSD === 100 &&
      Array.isArray(catalog.rates) && validStamp && (fresh || input.allowStale === true);
    const mapped = aliases(contract, data.Info[0].Mode === "SAMPLE"), selectedModel = mapped.get(filters.model);
    const candidates = usage(data, contract).filter(row => (!filters.start || row.Day >= filters.start) &&
      (!filters.end || row.Day <= filters.end) && (!filters.user || row.User === filters.user) &&
      (!filters.model || (selectedModel ? row.Model === selectedModel : row.RawModel === filters.model)));
    const rows = candidates.map(row => {
      const scope = (!filters.center || row.CenterId === filters.center) && (!filters.country || row.Country === filters.country);
      let reason = !scope ? "Center/region filter excludes unverified or other attribution" : row.Reason;
      let baseline = null, target = null;
      if (!reason && !usable) reason = "Official prices unavailable/stale or invalid";
      if (!reason) {
        baseline = cost(row, findRate(catalog, row.Model, options.tier, day), options);
        if (baseline === null) reason = "Source tariff/tier/cache-write unavailable";
        else if (options.mode === "unchanged" || options.replacement === 0) target = baseline;
        else {
          let migrated = 0;
          for (const weight of options.weights.filter(entry => entry.weight > 0)) {
            const value = cost(row, findRate(catalog, weight.model, options.tier, day), options);
            if (value === null) { reason = "Destination tariff/tier/cache-write unavailable"; break; }
            migrated += value * weight.weight;
          }
          if (!reason) {
            let discount = 0;
            if (options.fusion && options.fusionPromotionEligible) {
              if (!catalog.fusion || !number(catalog.fusion.discount) || catalog.fusion.discount > 1 ||
                  !isDay(catalog.fusion.effectiveTo)) reason = "Fusion promotion terms unavailable";
              else if (day < catalog.fusion.effectiveTo) discount = catalog.fusion.discount;
            }
            if (!reason) target = baseline * (1 - options.replacement) +
              migrated * options.replacement * options.targetVolumeFactor * options.overhead *
              (options.fusion ? options.fusionExtraFactor : 1) * (1 - discount);
          }
        }
      }
      return { ...row, Reason: reason, BaselineUSD: reason ? null : baseline, TargetUSD: reason ? null : target,
        DeltaUSD: reason ? null : target - baseline };
    });
    const eligible = rows.filter(row => !row.Reason);
    const sum = key => eligible.length ? eligible.reduce((total, row) => total + row[key], 0) : null;
    const baseline = sum("BaselineUSD"), target = sum("TargetUSD");
    const excluded = [...new Set(rows.filter(row => row.Reason).map(row => row.Reason))].map(Reason =>
      ({ Reason, Rows: rows.filter(row => row.Reason === Reason).length }));
    return { state: usable ? fresh ? "ready" : "explicit-stale" : "unavailable",
      error: usable ? null : "Projections are N/D until official pricing is available or an old verified catalog is explicitly accepted.",
      baselineUSD: baseline, targetUSD: target, deltaUSD: baseline === null ? null : target - baseline,
      deltaPct: baseline > 0 ? (target - baseline) / baseline : null,
      baselineCredits: baseline === null ? null : baseline * 100, targetCredits: target === null ? null : target * 100,
      rows, excluded, eligibleRows: eligible.length, selectedRows: rows.length, valuationDay: day,
      knownInputTokens: candidates.filter(row => number(row.PromptTokens)).reduce((n, row) => n + row.PromptTokens, 0),
      knownOutputTokens: candidates.filter(row => number(row.OutputTokens)).reduce((n, row) => n + row.OutputTokens, 0),
      missingTokenRows: candidates.filter(row => !number(row.PromptTokens) || !number(row.OutputTokens)).length,
      attributionRows: candidates.filter(row => ["verified-client-center", "unique-api-user-billing"].includes(row.Attribution)).length };
  }
  return { aliases, usage, assumptions, findRate, cost, simulate };
});

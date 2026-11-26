(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CopilotProjections = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const isDay = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  function sourceKey(raw, canonical) {
    const hex = [...new TextEncoder().encode(canonical || raw)].map(byte => byte.toString(16).padStart(2, "0")).join("").toUpperCase();
    return (canonical ? "K:" : "U:") + hex;
  }
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
  function priceContext(contract, pricing, input) {
    const catalog = pricing?.catalog;
    const day = input.valuationDay === undefined ? catalog?.asOf?.slice(0, 10) || new Date().toISOString().slice(0, 10) : input.valuationDay;
    const age = catalog ? Date.now() - Date.parse(catalog.asOf) : NaN;
    const validStamp = Number.isFinite(age) && age >= 0 && new Date(catalog.asOf).toISOString().slice(0, 10) === catalog.asOf.slice(0, 10);
    const fresh = pricing?.state === "ready" && validStamp && age <= contract.maxAgeHours * 3600000;
    const usable = isDay(day) && catalog && catalog.version === contract.version && catalog.creditsPerUSD === 100 &&
      Array.isArray(catalog.rates) && validStamp && (fresh || input.allowStale === true);
    const cache = new Map();
    return { catalog, day, fresh, usable, rate(model, tier) {
      const key = JSON.stringify([model, tier]);
      if (!cache.has(key)) cache.set(key, usable ? findRate(catalog, model, tier, day) : null);
      return cache.get(key);
    } };
  }
  function modeledCosts(row, context, options) {
    let source = null, target = null, reason = "";
    if (!context.usable) reason = "Official prices unavailable/stale or invalid";
    else if (!number(row.PromptTokens) || !number(row.OutputTokens)) reason = "Missing/invalid token counters";
    else {
      source = cost(row, context.rate(row.Model, options.tier), options);
      if (!number(source)) reason = "Source tariff/tier/cache-write unavailable or non-finite";
      else if (options.mode === "unchanged" || options.replacement === 0) target = source;
      else {
        let migrated = 0;
        for (const weight of options.weights.filter(entry => entry.weight > 0)) {
          const value = cost(row, context.rate(weight.model, options.tier), options);
          if (!number(value)) { reason = "Destination tariff/tier/cache-write unavailable or non-finite"; break; }
          migrated += value * weight.weight;
        }
        if (!reason) {
          let discount = 0;
          if (options.fusion && options.fusionPromotionEligible) {
            const promo = context.catalog.fusion;
            if (!promo || !number(promo.discount) || promo.discount > 1 || !isDay(promo.effectiveTo)) reason = "Fusion promotion terms unavailable";
            else if (context.day < promo.effectiveTo) discount = promo.discount;
          }
          if (!reason) target = source * (1 - options.replacement) +
            migrated * options.replacement * options.targetVolumeFactor * options.overhead *
            (options.fusion ? options.fusionExtraFactor : 1) * (1 - discount);
          if (!reason && !number(target)) reason = "Invalid/non-finite token modeled amount";
        }
      }
    }
    return { source: reason ? null : source, target: reason ? null : target, reason };
  }
  function simulate(data, contract, pricing, input = {}, filters = {}) {
    let options;
    try { options = assumptions(contract, input); }
    catch (error) { return { state: "invalid", error: error.message, baselineUSD: null, targetUSD: null, deltaUSD: null, deltaPct: null, rows: [] }; }
    const context = priceContext(contract, pricing, input), { fresh, usable, day } = context;
    const mapped = aliases(contract, data.Info[0].Mode === "SAMPLE"), selectedModel = mapped.get(filters.model);
    const candidates = usage(data, contract).filter(row => (!filters.start || row.Day >= filters.start) &&
      (!filters.end || row.Day <= filters.end) && (!filters.user || row.User === filters.user) &&
      (!filters.model || (selectedModel ? row.Model === selectedModel : row.RawModel === filters.model)));
    const rows = candidates.map(row => {
      const scope = (!filters.center || row.CenterId === filters.center) && (!filters.country || row.Country === filters.country);
      let reason = !scope ? "Center/region filter excludes unverified or other attribution" : row.Reason;
      const modeled = reason ? { source: null, target: null, reason } : modeledCosts(row, context, options);
      const baseline = modeled.source, target = modeled.target;
      reason = modeled.reason;
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
  function billingBuckets(data, contract) {
    const names = aliases(contract, data.Info[0].Mode === "SAMPLE", true);
    const centers = new Map(data.Centers.map(row => [row.CenterId, row]));
    const tokens = usage(data, contract), groups = new Map(), tokenGroups = new Map();
    const residual = new Set((data.Users || []).filter(row => row.IsResidual).map(row => row.User));
    for (const row of tokens) {
      if (!row.Model) continue;
      const key = JSON.stringify([row.Day, row.User, row.Model]);
      if (!tokenGroups.has(key)) tokenGroups.set(key, { centers: new Map(), unresolved: false });
      const group = tokenGroups.get(key);
      if (!["verified-client-center", "unique-api-user-billing"].includes(row.Attribution)) group.unresolved = true;
      else {
        if (!group.centers.has(row.CenterId)) group.centers.set(row.CenterId, []);
        group.centers.get(row.CenterId).push(row);
      }
    }
    const sum = (rows, key) => {
      if (!rows.length || !rows.every(row => number(row[key]))) return null;
      const total = rows.reduce((n, row) => n + row[key], 0);
      return number(total) ? total : null;
    };
    for (const row of data.Billing) {
      if (row.UnitType !== "ai-credits" || row.Product !== "Copilot") continue;
      const model = names.get(row.Model) || null, source = model || row.Model;
      const key = JSON.stringify([row.Day, row.User, source, row.CenterId]);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    }
    return [...groups].map(([key, bills], RowId) => {
      const [Day, User, SourceModel, CenterId] = JSON.parse(key), Model = names.get(bills[0].Model) || null;
      const group = Model ? tokenGroups.get(JSON.stringify([Day, User, Model])) : null;
      const matched = group?.centers.get(CenterId) || [];
      const unresolved = group?.unresolved || false;
      const evidence = bills.every(row => row.Attribution === "API user filter") ||
        matched.length > 0 && matched.every(row => row.Attribution === "verified-client-center") &&
        !residual.has(User);
      const inputTokens = sum(matched, "PromptTokens"), outputTokens = sum(matched, "OutputTokens");
      const reason = !Model ? "Unknown exact Billing model alias" : !evidence ? "No audited user/center Billing evidence" :
        unresolved ? "Incomplete/ambiguous token center attribution" : !matched.length ? "No complete token bucket" :
          matched.some(row => row.Reason) ? "Incomplete token bucket: " + matched.find(row => row.Reason).Reason :
            inputTokens === null || outputTokens === null ? "Invalid/non-finite token bucket aggregate" : "";
      const keyValue = sourceKey(bills[0].Model, Model);
      return { RowId, Day, User, RawModel: bills[0].Model, Model, SourceModel, SourceKey: keyValue,
        SourceLabel: Model || `[Unknown exact alias] ${bills[0].Model} [${keyValue.slice(2)}]`, CenterId,
        Country: centers.get(CenterId)?.Country || null, BillingRows: bills.length, TokenRows: matched.length,
        ReportedCredits: sum(bills, "grossQuantity"), ReportedUSD: sum(bills, "grossAmount"),
        DiscountUSD: sum(bills, "discountAmount"), NetUSD: sum(bills, "netAmount"),
        PromptTokens: inputTokens, OutputTokens: outputTokens,
        Requests: sum(matched, "Requests"), CalibrationReason: reason,
        Attribution: !reason ? "complete-verified-bucket" : "unprojected-bucket" };
    });
  }
  function calibrate(data, contract, pricing, input = {}, filters = {}) {
    const names = aliases(contract, data.Info[0].Mode === "SAMPLE", true);
    const source = names.get(filters.model) || filters.model;
    const buckets = billingBuckets(data, contract).filter(row => (!filters.start || row.Day >= filters.start) &&
      (!filters.end || row.Day <= filters.end) && (!filters.user || row.User === filters.user) &&
      (!filters.center || row.CenterId === filters.center) && (!filters.country || row.Country === filters.country) &&
      (!filters.model || row.SourceModel === source));
    const start = filters.start || data.Info[0].StartDay, end = filters.end || data.Info[0].EndDay;
    const sources = new Map(data.SourceCoverage.map(row => [row.Day, row.BillingAvailable === true]));
    let complete = isDay(start) && isDay(end) && start <= end;
    if (complete) for (let t = Date.parse(start); t <= Date.parse(end); t += 86400000) {
      if (!sources.get(new Date(t).toISOString().slice(0, 10))) { complete = false; break; }
    }
    const sum = (rows, key) => {
      if (!rows.every(row => number(row[key]))) return null;
      const total = rows.reduce((n, row) => n + row[key], 0);
      return number(total) ? total : null;
    };
    const knownSum = key => {
      const known = buckets.filter(row => number(row[key]));
      return known.length || buckets.length === 0 ? sum(known, key) : null;
    };
    const partialCredits = knownSum("ReportedCredits"), partialUSD = knownSum("ReportedUSD");
    const missingAmountPair = buckets.some(row => !number(row.ReportedCredits) || !number(row.ReportedUSD));
    const baselineCredits = complete && !missingAmountPair ? partialCredits : null;
    const baselineUSD = complete && !missingAmountPair ? partialUSD : null;
    let options, optionError = "";
    try { options = assumptions(contract, input); }
    catch (error) { options = { ...contract.defaults, ...input }; optionError = error.message; }
    const replaceSource = options.replaceSourceKey || (options.replaceSourceModel ?
      sourceKey(options.replaceSourceModel, names.get(options.replaceSourceModel)) : "");
    const context = priceContext(contract, pricing, input);
    const rows = buckets.map(bucket => {
      const requested = options.mode !== "unchanged" && options.replacement !== 0 &&
        (!replaceSource || bucket.SourceKey === replaceSource);
      const identity = !requested || !optionError && options.mode === "target" && bucket.Model &&
        (names.get(options.targetModel) || options.targetModel) === bucket.Model &&
        options.targetVolumeFactor === 1;
      let reason = "", ratio = identity ? 1 : null, tokenSource = null, tokenScenario = null;
      if (!number(bucket.ReportedCredits) || !number(bucket.ReportedUSD)) reason = "Missing/invalid reported Billing amount";
      else if (!identity) {
        reason = optionError || bucket.CalibrationReason;
        if (!reason) {
          const modeled = modeledCosts(bucket, context, options);
          tokenSource = modeled.source; tokenScenario = modeled.target;
          if (!number(tokenSource) || !number(tokenScenario)) reason = modeled.reason || "Invalid/non-finite token modeled amount";
          else if (tokenSource > 0) ratio = tokenScenario / tokenSource;
          else if (tokenScenario === 0 && bucket.ReportedCredits === 0 && bucket.ReportedUSD === 0) ratio = 1;
          else reason = "Zero modeled source denominator for a nonzero destination or reported consumption";
        }
      }
      if (!reason && (!number(ratio) || !number(bucket.ReportedUSD * ratio) || !number(bucket.ReportedCredits * ratio))) {
        reason = "Invalid/non-finite calibrated amount or ratio";
      }
      let coverageReason = reason || bucket.CalibrationReason;
      if (!coverageReason) {
        const sourceCost = optionError ? null : cost(bucket, context.rate(bucket.Model, options.tier), options);
        if (!number(sourceCost)) coverageReason = "Source token tariff not verified; actual amount retained if unchanged";
        else if (sourceCost === 0 && (bucket.ReportedCredits > 0 || bucket.ReportedUSD > 0)) coverageReason = "Zero source modeled denominator";
      }
      return { ...bucket, RequestedChange: requested && !identity, Reason: reason,
        CoverageReason: coverageReason,
        Ratio: ratio, TokenBaselineUSD: tokenSource, TokenScenarioUSD: tokenScenario,
        BaselineUSD: bucket.ReportedUSD, BaselineCredits: bucket.ReportedCredits,
        TargetUSD: reason ? null : bucket.ReportedUSD * ratio,
        TargetCredits: reason ? null : bucket.ReportedCredits * ratio,
        DeltaUSD: reason ? null : bucket.ReportedUSD * (ratio - 1) };
    });
    const valid = rows.filter(row => !row.Reason), failed = rows.filter(row => row.Reason);
    const targetUSD = complete && !failed.length ? sum(rows, "TargetUSD") : null;
    const targetCredits = complete && !failed.length ? sum(rows, "TargetCredits") : null;
    const invalidTotals = !number(partialCredits) || !number(partialUSD) ||
      complete && !failed.length && (!number(targetUSD) || !number(targetCredits));
    const unprojected = rows.filter(row => row.CoverageReason);
    const unresolved = sum(failed, "ReportedCredits");
    return { basis: "reported-billing", state: invalidTotals ? "invalid-totals" : !complete ? "partial-billing" : failed.length ? "partial" :
      !context.fresh && rows.some(row => row.RequestedChange) ? "explicit-stale" : "ready",
      error: invalidTotals ? "Reported or calibrated aggregate is missing or outside the finite numeric range; total is N/D." :
        !complete ? "Billing does not cover the full selection; total is N/D." :
        failed.length ? "Some requested buckets cannot be calibrated. Total estimate is N/D; partial values are not a forecast." : null,
      baselineUSD, baselineCredits, targetUSD, targetCredits,
      deltaUSD: baselineUSD !== null && targetUSD !== null ? targetUSD - baselineUSD : null,
      deltaCredits: baselineCredits !== null && targetCredits !== null ? targetCredits - baselineCredits : null,
      deltaPct: baselineCredits > 0 && targetCredits !== null ? (targetCredits - baselineCredits) / baselineCredits : null,
      deltaUSDPct: baselineUSD > 0 && targetUSD !== null ? (targetUSD - baselineUSD) / baselineUSD : null,
      partialReportedUSD: partialUSD, partialReportedCredits: partialCredits,
      partialTargetUSD: valid.length ? sum(valid, "TargetUSD") : null,
      partialTargetCredits: valid.length ? sum(valid, "TargetCredits") : null,
      unprojectedCredits: sum(unprojected, "ReportedCredits"), unresolvedChangeCredits: unresolved,
      unchangedCredits: sum(rows.filter(row => !row.RequestedChange && !row.Reason), "ReportedCredits"),
      changedCredits: sum(rows.filter(row => row.RequestedChange && !row.Reason), "ReportedCredits"),
      reportedDiscountUSD: sum(rows, "DiscountUSD"), reportedNetUSD: sum(rows, "NetUSD"),
      rows, selectedRows: rows.length, eligibleRows: rows.filter(row => !row.CoverageReason).length,
      changedRows: rows.filter(row => row.RequestedChange).length, unresolvedRows: failed.length,
      excluded: [...new Set(unprojected.map(row => row.CoverageReason))].map(Reason =>
        ({ Reason, Rows: unprojected.filter(row => row.CoverageReason === Reason).length })),
      knownInputTokens: sum(rows, "PromptTokens"), knownOutputTokens: sum(rows, "OutputTokens"),
      missingTokenRows: rows.filter(row => !number(row.PromptTokens) || !number(row.OutputTokens)).length,
      attributionRows: rows.filter(row => !row.CalibrationReason).length,
      valuationDay: context.day };
  }
  return { aliases, usage, assumptions, findRate, cost, simulate, sourceKey, billingBuckets, calibrate };
});

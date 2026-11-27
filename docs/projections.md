# Projections: reported Billing baseline, calibrated alternatives

The primary baseline is **reported Copilot Billing consumption**: gross AI credits from `grossQuantity` and gross USD from `grossAmount`, summed **independently** under the same period/user/center/source-model filters. **No changes equals that reported baseline**, not a token-priced reconstruction. Zero replacement and a same-target identity also keep it unchanged, without requiring live pricing.

Alternatives are approximate **Billing-calibrated estimates**. The token model is a relative-cost hypothesis, not actual spend. Projections do not predict your net invoice, change GitHub policy or call a model. Actual discounts and net amounts remain separate and are never scenario-scaled. A real net invoice of zero is not guaranteed cash savings.

## How calibration works

Group the original Billing rows once by **day + user + explicitly aliased source model + historical center**. Aggregate the complete matching ClientModels token bucket before applying filters or weights. Compute:

```text
ratio = modeled scenario USD / modeled source USD (same complete token bucket and assumptions)
estimated bucket credits = reported bucket grossQuantity × ratio
estimated bucket USD     = reported bucket grossAmount × ratio
```

Credits and USD are independent reported anchors; do not convert one into the other. Several clients or Billing SKU rows in one bucket do not duplicate the Billing amount. No reported money is allocated among requests or token rows.

**Fictional example:** A reports 100 credits, B reports 40. For A, the comparable token estimate is 14 USD at its source tariff and 2.8 USD at the destination tariff (ratio 0.2). Replacing **only A** gives 20 estimated credits + B's untouched 40 = **60**, against a reported baseline of **140**. Replacing half of A gives 100 total credits. If A reports 1.30 USD and B 0.40 USD, the same complete change estimates 0.66 USD—not 0.60 USD derived from the credit denomination.

The **Source model (scope filter)** limits both baseline and scenario. The separate **Models to replace (scenario)** control selects All or one model inside that scope. This lets you change A while preserving B in the total.

## Prices really refresh

Docker fetches the two fixed, anonymous **official Copilot** sources when you open **Projections** or choose **Refresh official prices**:

- https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing.md
- https://docs.github.com/en/copilot/concepts/models/copilot-fusion.md

Power BI imports those same sources on **Refresh**. It is not a push feed or a continuously running price monitor. The public pricing queries do not depend on your business dataset, send no usernames/tokens/report values in URLs, and do not use a private demo endpoint. Allow anonymous access to the public source if Power BI asks; the business-report credential remains separate. Only Projections needs pricing internet access; the original pages and local JSON import remain available.

The view shows source URLs, **last checked**, catalog **AsOf**, parser/alias/calibration versions, a content fingerprint and effective dates. Docker also retains a SHA-256 digest. The non-cryptographic Adler-32 fingerprint identifies source changes, not authenticity. A fetch/parser error makes **required alternative ratios N/D**, never a zero price or silently current old prices. **Reported Billing and no changes remain available.** Docker offers an explicit last-verified-catalog opt-in. Power BI loads a pricing-error status and no prices after a failed pricing refresh; it does not silently retain a “latest” alternative.

Tariffs are USD per **one million text tokens**. The secondary token-only diagnostic verifies the published denomination (currently $0.01 per AI credit); primary credits always come from Billing, not that conversion. Provider APIs, GitHub Models prices, images, legacy request multipliers and review estimates are not substituted.

## Comparable scenarios

Use the same period, users, historical center and **source model** for the baseline and destination:

- **No changes** is the reported identity case, including Billing without token/pricing coverage. Zero replacement also keeps the baseline unchanged.
- **Target model** substitutes the selected fraction in the requested Billing buckets. A same-model identity requires unchanged effective volume; a different multiplier is still an estimated change.
- **Custom mixture EXAMPLE** is an editable list/weight example (technical key `recommended`), **not advice or a task-quality recommendation**.

**Fusion Standard/High/Max projections and their promotion/extra-call controls are removed.** The routing algorithm is unknown, so no hypothetical Fusion routing or promotional savings are estimated. Reported Fusion usage stays in Billing and the baseline, and official model tariffs remain available. Legacy `fusion-*` mixture entries cannot reactivate these modes and are ignored when loading a valid mixture file. Keep a valid `recommended` entry for a custom mixture, or use No changes / Target model; no business-data redownload is needed.

`projections/contract.json` versions the exact aliases and example mixtures. Docker lets you edit mixture JSON. In Power BI Desktop, leave the optional **ProjectionMixFile** parameter blank for embedded examples, or set an absolute path to the included **`projections/mixes.json`** (or your copy) and Refresh after edits. `ProjectionMixJSON` is an internal query, not the field to fill in. A nonblank missing/invalid file is an explicit error, never a default fallback. The separate cloud generator keeps embedded mixtures with no laptop-file dependency. See the [file setup steps](local-kit.md#optional-example-mixtures-from-a-json-file). Weights must be non-negative and sum to one; overhead and optional target-volume multipliers are disclosed assumptions, not measured efficiencies.

**Delta = estimated scenario − reported baseline.** Negative means lower estimated gross consumption, not guaranteed net savings. Credits and USD have their own deltas/percentages; a zero reported denominator gives N/D. The total estimate is shown only if **every requested change** is resolvable. Partial components are labeled **NOT a complete forecast**, never compared as a successful smaller total against the whole baseline.

## Cache, context and promotions

Total input tokens are partitioned into **disjoint** uncached, cached-read and cache-write shares. Read + write must not exceed 100%. A separately priced write bucket uses its published write tariff. **Not applicable** for a separate write tariff means ordinary input pricing for that bucket, not free input; an unknown/missing required price remains N/D. Input is never charged twice.

Actual cache split and request-level context sizes are not in the current aggregate source. Select a context tier explicitly: **do not infer it from average tokens per request**. Models without the selected tier are excluded. The rate table exposes each model's threshold. The valuation day applies current published/announced tariffs to observed volume; it is **not historical billing reconstruction** or a guarantee of future prices.

Published model tariffs have effective-date boundaries. Known successor prices are applied only from their announced date; an expired price with no published successor becomes unavailable. No Fusion-specific promotional discount or extra-call multiplier is applied to an estimate.

## Coverage and historical attribution

Billing without matching tokens, aliases or usable tariffs **stays in the reported baseline**. If untouched, it also stays actual in the scenario and is labeled **unprojected**. If you request a change to it, the full estimate becomes **N/D / partial**, with its unresolved reported credits visible. It is never dropped, set to zero or silently carried forward as though calibrated.

Any missing input/output token value, unknown/custom hosting or unresolved center in a required bucket prevents calibrating only its known subset. A positive reported amount with zero modeled source cost has no reliable ratio; zero-source/positive-target pricing also gives N/D even when reported spend is zero. Valid known zeros remain zero; missing Billing coverage yields N/D totals with observed partial amounts separate. Non-finite amounts/ratios are explicitly invalid. Requests are diagnostics, **never a money allocator**.

If any reported bucket is missing its gross-credit/gross-USD pair, **both baseline totals and the complete scenario are N/D**. Only explicitly labeled partial-known amounts sum the available values for each unit separately. An unknown unresolved credit quantity is N/D, not zero; the bucket remains counted as unresolved.

Attribution is resolved **before** center/country filters. A verified non-virtual ClientModels center is kept. Otherwise, only a **unique** API-user-filter billing match at **day + user + explicitly aliased canonical model** can supply a center. Multiple centers, missing aliases or current-only memberships do not backdate historical tokens. A unique billing center `none` is explicit enterprise-only usage, **not a country or a named center**. No proportional token/credit allocation is performed.

Projection-only source keys distinguish known canonical names from exact unknown raw aliases using tagged UTF-8 hex. This prevents Power BI's case-insensitive model collation from silently matching an unknown case variant or rejecting the derived dimension. Unknown labels are explicit and their reported amounts remain in the baseline.

The 21-array downloaded JSON stays compatible. Power BI adds derived Projection tables and an eleventh native page; the original ten pages and numeric finance alert cards are unchanged. SAMPLE volume/model mappings are fictional demonstration aliases, clearly labeled. No quality, equivalence, productivity, ROI or unverified pool-balance inference is made.

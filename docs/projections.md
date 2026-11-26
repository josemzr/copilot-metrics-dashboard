# Projections: current public prices, explicit assumptions

Projections reprice **ClientModels text-token volume** under the same assumptions on both sides. They do not predict your invoice, change GitHub policy or call a model. Gross/discount/net amounts reported by the billing API stay separate. A real net invoice of zero is not a cash-savings opportunity.

## Prices really refresh

Docker fetches the two fixed, anonymous **official Copilot** sources when you open **Projections** or choose **Refresh official prices**:

- https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing.md
- https://docs.github.com/en/copilot/concepts/models/copilot-fusion.md

Power BI imports those same sources on **Refresh**. It is not a push feed or a continuously running price monitor. The public pricing queries do not depend on your business dataset, send no usernames/tokens/report values in URLs, and do not use a private demo endpoint. Allow anonymous access to the public source if Power BI asks; the business-report credential remains separate. Only Projections needs pricing internet access; the original pages and local JSON import remain available.

The view shows source URLs, **last checked**, catalog **AsOf**, parser/alias versions, a content fingerprint and effective dates. Docker also retains a SHA-256 digest. The non-cryptographic Adler-32 fingerprint in both implementations identifies source changes, not authenticity. A fetch/parser error gives **N/D**, never a zero price or silently current old prices. Docker offers an explicit, clearly labeled last-verified-catalog opt-in. Power BI loads a pricing-error status and no prices on a failed pricing refresh; it does not silently retain a “latest” projection.

Tariffs are USD per **one million text tokens**. AI credits are derived only after verifying the published denomination (currently $0.01 per AI credit). Provider APIs, GitHub Models prices, images, legacy request multipliers and review estimates are not substituted.

## Comparable scenarios

Use the same period, users, historical center and **source model** for the baseline and destination:

- **No changes** is the identity case. Zero replacement also keeps the baseline unchanged.
- **Target model** substitutes the selected fraction of eligible volume.
- **Recommended-set EXAMPLE** is an editable list/weight example, **not advice or a task-quality recommendation**.
- **Fusion Standard / High / Max HYPOTHESIS** combines an example mixture with explicit token overhead. It is not GitHub's actual router. `SelectionMode=auto` does not identify Fusion.

`projections/contract.json` versions the exact aliases and example mixtures. Docker lets you edit mixture JSON; Power BI's `ProjectionMixJSON` text parameter holds the same configurable examples. Weights must be non-negative and sum to one; overhead and optional target-volume multipliers are disclosed assumptions, not measured efficiencies.

**Delta cost = scenario − baseline.** Negative means lower *modeled gross cost*. Percentage change is N/D if baseline cost is zero. Compare two modeled totals on their **common eligible rows**, never a partly modeled destination against the full actual bill.

## Cache, context and promotions

Total input tokens are partitioned into **disjoint** uncached, cached-read and cache-write shares. Read + write must not exceed 100%. A separately priced write bucket uses its published write tariff. **Not applicable** for a separate write tariff means ordinary input pricing for that bucket, not free input; an unknown/missing required price remains N/D. Input is never charged twice.

Actual cache split and request-level context sizes are not in the current aggregate source. Select a context tier explicitly: **do not infer it from average tokens per request**. Models without the selected tier are excluded. The rate table exposes each model's threshold. The valuation day applies current published/announced tariffs to observed volume; it is **not historical billing reconstruction** or a guarantee of future prices.

Promotions have effective-date boundaries. Known published successor prices are applied only from their announced date; an expired promotion with no published successor becomes unavailable. Fusion's published discount is only applied if you explicitly assume paid-plan eligibility and the valuation date is eligible. It does not imply guaranteed net savings; extra model calls/overhead can increase cost.

## Coverage and historical attribution

Unknown exact models, custom/BYOK/unknown hosting, unsupported tariffs/tiers, missing input/output counters and unavailable source days are excluded and counted. Zero observed tokens/prices are valid zeros; missing values are not. Requests are shown for coverage, **never used to allocate credits or costs**.

Source-row and known-token denominators are labeled **before center filtering**; comparable modeled volume is after that filter and eligibility checks. Other centers deliberately excluded by your filter are listed separately from unmodellable rows in the web exclusions. These are not percentages of coverage inside the chosen center.

Attribution is resolved **before** center/country filters. A verified non-virtual ClientModels center is kept. Otherwise, only a **unique** API-user-filter billing match at **day + user + explicitly aliased canonical model** can supply a center. Multiple centers, missing aliases or current-only memberships do not backdate historical tokens. A unique billing center `none` is explicit enterprise-only usage, **not a country or a named center**. No proportional token/credit allocation is performed.

The 21-array downloaded JSON stays compatible. Power BI adds derived Projection tables and an eleventh native page; the original ten pages and numeric finance alert cards are unchanged. SAMPLE volume/model mappings are fictional demonstration aliases, clearly labeled. No quality, equivalence, productivity, ROI or unverified pool-balance inference is made.

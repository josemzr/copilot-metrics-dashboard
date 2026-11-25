# Power BI

Open **`powerbi/CopilotMetrics.pbip`** in a recent **Power BI Desktop on Windows**. Enable Power BI project / enhanced report format support if your Desktop version requires it.

The project embeds only the fictional SAMPLE data. Its ten pages cover overview, billing, adoption/models, budgets/pools, source coverage, licenses/adoption, code/acceptance, users, 14-day model blocks and surfaces/telemetry coverage.

## Use a private REAL snapshot

1. Enable the [collector](github-app.md) and wait for a successful run.
2. Export the last validated JSON to a private Windows-accessible folder **outside this repository**:

```sh
mkdir -p ../copilot-metrics-private
docker compose cp web:/data/dataset.json ../copilot-metrics-private/dataset.json
```

3. In Desktop, open **Transform data → Manage parameters**. Set `DataMode` to `REAL` and `DataRootPath` to the folder containing `dataset.json`, then refresh. The model rejects a mode mismatch.

The container **does not run Power BI Desktop or Power BI Service**. A file copied once does not update automatically. For scheduled Service refresh, provide an accessible private data source and the appropriate gateway or deployment; the Service cannot fetch `localhost` from your laptop. These deployment steps are not automated here.

The [optional Azure adapter](azure.md#choose-the-power-bi-authentication-mode) includes a separate static-URL model generator. Its default Function-key / Web API mode is for **Desktop/Excel, not Power BI Service**: Microsoft's [Web connector documentation](https://learn.microsoft.com/en-us/power-query/connectors/web/web) excludes Service Web API authentication. Explicit `basic-gateway` mode targets a separately deployed APIM endpoint with Basic credentials in the Service store; gateway deployment and end-to-end refresh are not verified here. Provisioning, publishing and credentials remain operator steps; the checked-in SAMPLE model is unchanged.

## Read the numbers carefully

N/D / blank means missing or unsupported, not zero. License snapshots are not historical rosters. Activity and acceptance are usage signals, not individual productivity or ROI. Fact tables have separate grains: do not add Metrics, ModelFeatures, ClientModels and CLI together. Models join only by their exact identifiers; AI credits use billing quantities, never request counts or proportional allocation.

The overview shows each billed model's **gross USD, discounts USD and net USD** together, so fully discounted usage remains visible even when net cost is zero. These are the API's monetary amounts, not a conversion from credits. The 14-day model chart uses the built-in stacked-column visual.

An empty diagnostic count or residual is **0 only when its source covers the complete selection**; missing coverage stays blank/N/D. A ratio with no denominator and a missing budget-consumed amount remain N/D. Numeric card displays render N/D without changing the numeric measures used by tables and charts. **Client telemetry present rate (known-status user-day rows)** means TRUE / (TRUE + FALSE): one present and twenty absent rows is 4.8%, not a percentage of users. Unknown status is excluded; zero known rows gives N/D.

For classic Power BI dashboard alerts, pin the overview **Gross AI credits** or **Net cost USD** card: both keep their numeric base measure, including a valid zero. Cards using N/D text displays are not numeric and do not support classic numeric alerts.

Rebuild the neutral project with `python3 scripts/build_powerbi.py`. This regenerates SAMPLE only. Structural and TOM validation cannot replace opening Desktop and checking queries, visuals and refresh with your actual environment.

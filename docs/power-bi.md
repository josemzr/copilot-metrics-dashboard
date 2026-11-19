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

## Read the numbers carefully

N/D / blank means missing or unsupported, not zero. License snapshots are not historical rosters. Activity and acceptance are usage signals, not individual productivity or ROI. Fact tables have separate grains: do not add Metrics, ModelFeatures, ClientModels and CLI together. Models join only by their exact identifiers; AI credits use billing quantities, never request counts or proportional allocation.

Rebuild the neutral project with `python3 scripts/build_powerbi.py`. This regenerates SAMPLE only. Structural and TOM validation cannot replace opening Desktop and checking queries, visuals and refresh with your actual environment.

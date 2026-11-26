# Copilot Metrics

A local dashboard for GitHub Copilot usage, AI credits, models and data coverage, with an optional Power BI report. No account is needed to try it.

## Start here

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), then run:

```sh
git clone https://github.com/josemzr/copilot-metrics-dashboard.git
cd copilot-metrics-dashboard
docker compose up --build
```

Open **http://localhost:8080**. **SAMPLE** usage is fictional. The original views make no GitHub report calls, need no keys and create no paid usage; only optional **Projections** checks public official pricing. Stop it with `Ctrl+C`, then `docker compose down`. Use `PORT=8081 docker compose up --build` if port 8080 is busy.

Filter by region, cost center, model and dates. Explore **Overview, Users, Daily, Models and Data quality**. Export filtered CSV tables or SVG/PNG charts. **Import JSON** opens a file locally without uploading it. **Projections** starts with reported Billing: no changes equals actual gross consumption. Alternatives are approximate, Billing-calibrated scenarios using current official tariffs, not promised invoice savings. Only those tariff checks need internet.

## Your own data

Prefer manual downloads with your own GitHub account and one JSON for both viewers? Use the **[manual local kit](docs/local-kit.md)**: no Azure, App or PEM, isolated Docker on port 8081, and Power BI Desktop Refresh on Windows. Only the downloader needs GitHub permissions, not people opening the JSON.

In Power BI Desktop, **DataRootPath** is the private data folder. Leave **ProjectionMixFile** blank for default examples, or point it at the editable **`projections/mixes.json`** file. The kit guide explains the [optional file and recovery steps](docs/local-kit.md#optional-example-mixtures-from-a-json-file); no large JSON paste is needed.

**Scheduled REAL collection** is also opt-in. A [GitHub App](docs/github-app.md) collects read-only reports into a private Docker volume. The browser reads that stored snapshot, not GitHub or the App key. Failed collection keeps the last valid snapshot and shows an error.

```text
GitHub -> collector -> stored JSON -> web dashboard
                                -> Power BI
```

The collector runs at startup and once a day by default. GitHub reports are published daily, not live; collection ends **two full UTC days before today**. The browser checks REAL snapshots every minute; **Refresh** checks immediately.

**N/D means unavailable, not zero.** A license snapshot is not license history. Activity is not productivity, ROI or code quality. AI credits are not requests; credits are never divided between models using activity ratios. ROI, cohorts and pull-request outcomes are not implemented.

[GitHub App setup](docs/github-app.md) · [Power BI](docs/power-bi.md) · [API and JSON examples](docs/api-examples.md)

For collection without a laptop, see the [optional Azure adapter](docs/azure.md). It needs separately configured paid infrastructure; Docker SAMPLE does not use Azure.

## Development

Development checks use Python 3.11+, Node.js 20+ and the declared test dependencies. Use your organization's approved package index if required.

```sh
python3 -m pip install -r requirements-dev.txt
python3 scripts/build_powerbi.py
python3 web/build.py
python3 -m unittest discover -s tests
node --test web/tests/core.test.cjs web/tests/projections.test.cjs web/tests/calibration.test.cjs
```

Power BI preserves its 10 original pages, 21 source tables, 37 original relationships and 90 analytical measures, plus hidden numeric-card displays for N/D. An eleventh **[Projections](docs/projections.md)** page adds derived tables and anonymous live-price imports without changing the downloaded JSON. [Validation](validation/README.md) checks its file structure; Power BI Desktop is needed to verify rendering and DAX execution.

# Copilot Metrics

A local dashboard for GitHub Copilot usage, AI credits, models and data coverage, with an optional Power BI report. No account is needed to try it.

## Start here

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), then run:

```sh
git clone https://github.com/josemzr/copilot-metrics-dashboard.git
cd copilot-metrics-dashboard
docker compose up --build
```

Open **http://localhost:8080**. Everything marked **SAMPLE** is fictional. The demo makes no GitHub calls, needs no keys and creates no paid usage. Stop it with `Ctrl+C`, then `docker compose down`. Use `PORT=8081 docker compose up --build` if port 8080 is busy.

Filter by region, cost center, model and dates. Explore **Overview, Users, Daily, Models and Data quality**. Export filtered CSV tables or SVG/PNG charts. **Import JSON** opens a file locally without uploading it.

## Your own data

**REAL** is opt-in. A [GitHub App](docs/github-app.md) collects read-only reports into a private Docker volume. The browser reads that stored snapshot, not GitHub or the App key. Failed collection keeps the last valid snapshot and shows an error.

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
node --test web/tests/core.test.cjs
```

The generated Power BI project includes 10 pages, 21 tables, 37 relationships and 90 measures. [Validation](validation/README.md) checks its file structure; Power BI Desktop is needed to verify rendering and DAX execution.

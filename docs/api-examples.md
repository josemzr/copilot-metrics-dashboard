# API and JSON examples

The demo needs no API calls. For real data, prefer the built-in collector: it creates a short-lived GitHub App installation token and keeps it away from the browser.

## Three optional cURL steps

The collector does all of this for you. To see the individual pieces, use its existing App signer as a small command-line helper. It creates a short-lived installation token and passes the header straight to cURL's standard input: no token to find, paste or put in process arguments. **Never run the header helper on its own**, use shell tracing or publish the outputs.

First install `requirements.txt` using your approved Python package index and set your own App details. These values are deliberately fictitious. Keep the key and output folder outside this repository.

```sh
export GITHUB_APP_ID=000000
export GITHUB_INSTALLATION_ID=000000
export GITHUB_APP_PRIVATE_KEY_FILE=/path/outside/project/github-app-private-key.pem
ENTERPRISE=example-enterprise
PRIVATE_DIR=../copilot-metrics-private
mkdir -p "$PRIVATE_DIR"
chmod 700 "$PRIVATE_DIR"
```

### 1. Ask for the daily report

```sh
python3 scripts/collect.py --authorization-header |
  curl --fail-with-body --silent --show-error --proto '=https' \
    --header @- \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2026-03-10' \
    --output "$PRIVATE_DIR/report.json" \
    "https://api.github.com/enterprises/$ENTERPRISE/copilot/metrics/reports/users-1-day?day=2026-11-01"
```

Choose an available report day. `report.json` is **JSON metadata**, not the user rows. Its temporary `download_links` are sensitive.

### 2. Download the report, without the App header

This example downloads the first part. The Python line reads its URL privately and sends it to cURL through standard input, not a command argument.

```sh
python3 -c 'import json,sys; links=json.load(open(sys.argv[1]))["download_links"]; print("url = " + json.dumps(links[0]))' "$PRIVATE_DIR/report.json" |
  curl --fail --silent --show-error --proto '=https' \
    --config - --output "$PRIVATE_DIR/users.ndjson"
```

There is **no Authorization header** and no redirect-following flag here. Repeat for other parts if present, or use the collector to handle them all. The downloaded file is **NDJSON**: one JSON value per line. The collector also enforces public HTTPS hosts, size/part limits, bounded retries and pagination.

### 3. Read the day's AI credit billing

```sh
python3 scripts/collect.py --authorization-header |
  curl --fail-with-body --silent --show-error --proto '=https' \
    --header @- \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2026-03-10' \
    --output "$PRIVATE_DIR/billing.json" \
    "https://api.github.com/enterprises/$ENTERPRISE/settings/billing/ai_credit/usage?year=2026&month=11&day=1&cost_center_id=none"
```

This returns **billing JSON**, not activity rows. `none` means enterprise usage without a cost center; substitute your own cost-center ID privately when needed. Neither report downloads nor these read calls generate AI usage.

Other read endpoints used by the collector:

```text
GET /enterprises/{enterprise}/settings/billing/cost-centers
GET /enterprises/{enterprise}/settings/billing/cost-centers/{id}
GET /enterprises/{enterprise}/settings/billing/budgets
GET /enterprises/{enterprise}/settings/billing/ai_credit/usage?year=2026&month=11&day=1&cost_center_id=none
GET /enterprises/{enterprise}/copilot/billing/seats
```

The collector follows list/resource pagination. Billing extracts are daily, canonical totals are retained, and unavailable telemetry is not fabricated. API responses can change: unexpected contracts fail explicitly without replacing the last valid snapshot.

## Dashboard JSON

The dashboard and Power BI consume one **JSON object of table arrays**, not raw NDJSON. `Info` contains one row with `Mode`, `Label`, `AsOf`, `StartDay` and `EndDay`; separate coverage tables say which sources and license history are available. Table names and field names are English, case-sensitive contracts.

Generate a complete working example with `python3 scripts/make_sample.py`. Its output is `data/sample/dataset.json`. Import that file in the dashboard, or inspect it to understand the table shape. No paid traffic generator or cloud deployment is needed.

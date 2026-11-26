# Manual local kit

**One private `dataset.json`, two manual viewers:** Power BI Desktop or Docker. No Azure, GitHub App or PEM is needed. Viewers never request private GitHub business reports. Only **Projections** checks anonymous public GitHub pricing when opened/refreshed; nothing is scheduled in this mode.

Run commands from the project or unpacked kit folder. Prerequisites are **PowerShell 7** (`pwsh`) and **Python 3.11+** (`python3` or `python` on PATH). REAL downloads also need **GitHub CLI** (`gh`). Install these yourself; the scripts install nothing. Docker Desktop is only needed for the browser viewer. **Power BI Desktop is Windows-only**; Linux can download the JSON and use Docker, or transfer the private JSON to Windows.

## REAL Power BI: download, point at the folder, refresh

1. Sign in with your own authorized account:

```powershell
gh auth login --hostname github.com --web --scopes "read:enterprise,manage_billing:enterprise"
```

2. Download explicitly, replacing the fictitious account/enterprise and dates:

```powershell
pwsh -NoProfile -File ./scripts/download.ps1 -GitHubUser your-login -Enterprise example-enterprise -StartDay 2026-11-15 -EndDay 2026-11-18 -OutputDirectory "../private real data"
```

3. From the **same working folder**, print the absolute folder you just downloaded to:

```powershell
pwsh -NoProfile -Command "(Resolve-Path '../private real data').Path"
```

4. On **Windows**, open `powerbi/CopilotMetrics.pbip`. Go to **Transform data → Manage parameters / Edit parameters**. Change **DataMode** from **SAMPLE** to **REAL**. Copy the **exact printed folder path** into **DataRootPath**, for example `C:/CopilotMetrics/private real data`. It is the **ABSOLUTE FOLDER containing `dataset.json`**, **not** the JSON filename, a relative path, or a URL. Do not copy the command's quotation marks into the parameter dialog. **Leave the optional ProjectionMixFile blank** to use the embedded example mixtures, or set the absolute JSON **file** path described below.
5. Choose **Apply / Close & Apply**, then **Refresh**. Confirm the report's **REAL** source label and selected coverage dates. Leave the JSON private and outside the kit folder.

These are single-line commands usable from Bash or PowerShell. Power BI refresh reads your local JSON; it does **not** run the downloader. Projections imports current public Copilot pricing at Refresh, not continuously. If prompted for either of the two official public documentation sources, select **Anonymous → Connect** (internet required). Do **not** supply a GitHub token, business OAuth credential or private JSON URL for the pricing sources. No private report values are sent to the pricing site.

## Optional example mixtures from a JSON file

**ProjectionMixFile can be blank:** that explicitly selects the example mixtures embedded in the model. Nothing needs to be pasted into a large JSON field.

To customize them, use the included **`projections/mixes.json`**, which contains only the four example mixtures, not tariffs or the entire contract:

1. Open that file in a text editor and save your changes as **UTF-8 JSON**. Keep the `recommended`, `fusion-standard`, `fusion-high` and `fusion-max` example entries; each has `overhead` and a `weights` list of `model` / `weight` pairs.
2. From the unpacked kit folder, print its absolute **file path**:

```powershell
pwsh -NoProfile -Command "(Resolve-Path './projections/mixes.json').Path"
```

3. Copy the printed path into **ProjectionMixFile → Current Value** in **Manage parameters**, for example `C:/CopilotMetrics/projections/mixes.json`. Enter the **absolute file path**, not the folder, JSON contents, a URL, a Power Query expression or extra enclosing quotes.
4. Choose **Close & Apply → Refresh**. After editing the file again, choose **Refresh** to reload it. If you use a copy elsewhere, resolve and enter that copy's absolute path instead.

**DataRootPath is a folder; ProjectionMixFile is a file.** `ProjectionMixJSON` is now an internal query, not a parameter you fill in. This file option is for Desktop; the separate cloud model generator keeps embedded mixtures and does not read a laptop file.

Only a blank parameter selects embedded defaults. A missing file, an empty file or invalid JSON produces an explicit Refresh error, **not** a fallback to defaults. Weights must be non-negative and sum to one; overhead must be between 0 and 10. These mixtures are editable examples, not recommendations or measured Fusion routing.

For a clean check after upgrading to **1.2.1**, unpack it into a **new folder** and open its PBIP with **DataMode = SAMPLE**, the default **DataRootPath**, and **ProjectionMixFile blank**. After a successful **Close & Apply → Refresh**, repeat REAL steps 4–5 with your existing private data folder; optionally point ProjectionMixFile at your saved custom mixture file. Keep private JSON and customized files; do not overwrite your old kit or data folder. Older kits use the JSON-text parameter and do not support this blank/file-path option.

## Try it offline

```powershell
pwsh -NoProfile -File ./scripts/download.ps1 -Sample -OutputDirectory "../private sample data"
docker compose -p copilot-metrics-manual -f compose.manual.yaml --profile manual up --build
```

Open **http://localhost:8081**, choose **Import JSON**, and select `dataset.json` from that folder. SAMPLE is synthetic. The bundled `powerbi/CopilotMetrics.pbip` opens directly on Windows with the same generated SAMPLE scenario embedded for an offline check.

This Docker mode has **no worker, scheduler, credentials, data volume or automatic refresh**. Import happens only in browser memory, never uploads the file, and Refresh only recalculates the loaded JSON. Import a newly downloaded file to update it. The original views make no GitHub calls; opening **Projections** or its price-refresh button fetches only official public pricing. Stop this separate viewer with:

```powershell
docker compose -p copilot-metrics-manual -f compose.manual.yaml --profile manual down
```

This does not touch any separate Docker setup on port 8080.

## Who needs GitHub access

**Only the person running a REAL download.** Anyone who receives the JSON and opens it in Power BI or Docker needs no GitHub account, role, token or consent. The file may contain private usernames and billing data: share/store it privately, never in this repository.

For the complete enterprise export, **Enterprise Billing Manager** is a sufficient role; Enterprise Owner also works but is not required. An organization owner only sees their associated scope, not necessarily the whole enterprise. An ordinary enterprise member is not enough. Custom roles can have partial access and may fail, especially on licenses; the downloader will not silently substitute zero rows.

Role, CLI OAuth consent and SSO are separate checks. Consent does not elevate your role. The documented conservative CLI consent is **`read:enterprise` plus `manage_billing:enterprise`**. GitHub can normalize/inherit these grants and report only `manage_billing:enterprise` for enterprise access; a missing literal `read:enterprise` in the scope header is **not** a reason to request more permissions. The billing scope permits billing **read and write** even though **this downloader sends GET requests only**. Do not request `admin:enterprise` as a minimum. GitHub CLI may add its own default scopes.

Sign in yourself before downloading:

```powershell
gh auth login --hostname github.com --web --scopes "read:enterprise,manage_billing:enterprise"
```

Authorize the CLI/token for SAML/SSO if your enterprise policy requires it. Enterprise **Copilot usage metrics** must be enabled. A personal Copilot Pro account does not grant enterprise reports. No employee-by-employee OAuth or MFA exception is needed.

The script selects the stored `gh` account you name and verifies `/user`, then checks access to all five source endpoints **before downloading report rows**. Those actual GET results are authoritative, not a textual comparison of normalized scope names. A denied source reports its name and HTTP status with role/consent/SSO guidance, without response bodies or tokens, and leaves the previous JSON intact. The script never switches accounts, changes global auth, uses an admin fallback or accepts a token flag. Token environment overrides are rejected rather than silently used.

## Download REAL data explicitly

Choose published UTC report dates, at most **31 days**. There is deliberately **no hidden default date window**. This example uses fictitious account and enterprise names; replace them and choose your own dates:

```powershell
pwsh -NoProfile -File ./scripts/download.ps1 -GitHubUser your-login -Enterprise example-enterprise -StartDay 2026-11-15 -EndDay 2026-11-18 -OutputDirectory "../private real data"
```

The same PowerShell command works on Linux and Windows; quoted paths with spaces are supported. Output stays outside the project/kit. Python uses only its standard library: no pip installation or signing library is required.

The downloader reads daily user reports, cost centers, current memberships, budgets, licenses and billing, then runs the **shared** normalizer/validator. The output is the complete **21-table `dataset.json`**, not raw NDJSON or report-link metadata. It reads your selected account from GitHub CLI's existing credential store; configure secure OS credential storage for `gh`. The downloader creates no token file or auth configuration, and never passes a token as a process argument or writes it to logs/M/JSON. Signed report downloads receive **no GitHub Authorization header**.

The selected dates are printed and recorded in the JSON and dashboard. Metrics availability does not mean billing has finished settling. Errors, denied permissions, missing licenses or inconsistent billing keep the previous valid dataset; they do not create a successful SAMPLE/zero fallback. `download-status.json` records a safe error/stage, not response bodies or tokens. Known unavailable metrics can be allowed explicitly with `-AllowMissingMetrics`; gaps stay N/D. Current membership/licenses never become invented historical assignments. Country remains unmapped without a governed map.

In Power BI Desktop, open `powerbi/CopilotMetrics.pbip`, then **Transform data → Manage parameters**: set **DataMode = REAL** and **DataRootPath** to the private folder containing that **same `dataset.json`**. Click **Refresh**. In Docker, import that file. Download again and repeat those manual viewer steps when you want new data. No Power BI Service automation is configured.

In Power BI, model costs show gross USD, discounts USD and net USD together, including fully discounted usage with net cost zero. Covered empty diagnostic counts display 0; unknown values, zero-denominator ratios and missing budget consumption display N/D. Client telemetry present rate is the share of **known-status user-day rows** marked present, not the share of users.

If you publish to Power BI Service and need classic dashboard alerts, pin the overview **Gross AI credits** or **Net cost USD** numeric card. N/D text-display cards cannot provide numeric alerts. The manual kit does not publish or configure Service alerts for you.

**Projections** uses **reported Billing gross AI credits and gross USD as the primary baseline**. No changes / 0% replacement equals that baseline, even when prices are offline. The separate **Source model (scope filter)** and **Models to replace (scenario)** controls let you change one model while preserving the rest of your actual consumption. Alternatives multiply each complete Billing bucket by its comparable token-cost ratio using current official tariffs, cache/context assumptions and example mixes.

Unmatched Billing remains visible as **unprojected actual consumption**. If you request changing a bucket with no reliable ratio, the full estimate is N/D, and partial components are explicitly **NOT a complete forecast**. Actual discounts/net are not predicted or scaled. This is an approximation, not invoice savings or actual Fusion routing. See the [calibration rules and limits](projections.md). The five REAL setup steps above remain unchanged; neither viewer runs the downloader or private GitHub report APIs.

Permission references: [billing usage](https://docs.github.com/en/enterprise-cloud@latest/rest/billing/usage?apiVersion=2026-03-10), [cost centers](https://docs.github.com/en/enterprise-cloud@latest/rest/billing/cost-centers), [budgets](https://docs.github.com/en/enterprise-cloud@latest/rest/billing/budgets), [Copilot licenses](https://docs.github.com/en/enterprise-cloud@latest/rest/copilot/copilot-user-management), [Copilot metrics](https://docs.github.com/en/enterprise-cloud@latest/rest/copilot/copilot-usage-metrics?apiVersion=2026-03-10).

## Build a portable ZIP (maintainers)

From a Git checkout, run `python3 kit/build_local_kit.py`. The ignored `kit/dist/CopilotMetrics-LocalKit.zip` contains only explicit public sources and tracked neutral Power BI files, plus this guide as its README. It refuses a modified/non-SAMPLE model and never includes credentials, downloaded REAL data or Git history.

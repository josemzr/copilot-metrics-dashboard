# Optional Azure collection and Power BI refresh

The normal Docker quickstart stays local and costs nothing in Azure. This optional adapter is for running collection when your laptop is off:

```text
GitHub App -> timer Function -> private Blob -> authenticated read endpoint -> Power BI
                    |
              Key Vault key
```

**Included:** a Function runtime, an allowlisted source-package builder, a cloud-model generator and credential-free tests. They reuse the same public collector, normalizer and validation rules as Docker.

**Not included:** turnkey Azure provisioning, private-network bootstrap, package deployment or Power BI Service upload/binding. Infrastructure acceptance alone does not prove that functions indexed or that collection/refresh succeeded. This repository does not claim an end-to-end cloud deployment has been verified.

## What your Azure administrator provides

Use an approved region and your own resource names. No Azure resource or Power BI workspace/model ID is supplied by this project.

- A Linux Python 3.13 Function app, separate private host/deployment and data storage, plus Key Vault.
- Managed identity with **Key Vault Secrets User** scoped to the required secret and **Storage Blob Data Contributor** scoped to the data container, subject to your policies. Configure host/deployment-storage identity permissions separately for the hosting plan. The web read response contains no GitHub credentials.
- For storage/vaults with public networking disabled: VNet integration, private endpoints, private DNS and outbound connectivity to GitHub. Do not solve connectivity by enabling shared account keys, public containers or SAS tokens.
- A deployment method appropriate to the hosting plan, including Linux Python dependencies and verified function indexing.

Hosting plans are not interchangeable. **Flex does not use `WEBSITE_RUN_FROM_PACKAGE`.** Premium can use an external private Blob package with managed identity and no Azure Files, subject to its documented requirements. This source package is not a ready-to-run release or a tested provisioning recipe. See Microsoft's [storage guidance](https://learn.microsoft.com/en-us/azure/azure-functions/storage-considerations#create-an-app-without-azure-files) and [external package guidance](https://learn.microsoft.com/en-us/azure/azure-functions/deployment-zip-push#run-from-an-external-package-url).

**Azure is paid.** Premium plans, NAT gateways and private endpoints can have continuing fixed charges. Stopping a Function app does not stop those charges. Review costs and a deliberate cleanup plan for a dedicated resource group; nothing here automatically creates or deletes resources.

## Runtime configuration

`cloud/settings.example.json` contains fictitious, non-secret application settings only, not a complete host/storage configuration. Keep real settings and attribution mappings outside this repository. Use numeric `GITHUB_APP_ID` and `GITHUB_INSTALLATION_ID`, as with Docker.

The runtime uses **ManagedIdentityCredential**, not interactive/developer fallback. It reads `GITHUB_KEY_SECRET_NAME` from `KEY_VAULT_URL`, signs in memory and never writes the PEM or installation token to disk. `DATA_BLOB_ACCOUNT_URL` and `DATA_CONTAINER` select the private data container. These adapters support the standard public-Azure DNS suffixes.

`METRICS_SCHEDULE` is an Azure timer expression; the example runs at **06:00 UTC**. The default rolling window is three days, ending **UTC today minus two days**. GitHub publishes daily reports, not a live feed. `ALLOW_MISSING_METRICS=false` fails on unavailable history; explicit `true` preserves known empty reports as coverage gaps, not zeros. `COLLECTOR_CONFIG_JSON` accepts governed country/history mappings, never a secret or a replacement for audited historical evidence.

The timer validates before atomically replacing `latest/dataset.json`. Source/validation failure keeps the last good data. `latest/status.json` contains state, stage and error type without exception bodies; `latest/last-success.json` records AsOf, period and checksum. A failure after a successful dataset commit is explicitly distinguished from a source failure.

`GET /api/dataset` reads **only that fixed Blob** and never calls GitHub. Function authentication is required. Missing/invalid data returns 503, not SAMPLE. Host request-result logging, dependency tracking and extended HTTP collection are disabled; keep raw query logging disabled in any additional diagnostics too.

## Build the source package

```sh
python3 cloud/build_package.py
```

The ignored `cloud/dist/function-source.zip` contains seven explicit public files. It contains no local settings, sample/REAL data, keys or dependencies. The builder combines the shared signing requirements with optional Azure SDK requirements. An approved Linux Python 3.13 build/deployment step must install those dependencies and produce the actual release; no Azure CLI runs in this repository's CI.

## Connect Power BI without a laptop

First verify an actual timer run, fresh Blob AsOf, and anonymous rejection / authenticated success on the dataset endpoint. Then plan a separate cloud-connected model:

```sh
python3 cloud/powerbi.py --plan \
  --dataset-url https://example-metrics.azurewebsites.net/api/dataset
```

By default this prints a plan and makes **no network calls**. `--execute --output /path/outside/project/Cloud.SemanticModel` writes model files to an empty private folder only; it does not deploy, upload or configure a refresh. The checked-in SAMPLE model and Docker deployment stay unchanged.

The generated Power Query uses the **full static dataset URL** with `[ApiKeyName="code"]`. It includes neither a key nor a SAMPLE fallback. In Power BI's data-source credentials choose **Web API** and store a key scoped to the **dataset Function only**. Never use a host/master key, storage key, anonymous access or a copied short-lived OAuth token. [Web.Contents documentation](https://learn.microsoft.com/en-us/powerquery-m/web-contents) explains this credential pattern.

Publishing/binding to your own workspace and semantic model is a separate operator step. After a successful refresh matches the Blob's AsOf, configure a daily Service refresh after the timer, for example **07:00 UTC** after 06:00 collection. Check failure notifications and coverage. The Service needs access to the authenticated endpoint; it cannot reach your laptop's localhost or an inaccessible private network. Keep the [Desktop file workflow](power-bi.md) if you do not need cloud refresh.

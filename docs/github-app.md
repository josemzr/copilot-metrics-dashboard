# Connect real data

Use a **GitHub App**, not a separate sign-in for every employee. The collector does not need employee OAuth sessions or MFA exceptions. An enterprise administrator must approve the App and grant access to the relevant enterprise APIs.

Grant these **read** permissions, where supported by your enterprise:

| Permission | Purpose |
| --- | --- |
| `enterprise_copilot_metrics` | Daily user metrics reports |
| `enterprise_billing` | AI credit usage, cost centers and budget snapshots |
| `enterprise_copilot_licenses` | Current Copilot license roster |

Availability depends on your plan, policies and API rollout. This project supports **api.github.com only**. A permission does not guarantee that historical reports exist.

## Enable the collector

1. Register and approve the App. Save its private key **outside this project**, owned by your non-root user with file mode **0600**.
2. Copy `.env.example` to `.env`. Replace the fictitious App ID, installation ID, enterprise and absolute key path. Set `COLLECTOR_UID` to the key owner's numeric user ID (`id -u` on macOS/Linux), never 0. File-based Compose secrets can ignore `uid` / `gid` options, so ownership must match; do not relax the key's permissions.
3. Run:

```sh
docker compose -f compose.yaml -f compose.real.yaml --profile real up --build
```

The key is mounted read-only as a Docker secret. It never enters the build context, image, browser or stored dataset. Installation tokens are short-lived and stay in collector memory. Only token creation uses POST; data collection is GET-only. The web service never calls GitHub; only the optional collector does. The SAMPLE server also works with Docker networking disabled.

The web process stays UID 10001. Both processes use the private data volume's group 10001; snapshots are group-readable, not world-readable. A key ownership failure is reported explicitly and never triggers a token fallback.

**REAL** appears automatically when the collector is enabled. Until the first successful collection, the page clearly remains SAMPLE and reports that REAL is unavailable. A failed later run preserves REAL data with its original **AsOf**, plus visible collection status and the last error. Health checks show whether the processes are alive, not whether GitHub has current data.

`COLLECT_INTERVAL_SECONDS` controls the schedule (minimum 300, default 86400). `COLLECT_DAYS` controls the rolling window (1–31, default 7). The end date is always UTC today minus two days. The report window is replaced atomically, not appended or accumulated as history.

By default any missing report fails the run. `ALLOW_MISSING_METRICS=true` permits only GitHub's known empty-report response as an explicit coverage gap; it does not hide permission, HTTP or billing failures.

## Attribution and privacy

Real snapshots contain usernames and billing information: keep them private. Only localhost is published. There is no built-in sign-in, so add authentication and HTTPS before deploying anywhere shared. Do not publish a real dataset or copy it into a public report.

Current membership is **not** applied to past telemetry. Without governed historical mappings, telemetry remains unattributed; without audited license history, adoption and inactive-user counts stay N/D. Billing keeps the API's actual attribution, with an explicit residual when user details are missing.

Advanced use can mount a separate, private attribution JSON file read-only into the collector and set `ATTRIBUTION_FILE` to that container path in a local Compose override. Allowed fields are `countries`, `telemetry_assignments`, `license_history`, `license_history_coverage`, `user_classifications` and `billing_users`. Historical intervals use `valid_from`, `valid_to_exclusive` and nonempty `evidence`; telemetry assignments also need `user_id` or `user_login` and `cost_center_id`. Keep that override and mapping outside this repository.

Do not treat raw pool amounts as a remaining-credit balance when their unit is unknown. Budget and license values are current snapshots, not daily history.

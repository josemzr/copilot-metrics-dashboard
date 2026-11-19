"""Manual, own-account GitHub download. Python standard library only."""
import argparse
import datetime as dt
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

from collect import API_BASE, API_VERSION, Client, ContractError, collect, days
from make_sample import make_sample
from normalize import normalize
from snapshot import TABLES, atomic_json, read_snapshot, validate

ROOT = Path(__file__).resolve().parents[1]


class DownloadError(ContractError):
    pass


class ScopeCapture(urllib.request.BaseHandler):
    scopes = None

    def https_response(self, request, response):
        if request.full_url == API_BASE + "/user":
            self.scopes = response.headers.get("X-OAuth-Scopes")
        return response


class AccountClient(Client):
    def __init__(self, base, version, token):
        super().__init__(base, version, token)
        self.scope_capture = ScopeCapture()
        self.opener.add_handler(self.scope_capture)

    @property
    def oauth_scopes(self):
        return self.scope_capture.scopes

    def request(self, path, method="GET", body=None, **params):
        if method != "GET" or body is not None:
            raise DownloadError("Manual account collection is GET-only")
        return super().request(path, method, body, **params)


def account_client(login, runner=subprocess.run, client_factory=AccountClient):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", login):
        raise DownloadError("Provide the GitHub login you deliberately selected")
    if any(os.environ.get(key) for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")):
        raise DownloadError("Remove token environment overrides before using a selected stored gh account")
    environment = dict(os.environ)
    environment.pop("GH_DEBUG", None)
    result = runner(["gh", "auth", "token", "--hostname", "github.com", "--user", login],
                    capture_output=True, text=True, check=False, timeout=30, env=environment)
    if result.returncode:
        raise DownloadError("The selected gh account is unavailable; sign in yourself using the documented scopes")
    token = result.stdout.strip()
    if not 1 <= len(token) <= 16384 or not token.isascii() or any(c.isspace() for c in token):
        raise DownloadError("gh did not return one supported credential")
    client = client_factory(API_BASE, API_VERSION, token)
    token = None
    identity = client.get("/user")
    actual = identity.get("login") if isinstance(identity, dict) else None
    if not isinstance(actual, str) or actual.casefold() != login.casefold():
        raise DownloadError("Authenticated identity does not match the explicitly selected GitHub login")
    return client


def configuration(enterprise, start_day, end_day, now=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", enterprise):
        raise DownloadError("Provide a valid enterprise slug")
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).date()
    try:
        start, end = dt.date.fromisoformat(start_day), dt.date.fromisoformat(end_day)
    except ValueError:
        raise DownloadError("Use ISO report dates: YYYY-MM-DD") from None
    if start.isoformat() != start_day or end.isoformat() != end_day or end >= today:
        raise DownloadError("Choose explicit ISO start/end days ending before today UTC")
    try:
        list(days(start.isoformat(), end.isoformat()))
    except ContractError:
        raise DownloadError("Choose start day <= end day and no more than 31 days") from None
    return dict(enterprise=enterprise, start_day=start.isoformat(), end_day=end.isoformat(),
                collect_licenses=True, allow_missing_metrics=False, countries={}, billing_users=[],
                telemetry_assignments=[], license_history=[], license_history_coverage=[])


def preflight(client, config):
    def check(source, path, **params):
        try:
            return client.get(path, **params)
        except ContractError as error:
            code = re.search(r"\bHTTP (\d{3})\b", str(error))
            reason = "HTTP " + code.group(1) if code else "request or contract error"
            raise DownloadError(
                f"{source} preflight failed ({reason}). Check enterprise role, CLI consent, SSO and policy; "
                "no report rows were downloaded."
            ) from None

    base = "/enterprises/" + config["enterprise"]
    billing = base + "/settings/billing"
    check("Cost centers", billing + "/cost-centers", page=1, per_page=1)
    check("Budgets", billing + "/budgets", page=1, per_page=1)
    check("Licenses", base + "/copilot/billing/seats", page=1, per_page=1)
    date = dt.date.fromisoformat(config["end_day"])
    check("AI credit billing", billing + "/ai_credit/usage", year=date.year, month=date.month, day=date.day,
          cost_center_id="none")
    report = check("Metrics", base + "/copilot/metrics/reports/users-1-day", day=config["end_day"])
    if report == "" and config["allow_missing_metrics"]:
        return
    if not isinstance(report, dict) or report.get("report_day") != config["end_day"]:
        raise DownloadError("Metrics preflight is unavailable; check policy, permissions and report day")


def output_directory(path):
    output = Path(path).expanduser().resolve()
    if output.is_relative_to(ROOT) or output in (Path(output.anchor), Path.home().resolve()):
        raise DownloadError("Choose a dedicated private data folder outside the project or kit")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    return output


def download(output, config, login, *, client_loader=account_client, collector=collect):
    output = output_directory(output)
    status = dict(state="downloading", lastAttempt=dt.datetime.now(dt.timezone.utc).isoformat(),
                  lastSuccess=None, lastError=None)
    dataset_path = output / "dataset.json"
    if dataset_path.exists():
        # Never destroy or silently replace an invalid existing file.
        status["lastSuccess"] = read_snapshot(dataset_path, None)["Info"][0]["AsOf"]
    stage = "authentication"
    try:
        client = client_loader(login)
        stage = "preflight"
        preflight(client, config)
        stage = "collection"
        data = validate(normalize(collector(config, client), config, "REAL"), "REAL")
        if set(data) != TABLES or (data["Info"][0]["StartDay"], data["Info"][0]["EndDay"]) != (
                config["start_day"], config["end_day"]):
            raise DownloadError("Normalized dataset does not match the requested complete contract")
        stage = "save"
        atomic_json(dataset_path, data, file_mode=0o600)
        status.update(state="ready", lastSuccess=data["Info"][0]["AsOf"])
        atomic_json(output / "download-status.json", status, file_mode=0o600)
        return data
    except (ContractError, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        status.update(state="error", stage=stage, errorType=type(error).__name__,
                      lastError=str(error) if isinstance(error, DownloadError) else
                      "Manual download failed; the previous dataset is unchanged unless saving completed.")
        atomic_json(output / "download-status.json", status, file_mode=0o600)
        if isinstance(error, DownloadError):
            raise
        raise DownloadError(
            "Download failed at " + stage + ". Check enterprise role, CLI consent, SSO, policy and source availability."
        ) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=Path.home() / "CopilotMetricsData")
    parser.add_argument("--sample", action="store_true", help="Write the complete synthetic dataset offline")
    parser.add_argument("--github-user")
    parser.add_argument("--enterprise")
    parser.add_argument("--start-day")
    parser.add_argument("--end-day")
    parser.add_argument("--allow-missing-metrics", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.sample:
            if any((args.github_user, args.enterprise, args.start_day, args.end_day, args.allow_missing_metrics)):
                raise DownloadError("SAMPLE does not accept account, enterprise, dates or availability options")
            output = output_directory(args.output_directory)
            path = output / "dataset.json"
            if path.exists() and read_snapshot(path, None)["Info"][0]["Mode"] == "REAL":
                raise DownloadError("SAMPLE will not overwrite a REAL dataset; choose a different folder")
            atomic_json(path, validate(make_sample()[0], "SAMPLE"), file_mode=0o600)
            print("Saved complete SAMPLE dataset.json offline; no GitHub credentials or calls.")
        else:
            if not all((args.github_user, args.enterprise, args.start_day, args.end_day)):
                raise DownloadError("REAL requires --github-user, --enterprise, --start-day and --end-day")
            config = configuration(args.enterprise, args.start_day, args.end_day)
            config["allow_missing_metrics"] = args.allow_missing_metrics
            print(f"Selected UTC report window: {config['start_day']} to {config['end_day']}.")
            data = download(args.output_directory, config, args.github_user)
            info = data["Info"][0]
            print(f"Saved validated REAL dataset.json: {info['StartDay']} to {info['EndDay']}; account verified.")
        return 0
    except (ContractError, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, DownloadError) else "Local download failed; check prerequisites and private output access."
        print("ERROR: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

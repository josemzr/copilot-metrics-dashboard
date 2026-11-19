"""Bounded, GET-only GitHub collection. Authentication stays on the server."""
import base64
import datetime as dt
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.github.com"
API_VERSION = "2026-03-10"
MAX_BYTES = 16 * 1024 * 1024
MAX_KEY_BYTES = 64 * 1024
MAX_RECORDS = 150_000
MAX_PAGES = 100


class ContractError(ValueError):
    pass


class ReportUnavailable(ContractError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ContractError("Redirects are not accepted")


def days(start, end):
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last or (last - first).days > 30:
        raise ContractError("start_day must be <= end_day; maximum window is 31 days")
    for offset in range((last - first).days + 1):
        yield (first + dt.timedelta(days=offset)).isoformat()


def bounded_json(response, limit=MAX_BYTES):
    content = response.read(limit + 1)
    if len(content) > limit:
        raise ContractError("Response exceeds the size limit")
    try:
        return json.loads(content)
    except (ValueError, UnicodeError):
        raise ContractError("Response is not valid JSON") from None


def download_url(link):
    """Signed URLs are credentials too: never log or forward them."""
    try:
        parsed = urllib.parse.urlsplit(link)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError
    except (ValueError, TypeError, OSError):
        raise ContractError("Report download must use a public HTTPS address") from None
    request = urllib.request.Request(link, headers={"User-Agent": "copilot-metrics"})
    # Separate opener: no API Authorization header, cookies or redirects.
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            body = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError):
        raise ContractError("Report download failed; signed URL withheld") from None
    if len(body) > MAX_BYTES:
        raise ContractError("Report part exceeds 16 MiB")
    return body


class Client:
    def __init__(self, base, version, token):
        if base != API_BASE:
            raise ContractError("Only https://api.github.com is supported; no token sent")
        self.base, self.version, self.token = base, version, token
        self.opener = urllib.request.build_opener(NoRedirect())
        self.requests = 0
        self.deadline = time.monotonic() + 1800

    def request(self, path, method="GET", body=None, **params):
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            raise ContractError("Invalid API path")
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.version,
            "User-Agent": "copilot-metrics",
        })
        for attempt in range(3):
            self.requests += 1
            if self.requests > 5000 or time.monotonic() > self.deadline:
                raise ContractError("Collection request or time budget exhausted")
            try:
                with self.opener.open(request, timeout=60) as response:
                    return bounded_json(response)
            except urllib.error.HTTPError as error:
                code = error.code
                retryable = code in (429, 500, 502, 503, 504)
                try:
                    wait = min(30, max(1, int(error.headers.get("Retry-After", 2 ** attempt))))
                except (ValueError, TypeError):
                    wait = 2 ** attempt
                error.close()
                if not retryable or attempt == 2:
                    raise ContractError(
                        f"GitHub HTTP {code}; check permissions, quota and enterprise access"
                    ) from None
                time.sleep(wait)
            except (urllib.error.URLError, OSError):
                raise ContractError("GitHub connection failed") from None

    def get(self, path, **params):
        return self.request(path, **params)

    def report(self, path, day):
        metadata = self.get(path, day=day)
        if metadata == "":
            raise ReportUnavailable("Report is not available; not zero usage")
        if not isinstance(metadata, dict) or metadata.get("report_day") != day:
            raise ContractError("Report metadata date or shape differs from the request")
        links = metadata.get("download_links")
        if not isinstance(links, list) or not 1 <= len(links) <= 32:
            raise ContractError("Report download part count must be between 1 and 32")
        records, total_bytes = [], 0
        for link in links:
            content = download_url(link)
            total_bytes += len(content)
            if total_bytes > MAX_BYTES * 4:
                raise ContractError("Combined report exceeds 64 MiB")
            try:
                for line in content.decode("utf-8-sig").splitlines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    part = item if isinstance(item, list) else [item]
                    if any(not isinstance(row, dict) for row in part):
                        raise ValueError
                    records.extend(part)
                    if len(records) > MAX_RECORDS:
                        raise ContractError("Report exceeds the row limit")
            except (ValueError, UnicodeError):
                raise ContractError("Report contains invalid NDJSON") from None
        return records


def paged(client, path, key):
    result = []
    for page in range(1, MAX_PAGES + 1):
        response = client.get(path, page=page, per_page=100)
        if not isinstance(response, dict) or not isinstance(response.get(key), list):
            raise ContractError("Invalid paginated response")
        rows = response[key]
        result.extend(rows)
        if len(result) > MAX_RECORDS:
            raise ContractError("Pagination exceeds the row limit")
        if not response.get("has_next_page", len(rows) == 100):
            return result
    raise ContractError("Pagination did not terminate within 100 pages")


def center_snapshots(client, billing_base):
    centers = paged(client, billing_base + "/cost-centers", "costCenters")
    if len(centers) > 100:
        raise ContractError("More than 100 cost centers requires a narrower deployment")
    snapshots = []
    for center in centers:
        path = billing_base + "/cost-centers/" + urllib.parse.quote(center["id"], safe="")
        resources = []
        for page in range(1, MAX_PAGES + 1):
            response = client.get(path, page=page, per_page=100)
            if response["id"] != center["id"]:
                raise ContractError("Cost center detail ID differs from the list")
            if page == 1:
                snapshot = dict(response)
            resources.extend(response["resources"])
            if not response.get("has_next_page", len(response["resources"]) == 100):
                break
        else:
            raise ContractError("Membership pagination did not terminate")
        snapshot["resources"] = resources
        snapshots.append(snapshot)
    return snapshots


def license_snapshot(client, enterprise_base):
    seats = paged(client, enterprise_base + "/copilot/billing/seats", "seats")
    return {
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "complete": True,
        "seats": [{
            "assignee": ({"login": seat["assignee"]["login"], "id": seat["assignee"]["id"]}
                         if seat.get("assignee") else None),
            "organization": ({"login": seat["organization"]["login"]}
                             if seat.get("organization") else None),
            "plan_type": seat.get("plan_type", "unknown"),
            "pending_cancellation_date": seat.get("pending_cancellation_date"),
            "last_activity_at": seat.get("last_activity_at"),
        } for seat in seats],
    }


def collect(config, client):
    enterprise = config["enterprise"]
    if not enterprise or not all(c.isalnum() or c == "-" for c in enterprise):
        raise ContractError("Configure a valid enterprise slug")
    base = "/enterprises/" + urllib.parse.quote(enterprise, safe="")
    billing_base = base + "/settings/billing"
    requested = list(days(config["start_day"], config["end_day"]))
    centers = center_snapshots(client, billing_base)
    budgets = paged(client, billing_base + "/budgets", "budgets")
    licenses = license_snapshot(client, base) if config.get("collect_licenses", True) else None
    users_reports, coverage = [], []
    for day in requested:
        try:
            records = client.report(base + "/copilot/metrics/reports/users-1-day", day)
        except ReportUnavailable:
            if not config.get("allow_missing_metrics", False):
                raise
            coverage.append(dict(day=day, metrics_status="unavailable_empty_response",
                                 billing_status="available_snapshot"))
            continue
        if any(record.get("day") != day for record in records):
            raise ContractError("User report contains a different day")
        users_reports.extend(records)
        if len(users_reports) > MAX_RECORDS:
            raise ContractError("Combined metrics exceed the row limit")
        coverage.append(dict(day=day, metrics_status="available", billing_status="available_snapshot"))
    users = sorted({r["user_login"] for r in users_reports} | set(config.get("billing_users", [])))
    billing = []
    for day in requested:
        date = dt.date.fromisoformat(day)
        for center_id in [c["id"] for c in centers] + ["none"]:
            params = dict(year=date.year, month=date.month, day=date.day, cost_center_id=center_id)
            endpoint = billing_base + "/ai_credit/usage"
            total = client.get(endpoint, **params)
            details = []
            if total["usageItems"]:
                for user in users:
                    details.append(dict(user=user, response=client.get(endpoint, **params, user=user)))
                total = client.get(endpoint, **params)
            billing.append(dict(day=day, cost_center_id=center_id, total=total, details=details))
    return dict(collected_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                enterprise=enterprise, requested_days=requested, cost_centers=centers,
                budgets=budgets, users=users_reports, billing=billing,
                source_coverage=coverage, license_snapshot=licenses)


def app_client(app_id, installation_id, key_path=None, *, key_bytes=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    if not str(app_id).isdigit() or not str(installation_id).isdigit():
        raise ContractError("App ID and installation ID must be numeric")
    if (key_path is None) == (key_bytes is None):
        raise ContractError("Provide exactly one private key path or byte value")
    if key_path is not None:
        with key_path.open("rb") as stream:
            key_bytes = stream.read(MAX_KEY_BYTES + 1)
    if not isinstance(key_bytes, bytes) or not 1 <= len(key_bytes) <= MAX_KEY_BYTES:
        raise ContractError(f"Private key must be 1..{MAX_KEY_BYTES} bytes")
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=")
    now = int(time.time())
    header = encode(b'{"alg":"RS256","typ":"JWT"}')
    payload = encode(json.dumps(dict(iat=now - 60, exp=now + 540, iss=str(app_id))).encode())
    key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ContractError("GitHub App requires an RSA private key of at least 2048 bits")
    message = header + b"." + payload
    jwt = (message + b"." + encode(key.sign(message, padding.PKCS1v15(), hashes.SHA256()))).decode()
    auth = Client(API_BASE, API_VERSION, jwt)
    response = auth.request(f"/app/installations/{installation_id}/access_tokens",
                            method="POST", body=b"{}")
    token = response.get("token")
    if not isinstance(token, str) or not token:
        raise ContractError("Installation token was not returned")
    return Client(API_BASE, API_VERSION, token)


def main(argv=None):
    import argparse
    import os
    from pathlib import Path
    import sys

    parser = argparse.ArgumentParser(description="Optional short-lived App header for a cURL pipe.")
    parser.add_argument("--authorization-header", action="store_true", required=True,
                        help="Write an authorization header to stdout. Pipe it to cURL; never run alone.")
    parser.parse_args(argv)
    try:
        client = app_client(os.environ["GITHUB_APP_ID"], os.environ["GITHUB_INSTALLATION_ID"],
                            Path(os.environ["GITHUB_APP_PRIVATE_KEY_FILE"]))
        sys.stdout.write("Authorization: Bearer " + client.token + "\n")
        return 0
    except (ContractError, KeyError, ValueError, OSError, ImportError) as error:
        print(f"App authorization failed ({type(error).__name__}); check the private App configuration.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

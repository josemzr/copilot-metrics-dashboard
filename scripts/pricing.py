"""Public Copilot pricing only. No account, private configuration or report data."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "projections/contract.json").read_text())
SOURCES = tuple(CONTRACT["sources"])
MAX_SOURCE_BYTES = 1024 * 1024
MONTHS = {name: index for index, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"), 1)}
DATE_PATTERN = r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{1,2}), (\d{4})"


class PricingError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise PricingError("Official pricing redirects are not accepted")


def public_source(url):
    if url not in SOURCES:
        raise PricingError("Only the two fixed official Copilot pricing sources are permitted")
    request = urllib.request.Request(url, headers={"Accept": "text/markdown", "User-Agent": "copilot-metrics-pricing"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = response.read(MAX_SOURCE_BYTES + 1)
    except (urllib.error.URLError, OSError):
        raise PricingError("Official Copilot pricing could not be retrieved") from None
    if len(data) > MAX_SOURCE_BYTES:
        raise PricingError("Official pricing exceeds the source size limit")
    try:
        return data.decode("utf-8")
    except UnicodeError:
        raise PricingError("Official pricing is not UTF-8") from None


def money(text):
    if not re.fullmatch(r"\$\d+(?:\.\d+)?", text):
        raise PricingError("A published token price is not a supported USD amount")
    return float(text[1:])


def date_match(match):
    return dt.date(int(match[2]), MONTHS[match[0]], int(match[1]))


def pricing_rows(markdown):
    if not re.search(r"1 AI credit\s*=\s*\$0\.01 USD", markdown):
        raise PricingError("The published AI-credit denomination could not be verified")
    if "per 1 million tokens" not in markdown:
        raise PricingError("The published token-price denominator changed")
    notes = dict(re.findall(r"^\[\^([^\]]+)\]:\s*(.+)$", markdown, re.M))
    rates, columns = [], []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        values = [value.strip() for value in line.strip().strip("|").split("|")]
        if values[0] == "Model":
            columns = values
            continue
        if not values[0] or re.fullmatch(r"[-: ]+", values[0]):
            continue
        if not {"Model", "Input", "Cached input", "Output"} <= set(columns):
            continue  # Images/review estimates/legacy requests are not text-token tariffs.
        if len(values) != len(columns):
            raise PricingError("Official token-pricing table shape changed")
        row = dict(zip(columns, values))
        references = re.findall(r"\[\^([^\]]+)\]", row["Model"])
        model = re.sub(r"\[\^[^\]]+\]", "", row["Model"]).strip()
        tier = row.get("Tier", "Default")
        if tier not in ("Default", "Long context"):
            raise PricingError("Unsupported published context tier")
        write = row.get("Cache write", "Not applicable")
        item = dict(Model=model, Tier=tier, Threshold=row.get("Threshold (input tokens)", "Not applicable"),
                    InputUSD=money(row["Input"]), CachedInputUSD=money(row["Cached input"]),
                    CacheWriteUSD=None if write == "Not applicable" else money(write),
                    CacheWriteStatus="not-applicable" if write == "Not applicable" else "priced",
                    OutputUSD=money(row["Output"]), EffectiveFrom=None, EffectiveTo=None, Profile="published")
        if references:
            if len(references) != 1 or references[0] not in notes:
                raise PricingError("Published promotional pricing has no supported effective-date note")
            note = notes[references[0]]
            expiry = re.search(r"(through|until) " + DATE_PATTERN, note)
            if expiry is None:
                raise PricingError("Promotional rate expiry could not be parsed")
            day = date_match(expiry.groups()[1:])
            item.update(EffectiveTo=(day + dt.timedelta(days=expiry[1] == "through")).isoformat(),
                        Profile="promotional")
            future = re.search(r"Starting " + DATE_PATTERN + r", pricing is (.+)", note)
            if future:
                start = date_match(future.groups()[:3])
                parts = re.findall(r"\$\d+(?:\.\d+)?", future[4])
                if len(parts) != 3 or item["CacheWriteUSD"] is not None or start.isoformat() != item["EffectiveTo"]:
                    raise PricingError("Announced promotional successor has an unsupported shape")
                rates.append(dict(item, InputUSD=money(parts[0]), CachedInputUSD=money(parts[1]),
                                  OutputUSD=money(parts[2]), EffectiveFrom=start.isoformat(),
                                  EffectiveTo=None, Profile="announced"))
        rates.append(item)
    keys = [(r["Model"], r["Tier"], r["EffectiveFrom"], r["EffectiveTo"]) for r in rates]
    if not rates or len(keys) != len(set(keys)):
        raise PricingError("Official pricing is empty or contains ambiguous duplicate rates")
    return rates


def parse_catalog(pricing, fusion, checked=None):
    checked = checked or dt.datetime.now(dt.timezone.utc)
    match = re.search(r"Through " + DATE_PATTERN +
                      r", users on paid Copilot plans receive a (\d+(?:\.\d+)?)% discount on model costs when using Copilot Fusion", fusion)
    if not match:
        raise PricingError("Official Fusion promotion terms changed; no discount was inferred")
    until = date_match(match.groups()[:3]) + dt.timedelta(days=1)
    discount = float(match[4]) / 100
    if not 0 <= discount <= 1:
        raise PricingError("Invalid official Fusion discount")
    body = (pricing + "\n" + fusion).encode()
    return dict(version=CONTRACT["version"], parserVersion=CONTRACT["pricingParserVersion"],
                aliasesVersion=CONTRACT["aliasesVersion"], asOf=checked.isoformat(),
                contentHash="adler32:" + str(zlib.adler32(body) & 0xFFFFFFFF),
                sha256=hashlib.sha256(body).hexdigest(), sourceURLs=list(SOURCES),
                creditsPerUSD=100, rates=pricing_rows(pricing),
                fusion=dict(discount=discount, effectiveTo=until.isoformat(),
                            eligibility="Paid-plan eligibility is an explicit scenario assumption"))


class CatalogStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.catalog = None
        self.last_checked = None
        self.last_error = None

    def get(self, fetch=public_source, now=None):
        now = now or dt.datetime.now(dt.timezone.utc)
        with self.lock:
            # Opening the view and its explicit button are the only callers. Coalesce double-clicks.
            if self.last_checked is None or (now - self.last_checked).total_seconds() >= 5:
                self.last_checked = now
                try:
                    self.catalog = parse_catalog(fetch(SOURCES[0]), fetch(SOURCES[1]), now)
                    self.last_error = None
                except (PricingError, ValueError, UnicodeError) as error:
                    self.last_error = "Official pricing unavailable or changed. Reported Billing remains available; alternatives require verified prices or explicit acceptance of the last verified catalog."
            state = "ready" if self.last_error is None and self.catalog else "stale" if self.catalog else "error"
            if self.catalog and (now - dt.datetime.fromisoformat(self.catalog["asOf"])).total_seconds() > CONTRACT["maxAgeHours"] * 3600:
                state = "stale"
            return dict(state=state, lastChecked=self.last_checked.isoformat(), lastError=self.last_error,
                        catalog=self.catalog)


STORE = CatalogStore()

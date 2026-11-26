"""Cover-page share counts by class, from each company's latest 10-K/10-Q XBRL instance (WT-01).

companyfacts keeps only undimensioned facts, so a company that tags its cover-page counts by
class (`dei:EntityCommonStockSharesOutstanding` on `us-gaap:StatementClassOfStockAxis`) has no
share count there, and neither does the NCI ownership percentage an Up-C tags. This module reads
those facts from the filing's own instance document.

- Targets: CIKs listed on a default exchange whose latest periodic filing is a 10-K/10-Q (domestic
  forms; 20-F/40-F price metrics are n/m anyway), from the folder's ticker file and submissions.
- One cache entry per filing at `raw/sec-covers/<cik>/<accn>.json`, shared by every dated folder:
  a filing never changes, so each one is fetched once. Network errors aren't cached (retried on
  the next run); a filing with no XBRL instance, no filing index (HTTP 404) or an instance that
  isn't well-formed XML is cached as having no instance.
- All requests go through `core/http.py`'s SecGateway (≤ 8 req/s, User-Agent with contact).
- Balance-sheet debt facts companyfacts drops (custom-extension or dimensional), and the ASC 842
  `…StatementOfFinancialPositionExtensibleList` facts naming the balance-sheet line that holds a
  lease liability, are kept too (`parse_balance_facts`). A cache file written before they were
  (`version` < COVER_VERSION) is fetched again once; until that succeeds the old file stays.
"""

import asyncio
import dataclasses
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import orjson

from glint.contracts.enums import DEFAULT_EXCHANGES
from glint.core.errors import SourceError
from glint.core.http import SecGateway
from glint.core.log import get_logger, log_event
from glint.universe.submissions import read_submissions
from glint.universe.tickers import build_ticker_map

log = get_logger(__name__)

COVERS_DIR = "sec-covers"  # next to raw/sec/, whose subfolders are all dated downloads
DOMESTIC_FORMS = frozenset({"10-K", "10-KT", "10-Q", "10-QT"})
CLASS_AXIS = "us-gaap:StatementClassOfStockAxis"
NCI_TAG = "MinorityInterestOwnershipPercentageByNoncontrollingOwners"
_COVER_TAG = "EntityCommonStockSharesOutstanding"
_XBRLI = "{http://www.xbrl.org/2003/instance}"
_XBRLDI = "{http://xbrl.org/2006/xbrldi}"
_LINKBASE = re.compile(r"(_cal|_def|_lab|_pre)\.xml$|^FilingSummary\.xml$|^R\d+\.xml$")
_BATCH = 16
COVER_VERSION = 2  # 1: classes, symbols, NCI; 2: + balance-sheet debt facts and lease lines
_LEASE_LIST = re.compile(r"^(Finance|Operating)Lease\w*StatementOfFinancialPositionExtensibleList$")
# Names of liability-side debt concepts; matched facts are kept only if monetary and instant.
_DEBT_NAME = re.compile(r"Debt|Borrowing|Notes|Loan|Credit|Lease|CommercialPaper")
_NOT_DEBT = re.compile(r"Receivable|Securities|Investment|Asset|Collateral")


@dataclass(frozen=True)
class ClassCount:
    member: str | None  # StatementClassOfStockAxis member; None for an undimensioned count
    shares: float
    as_of: date


@dataclass(frozen=True)
class NciPercent:
    end: date
    value: float  # fraction
    dims: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class InstanceFact:
    """A monetary instant fact from the instance, with every dimension kept. `concept` is
    `us-gaap:X`, `ifrs-full:X`, `dei:X`, or `ext:X` for a company's own extension."""

    concept: str
    value: float
    end: date
    unit: str  # ISO 4217 code
    dims: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class LeaseLine:
    """ASC 842: the balance-sheet line(s) a lease liability is presented in, as the filing says."""

    concept: str  # e.g. FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList
    lines: list[str]  # e.g. ["us-gaap:LongTermDebtNoncurrent"]
    end: date
    dims: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class Cover:
    cik: str
    accn: str
    form: str
    filed: date
    instance: str | None
    classes: list[ClassCount]
    symbols: dict[str, str]  # class member ("" when undimensioned) → trading symbol
    nci: list[NciPercent]
    balance_facts: list[InstanceFact] = field(default_factory=list[InstanceFact])
    lease_lines: list[LeaseLine] = field(default_factory=list[LeaseLine])
    version: int = COVER_VERSION

    def to_json(self) -> bytes:
        return orjson.dumps({
            "cik": self.cik, "accn": self.accn, "form": self.form, "filed": self.filed,
            "instance": self.instance,
            "classes": [{"member": c.member, "shares": c.shares, "as_of": c.as_of}
                        for c in self.classes],
            "symbols": self.symbols,
            "nci": [{"end": n.end, "value": n.value, "dims": n.dims} for n in self.nci],
            "balance_facts": [{"concept": f.concept, "value": f.value, "end": f.end,
                               "unit": f.unit, "dims": f.dims} for f in self.balance_facts],
            "lease_lines": [{"concept": x.concept, "lines": x.lines, "end": x.end, "dims": x.dims}
                            for x in self.lease_lines],
            "version": self.version,
        })  # fmt: skip

    @staticmethod
    def from_json(raw: bytes) -> "Cover":
        d: dict[str, Any] = orjson.loads(raw)
        return Cover(
            cik=d["cik"],
            accn=d["accn"],
            form=d["form"],
            filed=date.fromisoformat(d["filed"]),
            instance=d["instance"],
            classes=[
                ClassCount(c["member"], float(c["shares"]), date.fromisoformat(c["as_of"]))
                for c in d["classes"]
            ],
            symbols=d["symbols"],
            nci=[
                NciPercent(date.fromisoformat(n["end"]), float(n["value"]), n["dims"])
                for n in d["nci"]
            ],
            balance_facts=[
                InstanceFact(
                    f["concept"],
                    float(f["value"]),
                    date.fromisoformat(f["end"]),
                    f["unit"],
                    f["dims"],
                )
                for f in d.get("balance_facts", [])
            ],
            lease_lines=[
                LeaseLine(x["concept"], list(x["lines"]), date.fromisoformat(x["end"]), x["dims"])
                for x in d.get("lease_lines", [])
            ],
            version=int(d.get("version", 1)),
        )


def parse_instance(raw: bytes) -> tuple[list[ClassCount], dict[str, str], list[NciPercent]]:
    """Cover-page share counts (by class), trading symbols and NCI ownership % from an XBRL
    instance. Pure."""
    root = ET.fromstring(raw)
    contexts = {k: (dims, end) for k, (dims, end, _) in _contexts(root).items()}
    classes: list[ClassCount] = []
    symbols: dict[str, str] = {}
    nci: list[NciPercent] = []
    for el in root:
        local = el.tag.rsplit("}", 1)[-1]
        if local not in (_COVER_TAG, "TradingSymbol", NCI_TAG):
            continue
        dims, end = contexts.get(el.get("contextRef") or "", ({}, None))
        text = (el.text or "").strip()
        if local == "TradingSymbol":
            if text and set(dims) <= {CLASS_AXIS}:
                symbols[dims.get(CLASS_AXIS, "")] = text
            continue
        if end is None or not text:
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        if local == _COVER_TAG:
            if set(dims) <= {CLASS_AXIS}:  # other axes (e.g. legal entity) aren't the registrant's
                classes.append(ClassCount(dims.get(CLASS_AXIS), value, end))
        else:
            nci.append(NciPercent(end, value, dims))
    return classes, symbols, nci


def _contexts(root: ET.Element) -> dict[str, tuple[dict[str, str], date | None, bool]]:
    """Context id → (dimensions, end date, is an instant). Typed members keep their text."""
    out: dict[str, tuple[dict[str, str], date | None, bool]] = {}
    for ctx in root.iter(f"{_XBRLI}context"):
        dims = {
            (m.get("dimension") or ""): (m.text or "").strip()
            for m in ctx.iter(f"{_XBRLDI}explicitMember")
        }
        for m in ctx.iter(f"{_XBRLDI}typedMember"):
            dims[m.get("dimension") or ""] = "".join(m.itertext()).strip()
        end_el = ctx.find(f"{_XBRLI}period/{_XBRLI}instant")
        instant = end_el is not None
        if end_el is None:
            end_el = ctx.find(f"{_XBRLI}period/{_XBRLI}endDate")
        end = None
        if end_el is not None and end_el.text:
            end = date.fromisoformat(end_el.text.strip()[:10])
        out[ctx.get("id") or ""] = (dims, end, instant)
    return out


def _prefix(namespace: str) -> str:
    if "fasb.org/us-gaap" in namespace:
        return "us-gaap"
    if "xbrl.sec.gov/dei" in namespace:
        return "dei"
    if "xbrl.ifrs.org" in namespace:
        return "ifrs-full"
    return "ext"


def _qname(tag: str) -> str:
    """`{namespace}Local` → `us-gaap:Local` (or `ext:Local` for a company extension)."""
    ns, _, local = tag[1:].partition("}") if tag.startswith("{") else ("", "", tag)
    return f"{_prefix(ns)}:{local}"


def _enum_value(token: str) -> str:
    """An extensible-enumeration value: `http://fasb.org/us-gaap/2025#X` (2.0) or `us-gaap:X`
    (1.0) → `us-gaap:X`."""
    if "#" in token:
        ns, _, local = token.rpartition("#")
        return f"{_prefix(ns)}:{local}"
    prefix, _, local = token.rpartition(":")
    return f"{prefix or 'ext'}:{local}"


def parse_balance_facts(raw: bytes) -> tuple[list[InstanceFact], list[LeaseLine]]:
    """Monetary instant facts whose concept names debt (any namespace, any dimensions), and the
    lease-liability line declarations, from an XBRL instance. Pure. Nothing is summed or chosen
    here: financials decides which fact, if any, is the balance-sheet line."""
    root = ET.fromstring(raw)
    contexts = _contexts(root)
    units: dict[str, str] = {}  # unit id → ISO 4217 code, for single-measure currency units
    for unit in root.iter(f"{_XBRLI}unit"):
        measures = [(m.text or "").strip() for m in unit.iter(f"{_XBRLI}measure")]
        if len(measures) == 1 and measures[0].startswith("iso4217:"):
            units[unit.get("id") or ""] = measures[0].removeprefix("iso4217:")
    facts: list[InstanceFact] = []
    leases: list[LeaseLine] = []
    for el in root:
        if not el.tag.startswith("{"):
            continue
        local = el.tag.rsplit("}", 1)[-1]
        dims, end, instant = contexts.get(el.get("contextRef") or "", ({}, None, False))
        text = (el.text or "").strip()
        if end is None or not text:
            continue
        if _LEASE_LIST.match(local):
            leases.append(LeaseLine(local, [_enum_value(t) for t in text.split()], end, dims))
            continue
        if not instant or not _DEBT_NAME.search(local) or _NOT_DEBT.search(local):
            continue
        unit = units.get(el.get("unitRef") or "")
        if unit is None:
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        facts.append(InstanceFact(_qname(el.tag), value, end, unit, dims))
    return facts, leases


def pick_instance(index: dict[str, Any]) -> str | None:
    """The XBRL instance in a filing's index.json: the inline-XBRL extract (`*_htm.xml`) if any,
    else the one .xml file that isn't a linkbase or rendering file."""
    names = [str(i["name"]) for i in index.get("directory", {}).get("item", [])]
    htm = [n for n in names if n.endswith("_htm.xml")]
    if htm:
        return htm[0]
    xml = [n for n in names if n.endswith(".xml") and not _LINKBASE.search(n)]
    return xml[0] if len(xml) == 1 else None


def cover_path(sec_raw: Path, cik: str, accn: str) -> Path:
    return sec_raw.parent / COVERS_DIR / cik / f"{accn}.json"


def load_cover(sec_raw: Path, cik: str, accn: str) -> Cover | None:
    path = cover_path(sec_raw, cik, accn)
    return Cover.from_json(path.read_bytes()) if path.exists() else None


def _is_current(path: Path) -> bool:
    """Cached and written by this version (older files lack the balance-sheet facts)."""
    if not path.exists():
        return False
    return int(orjson.loads(path.read_bytes()).get("version", 1)) >= COVER_VERSION


@dataclass(frozen=True)
class Target:
    cik: str
    accn: str
    form: str
    filed: date


def cover_targets(folder: Path) -> list[Target]:
    """CIKs on a default exchange whose latest periodic filing is a 10-K/10-Q (or -T): that
    filing, plus the latest 10-K when it is older (annual reports carry the ASC 842 lease-line
    declarations most 10-Qs leave out)."""
    tickers, subs_zip = folder / "company_tickers_exchange.json", folder / "submissions.zip"
    if not tickers.exists() or not subs_zip.exists():
        return []
    tmap = build_ticker_map(orjson.loads(tickers.read_bytes()))
    listed = [c for c, info in tmap.items() if info.primary.exchange in DEFAULT_EXCHANGES]
    try:
        as_of = date.fromisoformat(folder.name)
    except ValueError:
        as_of = datetime.now(UTC).date()
    subs, _ = read_submissions(subs_zip, listed, as_of)
    out: list[Target] = []
    for cik in listed:
        rec = subs.get(cik)
        filings = [f for f in (rec.last_annual, rec.last_quarterly) if f] if rec else []
        if not filings:
            continue
        latest = max(filings, key=lambda f: (f.filed, f.accn))
        if latest.form not in DOMESTIC_FORMS:
            continue
        out.append(Target(cik, latest.accn, latest.form, latest.filed))
        annual = rec.last_annual if rec else None
        if annual and annual is not latest and annual.form in DOMESTIC_FORMS:
            out.append(Target(cik, annual.accn, annual.form, annual.filed))
    return out


@dataclass(frozen=True)
class CoverReport:
    targets: int
    cached: int
    fetched: int
    no_instance: int
    failed: list[str]  # "cik accn: reason"


async def _fetch_one(gateway: SecGateway, sec_raw: Path, t: Target) -> str:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(t.cik)}/{t.accn.replace('-', '')}"
    index: dict[str, Any]
    try:
        index = await gateway.get_json(f"{base}/index.json")
    except SourceError as exc:
        if getattr(exc, "status", None) != 404:
            raise
        index = {}  # no filing index: cached like a filing without an instance
    name = pick_instance(index)
    classes: list[ClassCount] = []
    symbols: dict[str, str] = {}
    nci: list[NciPercent] = []
    balance: list[InstanceFact] = []
    leases: list[LeaseLine] = []
    if name is not None:
        tmp = cover_path(sec_raw, t.cik, t.accn).with_suffix(".xml.part")
        await gateway.download(f"{base}/{name}", tmp)
        try:
            raw = tmp.read_bytes()
            classes, symbols, nci = parse_instance(raw)
            balance, leases = parse_balance_facts(raw)
        except ET.ParseError as exc:  # a malformed instance stays malformed: cache, don't retry
            log_event(log, "sec_cover_unparseable", cik=t.cik, accn=t.accn, error=str(exc))
            name = None
        finally:
            tmp.unlink(missing_ok=True)
            tmp.with_name(tmp.name + ".meta.json").unlink(missing_ok=True)
    cover = Cover(t.cik, t.accn, t.form, t.filed, name, classes, symbols, nci, balance, leases)
    dest = cover_path(sec_raw, t.cik, t.accn)
    old = load_cover(sec_raw, t.cik, t.accn)
    if name is None and old is not None and old.instance is not None:
        cover = dataclasses.replace(old, version=COVER_VERSION)  # a re-fetch never loses facts
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".json.tmp")
    part.write_bytes(cover.to_json())
    part.replace(dest)
    return "fetched" if name is not None else "no_instance"


async def fetch_covers(gateway: SecGateway, sec_raw: Path, targets: list[Target]) -> CoverReport:
    """Fetch every target's cover facts not already cached. Errors are reported, not raised."""
    todo = [t for t in targets if not _is_current(cover_path(sec_raw, t.cik, t.accn))]
    counts = {"fetched": 0, "no_instance": 0}
    failed: list[str] = []
    for i in range(0, len(todo), _BATCH):
        batch = todo[i : i + _BATCH]
        results = await asyncio.gather(
            *(_fetch_one(gateway, sec_raw, t) for t in batch), return_exceptions=True
        )
        for t, res in zip(batch, results, strict=True):
            if isinstance(res, BaseException):
                msg = (
                    res.message if isinstance(res, SourceError) else f"{type(res).__name__}: {res}"
                )
                failed.append(f"{t.cik} {t.accn}: {msg}"[:300])
            else:
                counts[res] += 1
    report = CoverReport(len(targets), len(targets) - len(todo), counts["fetched"],
                         counts["no_instance"], failed)  # fmt: skip
    log_event(
        log, "sec_covers_done", targets=report.targets, cached=report.cached,
        fetched=report.fetched, no_instance=report.no_instance, failed=len(failed),
    )  # fmt: skip
    return report

"""Cover-page facts by class from a filing's own XBRL instance (ingest/sec/covers.py).

The instances in data/ are real filings trimmed to the cover counts, trading symbols and NCI
ownership % facts (values unchanged; each file names its accession). No network: SEC is faked.
"""

import asyncio
import zipfile
from datetime import date
from pathlib import Path

import httpx
import orjson

from glint.core.http import SecGateway
from glint.core.settings import Settings
from glint.ingest.sec.covers import (
    COVER_VERSION,
    Cover,
    InstanceFact,
    LeaseLine,
    Target,
    cover_path,
    cover_targets,
    fetch_covers,
    load_cover,
    parse_balance_facts,
    parse_instance,
    pick_instance,
)

DATA = Path(__file__).parent / "data"
AVEX = Target("0002096300", "0002096300-26-000022", "10-Q", date(2026, 8, 12))


def test_parse_avex_cover_classes_and_nci() -> None:
    classes, symbols, nci = parse_instance((DATA / "avex-20260630-cover.xml").read_bytes())
    by_member = {c.member: c.shares for c in classes}
    assert by_member == {
        "us-gaap:CommonClassAMember": 56_470_333,
        "us-gaap:CommonClassBMember": 57_571_367,
    }
    assert {c.as_of for c in classes} == {date(2026, 8, 12)}
    assert symbols == {"": "AVEX"}  # one listed class, tagged without a class member
    assert sorted(n.value for n in nci) == [0.495, 0.505]


def test_parse_googl_has_three_classes_and_no_nci() -> None:
    classes, symbols, nci = parse_instance((DATA / "goog-20260930-cover.xml").read_bytes())
    assert sum(c.shares for c in classes) == 5_888_000_000 + 827_000_000 + 5_579_000_000
    assert symbols["us-gaap:CommonClassAMember"] == "GOOGL"
    assert nci == []


def test_parse_cat_keeps_dimensional_debt_and_drops_assets() -> None:
    """CAT's 10-Q tags debt only by segment (companyfacts has no consolidated fact): every
    member is kept with its dimensions; receivables and total assets are not debt."""
    facts, leases = parse_balance_facts((DATA / "cat-20260930-debt.xml").read_bytes())
    assert leases == []
    seg = "srt:ProductOrServiceAxis"
    noncurrent = {
        (f.end, f.dims[seg]): f.value
        for f in facts
        if f.concept == "us-gaap:LongTermDebtAndCapitalLeaseObligations"
    }
    assert noncurrent == {
        (date(2026, 9, 30), "cat:MachineryPowerEnergyMember"): 10_614_000_000,
        (date(2025, 12, 31), "cat:MachineryPowerEnergyMember"): 10_678_000_000,
        (date(2026, 9, 30), "cat:FinancialProductsMember"): 21_552_000_000,
        (date(2025, 12, 31), "cat:FinancialProductsMember"): 20_018_000_000,
    }
    fair = [f for f in facts if f.concept == "us-gaap:LongTermDebtFairValue"]
    assert fair and all("us-gaap:FairValueByMeasurementBasisAxis" in f.dims for f in fair)
    assert {f.unit for f in facts} == {"USD"}
    names = {f.concept for f in facts}
    assert "us-gaap:NotesAndLoansReceivableNetCurrent" not in names
    assert "us-gaap:Assets" not in names


def test_parse_lng_lease_lines_name_the_balance_sheet_line() -> None:
    """Cheniere's FY2025 10-K: finance leases are presented in other liabilities, not debt."""
    facts, leases = parse_balance_facts((DATA / "lng-20251231-leases.xml").read_bytes())
    fy = date(2025, 12, 31)
    lines = {x.concept: x.lines for x in leases if x.end == fy and not x.dims}
    assert lines["FinanceLeaseLiabilityCurrentStatementOfFinancialPositionExtensibleList"] == [
        "us-gaap:OtherLiabilitiesCurrent"
    ]
    assert lines["FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList"] == [
        "us-gaap:OtherLiabilitiesNoncurrent"
    ]
    assert lines["FinanceLeaseRightOfUseAssetStatementOfFinancialPositionExtensibleList"] == [
        "us-gaap:PropertyPlantAndEquipmentNet"
    ]
    undim = {f.concept: f.value for f in facts if f.end == fy and not f.dims}
    assert undim["us-gaap:FinanceLeaseLiability"] == 931_000_000
    assert undim["us-gaap:LongTermDebtNoncurrent"] == 22_507_000_000
    vie = [f for f in facts if f.dims.get("srt:ConsolidatedEntitiesAxis") and f.end == fy]
    assert [f.value for f in vie] == [14_161_000_000]


def test_lease_line_qname_form_and_extension_concepts() -> None:
    """Extensible enumerations 1.0 (QNames) and company extension concepts."""
    raw = b"""<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024" xmlns:abc="http://abc.com/20250930"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <context id="c"><entity><identifier scheme="x">1</identifier></entity>
        <period><instant>2025-09-30</instant></period></context>
      <unit id="usd"><measure>iso4217:USD</measure></unit>
      <unit id="pure"><measure>xbrli:pure</measure></unit>
      <us-gaap:FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList
        contextRef="c">us-gaap:LongTermDebtNoncurrent</us-gaap:FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList>
      <abc:TermLoanNetOfCurrentPortion contextRef="c" unitRef="usd" decimals="-3">125000</abc:TermLoanNetOfCurrentPortion>
      <abc:DebtToCapitalRatio contextRef="c" unitRef="pure">0.4</abc:DebtToCapitalRatio>
    </xbrl>"""
    facts, leases = parse_balance_facts(raw)
    assert leases == [
        LeaseLine(
            "FinanceLeaseLiabilityNoncurrentStatementOfFinancialPositionExtensibleList",
            ["us-gaap:LongTermDebtNoncurrent"],
            date(2025, 9, 30),
        )
    ]
    assert facts == [
        InstanceFact("ext:TermLoanNetOfCurrentPortion", 125_000, date(2025, 9, 30), "USD")
    ]  # the ratio isn't monetary


def test_pick_instance() -> None:
    def index(*names: str) -> dict[str, object]:
        return {"directory": {"item": [{"name": n} for n in names]}}

    assert pick_instance(index("avex-20260630.htm", "avex-20260630_htm.xml", "R1.htm")) == (
        "avex-20260630_htm.xml"
    )
    assert pick_instance(index("x.xml", "x_cal.xml", "x_lab.xml", "FilingSummary.xml")) == "x.xml"
    assert pick_instance(index("a.xml", "b.xml")) is None  # ambiguous: don't guess
    assert pick_instance({}) is None


class FakeSec:
    def __init__(self, index_status: int = 200, instance: bytes | None = None) -> None:
        self.index_status = index_status
        self.instance = instance or (DATA / "avex-20260630-cover.xml").read_bytes()
        self.requests: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        name = req.url.path.rsplit("/", 1)[-1]
        self.requests.append(name)
        if name == "index.json":
            if self.index_status != 200:
                return httpx.Response(self.index_status)
            items = [{"name": "avex-20260630.htm"}, {"name": "avex-20260630_htm.xml"}]
            return httpx.Response(200, json={"directory": {"item": items}})
        return httpx.Response(200, content=self.instance)


def fetch(settings: Settings, fake: FakeSec, sec_raw: Path, targets: list[Target]):
    async def go():
        async with SecGateway(settings, transport=httpx.MockTransport(fake.handler)) as gw:
            return await fetch_covers(gw, sec_raw, targets)

    return asyncio.run(go())


def test_fetch_caches_each_filing_once(settings: Settings, tmp_path: Path) -> None:
    sec_raw = tmp_path / "sec"
    fake = FakeSec()
    first = fetch(settings, fake, sec_raw, [AVEX])
    assert (first.fetched, first.cached, first.failed) == (1, 0, [])
    assert fake.requests == ["index.json", "avex-20260630_htm.xml"]
    path = cover_path(sec_raw, AVEX.cik, AVEX.accn)
    assert path == tmp_path / "sec-covers" / AVEX.cik / f"{AVEX.accn}.json"
    assert not list(path.parent.glob("*.part*"))  # the instance itself isn't kept
    cover = load_cover(sec_raw, AVEX.cik, AVEX.accn)
    assert cover is not None and cover.instance == "avex-20260630_htm.xml"
    assert Cover.from_json(cover.to_json()) == cover

    second = fetch(settings, fake, sec_raw, [AVEX])
    assert (second.fetched, second.cached) == (0, 1)
    assert len(fake.requests) == 2  # no new requests


def test_missing_filing_index_is_cached_but_errors_are_retried(
    settings: Settings, tmp_path: Path
) -> None:
    sec_raw = tmp_path / "sec"
    gone = fetch(settings, FakeSec(index_status=404), sec_raw, [AVEX])
    assert (gone.no_instance, gone.failed) == (1, [])
    assert load_cover(sec_raw, AVEX.cik, AVEX.accn).classes == []  # type: ignore[union-attr]

    other = Target("0000000001", "0000000001-26-000001", "10-K", date(2026, 3, 1))
    broken = fetch(settings, FakeSec(index_status=400), sec_raw, [other])
    assert broken.fetched == 0 and len(broken.failed) == 1 and "HTTP 400" in broken.failed[0]
    assert load_cover(sec_raw, other.cik, other.accn) is None  # tried again next run


def _write_v1(sec_raw: Path, target: Target) -> None:
    """A cache file as written before COVER_VERSION 2: no balance facts, no version key."""
    d = orjson.loads(Cover(target.cik, target.accn, target.form, target.filed,
                           "avex-20260630_htm.xml", [], {"": "AVEX"}, []).to_json())  # fmt: skip
    for k in ("balance_facts", "lease_lines", "version"):
        d.pop(k)
    path = cover_path(sec_raw, target.cik, target.accn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(d))


def test_old_cache_files_are_fetched_again_once(settings: Settings, tmp_path: Path) -> None:
    sec_raw = tmp_path / "sec"
    _write_v1(sec_raw, AVEX)
    old = load_cover(sec_raw, AVEX.cik, AVEX.accn)
    assert old is not None and old.version == 1 and old.balance_facts == []
    fake = FakeSec()
    report = fetch(settings, fake, sec_raw, [AVEX])
    assert (report.fetched, report.cached) == (1, 0)
    new = load_cover(sec_raw, AVEX.cik, AVEX.accn)
    assert new is not None and new.version == COVER_VERSION and new.classes
    again = fetch(settings, fake, sec_raw, [AVEX])
    assert (again.fetched, again.cached) == (0, 1)


def test_failed_refetch_keeps_the_old_file(settings: Settings, tmp_path: Path) -> None:
    sec_raw = tmp_path / "sec"
    _write_v1(sec_raw, AVEX)
    broken = fetch(settings, FakeSec(index_status=400), sec_raw, [AVEX])
    assert len(broken.failed) == 1
    kept = load_cover(sec_raw, AVEX.cik, AVEX.accn)
    assert kept is not None and kept.version == 1 and kept.symbols == {"": "AVEX"}
    # A filing index that's gone now (404) doesn't erase what the old file had either.
    fetch(settings, FakeSec(index_status=404), sec_raw, [AVEX])
    kept = load_cover(sec_raw, AVEX.cik, AVEX.accn)
    assert kept is not None and kept.version == COVER_VERSION and kept.symbols == {"": "AVEX"}


def test_malformed_instance_is_cached_without_facts(settings: Settings, tmp_path: Path) -> None:
    sec_raw = tmp_path / "sec"
    bad = fetch(settings, FakeSec(instance=b"<xbrl><oops"), sec_raw, [AVEX])
    assert (bad.no_instance, bad.failed) == (1, [])
    cached = load_cover(sec_raw, AVEX.cik, AVEX.accn)
    assert cached is not None and cached.instance is None and cached.classes == []


def test_targets_are_listed_domestic_periodic_filers(tmp_path: Path) -> None:
    folder = tmp_path / "2026-10-30"
    folder.mkdir()
    tickers = {"fields": ["cik", "name", "ticker", "exchange"], "data": [
        [1, "Domestic Co", "DOM", "NYSE"], [2, "Foreign Co", "FOR", "NYSE"],
        [3, "Otc Co", "OTCX", "OTC"],
    ]}  # fmt: skip
    (folder / "company_tickers_exchange.json").write_bytes(orjson.dumps(tickers))

    def subs(cik: int, form: str, accn: str) -> bytes:
        recent = {"form": [form], "filingDate": ["2026-08-01"], "accessionNumber": [accn],
                  "reportDate": ["2026-06-30"], "primaryDocument": ["x.htm"]}  # fmt: skip
        return orjson.dumps({"cik": str(cik), "name": "X", "filings": {"recent": recent}})

    with zipfile.ZipFile(folder / "submissions.zip", "w") as zf:
        zf.writestr("CIK0000000001.json", subs(1, "10-Q", "0000000001-26-000005"))
        zf.writestr("CIK0000000002.json", subs(2, "20-F", "0000000002-26-000005"))
        zf.writestr("CIK0000000003.json", subs(3, "10-Q", "0000000003-26-000005"))
    targets = cover_targets(folder)
    assert [(t.cik, t.accn, t.form) for t in targets] == [
        ("0000000001", "0000000001-26-000005", "10-Q")
    ]
    assert cover_targets(tmp_path / "missing") == []


def test_targets_add_the_latest_10k_when_a_10q_is_newer(tmp_path: Path) -> None:
    folder = tmp_path / "2026-10-30"
    folder.mkdir()
    tickers = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[1, "Co", "CO", "NYSE"]]}
    (folder / "company_tickers_exchange.json").write_bytes(orjson.dumps(tickers))
    recent = {
        "form": ["10-Q", "10-K", "10-Q"],
        "filingDate": ["2026-08-01", "2026-02-20", "2025-11-01"],
        "accessionNumber": ["0000000001-26-000020", "0000000001-26-000005", "0000000001-25-000030"],
        "reportDate": ["2026-06-30", "2025-12-31", "2025-09-30"],
        "primaryDocument": ["q.htm", "k.htm", "q0.htm"],
    }
    with zipfile.ZipFile(folder / "submissions.zip", "w") as zf:
        zf.writestr("CIK0000000001.json", orjson.dumps(
            {"cik": "1", "name": "Co", "filings": {"recent": recent}}))  # fmt: skip
    assert [(t.accn, t.form) for t in cover_targets(folder)] == [
        ("0000000001-26-000020", "10-Q"),
        ("0000000001-26-000005", "10-K"),
    ]

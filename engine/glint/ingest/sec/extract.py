"""Extract `facts_raw` from companyfacts.zip (WT-01 step 2).

Streams each zip member (one per CIK) straight from the archive: nothing is extracted to disk.
Keeps taxonomies us-gaap / ifrs-full / dei and only the tags in concepts.yaml plus the dei cover
tags. `fy`/`fp` are kept raw: they describe the filing, and WT-03 identifies periods by dates.

Output: <sec folder>/facts_raw/bucket=NN/part-K.parquet with the `FACTS_RAW_COLUMNS` schema,
bucket = int(cik) % 64. Members are processed one bucket at a time, so memory holds at most one
bucket's rows (flushed every `flush_rows`). The dataset is written to a temp dir and swapped in
only when complete. `_extract.json` stamps the source sha256 and the tag whitelist; a matching
stamp means the work is already done (or can be hard-linked from the previous day's folder).
"""

import hashlib
import re
import shutil
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import polars as pl
import yaml

from glint.contracts.db import FACTS_RAW_COLUMNS
from glint.contracts.enums import Taxonomy
from glint.core.errors import SourceError
from glint.core.log import get_logger, log_event
from glint.core.settings import REPO_ROOT
from glint.fixtures.sec import kept_tags

log = get_logger(__name__)

BUCKETS = 64
FACTS_DIR = "facts_raw"
STAMP = "_extract.json"
CONCEPTS_PATH = REPO_ROOT / "config" / "concepts.yaml"
KEEP_TAXONOMIES = frozenset(t.value for t in Taxonomy)
_MEMBER = re.compile(r"^CIK(\d{10})\.json$")

SCHEMA: dict[str, Any] = {
    "cik": pl.String,
    "taxonomy": pl.String,
    "tag": pl.String,
    "unit": pl.String,
    "start": pl.Date,
    "end": pl.Date,
    "val": pl.Float64,
    "accn": pl.String,
    "fy": pl.Int32,
    "fp": pl.String,
    "form": pl.String,
    "filed": pl.Date,
    "frame": pl.String,
}
assert list(SCHEMA) == list(FACTS_RAW_COLUMNS), "facts_raw schema drifted from the contract"


@dataclass
class ExtractStats:
    companies: int = 0
    companies_without_kept_facts: int = 0
    facts_kept: int = 0
    files_written: int = 0
    seconds: float = 0.0
    skipped: bool = False
    reused_from: str | None = None


def load_whitelist(concepts_path: Path = CONCEPTS_PATH) -> dict[str, frozenset[str]]:
    keep = kept_tags(yaml.safe_load(concepts_path.read_text()))
    return {tax: frozenset(tags) for tax, tags in keep.items() if tax in KEEP_TAXONOMIES}


def whitelist_hash(whitelist: dict[str, frozenset[str]]) -> str:
    canon = orjson.dumps({k: sorted(v) for k, v in sorted(whitelist.items())})
    return hashlib.sha256(canon).hexdigest()[:16]


def member_cik(name: str) -> str | None:
    m = _MEMBER.match(name)
    return m.group(1) if m else None


def bucket_of(cik: str) -> int:
    return int(cik) % BUCKETS


class _Columns:
    """Column-wise row buffer (cheaper than a list of dicts)."""

    def __init__(self) -> None:
        self.cols: dict[str, list[Any]] = {c: [] for c in SCHEMA}

    def __len__(self) -> int:
        return len(self.cols["cik"])

    def frame(self) -> pl.DataFrame:
        raw = pl.DataFrame(
            {
                c: pl.Series(c, v, dtype=pl.String if SCHEMA[c] is pl.Date else SCHEMA[c])
                for c, v in self.cols.items()
            }
        )
        return raw.with_columns(
            pl.col(c).str.to_date("%Y-%m-%d", strict=True)
            for c, t in SCHEMA.items()
            if t is pl.Date
        )

    def clear(self) -> None:
        for v in self.cols.values():
            v.clear()


def rows_from_companyfacts(
    doc: dict[str, Any], cik: str, whitelist: dict[str, frozenset[str]], out: _Columns
) -> int:
    """Append the whitelisted facts of one companyfacts document. Returns rows added."""
    c = out.cols
    added = 0
    by_taxonomy: dict[str, dict[str, dict[str, Any]]] = doc.get("facts") or {}
    for taxonomy, tags in by_taxonomy.items():
        wanted = whitelist.get(taxonomy)
        if not wanted:
            continue
        for tag, body in tags.items():
            if tag not in wanted:
                continue
            units: dict[str, list[dict[str, Any]]] = body.get("units") or {}
            for unit, facts in units.items():
                for f in facts:
                    val = f.get("val")
                    if val is None or f.get("end") is None:
                        continue
                    c["cik"].append(cik)
                    c["taxonomy"].append(taxonomy)
                    c["tag"].append(tag)
                    c["unit"].append(unit)
                    c["start"].append(f.get("start"))
                    c["end"].append(f["end"])
                    c["val"].append(float(val))
                    c["accn"].append(f.get("accn"))
                    c["fy"].append(f.get("fy"))
                    c["fp"].append(f.get("fp"))
                    c["form"].append(f.get("form"))
                    c["filed"].append(f.get("filed"))
                    c["frame"].append(f.get("frame"))
                    added += 1
    return added


def _members_by_bucket(zf: zipfile.ZipFile) -> dict[int, list[tuple[str, str]]]:
    by_bucket: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for info in zf.infolist():
        cik = member_cik(info.filename)
        if cik is not None:
            by_bucket[bucket_of(cik)].append((info.filename, cik))
    return by_bucket


def _read_stamp(path: Path) -> dict[str, Any] | None:
    stamp = path / STAMP
    return orjson.loads(stamp.read_bytes()) if stamp.exists() else None


def _link_tree(src: Path, dst: Path) -> None:
    for f in src.rglob("*"):
        target = dst / f.relative_to(src)
        if f.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.hardlink_to(f)


def extract_facts(
    zip_path: Path,
    out_dir: Path,
    *,
    source_sha256: str,
    whitelist: dict[str, frozenset[str]] | None = None,
    previous_out: Iterable[Path] = (),
    flush_rows: int = 750_000,
    force: bool = False,
) -> ExtractStats:
    """Write facts_raw for one companyfacts.zip. Caller holds raw.lock."""
    whitelist = whitelist or load_whitelist()
    wanted_stamp = {"source_sha256": source_sha256, "whitelist": whitelist_hash(whitelist)}

    current = _read_stamp(out_dir) if out_dir.exists() else None
    if not force and current is not None and _same(current, wanted_stamp):
        log_event(log, "facts_extract_skipped", reason="already extracted", dir=str(out_dir))
        return _from_stamp(current)

    tmp = out_dir.with_name(out_dir.name + ".tmp")
    if not force:
        for prev in previous_out:
            stamp = _read_stamp(prev) if prev.exists() else None
            if stamp is not None and _same(stamp, wanted_stamp):
                # Link into tmp and swap, so an interrupted link never leaves a stamped partial.
                shutil.rmtree(tmp, ignore_errors=True)
                _link_tree(prev, tmp)
                shutil.rmtree(out_dir, ignore_errors=True)
                tmp.replace(out_dir)
                log_event(log, "facts_extract_reused", source=str(prev))
                return _from_stamp(stamp, reused_from=str(prev))

    started = time.monotonic()
    shutil.rmtree(tmp, ignore_errors=True)
    stats = ExtractStats()
    buf = _Columns()

    def flush(bucket: int, part: int) -> int:
        if not len(buf):
            return part
        target = tmp / f"bucket={bucket:02d}" / f"part-{part}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        buf.frame().write_parquet(target, compression="zstd", statistics=True)
        stats.files_written += 1
        buf.clear()
        return part + 1

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for bucket, members in sorted(_members_by_bucket(zf).items()):
                part = 0
                for name, cik in sorted(members):
                    doc = orjson.loads(zf.read(name))
                    added = rows_from_companyfacts(doc, cik, whitelist, buf)
                    stats.companies += 1
                    stats.facts_kept += added
                    if added == 0:
                        stats.companies_without_kept_facts += 1
                    if len(buf) >= flush_rows:
                        part = flush(bucket, part)
                flush(bucket, part)
                log_event(log, "facts_bucket_done", bucket=bucket, companies=len(members))
    except (zipfile.BadZipFile, orjson.JSONDecodeError) as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SourceError("sec", f"cannot extract {zip_path.name}: {exc}") from exc

    stats.seconds = round(time.monotonic() - started, 1)
    stamp = {
        **wanted_stamp,
        "companies": stats.companies,
        "companies_without_kept_facts": stats.companies_without_kept_facts,
        "facts_kept": stats.facts_kept,
        "files_written": stats.files_written,
    }
    (tmp / STAMP).write_bytes(orjson.dumps(stamp, option=orjson.OPT_INDENT_2))
    shutil.rmtree(out_dir, ignore_errors=True)
    tmp.replace(out_dir)
    log_event(
        log,
        "facts_extract_done",
        companies=stats.companies,
        no_kept_facts=stats.companies_without_kept_facts,
        facts=stats.facts_kept,
        files=stats.files_written,
        seconds=stats.seconds,
    )
    return stats


def _same(stamp: dict[str, Any], wanted: dict[str, str]) -> bool:
    return all(stamp.get(k) == v for k, v in wanted.items())


def _from_stamp(stamp: dict[str, Any], reused_from: str | None = None) -> ExtractStats:
    return ExtractStats(
        companies=int(stamp.get("companies", 0)),
        companies_without_kept_facts=int(stamp.get("companies_without_kept_facts", 0)),
        facts_kept=int(stamp.get("facts_kept", 0)),
        files_written=int(stamp.get("files_written", 0)),
        skipped=True,
        reused_from=reused_from,
    )

"""Back-fill memory (T-305b, D-403; TST-PERF-01): the back-fill's peak memory does not grow with the years of history.

Marker ``perf``: not in the unit run. ``TB_BACKFILL_SCALES`` (default ``1,4``) names how many copies of the synthetic
site A (600 fictional patients over 13 years) are stacked, each copy 28 years further back in time (the 28-year
calendar cycle keeps every date valid) with its own chart numbers. Each load runs in its own process, which reports
its own peak resident memory; the nightly full load (``run_ingest``) on the same feed is measured beside it. The
numbers of a run are in ``docs/plan/measurements/backfill-2026-11-11.md``.

    TB_BACKFILL_SCALES=1,4,8 pytest tests/perf/test_backfill_50k.py -m perf -s
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.perf
ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEEP_DATES = ("birth_date", "death_date")
_DATE = re.compile(r"^(\d{4})(-.*)$")

CHILD = r"""
import json, resource, sys, time
from pathlib import Path
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.backfill import backfill

mode, feed, work, mapping = sys.argv[1:5]
work = Path(work)
(work / "sec").mkdir(parents=True, exist_ok=True)
(work / "sec" / "site_hmac.key").write_bytes(b"p" * 32)
cfg = AdapterConfig(lake_dir=work / "lake", secrets_dir=work / "sec", mapping_path=Path(mapping), site_id="PERF")
t0 = time.perf_counter()
if mode == "backfill":
    rep = backfill(cfg, "csv", feed, snapshot="2026-11-10", validate=False, rebuild_lake=False)
    ok, counts, years = rep.state == "published", rep.counts, len(rep.years) - 1
else:
    rep = run_ingest(cfg, "csv", feed, snapshot="2026-11-10", load_fhir=False, rebuild_lake=False, validate=False)
    ok, counts, years = rep.passed, rep.counts, 0
print(json.dumps({"mode": mode, "ok": ok, "records": sum(counts.values()), "years": years,
                  "seconds": round(time.perf_counter() - t0, 1),
                  "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}))
"""


def stacked_feed(out: Path, copies: int) -> Path:
    """``copies`` copies of site A, copy ``c`` with its keys suffixed and its dates ``28 * c`` years earlier."""
    out.mkdir(parents=True, exist_ok=True)
    for src in sorted(SITE_A.glob("*.csv")):
        with src.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
            fields = list(rows[0]) if rows else []
        with (out / src.name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for c in range(copies if src.stem != "practitioner" else 1):
                for r in rows:
                    w.writerow({k: _shift(k, v, c) for k, v in r.items()})
    return out


def _shift(col: str, v: str, c: int) -> str:
    if c == 0 or not v:
        return v
    if col == "mrn" or col.endswith("_no"):
        return f"{v}{c:02d}"
    m = _DATE.match(v)
    if m and col not in KEEP_DATES:
        return f"{int(m.group(1)) - 28 * c}{m.group(2)}"
    return v


def _measure(mode: str, feed: Path, work: Path, db_url: str) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": "libs:services:.", "TB_DB_URL": db_url}
    out = subprocess.run(
        [sys.executable, "-c", CHILD, mode, str(feed), str(work), str(MAPPING)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=3600, check=False,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr[-2000:]
    got: dict[str, Any] = json.loads(out.stdout.strip().splitlines()[-1])
    return got


def test_backfill_memory_stays_flat_as_history_grows(tmp_path: Path, db_url: str) -> None:
    scales = [int(x) for x in os.environ.get("TB_BACKFILL_SCALES", "1,4").split(",")]
    rows = []
    for k in scales:
        feed = stacked_feed(tmp_path / f"feed{k}", k)
        for mode in ("backfill", "nightly"):
            got = _measure(mode, feed, tmp_path / f"{mode}{k}", db_url)
            assert got["ok"], got
            rows.append({"copies": k, **got})
    print(json.dumps(rows, indent=1))
    bf = [r for r in rows if r["mode"] == "backfill"]
    ni = [r for r in rows if r["mode"] == "nightly"]
    grow_bf = bf[-1]["peak_rss_mb"] - bf[0]["peak_rss_mb"]
    grow_ni = ni[-1]["peak_rss_mb"] - ni[0]["peak_rss_mb"]
    assert bf[-1]["records"] == ni[-1]["records"]
    if len(scales) > 1:
        assert grow_bf < grow_ni / 2, (grow_bf, grow_ni)  # the nightly load grows with the history, the back-fill not

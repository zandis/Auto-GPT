"""FEAS computation on the in-process lake (synthetic site A) + the manual-vs-system funnel harness (SPEC §11.2)."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from orchestrator.scenarios.feas_compute import FeasParams, compute, raw_json
from tb_common.ruleset import Ruleset

from tools import funnel_compare, manual_funnel

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")


@pytest.fixture(scope="module")
def lake(ingested: dict[str, Any]) -> LakeLocal:
    return LakeLocal(ingested["lake_dir"], HashEmbedder())


def _p(**kw: Any) -> FeasParams:
    return FeasParams(run_date=date(2026, 10, 5), snapshot="2026-10-04", capacity_per_month=9.0, **kw)


def test_funnel_semantics(lake: LakeLocal) -> None:
    res, raw = compute(lake, GZQO, _p())
    applied = [f for f in res.funnel if f.applied]
    rem = [raw.remaining[f.criterion_id] for f in applied]
    assert raw.start_n == 600 and rem == sorted(rem, reverse=True)  # monotone funnel
    assert [f.criterion_id for f in res.funnel] == GZQO.manifest.criteria  # manifest order, all criteria listed
    assert {f.criterion_id for f in res.funnel if not f.applied} == {
        "GZQO-INC-05",
        "GZQO-INC-07",
        "GZQO-EXC-11",
        "GZQO-EXC-12",
        "GZQO-EXC-14",
    }
    final = rem[-1]
    v = raw.variants
    assert v["bmi=27"] == final  # the protocol threshold reproduces the base count
    assert v["bmi=24"] >= v["bmi=25"] >= final and v["unknown_as_pass"] >= final
    assert raw.prevalent <= final and sum(raw.first_eligible.values()) == final
    assert len(res.monthly_new) == 24 and res.monthly_new[-1].month == "2026-09"
    for f in res.funnel:  # small cells suppressed in the aggregate output
        for val in (f.remaining, f.dropped, f.unknown):
            assert not (isinstance(val, int) and 0 < val < 5)
    sim = res.simulation
    assert sim.capacity_per_month == 9.0 and 0 <= sim.low <= sim.mid <= sim.high
    again, raw2 = compute(lake, GZQO, _p())
    assert again == res and raw_json(raw2) == raw_json(raw)  # deterministic


def test_scope_options(lake: LakeLocal) -> None:
    _, base = compute(lake, GZQO, _p())
    _, rheu = compute(lake, GZQO, _p(departments=["RHEU"]))
    _, short = compute(lake, GZQO, _p(lookback_months=12))
    assert rheu.start_n < base.start_n and short.start_n <= base.start_n
    assert len(short.index_dates) == 12
    last = GZQO.manifest.criteria[-1]
    _, inc08 = compute(lake, GZQO, _p(variants={"GZQO-INC-08": "15,60"}))
    assert inc08.variants["INC-08=15"] >= inc08.variants["INC-08=60"]
    assert last


def test_manual_vs_system_harness(lake: LakeLocal, synth_dir: Path) -> None:
    _, raw = compute(lake, GZQO, _p())
    manual = manual_funnel.counts(synth_dir / "site-a" / "cgrd.sqlite", date(2026, 9, 30), 36)
    rows_in = [
        {
            "criterion_id": k,
            "manual_n": str(n),
            "manual_definition": manual_funnel.DEFINITIONS[k],
            "explanation": manual_funnel.EXPLANATIONS.get(k, ""),
        }
        for k, n in manual.items()
    ]
    rows = funnel_compare.compare(funnel_compare.system_counts(json.loads(raw_json(raw))), rows_in, 15.0)
    report = funnel_compare.markdown(rows, 15.0)
    assert all(r.status == "ok" for r in rows), report  # every step within ±15 % and differences documented
    buf = io.StringIO()
    csv.DictWriter(buf, fieldnames=list(rows_in[0])).writeheader()
    assert "Result: PASS" in report

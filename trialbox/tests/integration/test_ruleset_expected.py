"""Checked-in rulesets vs their synthetic test sets (CPU CI, in-process lake; no HAPI needed).

* SQL results must match ``tests/expected.json`` (CQL verdicts recorded from HAPI at build time) — the §6.4
  equivalence gate replayed on every CI run.
* Planted generator states give an oracle independent of both engines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from lake.store import Lake
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]


def _results(ingested: dict[str, Any], rs: Ruleset, index_date: str) -> dict[str, dict[str, Any]]:
    rows = Lake(ingested["lake_dir"]).query(rs.sql, [[index_date], None]).to_pylist()
    return {r["pid"]: {k[2:]: v for k, v in r.items() if k.startswith("C_")} for r in rows}


@pytest.mark.parametrize("ruleset", [p.parent.parent.name for p in sorted(ROOT.glob("rulesets/*/tests/expected.json"))])
def test_sql_matches_recorded_cql(ingested: dict[str, Any], ruleset: str) -> None:
    rs = Ruleset.load(ROOT / "rulesets" / ruleset)
    expected = json.loads((ROOT / "rulesets" / ruleset / "tests" / "expected.json").read_text(encoding="utf-8"))
    got = _results(ingested, rs, expected["index_date"])
    agree = total = 0
    mismatches = []
    for mrn, verdicts in expected["patients"].items():
        row = got[pid_for_mrn(ingested["key"], mrn)]
        for cid, v in verdicts.items():
            total += 1
            if row.get(cid) == v:
                agree += 1
            else:
                mismatches.append((mrn, cid, v, row.get(cid)))
    assert total >= 200 * 10
    assert 100.0 * agree / total >= 98.0, mismatches[:10]
    assert rs.manifest.status == "approved" and rs.manifest.equivalence is not None
    assert (rs.manifest.equivalence.overall_pct or 0) >= 98.0


def test_gzqo_planted_state_oracle(ingested: dict[str, Any], synth_dir: Path) -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    got = _results(ingested, rs, "2026-10-05")
    states = json.loads((synth_dir / "site-a" / "states.json").read_text(encoding="utf-8"))
    rules: dict[str, dict[str, Any]] = {
        "bmi": {
            "crit": "GZQO-INC-03",
            ">30": True,
            "27-30": True,
            "<24": False,
            "24-25": False,
            "25-27": False,
            "missing": None,
            "stale": None,
            "no_height": None,
        },
        "creatinine": {"crit": "GZQO-INC-08", "normal": True, "low": False, "missing": None},
        "sbp": {"crit": "GZQO-EXC-09", "good": False, "bad": True, "missing": None},
        "alt": {"crit": "GZQO-EXC-13", "good": False, "bad": True, "missing": None},
        "hba1c": {"crit": "GZQO-EXC-06", "good": False, "bad": True, "missing": None},
        "ult": {
            "crit": "GZQO-INC-06",
            "long": True,
            "gappy_ok": True,
            "short": False,
            "none": False,
            "old": False,
            "gappy_bad": False,
        },
        "t1dm": {"crit": "GZQO-EXC-01", "yes": True},
        "bariatric": {"crit": "GZQO-EXC-05", "yes": True, "no": False},
        "urate": {"crit": "GZQO-INC-04", "good": True, "missing": None, "stale": None},
    }
    checked = 0
    for mrn, st in states.items():
        if st.get("archetype") != "gout":
            continue
        row = got.get(pid_for_mrn(ingested["key"], mrn))
        if row is None:  # minors etc. are still in scope; deceased excluded
            continue
        for attr, rule in rules.items():
            if attr in st and st[attr] in rule:
                assert row[rule["crit"]] == rule[st[attr]], (mrn, attr, st[attr], row[rule["crit"]])
                checked += 1
    assert checked > 1000

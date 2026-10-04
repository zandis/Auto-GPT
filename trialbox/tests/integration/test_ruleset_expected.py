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
    assert len(expected["patients"]) >= 200 and total >= 200 * len(
        {c for v in expected["patients"].values() for c in v}
    )
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


def test_ra_bio_planted_state_oracle(ingested: dict[str, Any], synth_dir: Path) -> None:
    """Every structured RA-BIO criterion against the generator's planted states (true / false / null cases)."""
    rs = Ruleset.load(ROOT / "rulesets" / "RA-BIO")
    got = _results(ingested, rs, "2026-10-05")
    states = json.loads((synth_dir / "site-a" / "states.json").read_text(encoding="utf-8"))
    p = "RA-BIO-"
    rules: list[tuple[str, str, dict[str, Any]]] = [
        ("ra_dx", p + "INC-02", {"long": True, "recent": False, "none": False}),
        ("mtx", p + "INC-03", {"long": True, "short": False, "gappy_bad": False, "none": False}),
        ("csdmard2", p + "INC-04", {"long": True, "short": False, "gappy_bad": False, "none": False}),
        (
            "das28_recent",
            p + "INC-05",
            {"high": True, "moderate": False, "low": False, "missing_component": None, "none": None},
        ),
        ("das28_earlier", p + "INC-06", {"high": True, "low": False, "none": None}),
        (
            "tb",
            p + "EXC-01",
            {"active": True, "igra_pos_untreated": False, "igra_pos_treated": False, "igra_neg": False, "none": False},
        ),
        ("tb", p + "EXC-02", {"igra_pos_untreated": True, "igra_pos_treated": False, "igra_neg": False}),
        ("hbv", p + "EXC-03", {"pos_no_av": True, "pos_av": False, "neg": False}),
        ("malignancy", p + "EXC-04", {"recent": True, "old": False, "no": False}),
        ("pregnancy", p + "EXC-05", {"dx": True, "no": False}),
        ("infection", p + "EXC-06", {"recent": True, "mid": False, "old": False, "no": False}),
        ("hf", p + "EXC-07", {"yes": True, "no": False}),
        (
            "das28_recent",
            p + "REN-01",
            {"high": True, "moderate": True, "low": True, "missing_component": None, "none": None},
        ),
        ("doc_hbsag", p + "DOC-01", {"yes": True}),
        ("doc_ahbc", p + "DOC-02", {"yes": True, "no": False}),
        ("doc_tb", p + "DOC-03", {"cxr": True}),
    ]
    checked: dict[str, int] = {}
    for mrn, st in states.items():
        if st.get("archetype") != "ra":
            continue
        row = got.get(pid_for_mrn(ingested["key"], mrn))
        if row is None:
            continue
        for attr, crit, rule in rules:
            if attr in st and st[attr] in rule:
                assert row[crit] == rule[st[attr]], (mrn, attr, st[attr], crit, row[crit])
                checked[crit] = checked.get(crit, 0) + 1
    assert len(checked) == len(rules) and sum(checked.values()) > 1500, checked


def test_onc_osi_planted_state_oracle(ingested: dict[str, Any], synth_dir: Path) -> None:
    """ONC-OSI structured criteria against the planted states: NSCLC only in the onc archetype, the EGFR result
    decides INC-03 (no test → null), the planted osimertinib course decides EXC-01 (first-line program)."""
    rs = Ruleset.load(ROOT / "rulesets" / "ONC-OSI")
    got = _results(ingested, rs, "2026-10-05")
    states = json.loads((synth_dir / "site-a" / "states.json").read_text(encoding="utf-8"))
    seen = {"onc": 0, "pos": 0, "neg": 0, "other": 0, "on": 0, "none": 0}
    for mrn, st in states.items():
        row = got.get(pid_for_mrn(ingested["key"], mrn))
        if row is None:
            continue
        if st.get("archetype") == "onc":
            seen["onc"] += 1
            assert row["ONC-OSI-INC-02"] is True, mrn
            assert row["ONC-OSI-INC-03"] is {"pos": True, "neg": False}[st["egfr_mut"]], (mrn, st)
            seen[st["egfr_mut"]] += 1
            assert row["ONC-OSI-EXC-01"] is (st["osi"] == "on"), (mrn, st)
            seen[st["osi"]] += 1
        else:
            seen["other"] += 1
            if st.get("malignancy") != "recent":  # a recent malignancy may be lung_ca (C34.90) — not planted per type
                assert row["ONC-OSI-INC-02"] is False, (mrn, st)
            assert row["ONC-OSI-INC-03"] is None, (mrn, st)
            assert row["ONC-OSI-EXC-01"] is False, mrn
    assert seen["pos"] >= 10 and seen["neg"] >= 2 and seen["on"] >= 5 and seen["none"] >= 5, seen
    assert seen["other"] >= 400, seen

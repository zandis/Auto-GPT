"""``e2e_simple`` (SRS FR-OPS-11, D-111): the one build gate. FEAS -> report -> investigator approval -> SCREEN ->
list -> N1/N2 mail -> REDCap simulator read-back -> screening log on one synthetic hospital, stub model, no network,
with checks at each stage, the audit events FR-AUD-01a/b/e and a byte-identical re-run (FR-REP-02).

Runs in the default suite (no compose stack needed) and as ``make e2e-simple``."""

from __future__ import annotations

from pathlib import Path

from tools import e2e_simple


def test_e2e_simple(tmp_path: Path) -> None:
    out = e2e_simple.run(tmp_path, "pw-" + "x" * 16, "ja")
    bad = [(st.name, what, detail) for st in out["stages"] for what, ok, detail in st.checks if not ok]
    assert not bad, e2e_simple.report(out)
    names = [st.name for st in out["stages"]]
    assert names[:2] == ["0 data in", "1 feasibility report"] and "audit" in names and "re-run (FR-REP-02)" in names
    assert sum(len(st.checks) for st in out["stages"]) >= 40
    assert out["seconds"] < e2e_simple.BUDGET_S

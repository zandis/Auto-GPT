"""D-104 feasibility profile: age/sex bands rounded like the funnel, the projection path from the same draws."""

from __future__ import annotations

from datetime import date

from orchestrator.scenarios.feas_compute import simulate
from orchestrator.scenarios.feas_profile import age_band, demographics


def test_age_band_edges() -> None:
    today = date(2026, 11, 5)
    assert age_band(date(1976, 11, 6), today) == "<50"  # 49, birthday tomorrow
    assert age_band(date(1976, 11, 5), today) == "50-59"
    assert age_band(date(1946, 11, 5), today) == "80+"


def test_demographics_rounds_and_hides_small_cells() -> None:
    rows: list[tuple[str, str | None, str | None]] = [(f"p{i}", "1950-01-01", "female") for i in range(12)]
    rows += [("m1", "1950-01-01", "M"), ("x", None, "F")]
    d = demographics(rows, date(2026, 11, 5), 5)
    band = next(b for b in d["bands"] if b["band"] == "70-79")
    assert band["F"] == 10 and band["M"] == "<5" and band["n"] == 15
    assert d["age_unknown"] == "<5" and d["sex"]["F"] == 10


def test_projection_path_ends_at_the_totals() -> None:
    sim = simulate(prevalent=40, monthly_rate=3, reach=0.6, accept=0.35, capacity=4, months=12, seed=7, path=True)
    path = sim["path"]
    assert len(path) == 12
    assert all(path[i][1] <= path[i + 1][1] for i in range(11))  # cumulative
    assert all(lo <= mid <= hi for lo, mid, hi in path)
    assert path[-1] == [sim["low"], sim["mid"], sim["high"]]
    plain = simulate(prevalent=40, monthly_rate=3, reach=0.6, accept=0.35, capacity=4, months=12, seed=7)
    assert {k: plain[k] for k in ("low", "mid", "high")} == {k: sim[k] for k in ("low", "mid", "high")}

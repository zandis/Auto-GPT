"""Card 10A-3 (lane H, 2026-11-18): the ladder report, widened.

Decisions per rung by criterion kind, note language and site, and the decided share, beside every accuracy figure
and every bound. The acceptance runs on launch P2b's stored verdicts (``tests/fixtures/public_accuracy_p2b``, cells
only, public data) and checks root review 15's rung table (section 2.2) and review 17's "138 of 895 decided"."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import ladder, replay

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
P2B = ROOT / "tests" / "fixtures" / "public_accuracy_p2b" / "ladder_cells.json"

#: review 15, section 2.2, "Which rung answered each patient-criterion cell" [M 1], and its tiers
REVIEW_15 = {
    "sigir": {"cells": 895, "rules": 103, "judge": 35, "unknown": 372, "person": 385, "decided": 138,
              "tiers": {"review": 83, "excluded": 19}},
    "jmed": {"cells": 1118, "rules": 592, "judge": 0, "unknown": 526, "person": 0, "decided": 592,
             "tiers": {"review": 524, "excluded": 70}},
    "tcga": {"cells": 500, "rules": 0, "judge": 427, "unknown": 73, "person": 0, "decided": 427,
             "tiers": {"high": 48, "review": 73, "excluded": 379}},
}  # fmt: skip


def _p2b() -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """{set: (ids, answers)} rebuilt from the cells-only fixture."""
    fx = json.loads(P2B.read_text(encoding="utf-8"))
    codes = fx["codes"]
    out = {}
    for name, s in fx["sets"].items():
        answers: dict[str, Any] = {}
        for rs, r in s["rulesets"].items():
            ids_ = [c[0] for c in r["criteria"]]
            pats: dict[str, Any] = {}
            for row, n in r["patients"].items():
                tier, key = row.split(":", 1)
                verdicts = [{"id": i, "verdict": codes[k][0], "basis": codes[k][1], "quote": None}
                            for i, k in zip(ids_, key, strict=True) if k != "-"]  # fmt: skip
                for j in range(n):
                    pats[f"{rs}-{row}-{j}"] = {"tier": tier, "verdicts": verdicts}
            answers[rs] = {"draft": [{"id": i, "text": t} for i, t in r["criteria"]], "patients": pats}
        out[name] = ({"set": name, "lang": s["lang"]}, answers)
    return out


@pytest.fixture(scope="module")
def p2b() -> dict[str, dict[str, Any]]:
    return {n: ladder.ladder(ids, ans) for n, (ids, ans) in _p2b().items()}


# ---------------------------------------------------------------- the acceptance
@pytest.mark.parametrize("name", sorted(REVIEW_15))
def test_the_rung_table_on_the_stored_p2b_sets_equals_review_15(p2b: dict[str, Any], name: str) -> None:
    want, got = REVIEW_15[name], p2b[name]
    assert got["cells"] == want["cells"]
    for rung in ("rules", "judge", "unknown", "person"):
        assert got["rungs"].get(rung, 0) == want[rung], rung
    assert set(got["rungs"]) <= {"rules", "judge", "unknown", "person"}  # no basis the ladder does not know
    assert got["decided"]["k"] == want["decided"] and got["decided"]["n"] == want["cells"]
    assert got["tiers"] == want["tiers"]


def test_it_prints_138_of_895_decided_for_sigir(p2b: dict[str, Any]) -> None:
    text = "\n".join(ladder.render(p2b))
    assert "decided 138 of 895 (15.4 %" in text  # review 17, section 3: 138 of 895, 15.4 %
    assert "decided 592 of 1118 (53.0 %" in text and "decided 427 of 500 (85.4 %" in text
    lo, hi = p2b["sigir"]["decided"]["ci95"]
    assert 0.13 < lo < 0.135 and 0.175 < hi < 0.18  # exact interval; review 17's Wilson is 13.2 to 17.9 %


def test_language_and_site_rows_add_up(p2b: dict[str, Any]) -> None:
    assert p2b["jmed"]["by_language"]["ja"]["cells"] == 1118
    assert p2b["sigir"]["by_language"]["en"]["decided"]["k"] == 138
    for x in p2b.values():
        assert sum(t["cells"] for t in x["by_site"].values()) == x["cells"]
        assert sum(t["decided"]["k"] for t in x["by_language"].values()) == x["decided"]["k"]
    text = "\n".join(ladder.render(p2b))
    assert "By note language, all sets:" in text and "By site, all sets:" in text


def test_the_kind_table_on_sigir(p2b: dict[str, Any]) -> None:
    """The kinds are a rough regular-expression classification (as review 15's [M 3] was); where this table and
    review 15's section 3 agree, it is pinned here; the rest is the tool's own and differs by a few criteria."""
    s = p2b["sigir"]
    assert s["criteria"] == 1165
    k = s["by_kind"]
    assert ladder.pct(k["temporal"]["criteria"]) == "28.1 %"  # review 15: 28.1 %
    assert ladder.pct(k["pregnancy"]["criteria"]) == "5.4 %"  # review 15: 5.4 %
    assert ladder.pct(k["lab"]["criteria"]) == "5.9 %"  # review 15: 6.0 %
    # the machine-decided cells per kind that equal review 15's
    for kind, decided in {"age_sex": 100, "medication": 4, "history": 4, "consent": 1, "procedure_device": 3,
                          "lab": 0, "pregnancy": 6, "scale_stage": 2, "lifestyle": 1, "allergy": 1,
                          "another_study": 1, "judgement": 1}.items():  # fmt: skip
        assert k[kind]["decided"]["k"] == decided, kind
    for t in k.values():  # a kind's rungs add up to its cells
        assert sum(t["rungs"].values()) == t["cells"] <= s["cells"]
    assert list(k)[-1] == "none" and 0 < k["none"]["criteria"]["k"] < s["criteria"]


# ---------------------------------------------------------------- the parts
def test_rung_of_reads_the_basis_and_keeps_an_unknown_basis_visible() -> None:
    assert ladder.rung_of({"verdict": "pass", "basis": "coded"}) == "rules"
    assert ladder.rung_of({"verdict": "fail", "basis": "notes"}) == "judge"
    assert ladder.rung_of({"verdict": "pass", "basis": "pair"}) == "judge"
    assert ladder.rung_of({"verdict": "pending_human", "basis": "person"}) == "person"
    assert ladder.rung_of({"verdict": "pending_human", "basis": None}) == "person"
    assert ladder.rung_of({"verdict": "unknown", "basis": None}) == "unknown"
    assert ladder.rung_of({"verdict": "pass", "basis": "crystal_ball"}) == "other:crystal_ball"
    assert ladder.rung_of({"verdict": "pass", "basis": None}) == "other:none"
    assert ladder.is_decided({"verdict": "fail"}) and not ladder.is_decided({"verdict": "pending_human"})


def test_kinds_in_three_languages() -> None:
    assert ladder.kinds_of("Age 18 to 75 years") == ["age_sex", "temporal"]
    assert ladder.kinds_of("20歳以上") == ["age_sex"]
    assert ladder.kinds_of("糖尿病の既往がある患者") == ["diagnosis", "history"]
    assert "vital" not in ladder.kinds_of("高血圧症の既往がある患者")  # a diagnosis, not a measured blood pressure
    assert "pregnancy" in ladder.kinds_of("懷孕或哺乳中的婦女")
    assert ladder.kinds_of("") == ["none"] and ladder.kinds_of("Not specified") == ["none"]


def test_pct_rounds_half_up_from_the_counts() -> None:
    assert ladder.pct({"k": 592, "n": 1118}) == "53.0 %"
    assert ladder.pct({"k": 138, "n": 895}) == "15.4 %"
    assert ladder.pct({"k": 1, "n": 8}) == "12.5 %" and ladder.pct({"k": 0, "n": 0}) == "n/a"
    assert ladder.decided_phrase(None) == "decided: not known (no ladder)"


def _set(tmp: Path, *, site: Any = None) -> tuple[Path, Path]:
    built, work = tmp / "built", tmp / "work"
    (built / "gold").mkdir(parents=True)
    work.mkdir()
    ids: dict[str, Any] = {"set": "syn", "lang": {"R1": "en", "R2": "ja"},
                           "patient_lang": {"900001": "zh-TW", "900002": "ja"}}  # fmt: skip
    if site is not None:
        ids["site"] = site
    (built / "gold" / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    answers = {
        "R1": {"draft": [{"id": "R1-1", "text": "Age >= 18 years"}, {"id": "R1-2", "text": "Pregnant women"}],
               "patients": {"pidA": {"tier": "review", "verdicts": [
                   {"id": "R1-1", "verdict": "pass", "basis": "coded"},
                   {"id": "R1-2", "verdict": "pending_human", "basis": "person"}]},
                            "pidC": {"tier": "review", "verdicts": [
                   {"id": "R1-1", "verdict": "unknown", "basis": None}]}}},
        "R2": {"draft": [{"id": "R2-1", "text": "糖尿病の既往"}],
               "patients": {"pidB": {"tier": "excluded", "verdicts": [
                   {"id": "R2-1", "verdict": "fail", "basis": "notes"}]}}},
    }  # fmt: skip
    (work / "answers.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    (work / "pidmap.json").write_text(json.dumps({"900001": "pidA", "900002": "pidB"}), encoding="utf-8")
    return built, work


def test_note_language_from_the_patient_and_site_per_protocol(tmp_path: Path) -> None:
    built, work = _set(tmp_path, site={"R1": "site-a", "R2": "site-b"})
    lad = ladder.ladder_of_folder(built, work)
    # pidA's note is zh-TW through the run's pseudonyms; pidC has none and takes its protocol's language
    assert lad["by_language"]["zh-TW"]["cells"] == 2 and lad["by_language"]["en"]["cells"] == 1
    assert lad["by_language"]["ja"]["rungs"] == {"judge": 1}
    assert lad["by_site"]["site-a"]["cells"] == 3 and lad["by_site"]["site-b"]["decided"]["k"] == 1
    assert lad["decided"]["k"] == 2 and lad["cells"] == 4
    assert lad["by_kind"]["pregnancy"]["rungs"] == {"person": 1}
    text = "\n".join(ladder.render({"syn": lad}))
    assert "  language zh-TW" in text and "  site site-a" in text


def test_one_named_site_and_a_set_that_did_not_run(tmp_path: Path) -> None:
    built, work = _set(tmp_path, site="Hospital A (synthetic)")
    assert list(ladder.ladder_of_folder(built, work)["by_site"]) == ["Hospital A (synthetic)"]
    (work / "answers.json").unlink()
    gone = ladder.ladder_of_folder(built, work)
    assert "not_scored_because" in gone
    assert "syn: not scored" in "\n".join(ladder.render({"syn": gone}))


def test_the_scorer_carries_the_ladder(tmp_path: Path) -> None:
    from tools import box_run
    from tools.public_accuracy import score

    built, work = _set(tmp_path)
    for f in ("pairs.jsonl", "criteria.jsonl"):
        (built / "gold" / f).write_text("", encoding="utf-8")
    (built / "gold" / "ids.json").write_text(json.dumps({**json.loads((built / "gold" / "ids.json").read_text()),
                                                         "rulesets": {}, "patients": {}}), encoding="utf-8")  # fmt: skip
    out = score.score(built, work)
    assert out["schema_version"] == score.SCHEMA_VERSION == 5
    assert out["ladder"]["cells"] == 4 and out["ladder"]["decided"]["k"] == 2
    assert "ladder" in box_run.SCORE_SUMMARY_KEYS


def test_the_replay_prints_the_decided_share_beside_every_figure() -> None:
    lad = ladder.ladder(*_p2b()["sigir"])
    r = {"ladder": {"a": {"sigir": lad, "tcga": {"not_scored_because": "x"}}}}
    assert replay._decided_beside(r, "a", ["sigir", "tcga"]) == (
        "sigir 138 of 895 (15.4 %, 95 % CI 13.1 to 17.9 %)"
    )
    assert replay._decided_beside(r, "b", ["sigir"]) == ""
    assert replay.SCHEMA_VERSION == 3

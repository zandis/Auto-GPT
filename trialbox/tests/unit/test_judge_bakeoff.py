"""Judge bake-off harness (D-181): the product's judge prompt and parser against a local OpenAI-compatible stub.

No network beyond 127.0.0.1, no real key: the "key" here is a test string that must reach the stub's Authorization
header and never the output files or stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import judge_bakeoff as jb

KEY = "sk-test-NOT-A-REAL-KEY-7f3a"


def _items(n: int = 30) -> list[jb.Item]:
    items = jb.synthetic_items()
    # every criterion and gold value in a small slice
    by: dict[tuple[str, str], list[jb.Item]] = {}
    for it in items:
        by.setdefault((it.criterion_text, it.gold), []).append(it)
    out: list[jb.Item] = []
    while len(out) < n:
        for group in by.values():
            if group and len(out) < n:
                out.append(group.pop())
    return out


def _bake(tmp: Path, url: str, items: list[jb.Item], **kw: Any) -> dict[str, Any]:
    return jb.bake(url, kw.pop("served", jb.STUB_NAME), items, tmp, sha=jb.set_sha(items), backoff=(0.0,), **kw)


def _first_sentence(inp: dict[str, Any]) -> tuple[str, str]:
    ex = inp["excerpts"][0]
    return str(ex["text"]).split("。")[0], str(ex["date"])


def test_stub_run_passes_gate_and_the_key_stays_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TB_BAKEOFF_API_KEY", KEY)
    items = _items()
    seen: list[str] = []
    with jb.stub_server(seen_auth=seen) as url:
        res = _bake(tmp_path / "a", url, items)
    assert res["gate"]["passed"], res["gate"]
    assert seen and set(seen) == {f"Bearer {KEY}"}  # the key reached the endpoint
    assert res["meta"]["auth"] == "env:TB_BAKEOFF_API_KEY" and res["meta"]["prompt"].startswith("judge@")
    assert res["meta"]["pin"]["id"] == jb.STUB_NAME
    g = res["gated"]
    assert g["n"] == len(items) and g["wrong_exclusion"]["k"] == 0 and g["wrong_exclusion"]["n"] > 0
    assert g["fits_precision"]["n"] > 0 and g["citation"]["quote_found"]["rate"] == 1.0
    assert g["latency_s"]["p95"] > 0 and g["tokens"]["in"] > 0 and g["served_mismatch"] == 0
    # the CLI on a frozen set, with the stub: same gate, and the key appears nowhere
    set_path = tmp_path / "set.jsonl"
    sha = jb.write_set(items, set_path)
    assert jb.read_set(set_path) == (items, sha)
    assert jb.main(["--stub", "--set", str(set_path), "--out", str(tmp_path / "b")]) == 0
    out = capsys.readouterr()
    assert "Gate: PASSED" in out.out
    for f in [*(tmp_path / "a").iterdir(), *(tmp_path / "b").iterdir()]:
        assert KEY not in f.read_text(encoding="utf-8"), f
    assert KEY not in out.out + out.err
    row = json.loads((tmp_path / "b" / "rows.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "quote" not in row and "excerpts" not in row  # no note text in the results


def test_a_judge_that_excludes_too_much_fails_the_gate_with_an_interval(tmp_path: Path) -> None:
    def always_yes(inp: dict[str, Any]) -> dict[str, Any]:
        q, d = _first_sentence(inp)
        return {"verdict": "pass", "quote": q, "quote_date": d, "confidence": 0.95, "reason": "r"}

    items = _items(40)
    with jb.stub_server(answer=always_yes) as url:
        res = _bake(tmp_path, url, items)
    we = res["gated"]["wrong_exclusion"]
    assert we["rate"] > jb.WRONG_EXCLUSION_MAX and not res["gate"]["checks"]["wrong_exclusion_rate_le_2pct"]
    assert not res["gate"]["passed"]
    assert 0.0 <= we["wilson95"][0] <= we["rate"] <= we["wilson95"][1] <= 1.0 and len(we["cluster95"]) == 2
    # an exclusion criterion answered "yes" excludes; an inclusion one answered "yes" fits
    rows = [json.loads(x) for x in (tmp_path / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["eligibility"] for r in rows if r["kind"] == "exclusion" and r["reason"] == "note"} == {"fail"}
    assert {r["eligibility"] for r in rows if r["kind"] == "inclusion" and r["reason"] == "note"} == {"pass"}
    assert "Gate: FAILED" in (tmp_path / "metrics.md").read_text(encoding="utf-8")


def test_a_quote_not_in_the_note_is_invalid_and_never_excludes(tmp_path: Path) -> None:
    def invents(inp: dict[str, Any]) -> dict[str, Any]:
        return {"verdict": "pass", "quote": "no such sentence anywhere", "quote_date": inp["index_date"],
                "confidence": 0.99, "reason": "r"}  # fmt: skip

    with jb.stub_server(answer=invents) as url:
        res = _bake(tmp_path, url, _items(20))
    a = res["all"]
    assert a["citation"]["quote_found"]["rate"] == 0.0 and a["citation"]["quote_found"]["n"] > 0
    assert a["wrong_exclusion"]["n"] == 0 and a["unknown"]["model_unknown_excluded"] == 0
    assert res["gate"]["passed"]  # unsafe answers became unknown: nothing excluded


def test_unknown_never_excludes_and_mapping() -> None:
    assert jb.eligibility("exclusion", "unknown") == "unknown" == jb.eligibility("inclusion", "unknown")
    assert jb.eligibility("exclusion", "pass") == "fail" and jb.eligibility("inclusion", "fail") == "fail"
    good = jb.Row("a", "synthetic", "p1", "", "exclusion", "unknown", True, raw_verdict="unknown")
    bad = jb.Row("b", "synthetic", "p2", "", "exclusion", "unknown", True, raw_verdict="unknown", eligibility="fail")
    m = jb.metrics([good, bad])
    assert m["all"]["unknown"]["model_unknown_excluded"] == 1 and m["all"]["unknown"]["gold_unknown_excluded"] == 1
    assert not m["gate"]["checks"]["unknown_never_excludes"] and not m["gate"]["passed"]
    assert m["gate"]["checks"]["model_answered_90pct"]
    # Study A's definition: among the judge's exclusions; and the share of non-excluding gold that was excluded
    assert m["gated"]["wrong_exclusion"]["k"] == 1 and m["gated"]["wrong_exclusion"]["n"] == 1
    assert m["gated"]["wrong_exclusion"]["of_not_excluding_gold"]["n"] == 2
    m2 = jb.metrics([good])
    assert m2["gate"]["passed"]  # no exclusion at all: nothing wrong (fits precision and abstention show the cost)
    # the optional upper-bound gate: with no exclusions the interval is 0-100 %, so it cannot pass on no evidence
    assert not jb.metrics([good], max_upper_ci=0.05)["gate"]["checks"]["wrong_exclusion_upper95_le_max"]


def test_served_name_pin(tmp_path: Path) -> None:
    items = _items(6)
    with jb.stub_server(served_name="gemma-4-31b-it", root="google/gemma-4-31B-it") as url:
        with pytest.raises(jb.PinRefused, match="not in /v1/models"):
            _bake(tmp_path, url, items, served="judge-current")
        with pytest.raises(jb.PinRefused, match="expected"):
            _bake(tmp_path, url, items, served="gemma-4-31b-it", expect_root="someone/gemma-4-31B-it-finetune")
        res = _bake(tmp_path, url, items, served="gemma-4-31b-it", expect_root="google/gemma-4-31B-it")
        assert res["gate"]["passed"] and res["meta"]["pin"]["root"] == "google/gemma-4-31B-it"
    # an endpoint that lists the name but answers from another model fails the gate
    with jb.stub_server(served_name="gemma-4-31b-it", report_model="something-else") as url:
        res = _bake(tmp_path, url, items, served="gemma-4-31b-it")
    assert res["all"]["served_mismatch"] > 0 and not res["gate"]["checks"]["served_name_pinned"]
    assert jb.main(["--base-url", "http://127.0.0.1:9/v1", "--served-name", "x", "--set", str(_set(tmp_path, items)),
                    "--out", str(tmp_path / "c")]) == 3  # fmt: skip


def _set(tmp: Path, items: list[jb.Item]) -> Path:
    p = tmp / "s.jsonl"
    jb.write_set(items, p)
    return p


def test_a_model_that_does_not_answer_fails_the_run_but_excludes_nobody(tmp_path: Path) -> None:
    with jb.stub_server(answer=lambda inp: {"label": "nonsense"}) as url:
        res = _bake(tmp_path, url, _items(8))
    a = res["all"]
    assert a["no_answer"]["rate"] == 1.0 and a["wrong_exclusion"]["n"] == 0
    assert not res["gate"]["checks"]["model_answered_90pct"] and not res["gate"]["passed"]


def test_public_set_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools import medtxt_eval, trec_ct_eval

    med = [
        {"id": "CR:1|0", "report": "CR:1", "finding": "pneumonia", "certainty": "positive", "strict": True},
        {"id": "CR:1|1", "report": "CR:1", "finding": "fever", "certainty": "negative", "strict": True},
        {"id": "CR:1|2", "report": "CR:1", "finding": "mass", "certainty": "negative", "strict": False},
        {"id": "CR:1|3", "report": "CR:1", "finding": "tumour", "certainty": "suspicious", "strict": True},
        {"id": "CR:1|4", "report": "CR:1", "finding": "gout", "certainty": "absent", "strict": True},
    ]
    notes = {"ja": {"CR:1": ["肺炎あり。", "発熱なし。"]}, "en": {"CR:1": ["Pneumonia.", "No fever."]}}
    monkeypatch.setattr(medtxt_eval, "dataset", lambda: (med, notes))
    got = {i.id: i for i in jb.medtxt_items()}
    assert len(got) == 8  # the non-strict tag is dropped; ja and en each
    assert [got[f"medtxt:ja:CR:1|{k}"].gold for k in (0, 1, 3, 4)] == ["pass", "fail", "unknown", "unknown"]
    assert got["medtxt:en:CR:1|0"].excerpts[0]["text"] == "Pneumonia. No fever." and got["medtxt:en:CR:1|0"].gated

    pairs = [
        {"year": "2021", "patient": "t1", "trial": "NCT1", "label": "2",
         "criteria": [("inclusion", "Adults."), ("exclusion", "Pregnancy.")]},
        {"year": "2021", "patient": "t2", "trial": "NCT2", "label": "1", "criteria": [("inclusion", "Children.")]},
    ]  # fmt: skip
    monkeypatch.setattr(trec_ct_eval, "dataset", lambda: (pairs, {"t1": ["A 40 year old man."]}, {}, {}))
    trec = jb.trec_items(pairs=10)
    assert [i.id for i in trec] == ["trec_ct:t1|NCT1|0", "trec_ct:t1|NCT1|1"]  # NIST-eligible pairs only
    assert {i.gold for i in trec} == {"not_excluded"} and not any(i.gated for i in trec)
    assert {jb.gold_eligibility(i) for i in trec} == {"not_fail"}
    rows = [jb.Row(i.id, i.source, i.cluster, i.pair, i.kind, i.gold, i.gated, raw_verdict="pass") for i in trec]
    rows[1].eligibility = "fail"
    m = jb.metrics(rows)
    assert m["all"]["eligible_pairs_lost"]["k"] == 1 and m["gated"]["n"] == 0
    assert not m["gate"]["checks"]["gated_items_present"]  # TREC alone cannot pass the gate

    def missing() -> Any:
        raise FileNotFoundError("x")

    monkeypatch.setattr(medtxt_eval, "dataset", missing)
    items, skipped = jb.build_set(("synthetic", "medtxt"), n_per_source=5)
    assert len(items) == 5 and skipped == {"medtxt": "data not fetched: python -m tools.medtxt_eval fetch"}


def test_compare_two_runs(tmp_path: Path) -> None:
    items = _items(6)
    with jb.stub_server(served_name="judge-a") as url:
        _bake(tmp_path / "a", url, items, served="judge-a")
    with jb.stub_server(served_name="judge-b") as url:
        _bake(tmp_path / "b", url, items, served="judge-b")
    table = jb.compare([tmp_path / "a", tmp_path / "b"])
    assert "| metric | judge-a | judge-b |" in table and "wrong exclusions (gated)" in table
    assert "WARNING" not in table

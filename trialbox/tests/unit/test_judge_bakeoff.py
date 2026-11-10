"""Judge bake-off harness (D-181): the product's judge prompt and parser against a local OpenAI-compatible stub.

No network beyond 127.0.0.1, no real key: the "key" here is a test string that must reach the stub's Authorization
header and never the output files, stdout or stderr.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import judge_bakeoff as jb

KEY = "sk-test-NOT-A-REAL-KEY-7f3a"
SMALL = jb.GateConfig(min_exclusions=1, min_answered=1, require=("synthetic",))


def _items(n: int = 30) -> list[jb.Item]:
    """A small slice with every criterion and gold value, items with notes only."""
    by: dict[tuple[str, str], list[jb.Item]] = {}
    for it in jb.synthetic_items():
        if it.excerpts:
            by.setdefault((it.criterion_text, it.gold), []).append(it)
    out: list[jb.Item] = []
    while len(out) < n:
        for group in by.values():
            if group and len(out) < n:
                out.append(group.pop())
    return out


def _bake(tmp: Path, url: str, items: list[jb.Item], **kw: Any) -> dict[str, Any]:
    kw.setdefault("expect_root", jb.STUB_ROOT)
    kw.setdefault("gate", SMALL)
    served = kw.pop("served", jb.STUB_NAME)
    return jb.bake(url, served, items, tmp, sha=jb.set_sha(items), backoff=(0.0,), **kw)


def _first_sentence(inp: dict[str, Any]) -> tuple[str, str]:
    ex = inp["excerpts"][0]
    return str(ex["text"]).split("。")[0], str(ex["date"])


def _rows(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (tmp / "rows.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]


def _row(i: int, source: str = "synthetic", **kw: Any) -> jb.Row:
    kind = kw.pop("kind", "exclusion")
    gold = kw.pop("gold", "fail")
    gated = kw.pop("gated", source != "trec_ct")
    cluster = kw.pop("cluster", f"p{i % 7}")
    kw.setdefault("raw_verdict", "pass")
    return jb.Row(f"{source}:{i}", source, cluster, "", kind, gold, gated, **kw)


def _excl(source: str, wrong: int, right: int, start: int = 0) -> list[jb.Row]:
    """``wrong`` exclusions of items whose gold does not exclude, ``right`` exclusions whose gold excludes."""
    rows = [
        _row(start + i, source, gold="unknown", predicate="pass", eligibility="fail", gold_eligibility="unknown")
        for i in range(wrong)
    ]
    rows += [
        _row(start + wrong + i, source, predicate="pass", eligibility="fail", gold_eligibility="fail")
        for i in range(right)
    ]
    return rows


# ------------------------------------------------------------------------------------------------- end to end
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
    assert res["meta"]["pin"]["id"] == jb.STUB_NAME and res["gate"]["checks"]["pin:unchanged_at_end"]
    g = res["gated"]
    assert g["n"] == g["asked"] == len(items) and g["wrong_exclusion"]["k"] == 0 and g["wrong_exclusion"]["n"] > 0
    assert g["fits_precision"]["n"] > 0 and g["citation"]["quote_found"]["rate"] == 1.0
    assert g["latency_s"]["p95"] > 0 and g["call_latency_s"]["calls"] == len(items) and g["tokens"]["in"] > 0
    # the CLI on a frozen set, with the stub: same gate, and the key appears nowhere
    set_path = tmp_path / "set.jsonl"
    sha = jb.write_set(items, set_path)
    assert jb.read_set(set_path) == (items, sha)
    argv = ["--stub", "--set", str(set_path), "--expect-set-sha", sha, "--require-sources", "synthetic"]
    assert jb.main([*argv, "--min-exclusions", "1", "--min-answered", "1", "--out", str(tmp_path / "b")]) == 0
    out = capsys.readouterr()
    assert "Gate: PASSED" in out.out
    sentence = max((s for it in items for e in it.excerpts for s in str(e["text"]).split("。")), key=len)
    for f in [*(tmp_path / "a").iterdir(), *(tmp_path / "b").iterdir()]:
        text = f.read_text(encoding="utf-8")
        assert KEY not in text, f
        assert sentence not in text, f  # no note text in the results
    assert KEY not in out.out + out.err


def test_key_never_leaks_on_refusal_and_never_goes_over_plain_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TB_BAKEOFF_API_KEY", KEY)
    p = tmp_path / "s.jsonl"
    jb.write_set(_items(4), p)
    tail = ["--served-name", "x", "--expect-root", "r", "--set", str(p), "--out", str(tmp_path / "o")]
    with jb.stub_server(served_name="other") as url:
        assert jb.main(["--base-url", url, *tail]) == 3
    assert jb.main(["--base-url", "http://10.1.2.3:8000/v1", *tail]) == 2
    out = capsys.readouterr()
    assert "plain http" in out.err and KEY not in out.out + out.err
    assert not (tmp_path / "o").exists()  # refused before anything was written


def test_a_judge_that_excludes_too_much_fails_the_gate_with_an_interval(tmp_path: Path) -> None:
    def always_yes(inp: dict[str, Any]) -> dict[str, Any]:
        q, d = _first_sentence(inp)
        return {"verdict": "pass", "quote": q, "quote_date": d, "confidence": 0.95, "reason": "r"}

    with jb.stub_server(answer=always_yes) as url:
        res = _bake(tmp_path, url, _items(40))
    we = res["gated"]["wrong_exclusion"]
    assert we["rate"] > jb.WRONG_EXCLUSION_MAX and not res["gate"]["checks"]["synthetic:wrong_exclusion_le_2pct"]
    assert not res["gate"]["passed"]
    assert 0.0 <= we["wilson95"][0] <= we["rate"] <= we["wilson95"][1] <= 1.0 and len(we["cluster95"]) == 2
    rows = _rows(tmp_path)
    assert {r["eligibility"] for r in rows if r["kind"] == "exclusion" and r["reason"] == "note"} == {"fail"}
    assert {r["eligibility"] for r in rows if r["kind"] == "inclusion" and r["reason"] == "note"} == {"pass"}
    assert "Gate: FAILED" in (tmp_path / "metrics.md").read_text(encoding="utf-8")


def test_invented_quotes_never_exclude_but_cannot_pass_the_gate(tmp_path: Path) -> None:
    def invents(inp: dict[str, Any]) -> dict[str, Any]:
        return {"verdict": "pass", "quote": "no such sentence anywhere", "quote_date": inp["index_date"],
                "confidence": 0.99, "reason": "r"}  # fmt: skip

    with jb.stub_server(answer=invents) as url:
        res = _bake(tmp_path, url, _items(20))
    a = res["all"]
    assert a["citation"]["quote_found"]["rate"] == 0.0 and a["citation"]["quote_found"]["n"] > 0
    assert a["wrong_exclusion"]["n"] == 0 and a["unknown"]["model_unknown_excluded"] == 0  # nothing excluded
    assert not res["gate"]["checks"]["synthetic:exclusions_ge_1"] and not res["gate"]["passed"]  # 0 of 0 is no pass


def test_quote_date_accepts_any_excerpt_holding_the_quote(tmp_path: Path) -> None:
    it = _items(1)[0]
    s = "目前無急性痛風發作，關節檢查無紅腫或壓痛。"
    it.excerpts = [
        {"date": "2026-09-01", "note_type": "n", "text": s},
        {"date": "2026-08-01", "note_type": "n", "text": s},
    ]

    def cites_older(inp: dict[str, Any]) -> dict[str, Any]:
        return {"verdict": "fail", "quote": s, "quote_date": "2026-08-01", "confidence": 0.9, "reason": "r"}

    with jb.stub_server(answer=cites_older) as url:
        _bake(tmp_path, url, [it])
    row = _rows(tmp_path)[0]
    assert row["quote_found"] is True and row["quote_date_ok"] is True


# ------------------------------------------------------------------------------------------------- gate edges
def test_wrong_exclusion_boundary_is_exact() -> None:
    ok = jb.metrics(_excl("synthetic", 1, 49), gate=SMALL)  # 1/50 = 2 %: passes
    assert ok["gate"]["checks"]["synthetic:wrong_exclusion_le_2pct"] and ok["gate"]["passed"]
    bad = jb.metrics(_excl("synthetic", 9, 440), gate=SMALL)  # 9/449 = 2.004 %: rounds to 0.02, still fails
    assert bad["gated"]["wrong_exclusion"]["rate"] == 0.02
    assert not bad["gate"]["checks"]["synthetic:wrong_exclusion_le_2pct"] and not bad["gate"]["passed"]


def test_each_gated_source_is_gated_separately() -> None:
    cfg = jb.GateConfig(min_exclusions=1, min_answered=1, require=("synthetic", "medtxt"))
    rows = _excl("synthetic", 5, 45) + _excl("medtxt", 0, 400, start=100)  # 10 % and 0 %: pooled 1.1 %
    m = jb.metrics(rows, gate=cfg)
    c = m["gate"]["checks"]
    assert m["gated"]["wrong_exclusion"]["rate"] < 0.02
    assert not c["synthetic:wrong_exclusion_le_2pct"] and c["medtxt:wrong_exclusion_le_2pct"]
    assert not m["gate"]["passed"]


def test_unanswered_gated_items_fail_even_when_trec_answers() -> None:
    silent = [_row(i, raw_verdict="", error="no_answer", reason="model_down") for i in range(300)]
    trec = [_row(1000 + i, "trec_ct", gold="not_excluded", gold_eligibility="not_fail") for i in range(3000)]
    m = jb.metrics(silent + trec, gate=SMALL)
    assert m["all"]["no_answer"]["rate"] < 0.10  # pooled with TREC it would look fine
    c = m["gate"]["checks"]
    assert not c["synthetic:no_answer_le_10pct"] and not c["synthetic:answered_ge_1"] and not m["gate"]["passed"]


def test_minimums_required_sources_and_upper_bound() -> None:
    rows = _excl("synthetic", 0, 10)
    m = jb.metrics(rows)  # defaults: 20 exclusions, 50 answers, synthetic and medtxt required
    c = m["gate"]["checks"]
    assert not c["synthetic:exclusions_ge_20"] and not c["synthetic:answered_ge_50"] and not c["medtxt:present"]
    assert not m["gate"]["passed"]
    cfg = jb.GateConfig(min_exclusions=1, min_answered=1, require=("synthetic",), max_upper_ci=0.05)
    m = jb.metrics(rows, gate=cfg)  # 0/10: upper Wilson bound about 28 %
    assert not m["gate"]["checks"]["gated:wrong_exclusion_upper95_le_max"] and not m["gate"]["passed"]
    assert jb.metrics(_excl("synthetic", 0, 100), gate=cfg)["gate"]["passed"]  # 0/100: about 3.7 %
    empty = [_row(i, raw_verdict="", reason="no_notes") for i in range(10)]  # nothing asked: nothing passes
    assert not jb.metrics(empty, gate=SMALL)["gate"]["passed"]


def test_unknown_mapping_and_the_product_self_check() -> None:
    assert jb.eligibility("exclusion", "unknown") == "unknown" == jb.eligibility("inclusion", "unknown")
    assert jb.eligibility("exclusion", "pass") == "fail" and jb.eligibility("inclusion", "fail") == "fail"
    assert jb.eligibility("renewal", "fail") == "fail"
    bug = [*_excl("synthetic", 0, 30), _row(99, predicate="unknown", gold="unknown", eligibility="fail")]
    m = jb.metrics(bug, gate=SMALL)
    assert not m["gate"]["checks"]["product:unknown_never_excludes"] and not m["gate"]["passed"]
    assert m["gated"]["unknown"]["gold_unknown_excluded"]["k"] == 1


def test_cluster_interval_resamples_patients_without_exclusions() -> None:
    rows = _excl("synthetic", 1, 9) + [_row(500 + i, cluster=f"q{i}") for i in range(20)]
    lo, hi = jb.metrics(rows, gate=SMALL)["gated"]["wrong_exclusion"]["cluster95"]
    assert 0.0 <= lo <= 0.1 <= hi <= 1.0


# ------------------------------------------------------------------------------------------------- the pin
def test_served_name_pin(tmp_path: Path) -> None:
    items = _items(6)
    with jb.stub_server(served_name="gemma-4-31b-it", root="google/gemma-4-31B-it") as url:
        with pytest.raises(jb.PinRefused, match="not in /v1/models"):
            _bake(tmp_path, url, items, served="judge-current")
        with pytest.raises(jb.PinRefused, match="expected"):
            _bake(tmp_path, url, items, served="gemma-4-31b-it", expect_root="someone/gemma-4-31B-it-finetune")
        res = _bake(tmp_path, url, items, served="gemma-4-31b-it", expect_root="google/gemma-4-31B-it", revision="abc")
        assert res["gate"]["passed"] and res["meta"]["pin"]["root"] == "google/gemma-4-31B-it"
        assert res["meta"]["weights"] == {"revision": "abc", "model_dir": None, "manifest_sha256": None}
        unverified = _bake(tmp_path, url, items, served="gemma-4-31b-it", expect_root="")
        assert not unverified["gate"]["checks"]["pin:root_verified"] and not unverified["gate"]["passed"]
        assert "UNVERIFIED" in (tmp_path / "metrics.md").read_text(encoding="utf-8")
    # a renaming proxy: the name listed, answers reported from another model
    with jb.stub_server(served_name="gemma-4-31b-it", report_model="something-else") as url:
        res = _bake(tmp_path, url, items, served="gemma-4-31b-it")
    assert res["all"]["served_mismatch"] > 0 and not res["gate"]["checks"]["pin:responses_report_served_name"]
    p = tmp_path / "s.jsonl"
    jb.write_set(items, p)
    base = ["--served-name", "x", "--set", str(p), "--out", str(tmp_path / "c")]
    assert jb.main(["--base-url", "http://127.0.0.1:9/v1", *base]) == 2  # --expect-root is required
    assert jb.main(["--base-url", "http://127.0.0.1:9/v1", "--expect-root", "r", *base]) == 3  # nothing listening


def test_weight_manifest_is_recorded_and_checked(tmp_path: Path) -> None:
    w = tmp_path / "w"
    w.mkdir()
    (w / "model.safetensors").write_bytes(b"weights")
    (w / "config.json").write_text("{}")
    rec = jb.weights_record(w, revision="r1")
    assert rec["manifest_sha256"] and rec["revision"] == "r1" and rec["files"] == 2
    assert jb.weights_record(w, expect_manifest=rec["manifest_sha256"])["manifest_sha256"] == rec["manifest_sha256"]
    with pytest.raises(jb.PinRefused, match="manifest"):
        jb.weights_record(w, expect_manifest="0" * 64)
    with pytest.raises(jb.PinRefused, match="model-dir"):
        jb.weights_record(None, expect_manifest="0" * 64)


def test_a_server_swapped_during_the_run_fails_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    orig = jb.models_entry
    calls = {"n": 0}

    def swapped(*a: Any, **k: Any) -> dict[str, Any]:
        calls["n"] += 1
        e = orig(*a, **k)
        return e if calls["n"] == 1 else {**e, "created": 2}  # the second read sees another start

    monkeypatch.setattr(jb, "models_entry", swapped)
    with jb.stub_server() as url:
        res = _bake(tmp_path, url, _items(4))
    assert calls["n"] == 2
    assert not res["gate"]["checks"]["pin:unchanged_at_end"] and not res["gate"]["passed"]


# ------------------------------------------------------------------------------------------------- failures
def test_a_model_that_does_not_answer_fails_the_run_but_excludes_nobody(tmp_path: Path) -> None:
    with jb.stub_server(answer=lambda inp: {"label": "nonsense"}) as url:
        res = _bake(tmp_path, url, _items(8))
    a = res["all"]
    assert a["no_answer"]["rate"] == 1.0 and a["wrong_exclusion"]["n"] == 0
    assert a["call_latency_s"]["calls"] == 16 and a["tokens"]["in"] > 0  # both schema attempts are counted
    assert not res["gate"]["checks"]["synthetic:no_answer_le_10pct"] and not res["gate"]["passed"]


def test_4xx_is_not_retried_5xx_is_and_a_malformed_200_does_not_crash(tmp_path: Path) -> None:
    items = _items(2)
    hits: list[int] = []

    def status(code: int, body: Any) -> Any:
        def f(_: dict[str, Any]) -> tuple[int, Any]:
            hits.append(code)
            return code, body

        return f

    def go(out: Path, raw: Any, its: list[jb.Item]) -> dict[str, Any]:
        with jb.stub_server(raw=raw) as url:
            return jb.bake(url, jb.STUB_NAME, its, out, sha="x", expect_root=jb.STUB_ROOT, backoff=(0.0, 0.0))

    res = go(tmp_path / "a", status(400, {"error": "context length"}), items)
    assert len(hits) == len(items) and res["all"]["no_answer"]["k"] == len(items)  # no retry on 4xx
    hits.clear()
    go(tmp_path / "b", status(503, {"error": "busy"}), items[:1])
    assert len(hits) == 3  # one call and two retries
    for body in ({"id": "x"}, "not json at all"):
        res = go(tmp_path / "c", status(200, body), items)
        assert res["all"]["no_answer"]["k"] == len(items) and len(_rows(tmp_path / "c")) == len(items)


def test_rows_are_written_as_they_complete_and_resume_keeps_them(tmp_path: Path) -> None:
    items = _items(6)
    with jb.stub_server() as url:
        _bake(tmp_path, url, items[:3])
    assert len(_rows(tmp_path)) == 3
    seen: list[str] = []
    with jb.stub_server(seen_auth=seen) as url:
        _bake(tmp_path, url, items, resume=True)
    assert len(seen) == 3 and [r["id"] for r in _rows(tmp_path)] == [i.id for i in items]


# ------------------------------------------------------------------------------------------------- the set
def test_frozen_set_is_checked(tmp_path: Path) -> None:
    items = _items(3)
    items[0].excerpts[0]["text"] += " line"  # U+2028 inside a note must not split the line
    p = tmp_path / "s.jsonl"
    sha = jb.write_set(items, p)
    assert jb.read_set(p, sha)[0] == items
    with pytest.raises(ValueError, match="expected"):
        jb.read_set(p, "0" * 64)
    doc = json.loads(p.read_text(encoding="utf-8").split("\n")[1])
    doc["gated"] = False  # never trusted from the file
    q = tmp_path / "t.jsonl"
    q.write_text(json.dumps(doc) + "\n", encoding="utf-8")
    assert jb.read_set(q)[0][0].gated is True
    doc["gold"] = "maybe"
    q.write_text(json.dumps(doc) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source/kind/gold"):
        jb.read_set(q)


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
    m = jb.metrics(rows, gate=SMALL)
    assert m["all"]["eligible_pairs_lost"]["k"] == 1 and m["gated"]["n"] == 0
    assert not m["gate"]["checks"]["synthetic:present"]  # TREC alone cannot pass the gate

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
        _bake(tmp_path / "c", url, items[:3], served="judge-b")
    table, ok = jb.compare([tmp_path / "a", tmp_path / "b"])
    assert ok and "| metric | judge-a | judge-b |" in table and "wrong exclusions, synthetic" in table
    assert jb.main(["--compare", str(tmp_path / "a"), str(tmp_path / "c")]) == 1  # different sets

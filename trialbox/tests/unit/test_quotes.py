"""Quote check tolerates the stray spaces models put into Japanese / Chinese quotes (2026-11-08 canary)."""

from __future__ import annotations

from datetime import date

from matching.cascade.judge import JudgeReply, verify_span
from orchestrator.scenarios.evaluate import postprocess
from tb_common.quotes import quote_in, quote_key

NOTE = "評価：2型糖尿病。メトホルミン500mg 1日2回内服中。HbA1c 7.4%。"


def test_spaces_next_to_cjk_do_not_count_but_latin_words_keep_theirs() -> None:
    assert quote_in("評価：2 型糖尿病。メトホルミン 500mg 1 日 2 回内服中。", NOTE)
    assert quote_in("2026 年に肝酵素上昇のためメトトレキサート中止。", "2026年に肝酵素上昇のためメトトレキサート中止。")
    assert quote_in("病人 目前 服用 metformin", "病人目前服用 metformin")
    assert quote_key("type 2  diabetes") == "type 2 diabetes"
    assert not quote_in("type2 diabetes", "type 2 diabetes")  # Latin spacing is still exact
    assert not quote_in("2型糖尿病なし", NOTE)  # a quote that is not in the note still fails
    assert not quote_in("", NOTE)


def test_screening_and_cascade_accept_the_spaced_japanese_quote() -> None:
    ex = [{"date": "2026-10-01", "note_type": "経過記録", "text": NOTE, "did": "d1"}]
    r = postprocess({"verdict": "pass", "confidence": 0.9, "quote": "評価：2 型糖尿病。"}, ex)
    assert r.predicate == "pass" and r.dids == ["d1"]
    reply = JudgeReply("pass", 0.9, "メトホルミン 500mg 1 日 2 回内服中", "2026-10-01", "")
    span = verify_span(reply, ex, date(2026, 1, 1), date(2026, 11, 1))
    assert span is not None and span["did"] == "d1"

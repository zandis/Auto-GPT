"""Card 10G-38 (D-1326): every accuracy report names its gold kind, and a figure that pools kinds is refused."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tools import gold_kind as gk
from tools import medtxt_eval
from tools.public_accuracy import replay

pytestmark = [pytest.mark.nodb]


def _set(name: str, kind: str | None, k: int, n: int) -> dict[str, Any]:
    return {"set": name, "gold_kind": kind, "scored": True, "numerator": k, "denominator": n,
            "with_conflicted": {"numerator": k, "denominator": n}, "conflicted": None,
            "conflicted_excluded_on_another_line": []}  # fmt: skip


def test_the_five_kinds_are_the_only_values() -> None:
    assert gk.KINDS == ("physician", "generated and checked", "translated", "structured truth", "enrolment")
    with pytest.raises(ValueError, match="not one of the five kinds"):
        gk.read({"gold_kind": "silver"})
    with pytest.raises(ValueError, match="not one of the five kinds"):
        gk.pooled([("a", "physician"), ("b", "clinician")])
    for name in ("medtxt", "criterion_ml", "sigir", "jmed", "trec", "trec2023", "tcga", "accuracy", "chia"):
        for lang in (None, "ja", "en", "zh-TW", "mixed"):
            assert gk.of_set(name, lang) in (*gk.KINDS, None)


def test_pooling_across_kinds_is_refused() -> None:
    with pytest.raises(gk.PoolingRefused, match=r"not pooled: .*sigir: physician; jmed: structured truth"):
        gk.pooled([("sigir", "physician"), ("jmed", "structured truth")])
    with pytest.raises(gk.PoolingRefused, match="trec: not stated"):
        gk.pooled([("sigir", "physician"), ("trec", None)])
    with pytest.raises(gk.PoolingRefused):  # two sets of unstated kind cannot be shown to share one
        gk.pooled([("trec", None), ("tcga", None)])
    assert gk.pooled([("sigir", "physician"), ("medtxt ja", "physician")]) == "physician"
    assert gk.pooled([("trec", None)]) == gk.NOT_STATED  # one set is not a pool


def test_a_report_without_the_field_reads_not_stated_and_never_pools() -> None:
    old: dict[str, Any] = {"set": "sigir", "pairs": {}}  # a score.json stored before 10G-38
    assert gk.read(old) == "not stated"
    with pytest.raises(gk.PoolingRefused):
        gk.pooled([("old sigir", None if gk.read(old) == gk.NOT_STATED else gk.read(old)), ("sigir", "physician")])
    # the replay's per-set figure of an old score carries no kind, so it pools with nothing
    f = replay.eligible_figure("sigir", {"set": "sigir", "criteria": {"wrong_exclusion": {"k": 1, "n": 4}}})
    assert f["gold_kind"] is None and (f["numerator"], f["denominator"]) == (1, 4)


def test_the_replay_figure_refuses_to_pool_sets_of_different_kinds() -> None:
    fig = replay.figure("a", "v2", [_set("sigir", "physician", 1, 10), _set("jmed", "structured truth", 0, 7)])
    assert fig["numerator"] is None and fig["denominator"] is None
    assert fig["with_conflicted"] == {"numerator": None, "denominator": None}
    assert "sigir: physician; jmed: structured truth" in fig["pooled_refused"]
    assert fig["by_gold_kind"] == {"physician": {"numerator": 1, "denominator": 10, "sets": ["sigir"]},
                                   "structured truth": {"numerator": 0, "denominator": 7, "sets": ["jmed"]}}  # fmt: skip
    assert [(x["set"], x["numerator"], x["denominator"]) for x in fig["per_set"]] == [("sigir", 1, 10), ("jmed", 0, 7)]
    assert fig["within_target"] is False  # read set by set: sigir excluded one eligible patient


def test_the_replay_figure_pools_one_stated_kind() -> None:
    fig = replay.figure("a", "v2", [_set("sigir", "physician", 1, 10), _set("criterion_ml en", "physician", 0, 5)])
    assert (fig["numerator"], fig["denominator"], fig["pooled_refused"]) == (1, 15, None)


def test_writers_name_the_kind() -> None:
    # public_accuracy's score.json (built from the set's ids): sigir physician, jmed structured truth, trec not stated
    assert (gk.of_set("sigir"), gk.of_set("jmed"), gk.of_set("trec")) == ("physician", "structured truth", None)
    # MedTxt: the Japanese annotation is the gold; on the clinicians' English translation it is carried over
    key = json.loads((medtxt_eval.RESULTS.parent / "key.json").read_text(encoding="utf-8"))["items"]
    items = [{"id": a, "certainty": c, "report": a.split("|")[0], "strict": False} for a, c in list(key.items())[:20]]
    model = "google/gemma-4-26b-a4b-it@fp4"
    assert medtxt_eval.score_combo([model], "ja", items)["gold_kind"] == "physician"
    assert medtxt_eval.score_combo([model], "en", items)["gold_kind"] == "translated"
    assert (gk.of_set("criterion_ml", "en"), gk.of_set("criterion_ml", "ja")) == ("physician", "translated")


def test_every_stated_kind_names_its_source() -> None:
    for name in ("medtxt", "criterion_ml", "sigir", "jmed"):
        assert gk.source(name)
    assert gk.source("trec") == ""

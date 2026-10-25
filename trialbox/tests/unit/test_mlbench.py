"""Multilingual criterion benchmark harness (tools/mlbench.py)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tools import mlbench


def test_dataset_aligned_across_languages() -> None:
    pairs = mlbench.load_pairs()
    assert len(pairs) == 1015
    notes = {lang: mlbench.load_notes(lang) for lang in mlbench.LANGS}
    for lang in mlbench.LANGS:
        assert notes[lang].keys() == notes["en"].keys()
        for pid, sents in notes["en"].items():
            assert len(notes[lang][pid]) == len(sents), (lang, pid)
    for p in pairs:
        n = len(notes["en"][p.patient_id])
        assert all(i < n for i in p.expert_sentences)
        assert p.expert_label in mlbench.LABELS[p.criterion_type]


def test_sample_keeps_blocking_pairs() -> None:
    pairs = mlbench.load_pairs()
    s = mlbench.sample(pairs, 400)
    assert len(s) == 400 and s == mlbench.sample(pairs, 400)
    ids = {p.annotation_id for p in s}
    assert all(p.annotation_id in ids for p in pairs if p.expert_label in mlbench.BLOCKS)
    small = mlbench.sample(pairs, 20)
    assert len(small) == 20 and all(p.expert_label in mlbench.BLOCKS for p in small)


@pytest.mark.parametrize(
    ("raw", "ctype", "want"),
    [
        ("Included.", "inclusion", "included"),
        ("not_enough_information", "exclusion", "not enough information"),
        ("met", "exclusion", "excluded"),
        ("excluded", "inclusion", None),
        (None, "inclusion", None),
    ],
)
def test_norm_label(raw: object, ctype: str, want: str | None) -> None:
    assert mlbench.norm_label(raw, ctype) == want


def test_run_and_score_with_fake_endpoint(tmp_path: Path) -> None:
    pairs = mlbench.sample(mlbench.load_pairs(), 20)
    gold = {p.annotation_id: p for p in pairs}
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(req.content)
        user = body["messages"][1]["content"]
        # an oracle that answers with the physician label for the criterion in the prompt
        p = next(p for p in pairs if f"Criterion: {p.criterion}\n" in user)
        out = {"label": p.expert_label, "evidence": list(p.expert_sentences), "explanation": "x"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "```json\n" + json.dumps(out) + "\n```"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0001},
            },
        )

    client = mlbench.Client("http://fake/v1", "k", tmp_path / "cache")
    client.http = httpx.Client(transport=httpx.MockTransport(handler))
    mlbench.run(client, ["fake/model"], ["en", "mixed"], pairs, tmp_path / "res", workers=4)
    assert calls["n"] == 40
    mlbench.run(client, ["fake/model"], ["en", "mixed"], pairs, tmp_path / "res", workers=4)
    assert calls["n"] == 40  # resumed: nothing re-asked
    table = mlbench.report(tmp_path / "res", list(gold.values()), pairs)
    s = table["fake/model"]["en"]
    assert s["accuracy"] == 1.0 and s["false_block_rate"] == 0.0 and s["valid_rate"] == 1.0
    assert table["fake/model"]["_summary"]["parity_gap"] == 0.0
    mlbench.write_markdown(table, tmp_path / "r.md", len(pairs))
    assert "fake/model" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_unusable_answer_counts_as_abstention(tmp_path: Path) -> None:
    pairs = mlbench.sample(mlbench.load_pairs(), 5)
    client = mlbench.Client("http://fake/v1", "k", tmp_path / "cache")
    client.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "I think yes"}}]})
        )
    )
    res = mlbench.judge(client, "m", "en", pairs[0], mlbench.load_notes("en")[pairs[0].patient_id])
    assert res.error == "unparseable" and res.label is None


def test_clopper_pearson_upper() -> None:
    assert abs(mlbench.cp_upper(0, 299) - 0.00997) < 2e-4  # rule of three
    assert abs(mlbench.cp_upper(1, 473) - 0.01) < 3e-4
    assert mlbench.cp_upper(0, 0) == 1.0


def test_gpt4_reference_on_all_pairs() -> None:
    pairs = mlbench.load_pairs()
    m = mlbench.gpt4_reference(pairs)
    assert m["n"] == 1015 and 0.0 < m["false_block_rate"] < m["false_block_upper95"] < 0.05
    assert m["trials_open"] > 0

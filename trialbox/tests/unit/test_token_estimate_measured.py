"""The token estimate against the models' own tokenizers (review test G-5; D-645).

``tests/fixtures/llm/token_counts_cjk.json`` holds 400 synthetic excerpts (ja, zh-TW) with their token counts by the
tokenizers of the registry's judge and verifier builds. Run C of 2026-11-13 found the worst real / estimated ratio at
1.2121 (zh-TW, the judge): over the share the budget keeps free (1 / SAFETY = 1.176). The cause: both tokenizers give
every digit a token of its own and the estimate counted digits as a quarter; the cascade's own estimate also counted
full-width punctuation (，：（）) as a quarter.

The rule held here is G-5's: the largest ratio, with 5 % for what the sample did not see, fits in 1 / SAFETY, for
every estimate the product makes of a text.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from matching.cascade import engine as cascade_engine
from matching.cascade.judge import expected_tokens
from matching.excerpts import sentences
from tb_llm.budget import SAFETY, estimate_tokens, excerpt_tokens

DOC = json.loads((Path(__file__).resolve().parents[1] / "fixtures/llm/token_counts_cjk.json").read_text("utf-8"))
ROWS = [dict(zip(DOC["columns"], r, strict=True)) for r in DOC["rows"]]
MARGIN = 1.05  # G-5's: for what a sample of 400 did not see
ESTIMATES: dict[str, Callable[[str], int]] = {
    "budget": estimate_tokens,
    "cascade": lambda text: expected_tokens([{"text": text}]) - 300,  # minus its fixed share for the prompt
}


def test_the_measured_set_is_whole() -> None:
    assert len(ROWS) == 400 and {r["language"] for r in ROWS} == {"ja", "zh-TW"}
    assert all(r["judge"] > 0 and r["verifier"] > 0 for r in ROWS)
    assert all(len(t["sha256"]) == 64 for t in DOC["tokenizers"].values())


@pytest.mark.parametrize("model", ["judge", "verifier"])
@pytest.mark.parametrize("estimate", sorted(ESTIMATES))
def test_the_worst_measured_ratio_fits_the_share_the_budget_keeps_free(estimate: str, model: str) -> None:
    worst = max(ROWS, key=lambda r: r[model] / ESTIMATES[estimate](r["text"]))
    ratio = worst[model] / ESTIMATES[estimate](worst["text"])
    assert ratio * MARGIN <= 1 / SAFETY, (round(ratio, 4), worst["language"], worst["text"])


@pytest.mark.parametrize("model", ["judge", "verifier"])
def test_no_measured_text_has_more_tokens_than_the_estimate(model: str) -> None:
    """Stronger than the share: on this set the estimate is an upper bound, so SAFETY is all margin."""
    over = [(r[model], estimate_tokens(r["text"]), r["text"]) for r in ROWS if r[model] > estimate_tokens(r["text"])]
    assert over == []


def test_a_digit_counts_as_a_token_and_the_cascade_uses_the_one_estimate() -> None:
    assert estimate_tokens("115") == 3 + 1 and estimate_tokens("民國115年3月14日") == 11 + 1
    assert estimate_tokens("abcdefgh") == 2 + 1  # other text as before: four characters per token
    text = "壓痛關節數22處，腫脹關節數25處：（左）"
    assert expected_tokens([{"text": text}]) == 300 + estimate_tokens(text)


@pytest.mark.parametrize("text", ["Stable. No change today.", "著変なし。"])
def test_the_cascades_excerpt_set_fits_its_budget_as_the_prompt_counts_it(text: str) -> None:
    """Review of D-645: the cascade sized its set on the notes' text alone; the prompt shows each note with its
    date and type as JSON. Hundreds of short notes passed as "all shown, none left out" and the gateway then
    refused the whole call as too long. The set is sized with the count the prompt is sized with."""
    notes = [cascade_engine._Note(f"d{i}", date(2026, 1, 1), "progress", text, sentences(text)) for i in range(400)]
    shown, left_out = cascade_engine._Run.excerpt_set(notes, {}, budget=cascade_engine.EXCERPT_TOKENS)
    assert sum(excerpt_tokens(e) for e in shown) <= cascade_engine.EXCERPT_TOKENS
    assert left_out == 400 - len(shown) > 0

"""D-910: SCREEN does not run S2b's embedding for a zero-hit pair whose whole window fits the excerpt budget.

With absence semantics off (SCREEN) every zero-hit pair with a sentence goes to S3 whatever its score; the ranking only
picks which notes the excerpt builder reads first. When every note of the window fits the budget whole, the builder
shows them all, newest first, so the ranking cannot change the prompt. The end-to-end check on the synthetic site
(prompts and answers equal with and without the skip) is in ``test_cascade_pipeline.py``.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from matching import excerpts as ex
from matching.excerpts import Note, build, fits_whole, note_tokens, sentences

WORDS = ["gout", "flare", "uric", "acid", "colchicine", "stable", "pain", "toe", "follow-up", "no", "change", "plan"]


def _window(rng: random.Random) -> list[Note]:
    out = []
    for i in range(rng.randint(1, 7)):
        if rng.random() < 0.1:
            text = "   "  # a note with no text: never shown, always left out
        else:
            text = ". ".join(
                " ".join(rng.choices(WORDS, k=rng.randint(3, 12))).capitalize() for _ in range(rng.randint(1, 6))
            )
        day = date(2026, 1, 1) + timedelta(days=rng.randint(0, 40))  # some days shared: the order within a day too
        out.append(
            Note(f"d{rng.randint(1, 30)}-{i}", day, rng.choice(["progress", "pathology"]), text, sentences(text))
        )
    return out


def _evidence(rng: random.Random, window: list[Note]) -> dict[str, set[str]]:
    picked = rng.sample(window, rng.randint(0, len(window)))
    return {n.did: set(rng.sample(list(n.sents or []), min(2, len(n.sents or [])))) for n in picked}


def test_a_ranking_changes_nothing_when_the_window_fits() -> None:
    rng = random.Random(910)
    fitted = 0
    for _ in range(400):
        window = _window(rng)
        whole = sum(note_tokens(n.text) for n in window if n.text.strip())
        budget = rng.choice([whole, whole + rng.randint(0, 200), max(0, whole - rng.randint(1, 200))])
        plain = build(window, {}, budget, ranked=True)
        if not fits_whole(window, budget):
            continue
        fitted += 1
        for _ in range(5):
            got = build(window, _evidence(rng, window), budget, ranked=rng.random() < 0.5)
            # the same notes, the same text, the same order, the same left out (the cascade reads shown and
            # left_out; ``cut`` lists the notes with no text in the order they were met)
            assert got.shown == plain.shown and got.left_out == plain.left_out and set(got.cut) == set(plain.cut)
        assert plain.left_out == sum(1 for n in window if not n.text.strip())
    assert fitted > 50


def test_a_ranking_can_change_the_prompt_when_the_window_does_not_fit() -> None:
    """Why the skip is bound to a window that fits: past the budget, the ranking picks the note that is shown."""
    a = Note("a", date(2026, 3, 2), "progress", "Gout flare of the toe.")
    b = Note("b", date(2026, 3, 1), "progress", "Uric acid high, colchicine started.")
    budget = max(note_tokens(a.text), note_tokens(b.text))  # one of the two, not both
    assert not fits_whole([a, b], budget)
    first = build([a, b], {"a": {a.text}}, budget, ranked=True).shown
    second = build([a, b], {"b": {b.text}}, budget, ranked=True).shown
    assert [x["did"] for x in first] == ["a"] and [x["did"] for x in second] == ["b"]


def test_the_cache_key_of_a_pair_without_ranking_follows_its_prompt() -> None:
    """Two pairs of one patient share a cached answer only when their prompts are the same (D-910)."""
    from matching.cascade.engine import _Note, _window_set

    text = "Gout flare of the toe. Colchicine started."
    win = [_Note("a", date(2026, 3, 2), "progress", text, sentences(text))]
    base = {"id": "C1", "text": "Gout flare", "note_question": "A flare?"}

    def crit(**kw: str) -> Any:  # the key reads the criterion's text and note question only
        return SimpleNamespace(**{**base, **kw})

    one = crit()
    assert _window_set(one, win) == _window_set(crit(id="C2"), win)
    assert _window_set(one, win) != _window_set(crit(text="Gout attack"), win)
    assert _window_set(one, win) != _window_set(crit(note_question="Any?"), win)
    other = [_Note("a", date(2026, 3, 2), "progress", text + " Pain.", sentences(text + " Pain."))]
    assert _window_set(one, win) != _window_set(one, other)
    assert ex.fits_whole([], 0)

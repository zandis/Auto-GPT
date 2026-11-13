"""`tb_common.encoding.detect` took time quadratic in the length of a run of non-ASCII characters: for each half-width
katakana of the Shift_JIS reading it walked back to the start of its run (8,000 `°` in a row: 17 s; 2 MB: past any
wait). One upload could hold a worker. The run's start is now found once, in one pass."""

from __future__ import annotations

import contextlib
import random
import time

import pytest
from datacore.sponsor import MAX_BYTES as SPONSOR_SHEET_BYTES  # 2 MB: a size an upload path already allows
from tb_common import encoding


def _seconds(data: bytes) -> float:
    t = time.perf_counter()
    with contextlib.suppress(encoding.EncodingRefused):
        encoding.detect(data)
    return time.perf_counter() - t


@pytest.mark.parametrize("unit", ["°", "é", "ｱ", "±,"])
def test_a_long_run_of_one_character_is_read_in_time_that_grows_with_its_length(unit: str) -> None:
    small, large = (unit * 4_000).encode(), (unit * 32_000).encode()
    a, b = _seconds(small), _seconds(large)
    # eight times the text: linear is about 8 times the time, quadratic 64. The floor keeps a fast machine honest
    assert b < max(20 * a, 2.0), (a, b)


def test_a_sheet_of_the_largest_size_an_upload_allows_is_decided_in_seconds() -> None:
    data = ("°" * (SPONSOR_SHEET_BYTES // 2)).encode()  # two bytes each: the whole 2 MB one run
    assert len(data) <= SPONSOR_SHEET_BYTES
    assert _seconds(data) < 60  # it took hours; now a few seconds on a loaded machine


def test_the_one_pass_answer_is_the_walk_back_answer() -> None:
    """The weight of every half-width katakana is what the walk back to its run's start gave."""
    rng = random.Random(7)
    alphabet = "ｱｶﾞﾟｰｧﾝ｡A1 ,あ漢"
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))
        walked = [encoding._hw_run_ok(text, i) for i, ch in enumerate(text) if 0xFF61 <= ord(ch) <= 0xFF9F]
        once = encoding._hw_runs_ok(text)
        assert [once[i] for i, ch in enumerate(text) if 0xFF61 <= ord(ch) <= 0xFF9F] == walked, text

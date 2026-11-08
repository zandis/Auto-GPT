"""Offline model-gate replay (D-111): the recorded SIGIR answers reproduce the committed N-11 tables and the recorded
TREC projection reproduces N-12, with no model call."""

from __future__ import annotations

from tools import parity_replay as pr


def test_replay_reproduces_the_recorded_numbers() -> None:
    res = pr.replay()
    assert not pr.reproduces(res)
    deployed, proxy = res["n11"]
    got = {r["lang"]: r for r in deployed["langs"]}
    # on the card, 2026-11-08 (6 Nov: EN 4, JA 3, zh-TW not run); gates 5 / 4 / 2
    assert {lang: got[lang]["lost"] for lang in ("en", "ja", "zh-TW")} == {"en": 4, "ja": 2, "zh-TW": 1}
    assert all(got[lang]["status"] == "pass" for lang in ("en", "ja", "zh-TW"))
    assert {r["lang"]: r["lost"] for r in proxy["langs"]} == {"en": 1, "ja": 2, "zh-TW": 1}
    assert res["n12"]["status"] == "pass" and abs(res["n12"]["projected_true_loss"] - 0.0357) < 0.0005

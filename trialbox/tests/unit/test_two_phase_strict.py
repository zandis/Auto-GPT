"""Two rules of the one-GPU rounds (``orchestrator.twophase``) that had no test (D-276; safety review S-3).

* The last round is strict: a verifier question still open after ``MAX_ROUNDS`` is an error (so ``unknown``), not
  the judge's own answer standing in for the verifier's. Without it a run whose path keeps changing would end with
  the judge agreeing with itself, and a note answer could exclude on one model's word.
* A judge that failed its wake check is not trusted for the run: its answers become errors (``unknown``). Only the
  verifier's wake failure was tested.
"""

from __future__ import annotations

from orchestrator.twophase import MAX_ROUNDS, two_phase

from tests.unit.test_model_swap import FakeClient, ToyJudge


def _models() -> tuple[FakeClient, FakeClient, dict[str, bool]]:
    awake = {"J": True, "V": True}
    answers = {f"q{i}": "fail" for i in range(1, MAX_ROUNDS + 2)}
    return FakeClient("J", dict(answers), awake), FakeClient("V", dict(answers), awake), awake


def test_a_verifier_answer_still_missing_in_the_last_round_is_unknown_not_the_judges_own() -> None:
    jc, vc, awake = _models()
    runs: list[int] = []

    def swap(endpoint: str) -> None:
        awake["J"], awake["V"] = endpoint == "serving", endpoint == "verifier"

    def drifting(j: ToyJudge) -> dict[str, str]:
        """A run that asks one question more every time it runs: the newest never has a verifier answer yet."""
        runs.append(1)
        return {q: j.ask(q) for q in (f"q{i}" for i in range(1, len(runs) + 1))}

    tj = ToyJudge(jc, vc)
    out = two_phase(tj, drifting, swap, workers=2)
    assert len(runs) == MAX_ROUNDS and list(out) == ["q1", "q2", "q3"]
    assert out["q1"] == out["q2"] == "fail"  # control: both models were asked and agree
    assert out["q3"] == "unknown"  # the verifier never saw q3: not an agreement
    assert "q3" not in vc.calls and tj.failures == 1


def test_a_judge_failing_its_wake_check_is_not_trusted_for_the_run() -> None:
    jc, vc, awake = _models()

    def swap(endpoint: str) -> None:
        awake["J"], awake["V"] = endpoint == "serving", endpoint == "verifier"

    def ask(j: ToyJudge) -> dict[str, str]:
        return {q: j.ask(q) for q in ("q1", "q2")}

    ok = two_phase(ToyJudge(jc, vc), ask, swap, workers=2, probe=lambda endpoint: None)
    assert ok == {"q1": "fail", "q2": "fail"}  # control: with a passing wake check the pair decides
    jc.calls.clear()
    tj = ToyJudge(jc, vc)
    out = two_phase(tj, ask, swap, workers=2, probe=lambda e: "wake check: 3 wrong" if e == "serving" else None)
    assert out == {"q1": "unknown", "q2": "unknown"}
    assert jc.calls == [] and tj.failures == 2  # the judge was not even asked

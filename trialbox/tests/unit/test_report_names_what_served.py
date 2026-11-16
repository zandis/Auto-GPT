"""G12 of the integrator's second review of the P1b run (#639, 2026-11-16), D-960: the SCREEN report named the judge by
the configured default (``config.py``), not the model that answered: a box whose gateway served another model under the
judge's alias said the default in its list, PDF and mail.

* The note judge keeps the names each model answered under; the run's ``judging`` record names the one that served
  most, for the judge and for the verifier, on the v1 path (``judging_info``) and the cascade's.
* With no answer yet, it names the configured model, as before.

Stand-in model clients; no patient data.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from orchestrator.scenarios import screen
from orchestrator.scenarios.evaluate import NoteJudge


class _Client:
    gateway = None

    def __init__(self, configured: str, served: str) -> None:
        self.model, self.served = configured, served

    def chat_json(self, prompt: str, variables: dict[str, Any], **kw: Any) -> Any:
        return SimpleNamespace(data={"verdict": "unknown", "confidence": 0.0, "quote": None, "reason": "none"},
                               model=self.served, output_sha="0" * 64, build_sha="b", prompt_id="judge",
                               prompt_version=5, tokens_in=1, tokens_out=1)  # fmt: skip


def test_the_record_names_the_models_that_answered() -> None:
    nj = NoteJudge(lake=None, llm=_Client("config-default", "served-judge"), verifier=_Client("cfg-v", "served-v"))  # type: ignore[arg-type]
    before = screen.judging_info(nj)
    assert (before["judge_model"], before["verifier_model"]) == ("config-default", "cfg-v")  # nothing answered yet
    for _ in range(2):
        nj._ask(nj.llm, {}, [], "chunks")
    nj._ask(nj.verifier, {}, [], "chunks")  # type: ignore[arg-type]
    after = screen.judging_info(nj)
    assert (after["judge_model"], after["verifier_model"]) == ("served-judge", "served-v")
    assert nj.served == {"judge": {"served-judge": 2}, "verifier": {"served-v": 1}}


def test_with_no_verifier_the_record_has_none() -> None:
    nj = NoteJudge(lake=None, llm=_Client("config-default", "served-judge"))  # type: ignore[arg-type]
    nj._ask(nj.llm, {}, [], "chunks")
    j = screen.judging_info(nj)
    assert j["judge_model"] == "served-judge" and j["verifier_model"] is None

"""The adversarial review of the G1 canary and rehearsal fixes (PR #335, 2026-11-12): five findings, one test each.

1. A pinned judge prompt the box's gateway refuses as unqualified stops the job on the first call, with the reason
   (it was ignored by the SCREEN breaker, so the job asked every pair and ended as "the model did not answer").
2. An empty environment name is this process's environment, as it is for ``load_prompt``: an approval on a PRODUCTION
   box pins the version that box serves.
3. A failed canary names every failed model, each line bounded by declared settings (OD-10), and the sentence of the
   mail and the PDF gives a short reason in the reader's language, never the diagnostic text.
4. The public end-to-end run asserts the administrator's refusal on the page that refuses (the study's week page),
   and the browser walk opens the audit trail as the steward, not the administrator (D-451).
5. Only an unqualified prompt gets the advice to approve the study again; another registry refusal says its own.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import selftest
from orchestrator.canary_gate import GATE
from orchestrator.clients import StepFailed
from orchestrator.i18n import t
from orchestrator.jobs import Breaker, BreakerSettings, GuardedLlm
from orchestrator.scenarios import screen
from orchestrator.selftest import ModelReport
from tb_common.llm import LlmClient, LlmError, LlmPromptUnqualified
from tb_common.ruleset import Ruleset
from tb_contracts import RulesetManifest
from tb_llm.prompt_registry import default_registry

ROOT = Path(__file__).resolve().parents[2]


def _manifest(**extra: Any) -> RulesetManifest:
    return RulesetManifest.model_validate(
        {
            "id": "REV-G1",
            "kind": "trial",
            "title": "synthetic review test",
            "version": "1.0.0",
            "status": "approved",
            "index_date_rule": "run_date",
            "scopes": {},
            "routing": {},
            "thresholds": {},
            "criteria": [],
            **extra,
        }
    )


# ------------------------------------------------------------------------------------------------ 1 the first call
class _ProductionGateway:
    """An installed gateway as a real ``GatewayClient`` shows it: no ``prompt_environment``, every version refused."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def context(self) -> None:
        return None

    def complete(self, body: dict[str, Any], labels: Any) -> dict[str, Any]:
        from tb_llm import GatewayRefused

        ref = labels.headers("orchestrator")["X-TB-Prompt"]
        self.sent.append(ref)
        raise GatewayRefused("prompt_unqualified", 403, f"{ref} has no qualification record")


_VARS = {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []}


def test_a_refused_pinned_prompt_stops_the_job_on_the_first_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common.audit import AuditLog

    monkeypatch.setenv("TB_ENV", "DEV")  # the orchestrator's process; the gateway is a PRODUCTION box
    reg = default_registry()
    top = reg.entry("judge")
    name = f"judge_v{top.version}"
    rs = Ruleset(_manifest(prompt_pins=reg.pins({"judge": top.version})), [], {})
    gw = _ProductionGateway()
    client = LlmClient("", "", gateway=gw, audit=AuditLog(tmp_path / "audit"))
    screen.usable_judge_prompt(rs, name, client)  # this process may load it: the check before the run passes
    b = Breaker(BreakerSettings(failures=5, window_s=300.0))
    g = GuardedLlm(client, lambda: False, b, "judge")
    with pytest.raises(StepFailed) as exc:
        g.chat_json(name, _VARS, job_id="J-1")
    msg = str(exc.value)
    assert "prompt_unqualified" in msg and name in msg, msg
    assert "No model was asked" in msg and "did not answer" not in msg
    assert isinstance(exc.value.__cause__, LlmPromptUnqualified)
    assert gw.sent == [f"judge@{top.version}"]  # one call, refused: not one per patient and criterion
    assert b.state == "closed" and b.failures == 0  # and no model was down


# ------------------------------------------------------------------------------------------------ 2 "" is no name
def test_an_empty_environment_name_pins_what_this_box_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    from criteria_compiler.service import approval_pins
    from tb_common.config import environment_name

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    reg = default_registry()
    served = reg.served("judge", "PRODUCTION")
    assert reg.pins({"judge": None}, "")["judge"]["version"] == served.version
    assert reg.pins({"judge": None}, "") == reg.pins({"judge": None}, None)
    assert approval_pins(_manifest(), environment="")["models"]["judge_prompt"] == f"judge_v{served.version}"
    # the harness names the gateway's environment by the one rule (an unset TB_ENV is PRODUCTION), never ""
    src = (ROOT / "tools" / "scenarios.py").read_text(encoding="utf-8")
    assert "client.prompt_environment = environment_name(env)" in src and environment_name({}) == "PRODUCTION"


# ------------------------------------------------------------------------------------------------ 3 the gate's words
def test_two_down_models_are_both_named_and_the_sentence_stays_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_CANARY_GATE", "on")
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    GATE.path = None
    GATE.configure(tmp_path)
    raw = "upstream connect error or disconnect/reset before headers " + "x" * 450  # a 500-character call error
    names = {"judge": "hospital-judge-build-a", "verifier": "hospital-verifier-build-b"}

    def down(role: str, client: Any, cases: list[dict[str, Any]], prompt: str = "judge") -> ModelReport:
        return ModelReport(role, names[role], cases=len(cases), errors=[f"{cases[0]['id']}: {raw}"])

    monkeypatch.setattr(selftest, "check_model", down)
    llm = SimpleNamespace(model=names["judge"], served_root="a")
    verifier = SimpleNamespace(model=names["verifier"], served_root="b")
    rep = selftest.run_selftest(llm, verifier)  # type: ignore[arg-type]
    GATE.record({**rep, "at_epoch": time.time()})
    info = screen.judging_info(SimpleNamespace(llm=llm, verifier=verifier, mode="agreement", disagreements=0,
                                               failures=0))  # type: ignore[arg-type]  # fmt: skip
    reason = info["note_block_reason"]
    # the diagnostic names both models, each line with its (cut) first error
    assert f"judge {names['judge']} failed" in reason and f"verifier {names['verifier']} failed" in reason, reason
    assert reason.count("upstream connect error") == 2 and "x" * (selftest.why_chars() + 1) not in reason
    assert all(len(p) <= 400 for p in rep["problems"])  # each line still reads on one screen line
    assert info["note_block_code"] == "failed" and info["may_block"] is False
    # the mail and the PDF: a short reason in the reader's language, none of the diagnostic text
    for lang in ("en", "ja", "zh-TW"):
        s = screen.judging_sentence(info, lang)
        why = t(lang, "screen.judging.why.failed")
        assert s == t(lang, "screen.judging.single", judge=names["judge"], why=why)
        assert "upstream" not in s and "failed the canary" not in s and "of 54" not in s and "xxx" not in s
        assert names["verifier"] not in s
    ja, zh = t("ja", "screen.judging.why.failed"), t("zh-TW", "screen.judging.why.failed")
    assert not re.search(r"[A-Za-z]{3,}", ja) and not re.search(r"[A-Za-z]{3,}", zh)
    # a list written before the code was recorded keeps its sentence
    old = {k: v for k, v in info.items() if k != "note_block_code"} | {"note_block_reason": "no verifier configured"}
    assert "no verifier configured" in screen.judging_sentence(old, "en")


def test_every_reason_a_note_answer_may_not_exclude_has_a_short_text_in_three_languages() -> None:
    from orchestrator.i18n import T
    from orchestrator.scenarios.evaluate import NOTE_BLOCK_CODES

    assert {"held", "configured", "no_judge", "no_verifier", "same_model", "wake", "none", "failed", "single",
            "stale"} <= set(NOTE_BLOCK_CODES)  # fmt: skip
    for lang in ("en", "ja", "zh-TW"):
        for code in NOTE_BLOCK_CODES:
            assert T[lang].get(f"screen.judging.why.{code}"), (lang, code)


def test_the_canary_lines_limits_are_declared_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.config import DECLARED

    assert DECLARED["TB_CANARY_WHY_CHARS"].kind == "int" and DECLARED["TB_CANARY_WHY_CASES"].kind == "int"
    assert selftest.why_chars() == int(DECLARED["TB_CANARY_WHY_CHARS"].default)
    assert selftest.why_cases() == int(DECLARED["TB_CANARY_WHY_CASES"].default)
    wrong = [{"id": f"en:c{i}:yes", "expected": "pass", "got": "unknown", "reason": "abstained"} for i in range(5)]
    m = ModelReport("judge", "J", cases=54, answered=54, wrong=wrong, errors=["en:c0:yes: " + "e" * 500])
    assert "en:c1:yes" in m.why() and "en:c2:yes" not in m.why() and "and 3 more" in m.why()
    monkeypatch.setenv("TB_CANARY_WHY_CASES", "3")
    monkeypatch.setenv("TB_CANARY_WHY_CHARS", "40")
    assert "en:c2:yes" in m.why() and "and 2 more" in m.why() and "e" * 41 not in m.why()


# ------------------------------------------------------------------------------------------------ 4 the harness
def test_the_public_run_asserts_the_administrators_refusal_where_it_is_refused() -> None:
    from tools import public_e2e

    admin = dict(public_e2e.other_screens("admin", "TRIAL-X"))
    # /week itself has no guard for the administrator: it sends them to the one study's week page, which refuses
    assert admin["/studies/TRIAL-X/week"] == 403 and "/week" not in admin
    assert admin["/home"] == 200 and admin["/reports"] == 200
    for who in ("crc", "pi"):
        other = dict(public_e2e.other_screens(who, "TRIAL-X"))
        assert other["/week"] == 200 and "/studies/TRIAL-X/week" not in other


def test_the_browser_walk_opens_the_audit_trail_as_the_steward() -> None:
    walk = (ROOT / "tools" / "public_walk.js").read_text(encoding="utf-8")
    forbidden = walk.split("const FORBIDDEN = {", 1)[1].split("};", 1)[0]
    admin_forbidden = next(ln for ln in forbidden.splitlines() if ln.strip().startswith("admin:"))
    assert '"/audit"' in admin_forbidden  # T-211c (D-451): 403 for the administrator
    pages = walk.split("const PAGES = {", 1)[1].split("\n};", 1)[0]
    steward = next(ln for ln in pages.splitlines() if ln.strip().startswith("stw:"))
    assert '"/audit"' in steward
    roles = re.search(r"const ROLES = \[(.*?)\];", walk)
    assert roles and '"stw"' in roles.group(1)
    assert not any(ln.strip().startswith("stw:") for ln in forbidden.splitlines())  # 200 for the steward


# ------------------------------------------------------------------------------------------------ 5 the advice
def _ctx(client: Any) -> Any:
    return SimpleNamespace(
        services=SimpleNamespace(llm=client, verifier=None, lake=None), job=SimpleNamespace(job_id="J1")
    )


def test_only_an_unqualified_prompt_is_told_to_approve_again(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = default_registry()
    top = reg.entry("judge")
    rs = Ruleset(_manifest(prompt_pins=reg.pins({"judge": top.version})), [], {})
    client = SimpleNamespace(gateway=SimpleNamespace(prompt_environment="PRODUCTION"))

    def changed(prompt_id: str, environment: str | None = None) -> Any:
        raise LlmError(f"prompt {prompt_id!r} refused (prompt_sha_mismatch): the file differs from the registry")

    monkeypatch.setattr(screen, "load_prompt", changed)
    with pytest.raises(StepFailed) as exc:
        screen.judge_for(_ctx(client), rs)
    msg = str(exc.value)
    assert f"judge_v{top.version}" in msg and "prompt_sha_mismatch" in msg and "No model was asked" in msg
    assert "Approve the study again" not in msg and "qualification record" not in msg
    assert "prompt registry" in msg

    def unqualified(prompt_id: str, environment: str | None = None) -> Any:
        raise LlmPromptUnqualified(f"prompt {prompt_id!r} refused (prompt_unqualified): no qualification record")

    monkeypatch.setattr(screen, "load_prompt", unqualified)
    with pytest.raises(StepFailed) as exc:
        screen.judge_for(_ctx(client), rs)
    assert "Approve the study again" in str(exc.value) and "prompt_unqualified" in str(exc.value)

"""Nightly model self-test (canary): 54 known note questions before the night's LLM jobs (survey 2026-11-07).

A model build that drifted, a serving image that changed how structured output works, a wrong quantisation or a
half-loaded GPU all look the same from outside: the night run finishes and its list is quietly worse. The canary
asks each model (the judge, then the verifier) the same 54 short, clear-cut questions in English, Japanese and
Traditional Chinese (``orchestrator/canary/judge_canary.jsonl``: yes, no and not-in-the-note cases for six
common criteria) through the normal gateway route, and the scheduler starts the night's LLM jobs only when both pass.

A model passes when, over the cases:

* at least ``MIN_ANSWERED`` (95%) came back schema-valid (the model is up and structured output works);
* at most ``MAX_FLIPS`` (1) answer says yes where the truth is no or the reverse (the dangerous error);
* at least ``MIN_ACCURACY`` (85%) match exactly (``unknown`` for a suspected or absent finding counts as correct
  only when expected).

The quote rule of the screening path applies (a decided answer whose quote is not in the excerpt is ``unknown``).

    python -m orchestrator.selftest            # uses the orchestrator's environment (TB_GATEWAY_URL ...)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tb_common.llm import LlmClient, LlmError

from orchestrator.scenarios.evaluate import postprocess

log = logging.getLogger("orchestrator.selftest")
CASES = Path(os.environ.get("TB_CANARY_CASES") or Path(__file__).with_name("canary") / "judge_canary.jsonl")
MIN_ANSWERED = 0.95
MAX_FLIPS = 1
MIN_ACCURACY = 0.85
# the pair the box runs (Fable review 2026-11-08, finding 4): a case where both models give the same decided answer
# and it is wrong (a flip, or yes/no where the note is silent) is a case where the box would exclude wrongly. Since
# a passing pair canary is what lets a note answer exclude (D-117), one such case is one too many.
MAX_PAIR_WRONG = 0


@dataclass
class ModelReport:
    role: str
    model: str
    cases: int = 0
    answered: int = 0
    correct: int = 0
    flips: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    wrong: list[dict[str, str]] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)  # case id -> predicate (not reported, used for the pair)

    @property
    def ok(self) -> bool:
        if self.cases == 0:
            return False
        return (
            self.answered >= MIN_ANSWERED * self.cases
            and self.flips <= MAX_FLIPS
            and self.correct >= MIN_ACCURACY * self.cases
        )

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k != "answers"}
        return {**d, "ok": self.ok, "errors": self.errors[:5], "wrong": self.wrong[:10]}


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_model(role: str, client: LlmClient, cases: list[dict[str, Any]], prompt: str = "judge") -> ModelReport:
    rep = ModelReport(role, str(getattr(client, "model", "")), cases=len(cases))
    t0 = time.perf_counter()
    for c in cases:
        variables = {k: c[k] for k in ("criterion_text", "note_question", "index_date", "excerpts")}
        try:
            res = client.chat_json(prompt, variables, job_id="selftest")
        except LlmError as exc:
            rep.errors.append(f"{c['id']}: {str(exc)[:120]}")
            continue
        rep.answered += 1
        got = postprocess(res.data, c["excerpts"]).predicate
        rep.answers[c["id"]] = got
        want = c["expected"]
        if got == want:
            rep.correct += 1
            continue
        if {got, want} == {"pass", "fail"}:
            rep.flips += 1
        rep.wrong.append({"id": c["id"], "expected": want, "got": got})
    rep.seconds = round(time.perf_counter() - t0, 1)
    return rep


def run_selftest(
    llm: LlmClient | None,
    verifier: LlmClient | None,
    swap: Callable[[str], None] | None = None,
    cases: list[dict[str, Any]] | None = None,
    release: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Check the judge and (when wired) the verifier; with ``swap`` each is woken in turn and the judge is left
    awake, or, with ``release`` (the gateway's hold, D-116), the card is released and the gateway wakes the judge
    when the next call needs it. Returns the report; ``report["ok"]`` gates the night's jobs."""
    cs = cases if cases is not None else load_cases()
    models: list[ModelReport] = []
    problems: list[str] = []
    if llm is None:
        problems.append("no judge model configured")
    for role, endpoint, client in (("judge", "serving", llm), ("verifier", "verifier", verifier)):
        if client is None:
            continue
        try:
            if swap is not None:
                swap(endpoint)
            models.append(check_model(role, client, cs))
        except LlmError as exc:  # the swap itself failed
            problems.append(f"{role}: {exc}")
    if release is not None:
        release()
    elif swap is not None and verifier is not None:
        try:
            swap("serving")
        except LlmError as exc:
            problems.append(f"judge did not wake after the self-test: {exc}")
    problems += [f"{m.role} {m.model} failed the canary" for m in models if not m.ok]
    by_role = {m.role: m for m in models}
    pair = None
    if "judge" in by_role and "verifier" in by_role:
        pair = pair_report(by_role["judge"], by_role["verifier"], cs)
        if pair["decided_wrong"] > MAX_PAIR_WRONG:
            problems.append(
                f"the pair agreed on a wrong decided answer in {pair['decided_wrong']} cases (at most {MAX_PAIR_WRONG})"
            )
    return {
        "ok": not problems,
        "cases": len(cs),
        "models": [m.as_dict() for m in models],
        "pair": pair,
        "problems": problems,
        "thresholds": {
            "min_answered": MIN_ANSWERED,
            "max_flips": MAX_FLIPS,
            "min_accuracy": MIN_ACCURACY,
            "max_pair_wrong": MAX_PAIR_WRONG,
        },
    }


def pair_report(judge: ModelReport, verifier: ModelReport, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """The canary scored as the box decides: a decided answer stands only when both models give it (NoteJudge)."""
    out: dict[str, Any] = {"cases": len(cases), "correct": 0, "decided_wrong": 0, "disagreed": 0, "wrong": []}
    for c in cases:
        a, b = judge.answers.get(c["id"], "unknown"), verifier.answers.get(c["id"], "unknown")
        decided = a in ("pass", "fail")
        got = a if decided and a == b else "unknown"
        if decided and a != b:
            out["disagreed"] += 1
        if got == c["expected"]:
            out["correct"] += 1
        elif got in ("pass", "fail"):
            out["decided_wrong"] += 1
            out["wrong"].append({"id": c["id"], "expected": c["expected"], "got": got})
    out["wrong"] = out["wrong"][:10]
    return out


def enabled() -> bool:
    return (os.environ.get("TB_SELFTEST") or "on").strip().lower() not in ("0", "off", "false", "no")


def preflight(orch: Any, force: bool = False) -> bool:
    """Run the canary for the night, record it in the audit log, ``<data dir>/selftest.json`` and the canary gate
    (:mod:`orchestrator.canary_gate`, D-117: a passing pair canary is what lets a note answer exclude); True when the
    night's LLM jobs may start (also when the self-test is switched off or no model is configured at all).
    ``force``: run even with ``TB_SELFTEST=off`` (the canary at start and the admin's "Run now")."""
    if (not enabled() and not force) or orch.services.llm is None:
        return True
    from orchestrator import canary_gate
    from orchestrator.twophase import GatewaySwap

    gs = GatewaySwap.from_env()
    report = run_selftest(
        orch.services.llm,
        orch.services.verifier,
        gs.use if gs is not None else None,
        release=gs.release if gs is not None else None,
    )
    report["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["at_epoch"] = round(time.time(), 1)
    canary_gate.GATE.configure(orch.data_dir)
    canary_gate.GATE.record(report)
    try:
        out = Path(orch.data_dir) / "selftest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    except (AttributeError, OSError) as exc:
        log.warning("selftest report not written: %s", exc)
    orch.audit.append(
        "selftest.passed" if report["ok"] else "selftest.failed",
        detail={k: report[k] for k in ("ok", "cases", "problems")}
        | {
            "models": [
                {k: m[k] for k in ("role", "model", "answered", "correct", "flips", "ok")} for m in report["models"]
            ],
            "pair": {k: v for k, v in (report.get("pair") or {}).items() if k != "wrong"} or None,
        },
    )
    if not report["ok"]:
        log.error("night self-test failed, LLM jobs not started: %s", "; ".join(report["problems"]))
    return bool(report["ok"])


def main(argv: list[str] | None = None) -> int:
    from tb_common.audit import AuditLog
    from tb_common.config import get_config

    from orchestrator.app import verifier_client
    from orchestrator.twophase import GatewaySwap

    cfg = get_config()
    audit = AuditLog(cfg.env.audit_path, cfg.env.tz)
    gs = GatewaySwap.from_env()
    report = run_selftest(
        LlmClient.from_config(audit),
        verifier_client(audit),
        gs.use if gs is not None else None,
        release=gs.release if gs is not None else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


__all__ = [
    "MAX_FLIPS",
    "MAX_PAIR_WRONG",
    "MIN_ACCURACY",
    "MIN_ANSWERED",
    "ModelReport",
    "check_model",
    "pair_report",
    "preflight",
    "run_selftest",
]

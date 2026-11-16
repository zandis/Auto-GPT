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

A failed canary says why (OD-10): which threshold failed, with the figures, and its first wrong cases, each with the
answer expected, the answer given and the reason code of the answer (``abstained``: the model said the note does not
say; ``quote_not_found``: its quote is in no excerpt; ``note``: it decided, the other way). The same line goes to the
log, the audit record, ``selftest.json`` and the Models tile, so nobody has to re-run the canary to learn it.

    python -m orchestrator.selftest            # uses the orchestrator's environment (TB_GATEWAY_URL ...)
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tb_common.llm import LlmClient, LlmError, LlmModelFault
from tb_common.pair import same_model, served_keys

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
# A failed model's problem line is read on one screen line of the log, the Models tile and the audit viewer, so its
# two open-ended parts are settings (OD-10; ``tb_common.config.DECLARED``): how many wrong cases it names
# (``TB_CANARY_WHY_CASES``; the first ten are in the report's "wrong") and how much of a call error it keeps
# (``TB_CANARY_WHY_CHARS``; the full error is in the gateway's log). Everything else in a line is figures.
WHY_CASES = 2
WHY_CHARS = 120


def _count(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name) or default))
    except ValueError:
        return default


def why_cases() -> int:
    return _count("TB_CANARY_WHY_CASES", WHY_CASES)


def why_chars() -> int:
    return _count("TB_CANARY_WHY_CHARS", WHY_CHARS)


def clip(text: str, chars: int | None = None) -> str:
    """``text`` on one line, at most ``chars`` (``TB_CANARY_WHY_CHARS``) characters; a cut one ends in "…"."""
    n = why_chars() if chars is None else chars
    one = " ".join(str(text).split())
    return one if len(one) <= n else one[:n] + "…"


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
    served: list[str] = field(default_factory=list)  # the model names the answers came back under (D-276)
    faults: int = 0  # calls the model did not answer for a reason of its own (LlmModelFault: down, not loaded)

    @property
    def unreached(self) -> bool:
        """D-915: no case answered, every call a model fault (the gateway's ``upstream_down``, an endpoint that
        cannot be reached): the model was not there to be checked, which says nothing about its answers."""
        return self.cases > 0 and self.answered == 0 and self.faults == self.cases

    @property
    def ok(self) -> bool:
        if self.cases == 0:
            return False
        return (
            self.answered >= MIN_ANSWERED * self.cases
            and self.flips <= MAX_FLIPS
            and self.correct >= MIN_ACCURACY * self.cases
        )

    def why(self, shown: int | None = None) -> str:
        """Why this model failed, for the report's ``problems`` line ("" when it passed): each threshold it missed
        with the figures, the first call error (cut, :func:`clip`), and the first ``shown`` wrong cases
        (:func:`why_cases`) with their reason codes. The line is bounded by those two settings: the canary gate
        joins the lines of every failed model uncut, so each must stay short by itself."""
        shown = why_cases() if shown is None else shown
        if self.ok:
            return ""
        if self.cases == 0:
            return "no canary cases"
        parts: list[str] = []
        need = math.ceil(MIN_ANSWERED * self.cases)
        if self.answered < need:
            parts.append(f"{self.answered} of {self.cases} answered, at least {need} needed")
        else:
            parts.append(f"{self.answered} of {self.cases} answered")
        need = math.ceil(MIN_ACCURACY * self.cases)
        if self.correct < need:
            parts.append(f"{self.correct} of {self.cases} correct, at least {need} needed")
        if self.flips > MAX_FLIPS:
            parts.append(f"{self.flips} answers the wrong way round, at most {MAX_FLIPS} allowed")
        if self.errors:
            parts.append(f"first error: {clip(self.errors[0])}")
        if self.wrong:
            first = "; ".join(
                f"{w['id']} expected {w['expected']}, got {w['got']}" + (f" ({w['reason']})" if w.get("reason") else "")
                for w in self.wrong[:shown]
            )
            more = len(self.wrong) - min(shown, len(self.wrong))
            parts.append(f"first wrong: {first}" + (f"; and {more} more" if more else ""))
        return "; ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k != "answers"}
        return {**d, "ok": self.ok, "errors": self.errors[:5], "wrong": self.wrong[:10]}


def load_cases(path: Path = CASES) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def model_name(client: LlmClient) -> str:
    """The name the canary reports: the client's model, else (a gateway client sends no model) the alias it asks the
    gateway for, else the gateway's own choice for the role. Never empty: an empty name hid which model failed."""
    name = str(getattr(client, "model", "") or "")
    gw = getattr(client, "gateway", None)
    if not name and gw is not None:
        name = str(getattr(gw, "model", "") or "") or "(the gateway's build)"
    return name or "(unnamed model)"


def check_model(role: str, client: LlmClient, cases: list[dict[str, Any]], prompt: str = "judge") -> ModelReport:
    rep = ModelReport(role, model_name(client), cases=len(cases))
    t0 = time.perf_counter()
    for c in cases:
        variables = {k: c[k] for k in ("criterion_text", "note_question", "index_date", "excerpts")}
        try:
            res = client.chat_json(prompt, variables, job_id="selftest")
        except LlmError as exc:
            rep.errors.append(clip(f"{c['id']}: {exc}"))
            rep.faults += isinstance(exc, LlmModelFault)
            continue
        rep.answered += 1
        for name in served_keys(getattr(res, "model", ""), getattr(res, "build_sha", "")):
            if name not in rep.served:
                rep.served.append(name)
        answer = postprocess(res.data, c["excerpts"])
        got = answer.predicate
        rep.answers[c["id"]] = got
        want = c["expected"]
        if got == want:
            rep.correct += 1
            continue
        if {got, want} == {"pass", "fail"}:
            rep.flips += 1
        rep.wrong.append({"id": c["id"], "expected": want, "got": got, "reason": str(answer.reason or "")})
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
    unreached: list[str] = []  # D-915: the roles whose model could not be reached (woken, or asked)
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
            problems.append(f"{role}: {clip(str(exc))}")
            if isinstance(exc, LlmModelFault):
                unreached.append(role)
    if release is not None:
        release()
    elif swap is not None and verifier is not None:
        try:
            swap("serving")
        except LlmError as exc:
            problems.append(f"judge did not wake after the self-test: {clip(str(exc))}")
    unreached += [m.role for m in models if m.unreached]
    problems += [
        f"{m.role} {m.model} could not be reached ({clip(m.errors[0])})" if m.unreached else
        f"{m.role} {m.model} failed the canary ({m.why()})"
        for m in models if not m.ok
    ]  # fmt: skip
    by_role = {m.role: m for m in models}
    pair = None
    if "judge" in by_role and "verifier" in by_role:
        pair = pair_report(by_role["judge"], by_role["verifier"], cs)
        # D-276 (review S-2): a "pair" that is one model agrees with itself on every case and would pass
        shared = sorted(set(by_role["judge"].served) & set(by_role["verifier"].served))
        one = same_model(llm, verifier) or (f"both answered as the same model ({shared[0]})" if shared else None)
        if one:
            pair["same_model"] = one
            problems.append(f"the verifier is not a second model ({one}): a note answer needs two different models")
        if pair["decided_wrong"] > MAX_PAIR_WRONG:
            problems.append(
                f"the pair agreed on a wrong decided answer in {pair['decided_wrong']} cases (at most {MAX_PAIR_WRONG})"
            )
    return {
        "ok": not problems,
        "reached": not unreached,
        "unreached": unreached,
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
    from orchestrator.twophase import GatewaySwap

    gs = GatewaySwap.from_env()
    report = run_selftest(
        orch.services.llm,
        orch.services.verifier,
        gs.use if gs is not None else None,
        release=gs.release if gs is not None else None,
    )
    return record(report, orch.data_dir, orch.audit)


def orch_data_dir(cfg: Any) -> Path:
    """The orchestrator's data folder (``TB_ORCH_DIR``, else ``<data dir>/orchestrator``): where the gate's
    ``selftest.json`` lives, for the orchestrator and for ``trialbox selftest`` in its container alike."""
    return Path(os.environ.get("TB_ORCH_DIR") or str(Path(cfg.env.data_dir) / "orchestrator"))


def record(report: dict[str, Any], data_dir: Path | str, audit: Any, by: str = "orchestrator") -> bool:
    """Record a canary as the gate's result: ``<data dir>/selftest.json`` (written whole, then moved into place), the
    canary gate of this process and the audit (``selftest.passed`` / ``selftest.failed``; D-915: a canary that could
    not reach a model is ``selftest.unreached`` and leaves the last result as it was). ``by``: who ran it, in the
    audit (``orchestrator``, or ``trialbox selftest`` from the box's command line, D-916). True when it passed."""
    from orchestrator import canary_gate

    report.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    report.setdefault("at_epoch", round(time.time(), 3))
    canary_gate.GATE.configure(data_dir)
    if not report["reached"]:
        # D-915: a model that was not there was not checked; the canary did not run. Nothing is recorded over the
        # last real result (the gate stays as it was, shut without a pass), the gate shows "waiting for the models"
        # and the canary is asked again (canary_gate.startup's backoff, the night gate's next tick)
        canary_gate.GATE.record_unreached(report)
        audit.append(
            "selftest.unreached",
            detail={k: report[k] for k in ("unreached", "problems", "cases")} | {"by": by},
        )
        log.warning("model self-test could not reach %s: not run, tried again", ", ".join(report["unreached"]))
        return False
    canary_gate.GATE.record(report)
    try:
        out = Path(data_dir) / "selftest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f".{out.name}.{os.getpid()}")  # the other process never reads half a report
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, out)
        canary_gate.GATE.written(out)
    except (AttributeError, OSError) as exc:
        log.warning("selftest report not written: %s", exc)
    audit.append(
        "selftest.passed" if report["ok"] else "selftest.failed",
        detail={k: report[k] for k in ("ok", "cases", "problems")}
        | {
            "by": by,
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
    """``python -m orchestrator.selftest`` (what ``trialbox selftest`` runs in the orchestrator's container): the
    canary, recorded as the gate's result (D-916; :func:`record`), so a pass at the box's command line opens the gate
    of the running orchestrator, which reads the newer ``selftest.json`` (:meth:`canary_gate.Gate.check`). The
    report is printed; exit 0 when it passed, 1 when it failed, 2 when it could not reach a model (not run)."""
    from tb_common.audit_writer import open_audit
    from tb_common.config import get_config

    from orchestrator.app import verifier_client
    from orchestrator.twophase import GatewaySwap

    cfg = get_config()
    audit = open_audit(cfg.env.audit_path, cfg.env.tz)
    gs = GatewaySwap.from_env()
    report = run_selftest(
        LlmClient.from_config(audit),
        verifier_client(audit),
        gs.use if gs is not None else None,
        release=gs.release if gs is not None else None,
    )
    ok = record(report, orch_data_dir(cfg), audit, by="trialbox selftest")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if ok else 1 if report["reached"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


__all__ = [
    "MAX_FLIPS",
    "MAX_PAIR_WRONG",
    "MIN_ACCURACY",
    "MIN_ANSWERED",
    "ModelReport",
    "check_model",
    "orch_data_dir",
    "pair_report",
    "preflight",
    "record",
    "run_selftest",
]

"""The canary gates ``may_block`` (TB-PLAN-03 step 2, D-117).

A note answer may exclude a patient only when the judge and the verifier agree (D-89), and only on models known to
answer correctly *now*. The 54-case canary (:mod:`orchestrator.selftest`) is that check; this module makes it the
product's gate instead of a night-job precondition only:

* **At start.** The orchestrator runs the canary on the pair in the background when it starts (``startup``), and
  the scheduler runs it again before each night's LLM jobs. Each report is kept here and in
  ``<data dir>/selftest.json``.
* **After each swap.** On a one-GPU box (``TB_MODEL_SWAP=sleep``) a woken model answers six of the canary's cases
  (one per criterion, all three languages; :func:`wake_probe`) before the run uses it. A model that gets one of
  them wrong, flips one, or answers fewer than five is not trusted for the rest of that run
  (:func:`orchestrator.twophase.two_phase` turns its answers into errors, so ``unknown``), and the gate stays shut
  until the next full canary passes.
* **The gate.** :func:`allows_block` is True only with a passing pair canary younger than ``TB_CANARY_MAX_AGE_H``
  (36 h) and no failed wake check since. Otherwise :func:`orchestrator.scenarios.evaluate.effective_note_block`
  falls back to ``never``: a note answer may send a patient to review, never out, and the run says why.

``TB_CANARY_GATE`` (on | off) switches the gate; unset it is on, except on a DEV or TEST box (``TB_ENV``), where the
stub model of the demos and tests would never pass a canary. The admin Models tile shows the gate's date and result.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tb_common.llm import LlmClient, LlmError

log = logging.getLogger(__name__)

WAKE_MIN_CORRECT = 5  # of the six wake cases
MAX_AGE_H = 36.0


def gate_on(env: dict[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    v = (e.get("TB_CANARY_GATE") or "").strip().lower()
    if v in ("on", "1", "true", "yes"):
        return True
    if v in ("off", "0", "false", "no"):
        return False
    return (e.get("TB_ENV") or "PRODUCTION").strip().upper() not in ("DEV", "TEST")


def _max_age_h() -> float:
    try:
        return float(os.environ.get("TB_CANARY_MAX_AGE_H") or MAX_AGE_H)
    except ValueError:
        return MAX_AGE_H


class Gate:
    """The last canary and the last failed wake check of this orchestrator (one per process)."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.report: dict[str, Any] | None = None
        self.at: float | None = None  # epoch seconds of the report
        self.wake_failure: dict[str, Any] | None = None
        self.running = False
        self._lock = threading.Lock()

    def configure(self, data_dir: Path | str) -> None:
        """Point at ``<data dir>/selftest.json`` and read the last report from it (a restart keeps the gate)."""
        p = Path(data_dir) / "selftest.json"
        with self._lock:
            if self.path == p:
                return
            self.path, self.report, self.at, self.wake_failure = p, None, None, None
            try:
                rep = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            self.report = rep
            self.at = float(rep.get("at_epoch") or p.stat().st_mtime)

    def record(self, report: dict[str, Any]) -> None:
        with self._lock:
            self.report = report
            self.at = float(report.get("at_epoch") or time.time())
            if report.get("ok"):
                self.wake_failure = None  # a full pass after the failed wake check reopens the gate

    def record_wake(self, endpoint: str, why: str) -> None:
        with self._lock:
            self.wake_failure = {"endpoint": endpoint, "why": why, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def check(self) -> tuple[bool, str, str]:
        """(may a note answer exclude, code, why not). Codes: ``ok``, ``off`` (gate switched off), ``wake`` (a
        failed wake check since the last pass), ``none`` (no canary yet), ``failed``, ``single`` (one model
        only), ``stale`` (older than ``TB_CANARY_MAX_AGE_H``). The console shows the code, translated."""
        if not gate_on():
            return True, "off", ""
        with self._lock:
            rep, at, wake = self.report, self.at, self.wake_failure
        if wake is not None:
            return False, "wake", f"the {wake['endpoint']} model failed its wake check ({wake['why']})"
        if rep is None:
            return False, "none", "the model self-test (canary) has not run on this box yet"
        if not rep.get("ok"):
            return (
                False,
                "failed",
                "the last model self-test (canary) failed: " + "; ".join(rep.get("problems") or [])[:200],
            )
        if not rep.get("pair"):
            return False, "single", "the last model self-test checked one model, not the pair"
        age = (time.time() - (at or 0)) / 3600
        if age > _max_age_h():
            return False, "stale", f"the last passing model self-test is {age:.0f} h old (at most {_max_age_h():.0f} h)"
        return True, "ok", ""

    def allows_block(self) -> tuple[bool, str]:
        """(may a note answer exclude, why not). With the gate off: (True, "")."""
        ok, _code, why = self.check()
        return ok, why

    def status(self) -> dict[str, Any]:
        ok, code, why = self.check()
        rep = self.report or {}
        pair = rep.get("pair") or {}
        return {
            "gate": "on" if gate_on() else "off",
            "allows_block": ok,
            "code": code,
            "reason": why,
            "running": self.running,
            "at": rep.get("at"),
            "ok": rep.get("ok") if rep else None,
            "cases": rep.get("cases"),
            "pair_correct": pair.get("correct"),
            "pair_decided_wrong": pair.get("decided_wrong"),
            "models": [
                {k: m.get(k) for k in ("role", "model", "correct", "flips", "ok")} for m in rep.get("models") or []
            ],
            "wake_failure": self.wake_failure,
        }


GATE = Gate()


def allows_block() -> tuple[bool, str]:
    return GATE.allows_block()


def status() -> dict[str, Any]:
    return GATE.status()


WAKE_PLAN = (("en", "pass"), ("ja", "fail"), ("zh-TW", "unknown"), ("en", "fail"), ("ja", "unknown"), ("zh-TW", "pass"))


def wake_cases(cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Six of the 54 (``lang:criterion:kind`` ids): one per criterion, in the order of the file, so that each
    language and each expected answer (yes, no, not stated) comes twice (:data:`WAKE_PLAN`)."""
    from orchestrator.selftest import load_cases

    cs = cases if cases is not None else load_cases()
    crits: list[str] = []
    for c in cs:
        crit = str(c["id"]).split(":")[1]
        if crit not in crits:
            crits.append(crit)
    out = []
    for i, crit in enumerate(crits):
        lang, want = WAKE_PLAN[i % len(WAKE_PLAN)]
        mine = [c for c in cs if str(c["id"]).split(":")[1] == crit]
        pick = next((c for c in mine if c.get("language") == lang and c["expected"] == want), None)
        out.append(pick or next((c for c in mine if c.get("language") == lang), mine[0]))
    return out


def check_wake(role: str, client: LlmClient, cases: list[dict[str, Any]] | None = None) -> str | None:
    """None when the woken model answers its wake cases well enough, else why not (for the run log and the gate)."""
    from orchestrator.selftest import check_model

    cs = cases if cases is not None else wake_cases()
    rep = check_model(role, client, cs)
    if rep.flips or rep.correct < min(WAKE_MIN_CORRECT, len(cs)) or rep.answered < len(cs) - 1:
        return f"wake check {rep.correct}/{len(cs)} correct, {rep.flips} flipped, {rep.answered} answered"
    return None


def wake_probe(llm: Any, verifier: Any) -> Callable[[str], str | None] | None:
    """The probe :func:`orchestrator.twophase.two_phase` runs after each real swap; None when the gate is off."""
    if not gate_on():
        return None
    clients = {"serving": llm, "verifier": verifier}

    def probe(endpoint: str) -> str | None:
        client = clients.get(endpoint)
        if client is None:
            return None
        try:
            why = check_wake("judge" if endpoint == "serving" else "verifier", client)
        except LlmError as exc:
            why = f"wake check errored: {str(exc)[:120]}"
        if why:
            GATE.record_wake(endpoint, why)
        return why

    return probe


def run_canary(orch: Any) -> dict[str, Any] | None:
    """The full pair canary now (at start, or from the admin "Run now"); records it and returns the report."""
    from orchestrator.selftest import preflight

    if orch.services.llm is None:
        return None
    GATE.configure(orch.data_dir)
    GATE.running = True
    try:
        preflight(orch, force=True)
    finally:
        GATE.running = False
    return GATE.report


def startup(orch: Any) -> threading.Thread | None:
    """At orchestrator start: read the last report, and with the gate on run the canary in the background (a
    run started meanwhile simply cannot exclude on a note answer until it passes)."""
    GATE.configure(orch.data_dir)
    if not gate_on() or orch.services.llm is None or (os.environ.get("TB_CANARY_AT_START") or "1") == "0":
        return None
    t = threading.Thread(target=run_canary, args=(orch,), name="canary-at-start", daemon=True)
    t.start()
    return t


__all__ = [
    "GATE",
    "Gate",
    "allows_block",
    "check_wake",
    "gate_on",
    "run_canary",
    "startup",
    "status",
    "wake_cases",
    "wake_probe",
]

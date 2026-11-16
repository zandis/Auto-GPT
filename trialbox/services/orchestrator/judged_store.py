"""The judged-pair store (D-908; the owner's D-519, CAS-5): a model's answer to a note question, kept across jobs.

SCREEN asks the note judge about every zero-hit (patient, criterion) pair; the next screening of the same patients at
the same index date asked the same questions again (lane G's review, #639: up to about 1,010 calls a job). This store
keeps each **model's** answer, in ``orch.judged_pairs``, so a question asked again of the same build is read, not
asked.

* **The key** is everything that could change the answer: the patient's pseudonym; the criterion's canonical hash,
  its exact wording and its note question; the hash of the exact excerpt set the model read (D-479); the model's
  role; the prompt's id and file sha; the build that answers the role; the criterion's window and the index date; and
  the note mask's version (``NOTE_MASK_VERSION``). The pseudonym, hash and window come from the cascade
  (:data:`matching.cascade.judge.ASKING`); the rest from the call itself.
* **What is stored:** a parsed answer (a verdict of ``pass``, ``fail`` or ``unknown`` with a confidence) from the build
  that answers the role in this run, the build of the role's first live answer here (as T-689's kept answers): never
  a refusal, a fault, an answer that names no build, or an unanswered call. A role that has not answered live in
  this run reads nothing.
* **One row per model.** The judge's and the verifier's answers are stored apart and recombined when read, by the
  pair rule and the one status function (D-478), exactly as a live answer: no stored row is a verdict.
* **Not stored, not read:** a question of an audit sample (CAS-8), a patient on the opt-out register (D-513: the
  register is read when the job starts; one that cannot be read turns the store off for the job), and every call
  with ``TB_JUDGED_STORE=off``.
* **Erasure and retention:** an opt-out deletes the patient's rows (``datacore.optout_worker.OWED_TABLES``); a row goes
  with the snapshot of the last run that used it, and the snapshots' retention (D-452, ``tb_common.retention``) is
  applied to the store when a SCREEN job starts.

Class D3: in the orchestrator's trial database, never exported, never in a support bundle.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from matching.cascade.judge import ASKING, Asking
from tb_common.llm import LlmResult, load_prompt
from tb_common.phi_guard import NOTE_MASK_VERSION
from tb_common.retention import snapshots_to_keep

ENV = "TB_JUDGED_STORE"
VERDICTS = ("pass", "fail", "unknown")


def enabled(env: dict[str, str] | None = None) -> bool:
    """``TB_JUDGED_STORE``: ``on`` (the default) or ``off``."""
    v = ((os.environ if env is None else env).get(ENV) or "on").strip().lower()
    if v not in ("on", "off"):
        raise ValueError(f"{ENV} must be on or off, not {v!r}")
    return v == "on"


def parsed(result: Any) -> bool:
    """A model's parsed answer: a verdict of the schema's three and a confidence that reads as a number."""
    if not isinstance(result, LlmResult) or not isinstance(result.data, dict):
        return False
    if result.data.get("verdict") not in VERDICTS:
        return False
    try:
        float(result.data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return False
    return True


class JudgedPairs:
    """One job's view of the store. ``register``: the opt-out register read when the job started (None: it could
    not be read, so nothing is read or stored). ``read`` and ``live`` count the model calls of the job's note
    questions answered from the store and asked of a model."""

    def __init__(
        self,
        db: Any,
        snapshot: str,
        register: Iterable[str] | None,
        now: Callable[[], str],
    ) -> None:
        self._db = db
        self.snapshot = snapshot
        self._register = None if register is None else frozenset(register)
        self._now = now
        self._build: dict[str, str] = {}  # role -> the build of its first live answer in this job
        self._lock = threading.Lock()
        self.read = 0
        self.live = 0

    @property
    def on(self) -> bool:
        return self._register is not None and bool(self.snapshot)

    def _asking(self) -> Asking | None:
        a = ASKING.get()
        if a is None or a.audit or not self.on or self._register is None or a.pid in self._register:
            return None
        return a

    def key(self, label: str, inner: Any, prompt_id: str, variables: Any, schema: str | None) -> str | None:
        """The key of this call, or None when the call is not one the store keeps (no question of the cascade's, an
        audit sample, an opted-out patient, a role with no live build yet, a prompt that cannot be loaded)."""
        a = self._asking()
        if a is None or not isinstance(variables, dict):
            return None
        with self._lock:
            build = self._build.get(label)
        if not build:
            return None
        try:
            env = getattr(inner, "_prompt_env", None) or getattr(
                getattr(inner, "gateway", None), "prompt_environment", None
            )
            sha = load_prompt(prompt_id, env).sha256
            excerpts = json.dumps(variables.get("excerpts"), sort_keys=True, ensure_ascii=False, default=str)
            body = json.dumps(
                [
                    a.pid,
                    a.criterion_hash,
                    variables.get("criterion_text"),
                    variables.get("note_question"),
                    hashlib.sha256(excerpts.encode("utf-8")).hexdigest(),  # the exact excerpt set (D-479)
                    label,
                    prompt_id,
                    sha,
                    schema,
                    build,
                    list(a.window),
                    variables.get("index_date"),
                    NOTE_MASK_VERSION,
                ],
                ensure_ascii=False,
                default=str,
            )
        except Exception:  # a prompt that cannot be loaded, variables that cannot be written: asked live, not stored
            return None
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def get(self, key: str) -> LlmResult | None:
        a = self._asking()
        if a is None:
            return None
        got = self._db.pair_get(key)
        if got is None:
            return None
        pid, raw = got
        if pid != a.pid:  # never another patient's answer
            return None
        try:
            out = LlmResult(**json.loads(raw))
        except (TypeError, ValueError):  # written by another build of the code: asked again
            return None
        self._db.pair_touch(key, self.snapshot)
        with self._lock:
            self.read += 1
        # read, not asked: no tokens were spent on it in this job
        return dataclasses.replace(out, tokens_in=0, tokens_out=0)

    def asked(self, label: str, result: Any) -> None:
        """A live call of a cascade question returned (or failed): count it, and learn the role's build from its
        first answer that names one."""
        if ASKING.get() is None:
            return
        with self._lock:
            self.live += 1
            build = getattr(result, "build_sha", "") if isinstance(result, LlmResult) else ""
            if build and label not in self._build:
                self._build[label] = build

    def put(self, key: str, label: str, result: Any) -> None:
        a = self._asking()
        if a is None or not parsed(result):
            return
        with self._lock:
            build = self._build.get(label)
        if not build or result.build_sha != build:  # only the build that answers the role in this job
            return
        try:
            raw = json.dumps(dataclasses.asdict(result), ensure_ascii=False)
        except (TypeError, ValueError):
            return
        self._db.pair_put(key, a.pid, self.snapshot, label, build, raw, self._now())

    def retain(self, today: date, nightly: int = 3, month_end_months: int = 36) -> int:
        """Apply the snapshots' retention (D-452) to the store: the rows of a snapshot the lake no longer keeps go.
        The kept set is the lake's rule over the store's own snapshots, the job's snapshot always kept."""
        snaps = self._db.pair_snapshots()
        keep = snapshots_to_keep(snaps, today, nightly, month_end_months) | {self.snapshot}
        return int(self._db.pairs_drop_snapshots(sorted(keep))) if set(snaps) - keep else 0

    def close(self, register_now: Callable[[], Iterable[str]]) -> int:
        """At the job's end: delete the rows of every patient who joined the opt-out register while the job ran, so a
        pseudonym on the register keeps no row whatever the order of the opt-out and the job's writes (D-513). A
        register that does not answer now is not a reason to keep anything: the opt-out worker deletes them."""
        if not self.on or self._register is None:
            return 0
        try:
            new = frozenset(register_now()) - self._register
        except Exception:
            return 0
        return int(self._db.pairs_drop_pids(sorted(new))) if new else 0

    def report(self) -> dict[str, Any]:
        """What a job's report says: whether the store was used and how many model calls it answered."""
        return {"on": self.on, "read": self.read, "live": self.live}


__all__ = ["ENV", "JudgedPairs", "enabled", "parsed"]

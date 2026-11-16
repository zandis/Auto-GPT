"""The judged-pair store (D-908; the owner's D-519, CAS-5): a model's answer to a note question, kept across jobs.

SCREEN asks the note judge about every zero-hit (patient, criterion) pair; the next screening of the same patients at
the same index date asked the same questions again (lane G's review, #639: up to about 1,010 calls a job). This store
keeps each **model's** answer, in ``orch.judged_pairs``, so a question asked again of the same build is read, not
asked.

* **The key** is everything that could change the answer: the patient's pseudonym; the criterion's canonical hash,
  its exact wording and its note question; the hash of the exact excerpt set the model read (D-479); the model's
  role; the prompt's id and file sha; the build that answers the role; the criterion's window and the index date; and
  the note mask's version (``NOTE_MASK_VERSION``), and the cascade's role (S3 ``judge``, S4 ``second_opinion``). The
  pseudonym, hash, window and role come from the cascade (:data:`matching.cascade.judge.ASKING`), the rest from the
  call; a call whose variables are not the cascade's question (a wake check's canary case) is never keyed.
* **What is stored:** a parsed answer (a verdict of ``pass``, ``fail`` or ``unknown`` with a confidence) from the build
  that answers the role now, the build of the role's latest live answer in this job (as T-689's kept answers): never
  a refusal, a fault, an answer that names no build, or an unanswered call. A role that has not answered live in
  this job reads nothing.
* **One row per model.** The judge's and the verifier's answers are stored apart and recombined when read, by the
  pair rule and the one status function (D-478), exactly as a live answer: no stored row is a verdict.
* **Not stored, not read:** a question of an audit sample (CAS-8), a patient on the opt-out register (D-513: read
  before every write and every read that finds a row; a register that does not answer means no read and no write),
  and every call with ``TB_JUDGED_STORE=off``. A fault of the store is never the job's: the call is asked live.
* **Erasure and retention:** an opt-out deletes the patient's rows (``datacore.optout_worker.OWED_TABLES``), and a
  job's end deletes those of a patient who opted out while it ran. A row stays with the snapshot whose notes it read;
  at each SCREEN job's end (store on or off) the rows of a snapshot the site's retention (D-452,
  ``settings.retention``, ``tb_common.retention``) no longer keeps are deleted.

Class D3: in the orchestrator's trial database, never exported, never in a support bundle.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Any

from matching.cascade.judge import ASKING, Asking, question_digest
from tb_common.llm import LlmResult, load_prompt
from tb_common.phi_guard import NOTE_MASK_VERSION
from tb_common.retention import snapshots_to_keep

log = logging.getLogger(__name__)

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


def kept_snapshots(snaps: Iterable[str], current: str, today: date, nightly: int, month_end_months: int) -> set[str]:
    """The store's snapshots the site's retention still keeps. The rule is the lake's (``snapshots_to_keep``) over
    every night up to the job's snapshot, not over the nights the store happens to hold: a snapshot the lake has
    dropped is never kept here, whatever ran since (a night the lake held back only makes this keep less)."""
    have = sorted(set(snaps) | {current})
    first = date.fromisoformat(have[0])
    last = date.fromisoformat(max(have[-1], current))
    nights = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    return snapshots_to_keep(nights, today, nightly, month_end_months) & set(have) | {current}


class JudgedPairs:
    """One SCREEN job's view of the store. ``snapshot``: the job's pinned snapshot, read when the store is first used
    (the job pins it after its services are built). ``register_now``: the opt-out register as it stands (D-441).
    ``on``: ``TB_JUDGED_STORE``. ``read`` and ``live`` count the model calls of the job's note questions answered
    from the store and asked of a model."""

    def __init__(
        self,
        db: Any,
        snapshot: Callable[[], str],
        register_now: Callable[[], Iterable[str]],
        now: Callable[[], str],
        on: bool = True,
        retention: tuple[int, int] = (3, 36),
    ) -> None:
        self._db = db
        self._snapshot = snapshot
        self._register_now = register_now
        self._now = now
        self.enabled = on
        self.retention = retention
        self._build: dict[str, str] = {}  # client role -> the build of its latest live answer in this job
        self._written: set[str] = set()  # the pseudonyms this job wrote rows for
        self._lock = threading.Lock()
        self.read = 0
        self.live = 0

    @property
    def snapshot(self) -> str:
        try:
            return str(self._snapshot() or "")
        except Exception:
            return ""

    @property
    def on(self) -> bool:
        return self.enabled and bool(self.snapshot)

    def _opted_out(self, pid: str) -> bool:
        """On the register now; a register that does not answer counts as yes (no read, no write; D-127)."""
        try:
            return pid in frozenset(self._register_now())
        except Exception:
            return True

    def _asking(self, variables: Any) -> Asking | None:
        """The cascade's question this call is, or None: no question, an audit sample, the store off, or a call
        whose variables are not the question (a wake check, another prompt)."""
        a = ASKING.get()
        if a is None or a.audit or not self.on or not isinstance(variables, dict):
            return None
        try:
            mine = question_digest(
                str(variables.get("criterion_text")),
                str(variables.get("note_question")),
                str(variables.get("index_date")),
                list(variables.get("excerpts") or []),
            )
        except (TypeError, ValueError, AttributeError):
            return None
        return a if a.question and mine == a.question else None

    def key(self, label: str, inner: Any, prompt_id: str, variables: Any, schema: str | None) -> str | None:
        """The key of this call, or None when the call is not one the store keeps (see :meth:`_asking`), its role has
        no live build yet, or its prompt cannot be loaded."""
        a = self._asking(variables)
        if a is None:
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
                    a.role,
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

    def get(self, key: str, variables: Any) -> LlmResult | None:
        a = self._asking(variables)
        if a is None:
            return None
        try:
            got = self._db.pair_get(key)
        except Exception:
            log.warning("judged-pair store: a read failed; the question is asked live")
            return None
        if got is None:
            return None
        pid, raw = got
        if pid != a.pid or self._opted_out(a.pid):  # never another patient's answer, never an opted-out patient's
            return None
        try:
            out = LlmResult(**json.loads(raw))
        except (TypeError, ValueError):  # written by another build of the code: asked again
            return None
        with self._lock:
            self.read += 1
        return dataclasses.replace(out, tokens_in=0, tokens_out=0)  # read, not asked: no tokens spent in this job

    def asked(self, label: str, result: Any, variables: Any) -> None:
        """A live call of the cascade's question returned (``result``) or failed (None): count it, and keep the
        role's build as the one of its latest answer that names one."""
        if self._asking(variables) is None:
            return
        with self._lock:
            self.live += 1
            build = getattr(result, "build_sha", "") if isinstance(result, LlmResult) else ""
            if build:
                self._build[label] = build

    def put(self, key: str, label: str, result: Any, variables: Any) -> None:
        a = self._asking(variables)
        if a is None or not parsed(result):
            return
        with self._lock:
            build = self._build.get(label)
        if not build or result.build_sha != build:  # only the build that answers the role now
            return
        if self._opted_out(a.pid):
            return
        try:
            raw = json.dumps(dataclasses.asdict(result), ensure_ascii=False)
            self._db.pair_put(key, a.pid, self.snapshot, label, build, raw, self._now())
        except Exception:
            log.warning("judged-pair store: a write failed; the answer stands, unstored")
            return
        with self._lock:
            self._written.add(a.pid)

    def close(self, today: date) -> dict[str, Any]:
        """At the job's end, however it ends: delete the rows this job wrote for a patient now on the register (one
        who opted out while it ran, D-513), apply the snapshots' retention (D-452), and say what the store did."""
        try:
            with self._lock:
                written = set(self._written)
            gone = sorted(written & frozenset(self._register_now())) if written else []
            if gone:
                self._db.pairs_drop_pids(gone)
        except Exception:  # the register did not answer: the opt-out worker deletes them at its next tick
            log.warning("judged-pair store: the opt-out check at the job's end failed")
        self.retain(today)
        return self.report()

    def retain(self, today: date) -> int:
        """Delete the rows of every snapshot the site's retention no longer keeps (see :func:`kept_snapshots`)."""
        snap = self.snapshot
        if not snap:
            return 0
        try:
            snaps = self._db.pair_snapshots()
            if not snaps:
                return 0
            keep = kept_snapshots(snaps, snap, today, *self.retention)
            return int(self._db.pairs_drop_snapshots(sorted(keep))) if set(snaps) - keep else 0
        except Exception:
            log.warning("judged-pair store: the retention sweep failed; it runs again at the next job's end")
            return 0

    def report(self) -> dict[str, Any]:
        """What a job's report says: whether the store was on, and how many model calls of note questions it
        answered (``read``) and how many were asked of a model (``live``)."""
        return {"on": self.on, "read": self.read, "live": self.live}


__all__ = ["ENV", "JudgedPairs", "enabled", "kept_snapshots", "parsed"]

"""One reveal path (T-103, D-438): the only console code that asks for a chart number.

Every surface that shows a chart number is a thin handler over :meth:`Reveal.identifier`: the patient page and its
``/api/v1`` twin, the job page, the candidate page and the referral print. The EMR launch link (T-301a, T-320a) calls
the same function with its own ``purpose``. The function

1. asks the one rule: the ``id.reveal`` row of the permission matrix for the account's role in a study it sees, then
   the study's delegation log for a role whose ``task.*`` rows the log decides (D-147); where the account does not
   reveal by its own rights, the one break-glass rule (D-280, D-430): an open grant for that patient, or for the job
   that is the study's latest list; such a reveal is signed ``BREAK_GLASS_ROLE``;
2. needs a purpose and a reason from the D-143 list, and for "other" a written note (ROLE-016);
3. takes one use of the per-person hourly cap (``TB_REVEAL_MAX_PER_HOUR``) in the study-team store, shared by every
   surface and every console process (``TeamStore.take``, kind ``reveal``), never a counter in memory;
4. writes one audit event shape, ``console.reveal_patient`` for a reveal and ``console.reveal_refused`` for a refusal
   after sign-in, then asks the orchestrator, the single back end (``/jobs/{id}/reveal``), which checks the signed role
   and studies, the job's list, the opt-out register and its own store-backed cap.

Nothing is stored but the audit records and the cap's use rows. Synthetic data only in tests.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from tb_common.authz import BREAK_GLASS_ROLE, conditional
from tb_common.service_auth import scope_of

from console.auth import REVEAL_REASONS, Session, reveal_reason
from console.backend import Refused

CAP_ENV = "TB_REVEAL_MAX_PER_HOUR"
CAP_DEFAULT = 60
CAP_KIND = "reveal"  # the use rows' kind in ``team.candidate_views``
REVEAL_NOTE_MIN = 10  # D-273 (ROLE-016): the written "why" a reveal for "other" needs, in characters
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_PURPOSE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")


def cap() -> int:
    """Chart numbers per person per rolling hour, every surface together (D-438). Read at each call."""
    try:
        return max(0, int(os.environ.get(CAP_ENV) or CAP_DEFAULT))
    except ValueError:
        return CAP_DEFAULT


@dataclass(frozen=True)
class Revealed:
    """One chart number given out: the patient context the page shows, the number, and the record's basis."""

    ctx: dict[str, Any]
    mrn: str
    basis: str
    cap: str
    grant: Any = None


@dataclass
class Reveal:
    """The one reveal path, bound to the console's helpers (``console.home.Helpers``) by ``console.home``."""

    h: Any
    study_or_404: Callable[[Session, str], str]

    # ------------------------------------------------------------------ the rule
    def own_basis(self, sess: Session, rid: str | None) -> str:
        """The basis on which the account reveals in study ``rid`` by its own rights, or "" when it does not: the
        ``id.reveal`` row (``role``) in a study it sees, then the delegation log where it decides the role (``log``)."""
        user = sess.user
        if not rid or not user.sees_study(rid):
            return ""
        if not self.h.permit(user, "id.reveal", rid).allowed:
            return ""
        if conditional(user.role, "task.screen"):
            return "log" if self.h.delegated_ok(user, rid) else ""
        return "role"

    def may_try(self, sess: Session, rid: str | None) -> bool:
        """May the account ask at all (its own rights, or a role that may hold a break-glass grant)? A page uses it
        before it looks anything up, so a reader with neither learns nothing about the job or the patient."""
        return bool(self.own_basis(sess, rid)) or self.h.permit(sess.user, "breakglass.open", rid).allowed

    def guard(self, sess: Session, rid: str | None, path: str, purpose: str, reason: str, via: str,
              job_id: str | None = None) -> None:  # fmt: skip
        """Refuse, with one ``console.reveal_refused`` event, an account that may not ask at all (:meth:`may_try`),
        before a surface looks up its job or referral."""
        rid = rid if rid and _RS.match(rid) else ""
        if not self.may_try(sess, rid):
            raise self.refuse(sess, path, rid, "", purpose, reason, via, "role", 403, "forbidden", job_id=job_id)

    # ------------------------------------------------------------------ audit
    def _detail(self, sess: Session, rid: str, pid: str, purpose: str, reason: str, via: str) -> dict[str, Any]:
        return {"pid": pid, "role": sess.user.role, "affiliation": sess.user.affiliation, "study": rid,
                "purpose": purpose, "reason": reveal_reason(reason), "via": via}  # fmt: skip

    def refuse(self, sess: Session, path: str, rid: str, pid: str, purpose: str, reason: str, via: str, why: str,
               status: int, key: str, job_id: str | None = None,
               values: dict[str, Any] | None = None) -> Exception:  # fmt: skip
        """One ``console.reveal_refused`` event, then the problem (``key`` with ``values``) to raise."""
        detail = self._detail(sess, rid, pid, purpose, reason, via)
        detail.update(refused=why, action=path[:80])
        self.h.au.append("console.reveal_refused", job_id=job_id, ruleset=rid or None, actor=self.h.actor(sess),
                         detail=detail)  # fmt: skip
        problem: Exception = self.h.problem(status, key, **(values or {}))
        return problem

    # ------------------------------------------------------------------ the cap
    def take(self, sess: Session, rid: str, pid: str, purpose: str) -> str | None:
        """One use of the per-person hourly cap, counted and recorded in one transaction in the store; ``n/limit``,
        or None when the cap is reached (or no store is wired: fail closed)."""
        team, limit = self.h.team, cap()
        if team is None:
            return None
        now = self.h.clock()
        since = (now - timedelta(hours=1)).isoformat()
        if not team.take(rid or "-", pid or "-", purpose, CAP_KIND, sess.user.username, now.isoformat(), since,
                         limit):  # fmt: skip
            return None
        return f"{team.count_views(sess.user.username, CAP_KIND, since)}/{limit}"

    def shown_in_line(self, sess: Session, rid: str, job_id: str, where: str) -> str | None:
        """A chart number shown in a request line (``console.view_id``) is a reveal too: it takes a use of the same
        cap. ``n/limit``, or None (refused and audited) when the cap is reached."""
        state = self.take(sess, rid, "-", "request_line")
        if state is None:
            self.h.au.append("console.view_id_refused", job_id=job_id, ruleset=rid or None, actor=self.h.actor(sess),
                             detail={"where": where, "reason": "rate limit", "limit": cap()})  # fmt: skip
        return state

    # ------------------------------------------------------------------ the one function
    def identifier(self, sess: Session, study: str, pid: str, purpose: str, reason: str, *, note: str = "",
                   via: str = "patient", path: str = "", job_id: str = "") -> Revealed:  # fmt: skip
        """The chart number of one listed patient of ``study`` for ``purpose`` with ``reason`` (D-143, D-438).

        ``via`` names the surface (patient, job, candidates, referral, emr, ...); ``job_id`` is the job page's job, so
        that a break-glass grant for that job counts. Raises the console problem on every refusal: 403 (no right:
        role, study, delegation, grant scope), 400 (purpose, reason, the note for "other"), 429 (the cap), 409 (the
        back end refused: not listed, opted out, its own cap)."""
        h = self.h
        rid = self.study_or_404(sess, study)
        path = path or f"reveal {rid}"
        purpose = (purpose or "").strip()
        basis = self.own_basis(sess, rid)
        grant = None
        if not basis and h.breakglass is not None and _PID.match(pid or ""):
            grant = h.breakglass(sess, ruleset=rid, pid=pid, what="reveal") or (
                h.breakglass(sess, job_id=job_id, what="reveal") if job_id else None
            )
        if not basis and grant is None:
            why = "delegation" if self.h.permit(sess.user, "id.reveal", rid).allowed else "role"
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, why, 403, "forbidden")
        if not _PURPOSE.match(purpose):
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "purpose", 400, "request.refused",
                              values={"reason": "say what the chart number is for"})  # fmt: skip
        if reason not in REVEAL_REASONS:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "reason", 400, "request.refused",
                              values={"reason": "choose why you need the chart number"})  # fmt: skip
        note = " ".join((note or "").split())[:200]
        if reason == "other" and len(note) < REVEAL_NOTE_MIN:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "note", 400, "reveal.note_needed",
                              values={"n": REVEAL_NOTE_MIN})  # fmt: skip
        ctx = h.patient_ctx(sess, rid, pid)  # 404 unless the patient is on the study's latest list
        job = ctx["job"]
        if grant is not None:
            basis = f"breakglass:{grant.id}"
            if grant.kind == "job" and job.job_id != grant.job_id:  # a job grant covers that job's list only
                raise self.refuse(sess, path, rid, pid, purpose, reason, via, "grant scope", 403, "forbidden",
                                  job_id=job.job_id)  # fmt: skip
        state = self.take(sess, rid, pid, purpose)
        if state is None:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "cap", 429, "reveal.rate_limited",
                              job_id=job.job_id, values={"n": cap()})  # fmt: skip
        detail = self._detail(sess, rid, pid, purpose, reason, via)
        detail.update(basis=basis, cap=state)
        if note:
            detail["note"] = note
        if grant is not None:
            detail["breakglass"] = grant.id
        h.au.append("console.reveal_patient", job_id=job.job_id, ruleset=rid, actor=h.actor(sess), detail=detail)
        role = BREAK_GLASS_ROLE if grant is not None else sess.user.role
        try:  # D-273 (PV-15): the role and the studies travel signed; the orchestrator checks them and the opt-out
            mrn = h.bk.reveal(job.job_id, pid, h.actor(sess), role=role, scope=scope_of(sess.user.studies),
                              purpose=purpose, reason=reveal_reason(reason))  # fmt: skip
        except Refused as exc:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "back end", 409, "request.refused",
                              job_id=job.job_id, values={"reason": str(exc)}) from exc  # fmt: skip
        return Revealed(ctx=ctx, mrn=mrn or "", basis=basis, cap=state, grant=grant)

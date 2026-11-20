"""One reveal path (T-103, D-438): the only console code that obtains a chart number.

Every surface that shows a chart number is a thin handler over this module: one patient's number
(:meth:`Reveal.identifier`: the patient page and its ``/api/v1`` twin, the job page, the candidate page, the referral
print; next the EMR launch link of T-301a / T-320a with its own ``purpose``), the request line of a job page
(:meth:`Reveal.shown_in_line`), the study's screening log with chart numbers (:meth:`Reveal.screening_log`) and a
patient-level workbook of a job (:meth:`Reveal.workbook`). Each

1. asks the one rule: the ``id.reveal`` row of the permission matrix for the account's role in a study it sees, then
   the study's delegation log for a role whose ``task.*`` rows the log decides (D-147); where the account does not
   reveal by its own rights, the one break-glass rule (D-280, D-430) for one patient or one job only: an open grant
   for that patient, or for the job; such a reveal carries the account's own role and the grant's id, and the
   orchestrator reads the grant row itself and writes its use (T-716, D-484). A grant never opens a whole list;
2. needs a purpose and, where a person asks, a reason from the D-143 list, and for "other" a written note
   (ROLE-016) of at least 10 characters that are not spaces;
3. takes one use of the per-person hourly cap (``TB_REVEAL_MAX_PER_HOUR``) in the study-team store, shared by every
   surface and every console process (``TeamStore.take``, kind ``reveal``), never a counter in memory; a request line
   costs one use per person, job and hour, and the page's own auto-refresh costs none;
4. asks the back end first and writes the record after it answers, before anything is shown: exactly one
   ``console.reveal_patient`` for a number given out, or exactly one ``console.reveal_refused`` for a refusal after
   sign-in. If the record cannot be written nothing is shown (fail closed). The record is never a second copy of an
   identifier: the pid is written only when it is a pseudonym, the note is kept only for "other" and masked.

Nothing is stored but the audit records and the cap's use rows. Synthetic data only in tests.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from tb_common.audit import ID_MASK, mask_ids
from tb_common.authz import conditional
from tb_common.phi_guard import mask_note, site_mrn_regex
from tb_common.service_auth import scope_of

from console import actor
from console.auth import REVEAL_REASONS, Session, reveal_reason
from console.backend import Refused

CAP_ENV = "TB_REVEAL_MAX_PER_HOUR"
CAP_DEFAULT = 60
CAP_KIND = "reveal"  # the use rows' kind in ``team.candidate_views``
REVEAL_NOTE_MIN = 10  # D-273 (ROLE-016): the written "why" a reveal for "other" needs, in characters (not spaces)
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_PURPOSE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_DIGITS = re.compile(r"\d{6,}")  # a chart number written without its label, when the site's pattern is not readable


def cap() -> int:
    """Chart numbers per person per rolling hour, every surface together (D-438). Read at each call."""
    try:
        return max(0, int(os.environ.get(CAP_ENV) or CAP_DEFAULT))
    except ValueError:
        return CAP_DEFAULT


def safe_pid(pid: str) -> str:
    """The pid as the record may hold it: a pseudonym as is, nothing as nothing, anything else ``invalid`` (a URL
    can carry a chart number or a name where a pseudonym belongs)."""
    if not pid:
        return ""
    return pid if _PID.match(pid) else "invalid"


def note_words(note: str) -> int:
    """The characters of a note that are not spaces (ROLE-016: "a b c d e f" is not a reason)."""
    return len("".join((note or "").split()))


def clean_note(note: str) -> str:
    """The note as the record keeps it: whitespace folded, at most 200 characters, identifiers masked (D-272's
    ``mask_ids``, the note masker with the site's chart-number pattern, and any long digit run)."""
    text = " ".join((note or "").split())[:200]
    text = mask_note(mask_ids(text), site_mrn_regex())
    return _DIGITS.sub(ID_MASK, text)


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
    def own_basis(self, sess: Session, rid: str | None, export: bool = False) -> str:
        """The basis on which the account reveals in study ``rid`` by its own rights, or "" when it does not: the
        ``id.reveal`` row (``role``) in a study it sees, then the delegation log where it decides the role (``log``).
        ``export`` (9f-3, D-1383): a whole list that leaves as a file asks the log without a cover (no export by a
        cover, ``Helpers.export_ok``)."""
        user = sess.user
        if not rid or not user.sees_study(rid):
            return ""
        if not self.h.permit(user, "id.reveal", rid).allowed:
            return ""
        if conditional(user.role, "task.screen"):
            ok = self.h.export_ok(user, rid) if export else self.h.delegated_ok(user, rid)
            return "log" if ok else ""
        return "role"

    def may_try(self, sess: Session, rid: str | None) -> bool:
        """May the account ask at all (its own rights, or a role that may hold a break-glass grant)? A page uses it
        before it looks anything up, so a reader with neither learns nothing about the job or the patient."""
        return bool(self.own_basis(sess, rid)) or self.h.permit(sess.user, "breakglass.open", rid).allowed

    def _why_not(self, sess: Session, rid: str) -> str:
        own_row = bool(rid) and sess.user.sees_study(rid) and self.h.permit(sess.user, "id.reveal", rid).allowed
        return "delegation" if own_row else "role"

    def guard(self, sess: Session, rid: str | None, path: str, purpose: str, reason: str, via: str,
              job_id: str | None = None) -> None:  # fmt: skip
        """Refuse, with one ``console.reveal_refused`` event, an account that may not ask at all (:meth:`may_try`),
        before a surface looks up its job or referral."""
        rid = rid if rid and _RS.match(rid) else ""
        if not self.may_try(sess, rid):
            raise self.refuse(sess, path, rid, "", purpose, reason, via, "role", 403, "forbidden", job_id=job_id)

    # ------------------------------------------------------------------ audit
    def _detail(self, sess: Session, rid: str, pid: str, purpose: str, reason: str, via: str) -> dict[str, Any]:
        return {"pid": safe_pid(pid), "role": sess.user.role, "affiliation": sess.user.affiliation, "study": rid,
                "purpose": purpose, "reason": reveal_reason(reason), "via": via}  # fmt: skip

    def refuse(self, sess: Session, path: str, rid: str, pid: str, purpose: str, reason: str, via: str, why: str,
               status: int, key: str, job_id: str | None = None,
               values: dict[str, Any] | None = None) -> Exception:  # fmt: skip
        """One ``console.reveal_refused`` event, then the problem (``key`` with ``values``) to raise."""
        detail = self._detail(sess, rid, pid, purpose, reason, via)
        action = path if not pid or safe_pid(pid) == pid else path.replace(pid, "invalid")
        detail.update(refused=why, action=mask_ids(action)[:80])
        self.h.au.append("console.reveal_refused", job_id=job_id, ruleset=rid or None, actor=self.h.actor(sess),
                         detail=detail)  # fmt: skip
        problem: Exception = self.h.problem(status, key, **(values or {}))
        return problem

    def _shown(self, sess: Session, rid: str, pid: str, purpose: str, reason: str, via: str, *, basis: str,
               state: str, job_id: str | None, **extra: Any) -> None:  # fmt: skip
        """The one record of an identifier given out (written after the back end answered, before it is shown)."""
        detail = self._detail(sess, rid, pid, purpose, reason, via)
        detail.update(basis=basis, cap=state, **extra)
        self.h.au.append("console.reveal_patient", job_id=job_id, ruleset=rid or None, actor=self.h.actor(sess),
                         detail=detail)  # fmt: skip

    def _reason_ok(self, sess: Session, path: str, rid: str, pid: str, purpose: str, reason: str, note: str,
                   via: str) -> str:  # fmt: skip
        """Check the purpose, the reason and the note for "other"; the note as the record keeps it ("other" only)."""
        if not _PURPOSE.match(purpose):
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "purpose", 400, "request.refused",
                              values={"reason": "say what the chart number is for"})  # fmt: skip
        if reason not in REVEAL_REASONS:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "reason", 400, "request.refused",
                              values={"reason": "choose why you need the chart number"})  # fmt: skip
        if reason != "other":
            return ""
        if note_words(note) < REVEAL_NOTE_MIN:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "note", 400, "reveal.note_needed",
                              values={"n": REVEAL_NOTE_MIN})  # fmt: skip
        return clean_note(note)

    # ------------------------------------------------------------------ the cap
    def _window(self) -> tuple[str, str]:
        now = self.h.clock()
        return now.isoformat(), (now - timedelta(hours=1)).isoformat()

    def take(self, sess: Session, rid: str, pid: str, purpose: str) -> str | None:
        """One use of the per-person hourly cap, counted and recorded in one transaction in the store; ``n/limit``,
        or None when the cap is reached (or no store is wired: fail closed)."""
        team, limit = self.h.team, cap()
        if team is None:
            return None
        now, since = self._window()
        if not team.take(rid or "-", pid or "-", purpose, CAP_KIND, sess.user.username, now, since, limit):
            return None
        return f"{team.count_views(sess.user.username, CAP_KIND, since)}/{limit}"

    def shown_in_line(self, sess: Session, rid: str, job_id: str, where: str, *, auto: bool = False,
                      basis: str = "") -> bool:  # fmt: skip
        """May the chart number in this job's request line be shown in clear now? A request line is a reveal too:
        one use of the same cap per person, job and hour (``TeamStore.take_once``), recorded once in the D-438 shape
        (``via`` ``request_line``). The page's own auto-refresh (``auto``) takes no use and writes nothing: it shows
        the number only while this person's use of this job is in the window. Over the cap: masked, refused once."""
        team, limit = self.h.team, cap()
        if team is None:
            return False
        now, since = self._window()
        key = f"job:{job_id}"
        if auto:
            return bool(team.used_since(key, "request_line", CAP_KIND, sess.user.username, since))
        got = team.take_once(rid or "-", key, "request_line", CAP_KIND, sess.user.username, now, since, limit)
        if got is None:
            self.refuse(sess, where, rid, "", "request_line", "", "request_line", "cap", 429, "reveal.rate_limited",
                        job_id=job_id)  # fmt: skip
            return False
        if got == "new":
            state = f"{team.count_views(sess.user.username, CAP_KIND, since)}/{limit}"
            self._shown(sess, rid, "", "request_line", "", "request_line", basis=basis, state=state, job_id=job_id,
                        where=where)  # fmt: skip
        return True

    # ------------------------------------------------------------------ one patient
    def identifier(self, sess: Session, study: str, pid: str, purpose: str, reason: str, *, note: str = "",
                   via: str = "patient", path: str = "", job_id: str = "") -> Revealed:  # fmt: skip
        """The chart number of one listed patient of ``study`` for ``purpose`` with ``reason`` (D-143, D-438).

        ``via`` names the surface (patient, job, candidates, referral, emr, ...); ``job_id`` is the job page's job, so
        that a break-glass grant for that job counts. Raises the console problem on every refusal: 403 (no right:
        role, study, delegation, grant scope), 400 (purpose, reason, the note for "other"), 429 (the cap), 409 (the
        back end refused: not listed, opted out, its own cap). A pseudonym the box's pid map lacks gives an empty
        number and one ``console.reveal_refused`` record (``not in the pid map``), never a reveal record."""
        h = self.h
        rid = self.study_or_404(sess, study)
        path = path or f"reveal {rid}"
        purpose = (purpose or "").strip()
        basis = self.own_basis(sess, rid)
        grant = None
        if not basis and h.breakglass_find is not None and _PID.match(pid or ""):
            # T-716 (D-484): found, not used: the orchestrator reads the grant and writes the use
            grant = h.breakglass_find(sess, ruleset=rid, pid=pid) or (
                h.breakglass_find(sess, job_id=job_id) if job_id else None
            )
        if not basis and grant is None:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, self._why_not(sess, rid), 403, "forbidden")
        kept = self._reason_ok(sess, path, rid, pid, purpose, reason, note, via)
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

        def sign(method: str, to: str, body: Any) -> dict[str, str]:
            """The one minting place: the account's own role, this study, and the grant's id when the right is one."""
            return actor.assert_for(h, sess, "id.reveal", rid, method, to, body, grant=grant)

        try:  # T-716 (D-484): the orchestrator reads the grant and the delegation log itself, and the opt-out
            mrn = h.bk.reveal(job.job_id, pid, sign, purpose=purpose, reason=reveal_reason(reason))
        except Refused as exc:
            raise self.refuse(sess, path, rid, pid, purpose, reason, via, "back end", 409, "request.refused",
                              job_id=job.job_id, values={"reason": str(exc)}) from exc  # fmt: skip
        if not mrn:  # nothing to show: the page says so; the record says no number went out
            self.refuse(sess, path, rid, pid, purpose, reason, via, "not in the pid map", 404, "notfound",
                        job_id=job.job_id)  # fmt: skip
            return Revealed(ctx=ctx, mrn="", basis=basis, cap=state, grant=grant)
        extra: dict[str, Any] = {}
        if kept:
            extra["note"] = kept
        if grant is not None:
            extra["breakglass"] = grant.id
            if h.breakglass_note is not None:  # the use itself is the orchestrator's row (T-716, D-484)
                h.breakglass_note(sess, grant, ruleset=rid, pid=pid, what="reveal")
        self._shown(sess, rid, pid, purpose, reason, via, basis=basis, state=state, job_id=job.job_id, **extra)
        return Revealed(ctx=ctx, mrn=mrn, basis=basis, cap=state, grant=grant)

    # ------------------------------------------------------------------ whole lists
    def screening_log(self, sess: Session, rs: str, reason: str, *, note: str = "", path: str = "",
                      before: Callable[[], None] | None = None) -> bytes:  # fmt: skip
        """The study's screening log with every chart number (the orchestrator's registry export), through the same
        rule: own rights only (a break-glass grant covers one patient or one job, never a list), a reason, one use
        of the cap, and one record in the D-438 shape with the number of chart numbers, never the pids."""
        purpose, via = "screening_log", "screening_log"
        rid = rs if _RS.match(rs) else ""
        path = path or f"screening log {rid}"
        basis = self.own_basis(sess, rid, export=True)  # 9f-3 (D-1383): the chart-number workbook, never by a cover
        if not basis:
            raise self.refuse(sess, path, rid, "", purpose, reason, via, self._why_not(sess, rid), 403, "forbidden")
        kept = self._reason_ok(sess, path, rid, "", purpose, reason, note, via)
        state = self.take(sess, rid, "", purpose)
        if state is None:
            raise self.refuse(sess, path, rid, "", purpose, reason, via, "cap", 429, "reveal.rate_limited",
                              values={"n": cap()})  # fmt: skip
        if before is not None:  # the caller's own record of the request, before the back end is asked
            before()
        try:
            data: bytes = self.h.bk.registry_export(rid, self.h.actor(sess), role=sess.user.role,
                                                    scope=scope_of(sess.user.studies))  # fmt: skip
        except Refused as exc:  # the orchestrator's cap on exports with chart numbers (S-09), its role check
            raise self.refuse(
                sess,
                path,
                rid,
                "",
                purpose,
                reason,
                via,
                "back end",
                409,
                "request.refused",
                values={"reason": "too many exports with chart numbers in the last hour"},
            ) from exc
        pids = workbook_pids(data)
        self._shown(sess, rid, "", purpose, reason, via, basis=basis, state=state, job_id=None, count=len(pids),
                    **({"note": kept} if kept else {}))  # fmt: skip
        return data

    def workbook(self, sess: Session, job: Any, out: Any, path: str = "") -> bytes:
        """A patient-level workbook of a job (the candidate list, a referral list, a navigation list: every listed
        patient's chart number), downloaded in the browser by a named recipient (D-369). Own rights only; refused,
        with the reason, when the workbook names a patient who has opted out since it was made (D-273 PV-4: run the
        list again); one use of the cap; one record in the D-438 shape with the count. The mailed copy is the
        job's delivery to its named recipients and is not counted again."""
        purpose, via = "workbook", "download"
        rid = str(job.ruleset or "")
        path = path or f"workbook {job.job_id}"
        basis = self.own_basis(sess, rid, export=True)  # 9f-3 (D-1383): a patient-level file, never by a cover
        if not basis:
            raise self.refuse(sess, path, rid, "", purpose, "", via, self._why_not(sess, rid), 404, "notfound",
                              job_id=job.job_id)  # fmt: skip
        data: bytes = self.h.bk.get_object(out.minio_key)
        pids = workbook_pids(data)
        from tb_common.optout import opted_out  # the register as it stands now, as a run reads it at publish (D-441)

        if pids & (opted_out() | self.h.gone()):
            raise self.refuse(sess, path, rid, "", purpose, "", via, "opted out", 409, "request.refused",
                              job_id=job.job_id,
                              values={"reason": "a patient on this list has opted out since it was made; run the "
                                                "list again"})  # fmt: skip
        state = self.take(sess, rid, "", purpose)
        if state is None:
            raise self.refuse(sess, path, rid, "", purpose, "", via, "cap", 429, "reveal.rate_limited",
                              job_id=job.job_id, values={"n": cap()})  # fmt: skip
        self._shown(sess, rid, "", purpose, "", via, basis=basis, state=state, job_id=job.job_id, count=len(pids),
                    file=str(out.filename)[:120])  # fmt: skip
        return data


def workbook_pids(data: bytes) -> set[str]:
    """The pseudonyms of a patient-level workbook: every value under a ``pid`` header, in every sheet."""
    from openpyxl import load_workbook

    out: set[str] = set()
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # not a workbook: no pids found (the caller's rule and cap still hold)
        return out
    for ws in wb.worksheets:
        col: int | None = None
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in row]
            if col is None:
                low = [c.lower() for c in cells]
                col = low.index("pid") if "pid" in low else None
                continue
            if col < len(cells) and _PID.match(cells[col]):
                out.add(cells[col])
    wb.close()
    return out

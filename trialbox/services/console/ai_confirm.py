"""D-989 (lane C2's card): a person's decision on a patient a model answered, as ``ai.confirmed``.

The console records two decisions on a patient's verdicts: the investigator's mark on the weekly list, and "this is
wrong, send to review" on the not-matched list. Each writes one ``ai.confirmed`` per verdict a model answered (its
``prov``, the call ids, not empty) through :mod:`tb_common.provenance`; the patient is named by the pseudonym the
list already uses, ``by`` is the person's user name.

* Approach: ``confirmed`` (the investigator goes ahead on the list's answers).
* A review of an exclusion: ``rejected``; the named criterion's verdict, else every verdict that excluded the patient.
* Not suitable now, Need info, Not now, Withdraw, Undo: no event. They decide nothing about the model's answer (Not
  suitable now's reasons are each site's own and may have nothing to do with it: the integrator's ruling), which
  stays unconfirmed (D-989: never inferred). Nothing maps to ``changed``.

A verdict no model answered (``prov`` empty: the coded records, a person; or absent: a list from before the field)
writes nothing."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from tb_common import provenance

#: the mark -> the decision on the model's answers of the row (a mark not here decides nothing about them)
MARK_DECISION = {"approach": "confirmed"}
REVIEW_DECISION = "rejected"


def on_verdicts(audit: Any, *, ruleset: str, version: str, job: str, pid: str, criteria: Iterable[Mapping[str, Any]],
                by: str, decision: str, crit: str = "", **extra: Any) -> int:  # fmt: skip
    """``ai.confirmed`` for each verdict of one patient's row that a model answered (``crit``: that criterion only).
    Returns how many were written."""
    n = 0
    for c in criteria:
        cid = str(c.get("id") or "")
        calls = [str(x) for x in c.get("prov") or [] if x]
        if not cid or not calls or (crit and cid != crit):
            continue
        record = provenance.ref(ruleset=ruleset, version=version, job=job, pid=pid, crit=cid)
        if provenance.confirmed(audit, "verdict", record, calls, by, decision, **extra):
            n += 1
    return n


def row_of(doc: Mapping[str, Any] | None, pid: str) -> Mapping[str, Any] | None:
    return next((r for r in (doc or {}).get("rows") or [] if str(r.get("pid")) == pid), None)

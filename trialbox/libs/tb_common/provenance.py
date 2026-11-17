"""D-989 step 2b: the two audit events the provenance index reads, written where a model's answer becomes part of a
record (``ai.used``) and where a person confirms, changes or rejects one (``ai.confirmed``).

* ``ai.used`` ``{record_kind, record_ref, calls}``: the record now holds an answer of these model calls (each call id
  resolves to its ``llm.call`` in the chain). One event per record, its calls listed; the index (step 2c) writes a row
  per call. A record no model answered writes nothing: its own ``prov: []`` says so.
* ``ai.confirmed`` ``{record_kind, record_ref, calls, by, decision}``: ``decision`` is ``confirmed``, ``changed`` or
  ``rejected``. A model answer nobody confirmed has no event and is reported unconfirmed, never inferred confirmed.

``record_ref`` names the record by the ids the console and the erasure registry use: ``(ruleset, version, crit)`` for
a criterion, ``(ruleset, version, job, pid, crit)`` for a verdict, ``(ruleset, version, valueset)`` for a value set,
``(draft, field)`` for an EDC draft field. A patient is named only by the pseudonym the chain already uses, never a
chart number or free text (the integrator's condition on D-989: the chain is not erased), so every part is a short
token: letters, digits and ``_ . : @ -``, nothing else, else :class:`ValueError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

USED, CONFIRMED = "ai.used", "ai.confirmed"
KINDS = ("verdict", "criterion", "valueset", "edc_field")
DECISIONS = ("confirmed", "changed", "rejected")
REF_PARTS = ("ruleset", "version", "job", "pid", "crit", "valueset", "draft", "field")
_TOKEN = re.compile(r"^[A-Za-z0-9_.:@-]{1,96}$")


def ref(**parts: Any) -> dict[str, str]:
    """A record's reference: known parts only, each a short token (a pseudonym, an id, a version)."""
    out: dict[str, str] = {}
    for k, v in parts.items():
        if k not in REF_PARTS:
            raise ValueError(f"record_ref part {k!r}: one of {', '.join(REF_PARTS)}")
        s = str(v)
        if not _TOKEN.match(s):
            raise ValueError(f"record_ref part {k!r}: an id or pseudonym, never free text or a chart number")
        out[k] = s
    return out


def _calls(calls: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(c) for c in calls if c))


def used(audit: Any, kind: str, record: Mapping[str, str], calls: Iterable[str], **extra: Any) -> bool:
    """Write ``ai.used`` for one record; nothing when no model call stands behind it. True when written."""
    if kind not in KINDS:
        raise ValueError(f"record_kind {kind!r}: one of {', '.join(KINDS)}")
    got = _calls(calls)
    if audit is None or not got:
        return False
    audit.append(USED, record_kind=kind, record_ref=dict(record), calls=got, **extra)
    return True


def confirmed(
    audit: Any, kind: str, record: Mapping[str, str], calls: Iterable[str], by: str, decision: str, **extra: Any
) -> bool:
    """Write ``ai.confirmed``: a person's ``decision`` on a record a model answered. True when written."""
    if kind not in KINDS:
        raise ValueError(f"record_kind {kind!r}: one of {', '.join(KINDS)}")
    if decision not in DECISIONS:
        raise ValueError(f"decision {decision!r}: one of {', '.join(DECISIONS)}")
    got = _calls(calls)
    if audit is None or not got:
        return False
    audit.append(CONFIRMED, record_kind=kind, record_ref=dict(record), calls=got, by=by, decision=decision, **extra)
    return True


def verdicts_used(audit: Any, ruleset: str, version: str, job: str, rows: Iterable[Any]) -> int:
    """``ai.used`` for each candidate-list verdict a model answered (``prov`` not empty), patient by pseudonym."""
    n = 0
    for row in rows:
        for v in getattr(row, "criteria", None) or []:
            prov = getattr(v, "prov", None) or []
            if prov and used(audit, "verdict", ref(ruleset=ruleset, version=version, job=job, pid=row.pid, crit=v.id),
                             prov):  # fmt: skip
                n += 1
    return n

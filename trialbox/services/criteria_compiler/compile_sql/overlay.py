"""Approved SQL run under today's safety rules (D-275; review S-1, S-5, S-9).

A ruleset's SQL is an approved artefact: it is stored at approval and run as stored. The SQL of rulesets approved
before D-275 compares a lab value with the criterion's number whatever the row's unit says, reads a sex of ``other``
or ``unknown`` as "not female", and counts an order with no end date as one day. Recompiling a ruleset needs a new
approval, so the runtime does not wait for it: :func:`safe_sql` runs the stored SQL **beside** a fresh rendering of
the same approved criteria and ValueSets by the current generator, and keeps a stored answer only where both agree.

* both give the same answer: that answer (with the stored evidence; with the fresh one when both are unknown);
* they differ (the stored SQL decided on data the current rules cannot read, or the other way round): **unknown**
  (NULL), with the fresh rendering's evidence and the reason ``rules_changed`` (a more specific reason of the fresh
  rendering, such as ``unit_mismatch``, is reported first). The fresh rendering never decides a criterion alone;
* a criterion the current generator cannot render (review F5): unknown with ``rules_changed``, for that criterion
  only; the other criteria and the job go on.

So an approved ruleset can only lose decided answers to "unknown", never gain an exclusion or an inclusion. The
stored text is not changed (it is embedded as it is). SQL compiled since D-1073 carries the generator's ``MARK`` line
in its header and is run alone. The guarded SQL is built once per ruleset content and kept (review F12).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading

from tb_common.labunit import RULES_CHANGED
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

from criteria_compiler.compile_sql.generator import MARK, SqlGenerator, lit, qcol
from criteria_compiler.semantics import compiled
from criteria_compiler.terminology.mapper import Terminology, ValueSets

log = logging.getLogger("criteria_compiler")
HEADER_LINES = 6  # the generator's header: four comment lines, the mark, "WITH"
_CACHE: dict[str, str] = {}
_LOCK = threading.Lock()


def guarded(sql: str) -> bool:
    """The SQL was compiled with the D-275 rules: the mark is a line of its header (never of a criterion's text)."""
    return MARK in sql.splitlines()[:HEADER_LINES]


def _key(rs: Ruleset) -> str:
    body = json.dumps(
        [rs.id, rs.version, rs.sql, [c.model_dump(mode="json") for c in rs.criteria], rs.valuesets],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def safe_sql(rs: Ruleset) -> str:
    """The SQL to run for ``rs``: its stored SQL, guarded by the current rules when it was compiled before them.
    Same parameters and same columns as the stored SQL."""
    if not rs.sql or guarded(rs.sql):
        return rs.sql
    k = _key(rs)
    with _LOCK:
        hit = _CACHE.get(k)
    if hit is not None:
        return hit
    out = _build(rs)
    with _LOCK:
        _CACHE[k] = out
    return out


def _render(rs: Ruleset, crit: list[CriterionIR]) -> list[tuple[list[str], str | None]]:
    """``[(criterion ids, fresh SQL or None when it cannot be rendered)]``: one rendering of all criteria, else one
    per criterion so a criterion the generator refuses leaves only itself unknown."""
    try:
        vs = ValueSets(rs.id, rs.valuesets, Terminology())
        return [([c.id for c in crit], SqlGenerator(rs.id, rs.version, vs).render(crit))]
    except Exception:  # a refused criterion, or the terminology itself: try each criterion alone
        log.warning("D-275 guard: %s v%s did not render as a whole; rendering each criterion", rs.id, rs.version)
    out: list[tuple[list[str], str | None]] = []
    for c in crit:
        try:
            vs = ValueSets(rs.id, rs.valuesets, Terminology())
            out.append(([c.id], SqlGenerator(rs.id, rs.version, vs).render([c])))
        except Exception:
            log.warning("D-275 guard: %s %s cannot be rendered now: unknown for every patient", rs.id, c.id)
            out.append(([c.id], None))
    return out


def _build(rs: Ruleset) -> str:
    crit = [c for c in compiled(rs.active()) if c.logic is not None and f'"C_{c.id}"' in rs.sql]
    if not crit:
        return rs.sql
    changed = lit(RULES_CHANGED)
    cols: list[str] = []
    joins: list[str] = []
    for n, (ids, fresh) in enumerate(_render(rs, crit)):
        alias = f"n{n}"
        if fresh is not None:
            joins.append(
                f"LEFT JOIN (\n{fresh}\n) {alias} ON {alias}.pid = o.pid AND {alias}.index_date = o.index_date"
            )
        for cid in ids:
            c_col, e_col = qcol("C_" + cid), qcol("E_" + cid)
            if fresh is None:
                cols += [f"CAST(NULL AS BOOLEAN) AS {c_col}", f"{changed} AS {e_col}"]
                continue
            oc, nc, oe, ne = f"o.{c_col}", f"{alias}.{c_col}", f"o.{e_col}", f"{alias}.{e_col}"
            cols.append(f"(CASE WHEN {oc} IS NOT DISTINCT FROM {nc} THEN {oc} END) AS {c_col}")
            cols.append(
                f"(CASE WHEN {oc} IS NOT DISTINCT FROM {nc} THEN (CASE WHEN {nc} IS NULL THEN {ne} ELSE {oe} END) "
                f"ELSE concat_ws(';', {ne}, {changed}) END) AS {e_col}"
            )
    return (
        f"-- {rs.id} v{rs.version}: approved SQL guarded by the current safety rules (D-275): unknown on a difference\n"
        "SELECT o.* REPLACE (\n  " + ",\n  ".join(cols) + ")\n"
        f"FROM (\n{rs.sql}\n) o\n" + "\n".join(joins) + "\nORDER BY o.pid, o.index_date\n"
    )


__all__ = ["guarded", "safe_sql"]

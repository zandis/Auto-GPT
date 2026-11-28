"""``match_stage`` adapter: a ``CascadeResult`` (its ``PatientTrace`` and ``Outcome`` rows, read through the
product's own ``verdict_of``) into ledger rows, and the reconciliation of those rows with the candidate list.

One S0 row per patient in the candidate list, one row per active inclusion or exclusion criterion for each patient in
scope (the outcome at the stage that decided it, or ``not_applicable`` when the cascade stopped before it), one
``tier`` row per patient. Nothing is re-derived: every column is read from what the cascade kept. What the cascade
does not keep today (the lake rows behind a coded answer, passage scores, code checks, raw model text) is written as
null, and ``LEDGER-SCHEMA.md`` names each gap.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from matching.cascade import CascadeResult
from matching.cascade.engine import _atoms
from matching.cascade.model import Outcome, PatientTrace
from orchestrator.scenarios.screen_cascade import verdict_of
from tb_common.ruleset import Ruleset

from bench.invest.ledger import LedgerWriter, canonical_json, content_hash, sha_of_text

_VERDICT = {"pass": "T", "fail": "F", "unknown": "U", "pending_human": "U"}
KINDS = ("inclusion", "exclusion")


def pseudonym(pid: str, salt: str) -> str:
    """The ledger's patient key: a salted hash, so a ledger moved or joined elsewhere carries no source id."""
    return "p-" + hashlib.sha256(f"{salt}|{pid}".encode()).hexdigest()[:16]


def add_cascade(
    w: LedgerWriter,
    rs: Ruleset,
    result: CascadeResult,
    *,
    lake_snapshot: str,
    pid_salt: str | None = None,
    pair: bool = False,
    gold: Mapping[tuple[str, str], Any] | None = None,
) -> dict[str, int]:
    """Write every stage row of one protocol's cascade run; return the row counts by stage.

    ``pid_salt``: given, patient ids are pseudonymised. ``gold``: optional ``(pid, criterion_id)`` -> gold label."""
    proto = rs.id
    hashes = result.criterion_hashes
    sql_sha = sha_of_text(rs.sql) if rs.sql else None
    cql_sha = sha_of_text(rs.cql.get(rs.library, "")) if rs.cql else None
    crits = [c for c in rs.active() if c.kind in KINDS]
    atoms = {c.id: _atoms(c.logic.model_dump(mode="json", by_alias=True, exclude_none=True)) for c in crits}
    counts: dict[str, int] = {}
    final = set(result.final_list)

    def put(stage: str, row: dict[str, Any]) -> None:
        w.add("match_stage", proto, {"protocol_id": proto, "stage": stage, "attempt": 0, **row})
        counts[stage] = counts.get(stage, 0) + 1

    for raw_pid in sorted(result.traces):
        t = result.traces[raw_pid]
        pid = pseudonym(raw_pid, pid_salt) if pid_salt else raw_pid
        base = {"pid": pid}
        put(
            "S0",
            {
                **base,
                "criterion_id": "",
                "inputs_hash": content_hash(pid, proto, "S0", lake_snapshot, t.index_date.isoformat(), t.department),
                "verdict": "T" if t.in_scope else "F",
                "reason_code": None if t.in_scope else "out_of_scope",
                "row_evidence_json": None if t.in_scope else {"scope_reason": t.scope_reason},
                "basis": "coded",
            },
        )
        if t.in_scope:
            for c in crits:
                o = t.outcomes.get(c.id)
                row = _criterion_row(c.id, o, t, pid, proto, hashes, pair, lake_snapshot)
                row.update(_static(c.id, hashes, atoms, sql_sha, cql_sha))
                if (g := (gold or {}).get((raw_pid, c.id))) is not None:
                    row["gold"] = canonical_json(g)
                put(o.stage if o else (t.exit_stage or "tier"), row)
        put(
            "tier",
            {
                **base,
                "criterion_id": "",
                "inputs_hash": content_hash(pid, proto, "tier", lake_snapshot),
                "verdict": "not_applicable",
                "reason_code": t.tier,
                "final": raw_pid in final,
            },
        )
    return counts


def _static(
    cid: str, hashes: Mapping[str, str], atoms: Mapping[str, Any], sql_sha: str | None, cql_sha: str | None
) -> dict[str, Any]:
    return {
        "canonical_hash": hashes.get(cid),
        "atoms_json": canonical_json(atoms[cid]),
        "sql_sha": sql_sha,
        "cql_sha": cql_sha,
    }


def _criterion_row(
    cid: str,
    o: Outcome | None,
    t: PatientTrace,
    pid: str,
    proto: str,
    hashes: Mapping[str, str],
    pair: bool,
    lake_snapshot: str,
) -> dict[str, Any]:
    if o is None:
        return {
            "pid": pid,
            "criterion_id": cid,
            "inputs_hash": content_hash(pid, proto, cid, lake_snapshot, hashes.get(cid), "not_evaluated", t.exit_stage),
            "verdict": "not_applicable",
            "reason_code": "not_evaluated",
        }
    v = verdict_of(o, pair)
    ev = v.evidence
    dump = (lambda x: x.model_dump(mode="json", exclude_none=True)) if ev else None
    return {
        "pid": pid,
        "criterion_id": cid,
        "inputs_hash": content_hash(
            pid,
            proto,
            cid,
            lake_snapshot,
            hashes.get(cid),
            o.stage,
            [e.get("did") or e.get("record") for e in o.evidence],
        ),
        "row_evidence_json": o.evidence or None,
        "model_raw_json": {"calls": v.prov} if v.prov else None,
        "verdict": _VERDICT[v.verdict],
        "unknown_kind": o.unknown_kind or ("pending_human" if v.verdict == "pending_human" else None),
        "reason_code": ev.reason if ev else None,
        "basis": v.basis,
        "final": v.final,
        "affirmed": v.affirmed,
        "opinions_json": [dump(x) for x in (ev.opinions or [])] if ev and ev.opinions and dump else None,
        "confidence": ev.confidence if ev else None,
    }


def reconcile(con: Any, result: CascadeResult, rs: Ruleset) -> list[str]:
    """Compare the ledger (a ``ledger.connect`` handle) with the cascade's own candidate list; return the mismatches
    (empty: every row count reconciles)."""
    proto = rs.id
    n = len(result.traces)
    in_scope = len(result.in_scope())
    n_crit = len([c for c in rs.active() if c.kind in KINDS])
    q = "SELECT count(*) FROM match_stage WHERE protocol_id=? AND stage=?"

    def one(sql: str, *a: Any) -> int:
        return int(con.execute(sql, list(a)).fetchone()[0])

    bad: list[str] = []
    if (got := one(q, proto, "S0")) != n:
        bad.append(f"S0 rows {got} != candidate list {n}")
    if (got := one(q, proto, "tier")) != n:
        bad.append(f"tier rows {got} != candidate list {n}")
    crit_rows = one("SELECT count(*) FROM match_stage WHERE protocol_id=? AND criterion_id<>''", proto)
    if crit_rows != in_scope * n_crit:
        bad.append(f"criterion rows {crit_rows} != in-scope patients {in_scope} x criteria {n_crit}")
    if (got := one("SELECT count(*) FROM match_stage WHERE protocol_id=? AND stage='tier' AND final", proto)) != len(
        result.final_list
    ):
        bad.append(f"final-list rows {got} != final list {len(result.final_list)}")
    rows = con.execute(
        "SELECT reason_code, count(*) FROM match_stage WHERE protocol_id=? AND stage='tier' GROUP BY 1", [proto]
    ).fetchall()
    if dict(rows) != _tiers_of(result):
        bad.append(f"tier counts differ: ledger {dict(rows)} vs cascade {_tiers_of(result)}")
    dup = one(
        "SELECT count(*) FROM (SELECT row_key FROM match_stage WHERE protocol_id=? GROUP BY 1 HAVING count(*)>1)", proto
    )
    if dup:
        bad.append(f"{dup} duplicate row keys")
    return bad


def _tiers_of(result: CascadeResult) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in result.traces.values():
        out[t.tier] = out.get(t.tier, 0) + 1
    return out

"""``ledger_agg``: the only thing that leaves the machine that holds a real ledger.

Counts per (protocol, criterion, stage, verdict, reason code, unknown kind), per (family, reason code), latency
quantiles, the data-gap matrix. Every count below ``MIN_CELL`` is suppressed; no patient id, quote, date or value is
written. The writer refuses (raises ``Refused``) rather than cleans: a value that is not a closed identifier, a
patient id, a day-level date, or an unsuppressed small count stops the export.

The product's counts-file writer (R1-1) is not built yet; these are the same three refusals (identifier, quote,
day-level date) plus the small-cell rule, kept here so the ledger can be exported before it exists.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from tb_common.reasons import CODES

from bench.invest.ledger import STAGES_MATCH, VERDICTS

MIN_CELL = 10
UNKNOWN_KINDS = frozenset({"data_gap", "uncertain", "pending_human"})
TIERS = frozenset({"strong", "potential:data_gap", "potential:uncertain", "watchlist", "excluded", "out_of_scope"})
REASONS = frozenset(CODES) | TIERS | {"not_evaluated", "out_of_scope"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}")
_DATE = re.compile(
    r"\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}"  # 2026-03-14, 2026/3/14
    r"|\b(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b"  # 20260314
    r"|\d{1,4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"  # 2026年3月14日
)
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_DIMS = ("protocol_id", "criterion_id", "stage", "verdict", "reason_code", "unknown_kind", "family")


class Refused(ValueError):
    """The export holds something that must not leave: nothing was written."""


def _suppress(n: int) -> int | None:
    return None if n < MIN_CELL else n


def ledger_agg(con: Any) -> dict[str, list[dict[str, Any]]]:
    """The aggregates of a ``ledger.connect`` handle, small cells already suppressed (``None``)."""
    q = con.execute
    stage_verdict = q(
        "SELECT protocol_id, criterion_id, stage, verdict, reason_code, unknown_kind, count(*) AS n "
        "FROM match_stage WHERE criterion_id <> '' GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    family_reason = q(
        "SELECT coalesce(split_part(card_id, '.', 1), 'uncarded') AS family, reason_code, count(*) AS n "
        "FROM match_stage WHERE criterion_id <> '' GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    gap = q(
        "SELECT protocol_id, reason_code, count(*) AS n FROM match_stage "
        "WHERE unknown_kind = 'data_gap' GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    lat = q(
        "SELECT s.protocol_id, s.stage, count(*) AS n, "
        "round(quantile_cont(t.ms_wall, 0.5)) AS p50, round(quantile_cont(t.ms_wall, 0.9)) AS p90, "
        "round(quantile_cont(t.ms_wall, 0.99)) AS p99 "
        "FROM match_stage s JOIN match_timing t USING (row_key) WHERE t.ms_wall IS NOT NULL GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {
        "stage_verdict": [
            dict(
                zip(
                    ("protocol_id", "criterion_id", "stage", "verdict", "reason_code", "unknown_kind"),
                    r[:6],
                    strict=True,
                )
            )
            | {"n": _suppress(r[6])}
            for r in stage_verdict
        ],
        "family_reason": [{"family": r[0], "reason_code": r[1], "n": _suppress(r[2])} for r in family_reason],
        "data_gap": [{"protocol_id": r[0], "reason_code": r[1], "n": _suppress(r[2])} for r in gap],
        "latency_ms": [
            {"protocol_id": r[0], "stage": r[1], "n": _suppress(r[2])}
            | ({"p50": r[3], "p90": r[4], "p99": r[5]} if r[2] >= MIN_CELL else {})
            for r in lat
        ],
    }
    return out


def pids_of(con: Any) -> set[str]:
    return {r[0] for r in con.execute("SELECT DISTINCT pid FROM match_stage WHERE pid IS NOT NULL").fetchall()}


def refuse(agg: Mapping[str, Sequence[Mapping[str, Any]]], pids: Collection[str], known_ids: Collection[str]) -> None:
    """Raise ``Refused`` when ``agg`` is not a closed-form count table. ``known_ids``: the protocol, criterion and
    card ids of the rulesets (the only free identifiers allowed)."""
    known = set(known_ids)
    pidset = set(pids)
    for table, rows in agg.items():
        for row in rows:
            for key, val in row.items():
                where = f"{table}.{key}"
                if key in ("n", "p50", "p90", "p99"):
                    _check_number(where, key, val)
                elif key in _DIMS:
                    _check_dim(where, key, val, known)
                else:
                    raise Refused(f"{where}: unknown column")
                for s in _strings(val):
                    _check_free(where, s, pidset)
    text = json.dumps(agg, ensure_ascii=False)
    if _DATE.search(text):
        raise Refused("a day-level date is in the export")


def _strings(val: Any) -> list[str]:
    return [val] if isinstance(val, str) else []


def _check_number(where: str, key: str, val: Any) -> None:
    if val is None:
        return
    if isinstance(val, bool) or not isinstance(val, int | float):
        raise Refused(f"{where}: not a number")
    if key == "n" and 0 < val < MIN_CELL:
        raise Refused(f"{where}: count {val} below {MIN_CELL} not suppressed")


def _check_dim(where: str, key: str, val: Any, known: set[str]) -> None:
    if val is None:
        return
    if not isinstance(val, str) or not _ID.fullmatch(val):
        raise Refused(f"{where}: not a closed identifier (a quote, a name or free text)")
    closed = {
        "stage": set(STAGES_MATCH),
        "verdict": set(VERDICTS),
        "reason_code": set(REASONS),
        "unknown_kind": set(UNKNOWN_KINDS),
    }
    if key in closed and val not in closed[key]:
        raise Refused(f"{where}: {val!r} is not in the closed list")
    if key in ("protocol_id", "criterion_id", "family") and val not in known and val != "uncarded":
        raise Refused(f"{where}: {val!r} is not an id of the rulesets")


def _check_free(where: str, s: str, pids: set[str]) -> None:
    """A patient id, whole or embedded between separators (``GZQO-p-0123``), is a leak."""
    spans = [m.span() for m in _TOKEN.finditer(s)]
    for i, (start, _) in enumerate(spans):
        for _, end in spans[i:]:
            if s[start:end] in pids:
                raise Refused(f"{where}: a patient id")


def write_agg(
    path: Path, agg: Mapping[str, Sequence[Mapping[str, Any]]], pids: Collection[str], known_ids: Collection[str]
) -> Path:
    """Refuse first, then write ``agg`` as JSON; nothing is written when a check fails."""
    refuse(agg, pids, known_ids)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agg, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path

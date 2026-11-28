"""``trial_stage`` adapter: the stage records the trial-side tools already write (lines, atoms, templates, card
proposals, compile and equivalence results; public registry text, no patients) into ledger rows.

The tools live outside the product tree (the corpus split and atoms, the template clustering, the card-proposal run).
This module reads their JSONL records and does not import them: a record is a mapping, and the mapper for each stage
names the keys it reads. A line is keyed ``nct:line``; the same line at two stages is two rows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from bench.invest.ledger import STAGES_TRIAL, LedgerWriter, canonical_json, content_hash, sha_of_text

STATUSES = ("ok", "CompileError", "uncompiled_construct", "no_card")
PARTITION = "trial"


def line_id(rec: Mapping[str, Any]) -> str:
    return f"{rec['nct']}:{rec.get('line', rec.get('i'))}"


def _split(rec: Mapping[str, Any]) -> dict[str, Any]:
    return {"output": {"side": rec.get("side")}, "status": "ok"}


def _atoms(rec: Mapping[str, Any]) -> dict[str, Any]:
    atoms = rec.get("atoms", rec.get("v2"))
    return {"output": atoms, "model_raw": {"model": rec["model"]} if rec.get("model") else None, "status": "ok"}


def _template(rec: Mapping[str, Any]) -> dict[str, Any]:
    return {"output": {"tid": rec.get("tid"), "fam": rec.get("fam")}, "status": "ok" if rec.get("tid") else "no_card"}


def _proposal(rec: Mapping[str, Any]) -> dict[str, Any]:
    p = rec.get("proposal") or {}
    return {"output": p, "status": "ok" if p.get("cards") else "no_card"}


def _compiled(rec: Mapping[str, Any]) -> dict[str, Any]:
    status = str(rec.get("status", "ok"))
    if status not in STATUSES:
        raise ValueError(f"trial_stage status {status!r} not in {STATUSES}")
    out = {k: rec[k] for k in ("sql_sha", "cql_sha", "pct", "ir_sha") if k in rec}
    return {"output": out, "status": status, "reason": rec.get("reason_code")}


MAPPERS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "region": _split,
    "split": _split,
    "atoms": _atoms,
    "template": _template,
    "card_proposal": _proposal,
    "instantiate": _compiled,
    "compile_sql": _compiled,
    "compile_cql": _compiled,
    "equivalence": _compiled,
}


def add_records(
    w: LedgerWriter,
    stage: str,
    records: Iterable[Mapping[str, Any]],
    *,
    source: str = "registry",
    gold: Mapping[str, Any] | None = None,
) -> int:
    """Write one ``trial_stage`` row per record of ``stage``; return how many. ``gold``: ``line_id`` -> label."""
    if stage not in STAGES_TRIAL:
        raise ValueError(f"unknown trial stage {stage!r}")
    n = 0
    for rec in records:
        lid = line_id(rec)
        text_sha = sha_of_text(str(rec["text"])) if rec.get("text") is not None else None
        m = MAPPERS[stage](rec)
        w.add(
            "trial_stage",
            PARTITION,
            {
                "nct": rec["nct"],
                "source": source,
                "section_region": rec.get("region") or rec.get("sec"),
                "line_id": lid,
                "line_text_sha": text_sha,
                "stage": stage,
                "inputs_hash": content_hash(source, lid, text_sha, stage),
                "output_json": m["output"],
                "model_raw_json": m.get("model_raw"),
                "status": m["status"],
                "reason_code": m.get("reason"),
                "ms": rec.get("ms"),
                "gold": canonical_json(gold[lid]) if gold and lid in gold else None,
            },
        )
        n += 1
    return n

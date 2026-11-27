"""Blast radius of a shared rule (RULEQ-1 §4): who depends on a card version, what a card change moves, where a verdict
came from.

* :func:`impact_index`: ``card_id@version`` -> the rulesets and criteria whose IR carries that ``card_ref`` (one scan).
* :func:`canary`: the per-patient, per-criterion diff between two rulesets' SQL on one lake; ``moved`` empty means the
  change is invisible there.
* :func:`provenance`: ruleset -> criterion -> card_ref -> library record, as stored ids.

A ruleset pins its criteria's ``card_ref``; the SQL is compiled from the criterion, so a card re-version or rollback
moves a ruleset only when its criterion is re-compiled and re-approved.

    python -m tools.blast_radius impact [--rulesets rulesets] [--card id@version]
    python -m tools.blast_radius provenance RULESET CRITERION [--rulesets rulesets]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from tb_common.ruleset import Ruleset
from tb_contracts.criterion_ir import CriterionIRv3, canonical_hash, upgrade_v1
from tb_contracts.generated.models import CriterionIR

ROOT = Path(__file__).resolve().parents[1]

Runner = Callable[[str, str], list[dict[str, Any]]]
"""``runner(sql, index_date)`` -> rows ``{"pid": ..., "C_<criterion>": verdict, ...}`` (a lake, or a fake in a test)."""


def impact_index(rulesets_dir: Path = ROOT / "rulesets") -> dict[str, list[dict[str, Any]]]:
    """``card_id@version`` -> dependents ``{ruleset, version, protocol_version, criterion, params}``."""
    manifests: dict[str, dict[str, Any]] = {}
    out: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(rulesets_dir.glob("*/ir/*.json")):
        crit = json.loads(path.read_text(encoding="utf-8"))
        ref = crit.get("card_ref")
        if not ref:
            continue
        rid = path.parent.parent.name
        if rid not in manifests:
            manifests[rid] = yaml.safe_load((rulesets_dir / rid / "manifest.yaml").read_text(encoding="utf-8"))
        m = manifests[rid]
        out.setdefault(f"{ref['card_id']}@{ref['card_version']}", []).append(
            {
                "ruleset": rid,
                "version": m["version"],
                "protocol_version": m.get("protocol_version"),
                "criterion": crit["id"],
                "params": ref.get("params", {}),
            }
        )
    return out


def reconfirm_rows(index: dict[str, list[dict[str, Any]]], card_id: str, version: str) -> list[dict[str, Any]]:
    """The PI "re-confirm" rows a defect or rollback of ``card_id@version`` opens: its dependents, nothing else."""
    return index.get(f"{card_id}@{version}", [])


def lake_runner(lake_dir: Path) -> Runner:
    """A :data:`Runner` over a lake (the synthetic 50k, the twin): the ruleset SQL with ``[[index_date], None]``."""
    from lake.store import Lake

    lake = Lake(lake_dir)
    return lambda sql, index_date: lake.query(sql, [[index_date], None]).to_pylist()


def _verdicts(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["pid"] in out:
            raise ValueError("two result rows for patient " + str(r["pid"]))
        out[r["pid"]] = {k[2:]: v for k, v in r.items() if k.startswith("C_")}
    return out


def canary(old: Ruleset, new: Ruleset, runner: Runner, index_date: str) -> dict[str, Any]:
    """Run both rulesets' SQL through ``runner`` and diff per patient and criterion.

    ``moved``: ``[{"pid", "criterion", "old", "new"}]`` for every shared criterion whose verdict differs (a patient
    missing on one side has a ``None`` verdict there); ``only_old`` / ``only_new``: criteria on one side only."""
    a, b = _verdicts(runner(old.sql, index_date)), _verdicts(runner(new.sql, index_date))
    old_ids = {c.id for c in old.criteria}  # the rulesets' own criteria, so an empty result cannot hide one
    new_ids = {c.id for c in new.criteria}
    moved = [
        {"pid": pid, "criterion": cid, "old": a.get(pid, {}).get(cid), "new": b.get(pid, {}).get(cid)}
        for pid in sorted(a.keys() | b.keys())
        for cid in sorted(old_ids & new_ids)
        if a.get(pid, {}).get(cid) != b.get(pid, {}).get(cid)
    ]
    return {
        "patients": len(a.keys() | b.keys()),
        "moved": moved,
        "only_old": sorted(old_ids - new_ids),
        "only_new": sorted(new_ids - old_ids),
    }


def provenance(rulesets_dir: Path, ruleset_id: str, criterion_id: str, library: Any | None = None) -> dict[str, Any]:
    """The stored-id chain of one criterion: manifest -> criterion (hash, source_ref) -> card_ref -> library record.

    ``library``: anything with ``by_hash(hash)`` (a ``criteria_compiler.library.repository.CriterionLibrary``). The
    chain stops where the repository stops: a card's ``sources`` (template ids) and the atoms behind them live on the
    bench, not here."""
    m = yaml.safe_load((rulesets_dir / ruleset_id / "manifest.yaml").read_text(encoding="utf-8"))
    raw = json.loads((rulesets_dir / ruleset_id / "ir" / f"{criterion_id}.json").read_text(encoding="utf-8"))
    ir = CriterionIRv3.model_validate(raw) if "atoms" in raw else upgrade_v1(CriterionIR.model_validate(raw))
    chash = canonical_hash(ir, None)
    out: dict[str, Any] = {
        "ruleset": {
            "id": m["id"],
            "version": m["version"],
            "protocol_version": m.get("protocol_version"),
            "source_documents": list(m.get("source_documents", [])),
        },
        "criterion": {"id": criterion_id, "canonical_hash": chash, "source_ref": raw.get("source_ref")},
        "card_ref": raw.get("card_ref"),
        "library": None,
    }
    rec = library.by_hash(chash) if library is not None else None
    if rec is not None:
        out["library"] = {"lib_id": rec.lib_id, "status": rec.status, "supersedes": rec.supersedes}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.blast_radius", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("impact", help="card@version -> dependent rulesets and criteria")
    pi.add_argument("--rulesets", type=Path, default=ROOT / "rulesets")
    pi.add_argument("--card", help="one card_id@version")
    pp = sub.add_parser("provenance", help="the id chain of one criterion")
    pp.add_argument("ruleset")
    pp.add_argument("criterion")
    pp.add_argument("--rulesets", type=Path, default=ROOT / "rulesets")
    args = ap.parse_args(argv)
    if args.cmd == "impact":
        idx = impact_index(args.rulesets)
        print(json.dumps({args.card: idx.get(args.card, [])} if args.card else idx, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(provenance(args.rulesets, args.ruleset, args.criterion), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

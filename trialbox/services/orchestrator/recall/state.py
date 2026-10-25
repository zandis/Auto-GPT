"""Canonical, resumable ``ConfidenceSequence`` state (spec v4 §6.7, App. F.2; S1-12).

The state is the log-capital and rejection flag of every grid point, ``n``, ``total``, ``sq_dev`` and ``upper``,
plus α and a fingerprint of the grid. It is serialised as canonical JSON (sorted keys, no whitespace, shortest
round-trip floats), so ``dumps(loads(s)) == s`` byte for byte and a resumed sequence continues exactly as an
uninterrupted one would.
"""

from __future__ import annotations

import json
from typing import Any

from tb_common.recall import GRID, GRID_POINTS, ConfidenceSequence

from orchestrator.db_pg import canonical_json, sha256_text

STATE_VERSION = 1
GRID_SHA = sha256_text(canonical_json(list(GRID_POINTS)))


class StateError(ValueError):
    pass


def to_state(cs: ConfidenceSequence) -> dict[str, Any]:
    return {
        "v": STATE_VERSION,
        "grid_sha": GRID_SHA,
        "alpha": float(cs.alpha),
        "n": int(cs.n),
        "total": float(cs.total),
        "sq_dev": float(cs.sq_dev),
        "upper": float(cs.upper),
        "log_capital": [float(v) for v in cs.log_capital],
        "rejected": "".join("1" if r else "0" for r in cs.rejected),
    }


def dumps(cs: ConfidenceSequence) -> str:
    return canonical_json(to_state(cs))


def from_state(state: dict[str, Any]) -> ConfidenceSequence:
    if state.get("v") != STATE_VERSION:
        raise StateError(f"unknown state version {state.get('v')!r}")
    if state.get("grid_sha") != GRID_SHA:
        raise StateError("state was written on a different grid")
    log_capital = [float(v) for v in state["log_capital"]]
    rejected_s = str(state["rejected"])
    if len(log_capital) != GRID or len(rejected_s) != GRID or set(rejected_s) - {"0", "1"}:
        raise StateError("state does not match the grid size")
    return ConfidenceSequence(
        alpha=float(state["alpha"]),
        log_capital=log_capital,
        rejected=[c == "1" for c in rejected_s],
        n=int(state["n"]),
        total=float(state["total"]),
        sq_dev=float(state["sq_dev"]),
        upper=float(state["upper"]),
    )


def loads(text: str) -> ConfidenceSequence:
    return from_state(json.loads(text))


__all__ = ["GRID_SHA", "STATE_VERSION", "StateError", "dumps", "from_state", "loads", "to_state"]

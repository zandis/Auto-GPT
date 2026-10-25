"""NCBI prompt drift check: regenerate or verify ``prompts.py`` from ``ncbi_upstream/`` (verbatim function extraction).

python -m matching.registry_match.sync_prompts [--check]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
UPSTREAM = PACKAGE / "ncbi_upstream"
TARGET = PACKAGE / "prompts.py"
SOURCES = [
    ("trialgpt_retrieval/keyword_generation.py", ["get_keyword_generation_messages"]),
    ("trialgpt_matching/TrialGPT.py", ["parse_criteria", "print_trial", "get_matching_prompt"]),
    ("trialgpt_ranking/TrialGPT.py", ["convert_criteria_pred_to_string", "convert_pred_to_prompt"]),
    ("trialgpt_ranking/rank_results.py", ["get_matching_score", "get_agg_score"]),
]
HEADER = '''"""NCBI TrialGPT prompt builders and scoring, extracted VERBATIM from ``ncbi_upstream/`` (tabs and all) by
``sync_prompts.py``. Do not edit by hand: the prompts must stay NCBI's for the benchmark to mean anything.
``tests/unit/test_registry_match_core.py`` checks this file against the upstream sources."""

# ruff: noqa
# mypy: ignore-errors
# fmt: off

eps = 1e-9


'''


def upstream_source(rel: str) -> str:
    """Text of one upstream file (stored with a ``.txt`` suffix so that it is never imported)."""
    return (UPSTREAM / f"{rel}.txt").read_text(encoding="utf-8")


def render() -> str:
    parts = []
    for rel, names in SOURCES:
        src = upstream_source(rel)
        found = {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
        parts += [str(found[n]) for n in names]
    return HEADER + "\n\n\n".join(parts) + "\n"


def in_sync() -> bool:
    return TARGET.read_text(encoding="utf-8") == render()


def main(argv: list[str]) -> int:
    if "--check" in argv:
        ok = in_sync()
        print("prompts.py is in sync" if ok else "prompts.py differs from the NCBI upstream sources")
        return 0 if ok else 1
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

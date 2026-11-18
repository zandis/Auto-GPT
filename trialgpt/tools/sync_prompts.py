"""Regenerate trialgpt_local/prompts.py from vendor/ncbi_trialgpt (verbatim function extraction).

python tools/sync_prompts.py [--check]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "vendor" / "ncbi_trialgpt"
SOURCES = [
    ("trialgpt_retrieval/keyword_generation.py", ["get_keyword_generation_messages"]),
    ("trialgpt_matching/TrialGPT.py", ["parse_criteria", "print_trial", "get_matching_prompt"]),
    ("trialgpt_ranking/TrialGPT.py", ["convert_criteria_pred_to_string", "convert_pred_to_prompt"]),
    ("trialgpt_ranking/rank_results.py", ["get_matching_score", "get_agg_score"]),
]
HEADER = '''"""NCBI TrialGPT prompt builders and scoring, extracted VERBATIM from ``vendor/ncbi_trialgpt``
(tabs and all) by ``tools/sync_prompts.py``. Do not edit by hand: the local-LLM comparison is only meaningful with
the same prompts. ``tests/test_core.py`` checks this file against the vendored sources."""

# ruff: noqa
# mypy: ignore-errors
# fmt: off

eps = 1e-9


'''


def render() -> str:
    parts = []
    for rel, names in SOURCES:
        src = (V / rel).read_text(encoding="utf-8")
        found = {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
        parts += [str(found[n]) for n in names]
    return HEADER + "\n\n\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    target = ROOT / "trialgpt_local" / "prompts.py"
    text = render()
    if "--check" in argv:
        ok = target.read_text(encoding="utf-8") == text
        print("prompts.py is in sync" if ok else "prompts.py differs from the vendored sources")
        return 0 if ok else 1
    target.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

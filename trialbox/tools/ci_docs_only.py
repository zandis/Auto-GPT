"""Is a pull request docs-only, and which tests read the documents it changes (CI-DOCS, D-969).

    git diff --name-only BASE HEAD | python3 trialbox/tools/ci_docs_only.py docs-only   # prints true or false
    git diff --name-only BASE HEAD | python3 trialbox/tools/ci_docs_only.py tests       # test files, one line

The `changes` job of ``.github/workflows/trialbox-ci.yml`` runs it with the runner's python3 (standard library only)
on the paths of the repository root. A card's pull request whose every changed file is a document runs the fast tier;
the tests that read those documents run in the `cross-card` job; a merge train (``train/*``) and master run
everything, so nothing reaches master untested.

A document is a file under ``trialbox/docs/`` or any ``.md`` file, except the documents code reads (``CODE_READS``:
the licence register, which the licence check reads and the image carries; the model change protocol, which the
image carries for ``qualify``; the prompts of ``libs/tb_llm/prompts/`` and the cards of ``models/``, H-110).
A test reads a document when its text names the document's path below ``trialbox/``, its file name, or its folder
(``docs/runbook``; not ``docs`` alone, which every document test names). The folder is
named by the folder itself (``"docs/runbook"``, ``"docs/runbook/*.md"``, ``f"docs/runbook/{page}"``), not by the path
of another document in it (H-81): ``docs/reviews/2026-11-12-architecture/decision.md`` in a property test's docstring
does not make it a test of every page under ``docs/reviews/``, and the `cross-card` job has no fonts or JVM to run it.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: documents that code reads (a check, or an image that carries it): their change runs the full tier
CODE_READS = (
    "trialbox/docs/licences/",
    "trialbox/docs/validation/model-change-protocol.md",
    # H-110 (L-CI-1): the prompts the model is given at run time, and the model cards (models/ is on
    # the full tier): a change to what the models are told is never a document-only change
    "trialbox/libs/tb_llm/prompts/",
    "trialbox/models/",
)


def docs_only(paths: Iterable[str]) -> bool:
    files = [p for p in paths if p]
    return bool(files) and all(
        (p.startswith("trialbox/docs/") or p.endswith(".md")) and not p.startswith(CODE_READS) for p in files
    )


def _needles(path: str) -> tuple[set[str], set[str]]:
    """The path and the file name, and the folder (matched as a folder: not followed by a name in it)."""
    rel = path.removeprefix("trialbox/")
    folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
    return {rel, rel.rsplit("/", 1)[-1]}, ({folder} if folder and folder != "docs" else set())


def _names(text: str, names: set[str], folders: set[str]) -> bool:
    """The text names a document, or a folder not followed by the name of something in it."""
    return any(n in text for n in names) or any(re.search(re.escape(f) + r"(?!/[\w.-])", text) for f in folders)


def tests_for(paths: Iterable[str], root: Path = ROOT) -> list[str]:
    """The test files under ``root/tests`` whose text names one of the changed documents, relative to ``root``."""
    names: set[str] = set()
    folders: set[str] = set()
    for p in paths or ():
        if p:
            more_names, more_folders = _needles(p)
            names |= more_names
            folders |= more_folders
    if not names:
        return []
    found = []
    for f in sorted((root / "tests").rglob("test_*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if _names(text, names, folders):
            found.append(f.relative_to(root).as_posix())
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("docs-only", "tests"):
        print("usage: ci_docs_only.py docs-only|tests < changed paths", file=sys.stderr)
        return 2
    paths = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    if argv[0] == "docs-only":
        print("true" if docs_only(paths) else "false")
    else:
        print(" ".join(tests_for(paths)) if docs_only(paths) else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Is a pull request docs-only, and which tests read the documents it changes (CI-DOCS, D-969).

    git diff --name-only BASE HEAD | python3 trialbox/tools/ci_docs_only.py docs-only   # prints true or false
    git diff --name-only BASE HEAD | python3 trialbox/tools/ci_docs_only.py tests       # test files, one line

The `changes` job of ``.github/workflows/trialbox-ci.yml`` runs it with the runner's python3 (standard library only)
on the paths of the repository root. A card's pull request whose every changed file is a document runs the fast tier;
the tests that read those documents run in the `cross-card` job; a merge train (``train/*``) and master run
everything, so nothing reaches master untested.

A document is a file under ``trialbox/docs/`` or any ``.md`` file, except the documents code reads (``CODE_READS``:
the licence register, which the licence check reads and the image carries, and the model change protocol, which the
image carries for ``qualify``). A test reads a document when its text names the document's path below ``trialbox/``,
its file name, or its folder (``docs/runbook``; not ``docs`` alone, which every document test names).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: documents that code reads (a check, or an image that carries it): their change runs the full tier
CODE_READS = ("trialbox/docs/licences/", "trialbox/docs/validation/model-change-protocol.md")


def docs_only(paths: Iterable[str]) -> bool:
    files = [p for p in paths if p]
    return bool(files) and all(
        (p.startswith("trialbox/docs/") or p.endswith(".md")) and not p.startswith(CODE_READS) for p in files
    )


def _needles(path: str) -> set[str]:
    rel = path.removeprefix("trialbox/")
    out = {rel, rel.rsplit("/", 1)[-1]}
    folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
    if folder and folder != "docs":
        out.add(folder)
    return out


def tests_for(paths: Iterable[str], root: Path = ROOT) -> list[str]:
    """The test files under ``root/tests`` whose text names one of the changed documents, relative to ``root``."""
    needles = set().union(*(_needles(p) for p in paths if p)) if paths else set()
    if not needles:
        return []
    found = []
    for f in sorted((root / "tests").rglob("test_*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if any(n in text for n in needles):
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

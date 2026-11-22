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
its file name, or its folder (``docs/runbook``; not ``docs`` alone, which every document test names). The folder is
named by the folder itself (``"docs/runbook"``, ``"docs/runbook/*.md"``, ``f"docs/runbook/{page}"``), not by the path
of another document in it (H-81): ``docs/reviews/2026-11-12-architecture/decision.md`` in a property test's docstring
does not make it a test of every page under ``docs/reviews/``, and the `cross-card` job has no fonts or JVM to run it.
Only the strings of a test's code count (H-87): each test file is parsed with ``ast``, and the needles are matched
against its string constants (an f-string's literal parts included) that are not docstrings (of the module, a class or
a function); a comment is not code either. A test whose docstring cites a page does not read it; one whose code names
it does. A file that does not parse is matched on its whole text: it is never left out unread.
"""

from __future__ import annotations

import ast
import re
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


def _needles(path: str) -> tuple[set[str], set[str]]:
    """The path and the file name, and the folder (matched as a folder: not followed by a name in it)."""
    rel = path.removeprefix("trialbox/")
    folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
    return {rel, rel.rsplit("/", 1)[-1]}, ({folder} if folder and folder != "docs" else set())


def _names(text: str, names: set[str], folders: set[str]) -> bool:
    """The text names a document, or a folder not followed by the name of something in it."""
    return any(n in text for n in names) or any(re.search(re.escape(f) + r"(?!/[\w.-])", text) for f in folders)


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of the docstring nodes: the first statement of the module, a class or a function, when a string."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                out.add(id(first.value))
    return out


def code_strings(text: str) -> str:
    """The string constants of a test's code, one per line, without its docstrings and comments; the whole text when
    it does not parse (a file never drops out of the selection because it cannot be read as code)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    skip = _docstrings(tree)
    return "\n".join(
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
    )


def tests_for(paths: Iterable[str], root: Path = ROOT) -> list[str]:
    """The test files under ``root/tests`` whose code names one of the changed documents, relative to ``root``."""
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
        text = code_strings(f.read_text(encoding="utf-8", errors="replace"))
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

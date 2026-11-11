"""T-650c: the committed ``rulesets/`` folder is read-only for the tests.

The criteria-compiler's ruleset repository re-materialises a ruleset in place (``.<id>.tmp`` then rmtree + rename).
Pointed at the committed folder, it broke a parallel test that was copying the folder (``.RA-BIO.tmp`` vanished in the
middle of ``copytree``). Every test that needs rulesets it can write copies them with :func:`copy_rulesets`, and
``tests/conftest.py`` fails any test after which the folder is not as it was (:func:`snapshot`).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

RULESETS = Path(__file__).resolve().parents[1] / "rulesets"

# left-overs of an interrupted write: never part of a ruleset, never copied
STRAY = (".*", "*.tmp", "__pycache__")

Entry = tuple[str, int, int, int]


def copy_rulesets(dst: Path, *skip: str, src: Path = RULESETS) -> Path:
    """Copy ``src`` (default: the committed rulesets) to ``dst``, without the names in ``skip`` and without stray
    temporary files."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*STRAY, *skip))
    return dst


def snapshot(root: Path = RULESETS) -> frozenset[Entry]:
    """Every file and folder under ``root`` with its inode, size and modification time: a rewrite with the same
    bytes, or a folder re-made by rename, still shows."""
    out: set[Entry] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            p = os.path.join(dirpath, name)
            try:
                st = os.lstat(p)
            except FileNotFoundError:  # removed while we looked: that is a change too
                out.add((os.path.relpath(p, root), -1, -1, -1))
                continue
            size = st.st_size if not os.path.isdir(p) else 0
            out.add((os.path.relpath(p, root), st.st_ino, size, st.st_mtime_ns))
    return frozenset(out)


def describe(before: frozenset[Entry], after: frozenset[Entry]) -> str:
    """The paths added, removed or changed between two snapshots, for the failure message."""
    old = {e[0]: e for e in before}
    new = {e[0]: e for e in after}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    parts = [f"{label}: {', '.join(paths[:10])}" for label, paths in
             (("added", added), ("removed", removed), ("changed", changed)) if paths]  # fmt: skip
    return "; ".join(parts) or "no difference"

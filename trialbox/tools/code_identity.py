"""The code a record names: a git commit, or the signed release tree of an installed box (QUALIFY-BOX, D-734).

A checkout is named by ``git rev-parse HEAD`` and is dirty when ``git status`` lists a tracked change, as before. A
box installed from a signed bundle has no git: its release folder (``/opt/trialbox/releases/<bundle id>``, D-367)
carries ``HOST-SHA256SUMS``, the sha256 of every file of the release, signed with the bundle. Its own sha256 names
exactly that code (``release:<sha256>``); the tree is dirty when a file differs from the sums, is missing, or was
added (``tools.host_tree.check_dir``). Neither: ``unknown`` and dirty. Standard library only."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

SUMS = "HOST-SHA256SUMS"


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return p.returncode, p.stdout.strip()


def head(root: Path) -> tuple[str, bool]:
    """``(name, dirty)`` of the code at ``root``: a commit, ``release:<sha256>``, or ``("unknown", True)``."""
    rc, sha = _git(root, "rev-parse", "HEAD")
    if rc == 0 and sha:
        rc2, changes = _git(root, "status", "--porcelain", "--untracked-files=no")
        return sha, rc2 != 0 or bool(changes)
    # D-881: in the trialbox-py image /app is neither: the box wrapper mounts the release tree (TB_RELEASE_TREE) and
    # passes the image's id (TB_CODE_IMAGE), which names the code when there is no tree (lane G's direct route)
    for tree in (root, Path(os.environ.get("TB_RELEASE_TREE") or root)):
        sums = tree / SUMS
        if sums.is_file():
            from tools import host_tree

            return f"release:{hashlib.sha256(sums.read_bytes()).hexdigest()}", bool(host_tree.check_dir(tree))
    image = (os.environ.get("TB_CODE_IMAGE") or "").strip()
    if image:
        return f"image:{image}", False
    return "unknown", True

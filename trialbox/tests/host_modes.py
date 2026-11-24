"""H-115: the folders and files a fixture builds get a host's modes, whatever the umask of the account running the tests.

On the box, root makes the folders that the product checks, with umask 022. An ordinary user's umask is often 002
(on Ubuntu, a user whose group is its own), so a tree a test builds comes out writable by the group. The product's
checks then rightly refuse it ("another account owns or may write", "can be written by others"). A fixture that builds
a stand-in tree calls :func:`as_root_makes_it` on it once the tree is built. Group and others lose write, and nothing
else changes. Links, other accounts' entries and sticky folders are left as they are, and the product's checks are
unchanged. A test that wants an open folder makes it so after the fixture."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def _tighten(path: Path) -> None:
    st = os.lstat(path)
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISLNK(st.st_mode) or st.st_uid != os.geteuid() or mode & stat.S_ISVTX or not mode & 0o022:
        return
    os.chmod(path, mode & ~0o022)


def as_root_makes_it(*tops: Path) -> None:
    """Drop group and others' write from each of ``tops`` and from everything below it (links not followed)."""
    for top in tops:
        _tighten(top)
        if not top.is_dir() or top.is_symlink():
            continue
        for folder, dirs, files in os.walk(top):
            for name in (*dirs, *files):
                _tighten(Path(folder) / name)

"""10K-4 (D-1390): which host folders a box owner may name for the backups, the audit anchor and the logs.

An allow rule, not a deny list. A folder is accepted only when all of this holds:

* it is written as one plain full path: ``/`` then letters, digits, ``.``, ``_``, ``-`` and ``/``; no ``.``, ``..``
  or empty part; at most 255 characters; a trailing ``/`` dropped (``plain``);
* it is not ``/`` and does not overlap a system folder: it is not one of :data:`SYSTEM`, not inside one, and does
  not contain one (``/var`` contains ``/var/lib``, so it is refused). The memory and kernel folders (``/proc``,
  ``/sys``, ``/dev``, ``/run``) and the folders every account may write (``/tmp``, ``/var/tmp``) are on the list;
  ``/mnt``, ``/media``, ``/srv`` and a folder of its own such as ``/data`` are not;
* the three folders the page asks are three separate folders: none equal to, inside or containing another
  (:func:`overlapping_pair`): the console reads the anchor folder, so it may hold neither backups nor logs, and the
  backup and log folders are pruned by different tools.

This module checks only the text, so the console's first-run page and the host's installer give the same answer.
What only the host can see (the real path, the file system, the disk, the install folder and the data folders of
``deploy/.env``) is ``tools/trialbox/finish_check.py``'s. Standard library only.
"""

from __future__ import annotations

import re

MAX = 255
_PLAIN = re.compile(r"^/[A-Za-z0-9._/-]*$")
#: the system folders a typed folder may not equal, be inside, or contain (named below "/")
_SYSTEM_NAMES = (
    "bin", "boot", "dev", "etc", "home", "opt", "proc", "root", "run", "sbin", "snap", "sys", "tmp", "usr",
    "var/lib", "var/run", "var/tmp",
)  # fmt: skip
SYSTEM = tuple(f"/{name}" for name in _SYSTEM_NAMES)


def plain(raw: object) -> str | None:
    """The folder as one plain full path, a trailing ``/`` dropped; empty: none given; None: not written so."""
    text = str(raw if raw is not None else "").strip()[: MAX + 1]
    if not text:
        return ""
    folder = text.rstrip("/")
    if len(text) > MAX or not _PLAIN.fullmatch(text) or not folder:
        return None
    if any(p in ("", ".", "..") for p in folder.split("/")[1:]):
        return None
    return folder


def overlaps(a: str, b: str) -> bool:
    """``a`` and ``b`` are one folder, or one is inside the other."""
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def system_folder(folder: str) -> str:
    """The system folder ``folder`` overlaps, or empty. Every top folder whose name starts with ``lib`` (``/lib``,
    ``/lib64``, ``/libx32`` ...) is one too."""
    top = folder.split("/")[1] if folder.count("/") >= 1 else ""
    if folder == "/" or top.startswith("lib"):
        return folder if folder == "/" else f"/{top}"
    return next((s for s in SYSTEM if overlaps(folder, s)), "")


def allowed(raw: object) -> str | None:
    """The folder when the text rule allows it; empty: none given; None: refused (not plain, or a system folder)."""
    folder = plain(raw)
    if not folder:
        return folder
    return None if system_folder(folder) else folder


def overlapping_pair(folders: dict[str, str]) -> tuple[str, str] | None:
    """The first two named folders (by key) that are one folder or one inside the other, or None."""
    named = [(k, v) for k, v in folders.items() if v]
    for i, (ka, a) in enumerate(named):
        for kb, b in named[i + 1 :]:
            if overlaps(a, b):
                return ka, kb
    return None

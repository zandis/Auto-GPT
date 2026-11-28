"""A file of secrets replaced whole, never rewritten in place (H-110: M-IB-2, ESC-5).

``deploy/.env`` holds every service password. A writer that truncates it and writes it again leaves it empty or cut
short when the power goes or the process is killed in between, and a file it makes is 0644 until a later chmod.
:func:`replace_private` writes a new file beside it, 0600 from its first byte (``O_EXCL``, a name of its own), puts
it on disk, makes it root's when it runs as root, and renames it over the old one: at every moment the
name holds the old file whole or the new one whole. Standard library only.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def replace_private(path: Path, text: str) -> None:
    """``path`` replaced by ``text``, 0600, by rename; root's when run as root. The old file stays on any failure."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if os.geteuid() == 0:  # OCR 1455-5: root's alone (M-LH-1), never the old file's owner handed on
            os.chown(tmp, 0, 0)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)

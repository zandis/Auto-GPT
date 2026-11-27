"""What one request leaves for the next, seen by every console worker process (P2-11, ASSESS-1-ADDENDUM D7).

The console runs ``TB_CONSOLE_WORKERS`` processes (sized from the site's declared concurrent users). Two things were
kept in one process's memory for the next request, which may now reach another process: the one-time password shown
once after a reset (D-133) and a pilot proposal awaiting its confirmation. They are kept here instead: one file per
key in a folder of the container's ``/tmp``, a tmpfs (memory, as before: never on disk, in a log, the audit trail or a
database; a restart forgets it), mode 0700 and 0600 to the console's user. A file's name is the SHA-256 of its key;
an entry older than its time to live is never returned, and is removed at the next keep or read, as the in-memory
store did. ``pop`` takes an entry once: the rename to a name of its own is atomic,
so two processes asked at the same moment cannot both read it. A value is JSON (a tuple comes back as a list).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any


class Held:
    def __init__(self, name: str, ttl: float, root: Path | None = None) -> None:
        self.folder = (root or Path(tempfile.gettempdir())) / f"tb-console-held-{os.getuid()}-{name}"
        self.ttl = ttl
        self.folder.mkdir(mode=0o700, exist_ok=True)
        st = self.folder.stat()  # a folder someone else made first is never used
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError(f"{self.folder}: not this user's own 0700 folder")

    def _path(self, key: str) -> Path:
        return self.folder / hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _sweep(self) -> None:
        now = time.time()
        for f in self.folder.iterdir():  # past the time to live: removed at the next keep or read
            try:
                if now - f.stat().st_mtime > self.ttl:
                    f.unlink()
            except FileNotFoundError:
                pass

    def put(self, key: str, value: Any) -> None:
        self._sweep()
        tmp = self.folder / f".{secrets.token_hex(8)}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        os.replace(tmp, self._path(key))

    def _read(self, path: Path) -> Any:
        try:
            if time.time() - path.stat().st_mtime > self.ttl:
                path.unlink(missing_ok=True)
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def get(self, key: str) -> Any:
        self._sweep()
        return self._read(self._path(key))

    def pop(self, key: str) -> Any:
        self._sweep()
        mine = self.folder / f".{secrets.token_hex(8)}"
        try:
            os.rename(self._path(key), mine)  # atomic: only one process takes it
        except FileNotFoundError:
            return None
        try:
            return self._read(mine)
        finally:
            mine.unlink(missing_ok=True)

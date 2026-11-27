"""What one request leaves for the next, seen by every console worker process (P2-11, ASSESS-1-ADDENDUM D7).

The console runs ``TB_CONSOLE_WORKERS`` processes (sized from the site's declared concurrent users). Two things were
kept in one process's memory for the next request, which may now reach another process: the one-time password shown
once after a reset (D-133) and a pilot proposal awaiting its confirmation. They are kept here instead: one file per
key in a folder of ``TB_CONSOLE_HELD_DIR`` (``/dev/shm``), which must be a memory filesystem (tmpfs or ramfs; any
other is refused at the start, as before: never on disk, in a log, the audit trail or a database; a restart forgets
it). The folder is this user's own, mode 0700, opened without following a symbolic link and checked as opened; every
file is reached through that open folder. A file's name is the SHA-256 of its key and it holds the value with the
monotonic time it was kept (one clock for every process on the host, not moved by setting the wall clock); an entry
older than its time to live, or dated ahead of that clock, is never returned and is removed at the next keep or read,
as the in-memory store did. Each keep, read and removal holds an ``flock`` on the folder, so a removal never takes an
entry another process put in its place, and ``pop`` takes an entry once. A value is JSON (a tuple comes back as a list).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import time
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

MOUNTINFO = Path("/proc/self/mountinfo")
MEMORY = ("tmpfs", "ramfs")


def fs_type(path: Path) -> str:
    """The filesystem type of the mount holding ``path`` (the longest mount point above it; the last one mounted)."""
    where, kind = "", ""
    for line in MOUNTINFO.read_text(encoding="utf-8").splitlines():
        left, _, right = line.partition(" - ")
        point = left.split()[4].replace("\\040", " ")
        if (str(path) == point or str(path).startswith(point.rstrip("/") + "/")) and len(point) >= len(where):
            where, kind = point, right.split()[0]
    return kind


class Held:
    def __init__(self, name: str, ttl: float, root: Path) -> None:
        self.folder = root / f"tb-console-held-{os.getuid()}-{name}"
        self.ttl = ttl
        kind = fs_type(root.resolve())
        if kind not in MEMORY:  # a credential is never written to a disk
            raise PermissionError(
                f"{root} is {kind or 'not a known mount'}, not memory: TB_CONSOLE_HELD_DIR names a tmpfs"
            )
        with contextlib.suppress(FileExistsError):
            os.mkdir(self.folder, 0o700)
        try:  # a link in its place (someone else's, made first) is never followed
            self._dir = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise PermissionError(f"{self.folder}: not this user's own 0700 folder ({exc.strerror})") from exc
        weakref.finalize(self, os.close, self._dir)
        st = os.fstat(self._dir)  # the folder opened is the one checked and the one used
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError(f"{self.folder}: not this user's own 0700 folder")

    def _name(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        # a fresh open each time: an flock excludes per open, so threads sharing one descriptor would not exclude
        fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=self._dir)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self, name: str) -> Any:
        """The entry's value, or None when it is missing or not live (then removed). Under the lock."""
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._dir)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, encoding="utf-8") as fh:
            try:
                entry = json.load(fh)
                live = 0 <= time.monotonic() - entry["issued"] <= self.ttl
            except (ValueError, KeyError, TypeError):
                live = False  # a file this class did not write is never returned
        if not live:
            os.unlink(name, dir_fd=self._dir)
            return None
        return entry["value"]

    def _sweep(self) -> None:
        for name in os.listdir(self._dir):  # past the time to live: removed at the next keep or read
            self._load(name)

    def put(self, key: str, value: Any) -> None:
        tmp = f".{secrets.token_hex(8)}"
        with self._locked():
            self._sweep()
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._dir)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"issued": time.monotonic(), "value": value}, fh)
            os.replace(tmp, self._name(key), src_dir_fd=self._dir, dst_dir_fd=self._dir)

    def get(self, key: str) -> Any:
        with self._locked():
            self._sweep()
            return self._load(self._name(key))

    def pop(self, key: str) -> Any:
        with self._locked():  # one process at a time: only one takes it
            self._sweep()
            value = self._load(self._name(key))
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self._name(key), dir_fd=self._dir)
            return value

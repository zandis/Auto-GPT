"""Git repository of rulesets (SPEC §2 ``rulesets/``, §4.3), implemented with dulwich object operations.

* ``main`` holds approved rulesets; drafts live on ``draft/<job_id>``; approvals are annotated tags
  ``<RULESET>/v<version>`` (DECISIONS D-08).
* The working directory of the repo is a *materialized* copy of approved rulesets (what services read at runtime);
  it is rewritten from ``main`` on approval, never edited in place.
"""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import logging
import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dulwich.index import commit_tree
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob, Commit, Tag, Tree
from dulwich.repo import Repo
from tb_common.ruleset import SEEDED_TAG

AUTHOR = b"TrialBox criteria-compiler <trialbox@localhost>"
FILE_MODE = 0o100644
_AT_FDCWD = -100
_RENAME_EXCHANGE = 2

log = logging.getLogger(__name__)


def _write_synced(path: Path, data: bytes) -> None:
    """Write ``path`` whole and fsync it. Its own write loop: ``os.write`` may write less than it is given."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _exchange(a: Path, b: Path) -> None:
    """Swap folders ``a`` and ``b`` in one rename (Linux ``renameat2`` RENAME_EXCHANGE). Where the kernel or the
    file system has no exchange the approval fails and the old copy stays whole: never a moment with no copy."""
    # ponytail: Linux only (the box runs in Linux containers); a pointer-file swap if another OS must write here
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(_AT_FDCWD, os.fsencode(a), _AT_FDCWD, os.fsencode(b), _RENAME_EXCHANGE) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(b))


class SwapUnsupported(RuntimeError):
    """INT-R3A: the rulesets folder's file system cannot exchange two folders in one rename, so an approval could
    not swap a ruleset's working copy whole (:meth:`RulesetRepo.check_swap`)."""


class RulesetRepo:
    def __init__(self, path: Path, seed: Path | None = None) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        if (path / ".git").exists():
            self.repo = Repo(str(path))
            self.refs: Any = self.repo.refs
            self._clean_left_overs()
        else:
            self.repo = Repo.init(str(path))
            self.refs = self.repo.refs
            files: dict[str, bytes] = {}
            if seed is not None and seed.exists():
                for f in sorted(seed.rglob("*")):
                    if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
                        files[f.relative_to(seed).as_posix()] = f.read_bytes()
            files.setdefault("README.md", b"# TrialBox rulesets (git; managed by criteria-compiler)\n")
            self._commit("refs/heads/main", None, files, "Initial rulesets", author=AUTHOR)
            self.refs.set_symbolic_ref(b"HEAD", b"refs/heads/main")
            self.materialize_all("main")
            self._tag_seeded(files)

    def _tag_seeded(self, files: dict[str, bytes]) -> None:
        """Vendor-shipped approved rulesets get their approval tag in the new repository."""
        import yaml

        for path, data in sorted(files.items()):
            parts = path.split("/")
            if len(parts) == 2 and parts[1] == "manifest.yaml":
                m = yaml.safe_load(data.decode("utf-8")) or {}
                if m.get("status") == "approved" and m.get("version"):
                    tag = f"{parts[0]}/v{m['version']}"
                    if f"refs/tags/{tag}".encode() not in self.refs:
                        self.tag(tag, "main", f"{tag} {SEEDED_TAG}")

    # ------------------------------------------------------------------ refs & reads
    def ref(self, name: str) -> bytes | None:
        for cand in (name, f"refs/heads/{name}", f"refs/tags/{name}"):
            key = cand.encode()
            if key in self.refs:
                sha = self.refs[key]
                obj = self.repo[sha]
                while isinstance(obj, Tag):
                    sha = obj.object[1]
                    obj = self.repo[sha]
                return bytes(sha)
        return None

    def _files(self, commit_sha: bytes | None) -> dict[str, bytes]:
        if commit_sha is None:
            return {}
        commit = self.repo[commit_sha]
        assert isinstance(commit, Commit)
        out = {}
        for entry in iter_tree_contents(self.repo.object_store, commit.tree):
            assert entry.path is not None and entry.sha is not None
            out[entry.path.decode()] = entry.sha
        return {p: self.repo[s].as_raw_string() for p, s in out.items()}

    def files(self, ref: str, prefix: str = "") -> dict[str, bytes]:
        sha = self.ref(ref)
        return {p: b for p, b in self._files(sha).items() if p.startswith(prefix)}

    def read(self, ref: str, path: str) -> bytes | None:
        return self.files(ref, path).get(path)

    def tags(self, prefix: str = "") -> list[str]:
        return sorted(
            k.decode()[len("refs/tags/") :]
            for k in self.refs.keys()  # noqa: SIM118 - dulwich RefsContainer
            if k.startswith(b"refs/tags/") and k.decode()[len("refs/tags/") :].startswith(prefix)
        )

    def branches(self) -> list[str]:
        keys = list(self.refs.keys())
        return sorted(k.decode()[len("refs/heads/") :] for k in keys if k.startswith(b"refs/heads/"))

    # ------------------------------------------------------------------ writes
    def _commit(
        self, ref: str, parent: bytes | None, files: dict[str, bytes], message: str, author: bytes = AUTHOR
    ) -> bytes:
        store = self.repo.object_store
        blobs = []
        for path, data in sorted(files.items()):
            blob = Blob.from_string(data)
            store.add_object(blob)
            blobs.append((path.encode(), blob.id, FILE_MODE))
        tree_id = commit_tree(store, blobs)
        if parent is not None:
            pc = self.repo[parent]
            assert isinstance(pc, Commit)
            if pc.tree == tree_id:
                return parent  # nothing changed
        c = Commit()
        c.tree = tree_id
        c.parents = [parent] if parent else []  # type: ignore[list-item]
        c.author = c.committer = author
        c.commit_time = c.author_time = int(time.time())
        c.commit_timezone = c.author_timezone = 8 * 3600
        c.encoding = b"UTF-8"
        c.message = message.encode("utf-8")
        store.add_object(c)
        self.refs[ref.encode()] = c.id
        return c.id

    def write_dir(
        self, branch: str, base: str, prefix: str, files: dict[str, bytes], message: str, author: str | None = None
    ) -> bytes:
        """Replace everything under ``prefix`` on ``branch`` (created from ``base`` if missing)."""
        parent = self.ref(branch) or self.ref(base)
        current = self._files(parent)
        merged = {p: b for p, b in current.items() if not p.startswith(prefix)}
        merged.update({f"{prefix}{p}": b for p, b in files.items()})
        who = f"{author} <{author}>".encode() if author else AUTHOR
        return self._commit(f"refs/heads/{branch}", parent, merged, message, who)

    def tag_message(self, name: str) -> str:
        """The message of annotated tag ``name``; "" for a bare tag, which names nobody."""
        obj = self.repo[self.refs[f"refs/tags/{name}".encode()]]
        return obj.message.decode("utf-8", "replace") if isinstance(obj, Tag) else ""

    def retag(self, name: str, message: str, tagger: str | None = None) -> bytes:
        """Write tag ``name`` again on the commit it names, with another message (D-640: an example ruleset the
        first start seeded, then installed or approved by somebody). The commit is never moved."""
        ref = f"refs/tags/{name}".encode()
        sha = self.ref(name)
        if sha is None or ref not in self.refs:
            raise KeyError(name)
        old = self.refs[ref]
        del self.refs[ref]
        try:
            return self._tag(name, sha, message, tagger)
        except Exception:
            self.refs[ref] = old
            raise

    def tag(self, name: str, ref: str, message: str, tagger: str | None = None) -> bytes:
        sha = self.ref(ref)
        if sha is None:
            raise KeyError(ref)
        key = f"refs/tags/{name}".encode()
        if key in self.refs:
            raise ValueError(f"tag {name} already exists")
        return self._tag(name, sha, message, tagger)

    def _tag(self, name: str, sha: bytes, message: str, tagger: str | None) -> bytes:
        key = f"refs/tags/{name}".encode()
        t = Tag()
        t.tagger = f"{tagger} <{tagger}>".encode() if tagger else AUTHOR
        t.message = message.encode("utf-8")
        t.name = name.encode()
        t.object = (Commit, sha)
        t.tag_time = int(time.time())
        t.tag_timezone = 8 * 3600
        self.repo.object_store.add_object(t)
        self.refs[key] = t.id
        return t.id

    def promote(self, ruleset: str, from_ref: str, message: str, author: str | None = None) -> bytes:
        """Copy ``<ruleset>/`` from ``from_ref`` onto ``main`` and refresh the materialized copy."""
        files = {p[len(ruleset) + 1 :]: b for p, b in self.files(from_ref, f"{ruleset}/").items()}
        sha = self.write_dir("main", "main", f"{ruleset}/", files, message, author)
        self.materialize(ruleset, "main")
        return sha

    def materialize(self, ruleset: str, ref: str = "main") -> None:
        """INT-R3A: the new copy is built whole beside the old one and fsynced, then the two folders are exchanged
        in one rename, so a reader finds the whole old copy or the whole new one, never none or a mix of files
        written in place. The old copy is removed after the swap; a kill leaves ``.<ruleset>.tmp``, removed at the
        next start (:meth:`_clean_left_overs`). One writer at a time (:meth:`_writing`)."""
        with self._writing():
            target = self.path / ruleset
            tmp = self.path / f".{ruleset}.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            files = self.files(ref, f"{ruleset}/")
            if not files:  # the ruleset is gone from ``ref``
                shutil.rmtree(target, ignore_errors=True)
                return
            for p, data in files.items():
                dest = tmp / p[len(ruleset) + 1 :]
                dest.parent.mkdir(parents=True, exist_ok=True)
                _write_synced(dest, data)
            for d in sorted((x for x in tmp.rglob("*") if x.is_dir()), key=lambda x: len(x.parts), reverse=True):
                _fsync_dir(d)
            _fsync_dir(tmp)
            if target.exists():
                _exchange(tmp, target)
                shutil.rmtree(tmp)
            else:
                os.rename(tmp, target)
            _fsync_dir(self.path)

    @contextlib.contextmanager
    def _writing(self, wait: bool = True) -> Iterator[None]:
        """The lock on the working copy's temporary folders: the compiler, an offline install, an update's restore
        and the doctor each open this repository. ``wait`` False: BlockingIOError when another holds it. A killed
        process's lock goes with it. On the ``.git`` folder itself: no lock file whose owner could shut another out."""
        fd = os.open(self.path / ".git", os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def check_swap(self) -> None:
        """INT-R3A (INTR3A-02): exchange two empty folders in the rulesets folder; :class:`SwapUnsupported` when its
        file system cannot. An approval asks before it writes its commit and tag, so a refusal changes nothing."""
        pair = (self.path / ".swap-a.tmp", self.path / ".swap-b.tmp")
        with self._writing():
            try:
                for p in pair:
                    shutil.rmtree(p, ignore_errors=True)
                    p.mkdir()
                _exchange(*pair)
            except OSError as exc:
                raise SwapUnsupported("the rulesets folder cannot swap two folders in one rename") from exc
            finally:
                for p in pair:
                    shutil.rmtree(p, ignore_errors=True)

    def _clean_left_overs(self) -> None:
        """A copy a kill left part way (``.<ruleset>.tmp``, built or swapped out): removed, and said. Never one a
        running writer holds (its lock), and a folder this process may not write is left and said."""
        left = sorted(p for p in self.path.glob(".*.tmp") if p.is_dir() and not p.is_symlink())
        if not left:
            return
        try:
            with self._writing(wait=False):
                for p in left:
                    log.warning("rulesets: removing %s, left by an interrupted materialisation", p.name)
                    shutil.rmtree(p, ignore_errors=True)
        except OSError as exc:  # another process is writing, or this one only reads
            log.warning("rulesets: %d temporary folder(s) left as they are (%s)", len(left), type(exc).__name__)

    def materialize_all(self, ref: str = "main") -> None:
        rulesets = {p.split("/", 1)[0] for p in self.files(ref) if "/" in p}
        for rs in sorted(rulesets):
            self.materialize(rs, ref)

    def tree_id(self, ref: str) -> str:
        sha = self.ref(ref)
        if sha is None:
            raise KeyError(ref)
        c = self.repo[sha]
        assert isinstance(c, Commit) and isinstance(self.repo[c.tree], Tree)
        return str(c.tree.decode())

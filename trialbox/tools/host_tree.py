"""The host tree in the signed release (T-631, D-367; review OPS-010).

The compose files, the host tools (``tools/``, ``libs/``, ``schemas/``) and the release's configuration (the Caddyfile,
``db-init``, ``egress.py``, ``network.sh``, the measured serving records, ``images.lock``) ride in the signed bundle as
one payload of kind ``host``: ``trialbox-host.tar``. Its first member is ``HOST-SHA256SUMS`` (the sha256 of every
other member); the tar itself is signed by its sha256 in the bundle manifest like every payload.

On the box (``BASE`` is the install folder, ``/opt/trialbox``)::

    BASE/releases/<bundle id>/   the host tree of that release, unpacked as signed
    BASE/current -> releases/<bundle id>
    BASE/tools, libs, schemas, ... -> current/...            (links, refreshed at every switch)
    BASE/deploy/                 a real folder: the site's own files (STATE) live here as before
    BASE/deploy/docker-compose.yml, docker/, Caddyfile ... -> ../current/deploy/...

So every path the box already uses (``/opt/trialbox/deploy/.env``, ``tools/apply_update.sh``, the cron lines) keeps
working, and switching ``current`` changes every release file at once. Inside a release, each STATE path is a link
back to ``BASE/deploy/<path>``, so a tool that resolves its own path into the release still finds the site's files.
An install or update unpacks the tree (``install``), switches ``current`` and refreshes the links; a rollback
switches back (``restore``). A file of an older, copied install that the release now provides is moved aside to
``BASE/releases/.replaced-<time>/``, never deleted. Standard library only: the host verifier imports it.

    python3 -m tools.host_tree pack --root . --out dist/trialbox-host.tar
    python3 -m tools.host_tree check trialbox-host.tar
    python3 -m tools.host_tree status --base /opt/trialbox
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import IO, Any

HOST_TAR = "trialbox-host.tar"
SUMS = "HOST-SHA256SUMS"
# what the host tree holds: these folders and files of the source tree
TOP_DIRS = ("deploy", "tools", "libs", "schemas")
TOP_FILES = (".env.example", "pyproject.toml", "NOTICE", "CHANGELOG.md")
# the site's own files under deploy/: never in a release, never replaced by an update
STATE = (
    "deploy/.env",
    "deploy/settings.yaml",
    "deploy/secrets",
    "deploy/keys",
    "deploy/updates",
    "deploy/refdata",
    "deploy/models",
    "deploy/site",
    "deploy/ops",
    "deploy/logs",
    "deploy/backups",
    "deploy/image-pins.json",
    "deploy/pgbackrest/repo",
)
RESERVED = ("releases", "current")
REQUIRED = ("deploy/docker-compose.yml",)
MAX_MEMBERS = 20000
MAX_SUMS_BYTES = 4 << 20
_EPOCH = 1_700_000_000  # a fixed mtime: the same source gives the same tar


class HostTreeError(Exception):
    pass


def _state_ancestors() -> set[str]:
    out: set[str] = set()
    for s in STATE:
        p = PurePosixPath(s).parent
        while str(p) != ".":
            out.add(str(p))
            p = p.parent
    return out


ANCESTORS = _state_ancestors()


def is_state(rel: str) -> bool:
    return any(rel == s or rel.startswith(s + "/") for s in STATE)


def _junk(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return "__pycache__" in parts or rel.endswith((".pyc", ".pyo")) or ".venv" in parts or ".cache" in parts


def _allowed(rel: str) -> bool:
    top = PurePosixPath(rel).parts[0]
    return (top in TOP_DIRS and len(PurePosixPath(rel).parts) > 1) or rel in TOP_FILES


def _sha(fh: IO[bytes]) -> str:
    h = hashlib.sha256()
    while chunk := fh.read(1 << 20):
        h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ vendor side
def tree_files(root: Path) -> list[str]:
    """The release files of a source tree: what git tracks (and new, not ignored files) under TOP_DIRS and TOP_FILES,
    without the site's STATE paths and caches. Outside a git checkout: every file there."""
    try:
        argv = ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--"]
        out = subprocess.run([*argv, *TOP_DIRS, *TOP_FILES], capture_output=True, check=True, timeout=120).stdout
        names = {n for n in out.decode().split("\0") if n}
    except (OSError, subprocess.SubprocessError):
        names = {p.relative_to(root).as_posix() for d in TOP_DIRS if (root / d).is_dir()
                 for p in (root / d).rglob("*") if p.is_file()}  # fmt: skip
        names |= {f for f in TOP_FILES if (root / f).is_file()}
    keep = []
    for n in sorted(names):
        p = root / n
        if is_state(n) or _junk(n) or not _allowed(n) or p.is_symlink() or not p.is_file():
            continue
        keep.append(n)
    return keep


def pack(root: Path, out: Path, files: Iterable[str] | None = None) -> dict[str, Any]:
    """Write the host tree of ``root`` to ``out``: ``HOST-SHA256SUMS`` first, then every file sorted, owner 0, a fixed
    mtime, mode 0755 for an executable and 0644 for the rest.

    Each file is read ONCE: hashed while it is copied into a private snapshot beside ``out``, and the tar is written
    from that snapshot. A file that changes while the tree is packed (an editor's save, a parallel test writing into
    the checkout) can no longer give a tar whose bytes differ from its own sums (H-56: the box-run rehearsal's build
    cases were refused at b06 with "sha256 differs from HOST-SHA256SUMS" on a CI runner)."""
    names = sorted(files) if files is not None else tree_files(root)
    for n in REQUIRED:
        if n not in names:
            raise HostTreeError(f"the host tree has no {n}")
    for n in names:
        if is_state(n) or not _allowed(n):
            raise HostTreeError(f"{n} may not be in a host tree")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    snap = out.with_name(out.name + ".snap")
    shutil.rmtree(snap, ignore_errors=True)
    try:
        snap.mkdir(mode=0o700)
        sums: dict[str, str] = {}
        modes: dict[str, int] = {}
        for i, n in enumerate(names):
            p = root / n
            modes[n] = 0o755 if os.access(p, os.X_OK) else 0o644
            h = hashlib.sha256()
            with p.open("rb") as src, (snap / str(i)).open("wb") as dst:
                while chunk := src.read(1 << 20):
                    h.update(chunk)
                    dst.write(chunk)
            sums[n] = h.hexdigest()
        body = "".join(f"{sums[n]}  {n}\n" for n in names).encode()
        with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tf:
            tf.addfile(_info(SUMS, len(body), 0o644), io.BytesIO(body))
            for i, n in enumerate(names):
                s = snap / str(i)
                with s.open("rb") as fh:
                    tf.addfile(_info(n, s.stat().st_size, modes[n]), fh)
    finally:
        shutil.rmtree(snap, ignore_errors=True)
    tmp.replace(out)
    return {"files": len(names), "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def _info(name: str, size: int, mode: int) -> tarfile.TarInfo:
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.mtime = size, mode, _EPOCH
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    return ti


# ------------------------------------------------------------------------------------------------ the check
def _safe(name: str) -> str:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or name != str(p) or "\\" in name:
        raise HostTreeError(f"unsafe path in the host tree: {name!r}")
    return name


def _parse_sums(body: bytes) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in body.decode("utf-8").splitlines():
        sha, sep, name = line.partition("  ")
        if not sep or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise HostTreeError(f"{SUMS}: bad line {line[:80]!r}")
        if name in sums:
            raise HostTreeError(f"{SUMS} lists {name} twice")
        sums[_safe(name)] = sha
    return sums


def check_tar(src: Path | IO[bytes]) -> dict[str, str]:
    """Every rule a host tree must meet, before a byte of it is unpacked: ``HOST-SHA256SUMS`` first; regular files
    only (no link, device or folder entry); safe paths under TOP_DIRS or TOP_FILES; no STATE path and no reserved
    name; every file listed once with its sha256, nothing unlisted; ``deploy/docker-compose.yml`` present. Returns
    ``{path: sha256}``."""
    try:
        tf = tarfile.open(src, "r:") if isinstance(src, Path) else tarfile.open(fileobj=src, mode="r:")  # noqa: SIM115
    except (tarfile.TarError, OSError) as exc:
        raise HostTreeError(f"the host tree is not a tar: {exc}") from exc
    with tf:
        sums: dict[str, str] | None = None
        seen: set[str] = set()
        for i, m in enumerate(tf):
            if i > MAX_MEMBERS:
                raise HostTreeError(f"the host tree has more than {MAX_MEMBERS} members")
            if not m.isfile():
                raise HostTreeError(f"host tree member {m.name!r} is not a regular file")
            name = _safe(m.name)
            if i == 0:
                if name != SUMS or m.size > MAX_SUMS_BYTES:
                    raise HostTreeError(f"the host tree does not begin with {SUMS}")
                f = tf.extractfile(m)
                assert f is not None
                sums = _parse_sums(f.read())
                continue
            assert sums is not None
            if name in seen:
                raise HostTreeError(f"host tree member {name} twice")
            seen.add(name)
            if is_state(name) or not _allowed(name) or name.split("/", 1)[0] in RESERVED:
                raise HostTreeError(f"{name} may not be in a host tree (a site file or outside the tree)")
            if name not in sums:
                raise HostTreeError(f"{name} is not in {SUMS}")
            f = tf.extractfile(m)
            assert f is not None
            if _sha(f) != sums[name]:
                raise HostTreeError(f"{name}: sha256 differs from {SUMS}")
        if sums is None:
            raise HostTreeError("the host tree is empty")
        if set(sums) - seen:
            raise HostTreeError(f"{SUMS} lists files the tree does not hold: {sorted(set(sums) - seen)[:5]}")
        for n in REQUIRED:
            if n not in sums:
                raise HostTreeError(f"the host tree has no {n}")
        return sums


def check_dir(release: Path) -> list[str]:
    """The unpacked release against its own ``HOST-SHA256SUMS`` (the back-links to the site's files aside):
    the differences, empty when it is exactly as signed."""
    try:
        sums = _parse_sums((release / SUMS).read_bytes())
    except (OSError, HostTreeError) as exc:
        return [f"{SUMS}: {exc}"]
    bad = []
    for name, sha in sums.items():
        p = release / name
        if p.is_symlink() or not p.is_file():
            bad.append(f"{name}: missing")
            continue
        with p.open("rb") as fh:
            if _sha(fh) != sha:
                bad.append(f"{name}: changed")
    for top, _dirs, files in os.walk(release):  # links (the back-links among them) are not followed
        for f in files:
            p = Path(top) / f
            rel = p.relative_to(release).as_posix()
            if not p.is_symlink() and rel != SUMS and rel not in sums and not _junk(rel):
                bad.append(f"{rel}: not in the release")
    return bad


# ------------------------------------------------------------------------------------------------ on the box
def current(base: Path) -> str | None:
    link = base / "current"
    if not link.is_symlink():
        return None
    return PurePosixPath(os.readlink(link)).name


def _unpack(tar: Path, dest: Path) -> None:
    tmp = dest.with_name(f".{dest.name}.partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(tar, "r:") as tf:
        for m in tf:
            target = tmp / _safe(m.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            f = tf.extractfile(m)
            assert f is not None
            with target.open("xb") as out:
                shutil.copyfileobj(f, out, 1 << 20)
            target.chmod(0o755 if m.mode & 0o100 else 0o644)
    tmp.rename(dest)


def _back_links(release: Path, base: Path) -> None:
    """Each STATE path inside the release is a link to the site's own file under ``base``."""
    for s in STATE:
        p = release / s
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink():
            p.unlink()
        p.symlink_to(os.path.relpath(base / s, p.parent))


def install(tar: Path, base: Path, release_id: str) -> dict[str, Any]:
    """Unpack a checked host tree to ``base/releases/<release_id>`` (kept when it is already there exactly as
    signed), switch ``current`` to it and refresh the links. Returns what :func:`restore` needs."""
    if PurePosixPath(release_id).name != release_id or release_id.startswith("."):
        raise HostTreeError(f"bad release id {release_id!r}")
    check_tar(tar)
    rels = base / "releases"
    rels.mkdir(parents=True, exist_ok=True)
    dest = rels / release_id
    previous = current(base)
    fresh = False
    if dest.exists() and check_dir(dest):  # left over and changed: set aside, unpack again
        dest.rename(rels / f".changed-{release_id}-{int(time.time())}")
    if not dest.exists():
        _unpack(tar, dest)
        fresh = True
    _back_links(dest, base)
    info: dict[str, Any] = {"previous": previous, "release": release_id, "fresh": fresh}
    info.update(switch(base, release_id))
    return info


def switch(base: Path, release_id: str) -> dict[str, Any]:
    """``current`` -> ``releases/<release_id>`` in one rename, then the links refreshed."""
    if not (base / "releases" / release_id).is_dir():
        raise HostTreeError(f"no release {release_id} in {base / 'releases'}")
    tmp = base / ".current.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(f"releases/{release_id}")
    os.replace(tmp, base / "current")
    return sync(base)


def sync(base: Path) -> dict[str, Any]:
    """Make every release path under ``base`` a link through ``current``: a real file or folder of a copied install
    in its place is moved to ``releases/.replaced-<time>/``; a link to a path the release no longer has is removed.
    STATE paths are never touched; their parent folders stay real folders."""
    cur = base / "current"
    if not cur.is_dir():
        raise HostTreeError(f"{cur} names no release")
    moved: list[str] = []
    made: list[str] = []
    aside = base / "releases" / f".replaced-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"

    def walk(rel: PurePosixPath) -> None:
        here = base / rel
        rdir = cur / rel
        for child in sorted(rdir.iterdir()):
            r = (rel / child.name).as_posix() if str(rel) != "." else child.name
            if child.is_symlink() or is_state(r) or r == SUMS or (str(rel) == "." and child.name in RESERVED):
                continue
            p = here / child.name
            if r in ANCESTORS:  # holds site files below it: a real folder
                if p.is_symlink():
                    p.unlink()
                elif p.exists() and not p.is_dir():
                    _aside(p, aside / r, moved, r)
                p.mkdir(exist_ok=True)
                walk(PurePosixPath(r))
                continue
            target = os.path.relpath(cur / r, here)
            if p.is_symlink():
                if os.readlink(p) == target:
                    continue
                p.unlink()
            elif p.exists():
                _aside(p, aside / r, moved, r)
            p.symlink_to(target)
            made.append(r)
        for p in sorted(here.iterdir()):  # links into current whose target the release dropped
            r = (rel / p.name).as_posix() if str(rel) != "." else p.name
            if p.is_symlink() and not p.exists() and os.readlink(p) == os.path.relpath(cur / r, here):
                p.unlink()

    walk(PurePosixPath("."))
    return {"moved": moved, "aside": str(aside) if moved else None, "linked": made}


def _aside(p: Path, to: Path, moved: list[str], rel: str) -> None:
    to.parent.mkdir(parents=True, exist_ok=True)
    p.rename(to)
    moved.append(rel)


def restore(base: Path, info: dict[str, Any]) -> None:
    """Undo :func:`install`: ``current`` back to the previous release (or, for the first host tree on a copied install,
    the links removed and the moved files put back); a release unpacked by that install is removed."""
    prev, rel = info.get("previous"), info.get("release")
    if prev:
        switch(base, prev)
    else:
        cur = base / "current"
        for r in sorted(info.get("linked") or [], reverse=True):
            p = base / r
            if p.is_symlink():
                p.unlink()
        if cur.is_symlink():
            cur.unlink()
        aside = info.get("aside")
        for r in info.get("moved") or []:
            src = Path(str(aside)) / r
            if src.exists() or src.is_symlink():
                (base / r).parent.mkdir(parents=True, exist_ok=True)
                src.rename(base / r)
    if info.get("fresh") and rel and rel != prev:
        shutil.rmtree(base / "releases" / str(rel), ignore_errors=True)


def status(base: Path) -> dict[str, Any]:
    cur = current(base)
    out: dict[str, Any] = {"base": str(base), "current": cur}
    if cur:
        out["problems"] = check_dir(base / "releases" / cur)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="vendor: write the host tree of a source tree")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check", help="check a host tree tar")
    c.add_argument("tar", type=Path)
    s = sub.add_parser("status", help="the release BASE/current names, checked against its HOST-SHA256SUMS")
    s.add_argument("--base", type=Path, default=Path("/opt/trialbox"))
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pack":
            print(json.dumps(pack(a.root, a.out)))
        elif a.cmd == "check":
            print(f"host tree: {len(check_tar(a.tar))} files, PASS")
        else:
            st = status(a.base)
            print(json.dumps(st, indent=1))
            return 1 if st.get("problems") or not st["current"] else 0
    except HostTreeError as exc:
        print(f"host tree: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

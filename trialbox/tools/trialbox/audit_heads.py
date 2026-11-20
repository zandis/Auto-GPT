"""``trialbox audit-sign``: the hourly signed head of the audit chain (NEW-STD-2, D-562, 10G-2, D-1345; STD-002).

D-355 built the control: an Ed25519 key signs where the audit chain stands and the signed head is kept, write-once,
in a folder off the audit volume (``TB_AUDIT_ANCHOR_TARGETS``). This module is what runs it on a box, every hour,
from the installer's cron file (10G-2, D-1345; nightly until then):

1. **check**: the chain must verify against its own head anchor and against every signed head already in every
   anchor folder, under the box's own public keys (``audit_sign*.pub`` in the secrets folder, never the keys an
   anchor folder offers). A chain that does not agree is never signed again;
2. **sign and publish**: the head, write-once, to every anchor folder;
3. **record**: ``audit.head_signed`` goes through the audit journal, as every event of a box does.

The host never writes the audit volume (D-394: only the audit writer does). On a site box the signer runs in the
box's own image with the audit volume mounted read-only; the chain is read under a shared lock on the writer's lock
file, opened read-only and never made here: a file made by the host's root could not be written by the audit writer,
and the next event of the box would fail. On an in-process box (``--local``) the event is appended directly.

    python3 -m tools.trialbox audit-sign [--deploy deploy] [--local]
    python  -m tools.trialbox.audit_heads --init-key --secrets DIR      # made once (deploy/hardening/seal_keys.sh)
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ACTOR = "trialbox:audit-sign"
PROJECT = "trialbox"
VOLUMES = "/var/lib/docker/volumes"
KEK_FILE = "/run/trialbox/kek"  # tb_common.kek.DEFAULT_KEK_FILE (the host wrapper imports no library)
#: the environment the signer's container is given, by name: a value never goes on a command line
PASSED = ("TB_ENV", "TB_KEK_FILE", "TB_KEK_PASSPHRASE", "TB_KMS_TOKEN", "TB_TZ")

Recorder = Callable[[str, str, dict[str, Any]], None]
Run = Callable[..., str]


@dataclass
class Night:
    """One night's result: ``signed`` is the head that at least one folder took, ``detail`` the event's detail."""

    ok: bool
    problems: list[str] = field(default_factory=list)
    signed: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    #: 10G-2: the problems that are only "this folder cannot be shown root-proof" (doctor: FAIL in PRODUCTION only)
    open_to_root: list[str] = field(default_factory=list)
    #: 10G-2: each anchor folder's judgement, as the signer (root, in its container) made it; absent: not judged
    root_proof: dict[str, str] | None = None


def _libs() -> None:
    for p in (ROOT, ROOT / "libs"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


class LockRefused(ValueError):
    """The audit writer's lock file is a link or not a regular file: refused, never followed."""


@contextlib.contextmanager
def reading(audit_dir: Path) -> Iterator[None]:
    """A shared lock on the audit writer's own lock file, so the chain and its anchor are read at one moment. The
    file is opened read-only and never made here; with no lock file no writer has run, and nothing is locked. A
    link or anything but a regular file in its place is refused (:class:`LockRefused`), never followed (10G-2)."""
    try:
        fd = os.open(audit_dir / ".lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        yield
        return
    except OSError as exc:
        raise LockRefused(
            f"the audit writer's lock file {audit_dir / '.lock'} cannot be opened as a file ({exc})"
        ) from exc
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise LockRefused(f"the audit writer's lock file {audit_dir / '.lock'} is not a regular file")
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def own_keys(secrets_dir: Path) -> dict[str, bytes]:
    """The public keys this box trusts for its own heads: the current one and the ones it rotated out. Not the key
    that still waits for its hand-over record (``audit_sign.next.pub``)."""
    _libs()
    from tb_common import audit

    files = [p for p in sorted(secrets_dir.glob("audit_sign*.pub")) if p.name != "audit_sign.next.pub"]
    return audit.read_public_keys(files)


# ------------------------------------------------------------------------------------------------ root-proof
#: file systems whose writes another machine decides (a share): the only kind that can be shown root-proof here
REMOTE_FS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs"})
#: the one test file the judgement keeps in heads/ (not a head: read_signed_heads reads *.json only)
PROBE = ".root-probe"
_REFUSED = frozenset({errno.EACCES, errno.EPERM, errno.EROFS})


@dataclass
class Proof:
    ok: bool
    why: str


def fs_type(path: Path) -> str | None:
    """The type of the file system ``path`` is on (``/proc/self/mountinfo``, matched by device number of the folder
    itself, not by resolving a path). None when it cannot be told."""
    try:
        st = os.stat(path, follow_symlinks=False)
        dev = f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
        with open("/proc/self/mountinfo", encoding="utf-8") as fh:
            for line in fh:
                left, _, right = line.partition(" - ")
                if left.split()[2] == dev and right.split():
                    return right.split()[0]
    except (OSError, IndexError, ValueError):
        return None
    return None


def _allowed(op: Callable[[], object]) -> bool:
    """True when the kernel let ``op`` through, False when it refused it as a permission (EACCES, EPERM, EROFS);
    any other error is raised: the judgement then says it cannot tell."""
    try:
        op()
    except OSError as exc:
        if exc.errno in _REFUSED:
            return False
        raise
    return True


def _try_overwrite(dfd: int, name: str) -> bool:
    return _allowed(lambda: os.close(os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)))


def _try_rename(dfd: int, name: str) -> bool:
    moved = name + ".moved"
    if not _allowed(lambda: os.rename(name, moved, src_dir_fd=dfd, dst_dir_fd=dfd)):
        return False
    with contextlib.suppress(OSError):
        os.rename(moved, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    return True


def _try_unlink(dfd: int, name: str) -> bool:
    return _allowed(lambda: os.unlink(name, dir_fd=dfd))


def _plain_file(dfd: int, name: str) -> str | None:
    """None when ``name`` in the folder is a regular file with one link; else what it is (never followed)."""
    st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode):
        return f"{name} is not a regular file"
    if st.st_nlink != 1:
        return f"{name} has {st.st_nlink} links"
    return None


def root_proof(target: Path, head: str | None, *, fs: Callable[[Path], str | None] = fs_type) -> Proof:
    """10G-2 (review 16-19, D-1345): whether the box's root is refused every way of changing the signed heads of
    ``target``: overwriting ``head`` (the head just written, by name), and renaming, deleting or overwriting a file
    in ``heads/`` (the test file :data:`PROBE`, made once and kept). Run by the signer as root. A folder on the
    box's own disk is never root-proof (root can change any mode, owner or attribute there); a share is root-proof
    only when the share refuses all of it; anything this cannot tell is "cannot be shown root-proof". Nothing is
    followed through a link: the folder is opened once without following, every name under it likewise, and a name
    that is not a regular file with one link stops the judgement."""
    kind = fs(target)
    if kind is None:
        return Proof(False, "cannot be shown root-proof: its file system cannot be told")
    if kind not in REMOTE_FS:
        return Proof(False, f"cannot be root-proof: a {kind} folder on this box's own disk, where root can change "
                            "any mode, owner or attribute (chattr +i included)")  # fmt: skip
    if head is None:
        return Proof(False, "cannot be shown root-proof: no head was written there to judge")
    try:
        top = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            dfd = os.open("heads", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=top)
        finally:
            os.close(top)
    except OSError as exc:
        return Proof(False, f"cannot be shown root-proof: {target}/heads cannot be opened as a folder ({exc})")
    try:
        if why := _plain_file(dfd, head):
            return Proof(False, f"cannot be shown root-proof: {why}")
        if _try_overwrite(dfd, head):
            return Proof(False, f"the box's root can overwrite the head just written ({head})")
        try:
            fd = os.open(PROBE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=dfd)
        except FileExistsError:
            pass
        else:
            try:
                os.write(fd, b"trialbox audit-sign: the root-proof test file; not a signed head\n")
            finally:
                os.close(fd)
        if why := _plain_file(dfd, PROBE):
            return Proof(False, f"cannot be shown root-proof: {why}")
        if _try_rename(dfd, PROBE):
            return Proof(False, "the box's root can rename a file in heads/ (and so move a head away)")
        if _try_unlink(dfd, PROBE):
            return Proof(False, "the box's root can delete a file in heads/ (and so delete a head and write another "
                                "in its place)")  # fmt: skip
        if _try_overwrite(dfd, PROBE):
            return Proof(False, "the box's root can overwrite a file in heads/")
        return Proof(True, f"a {kind} share that refused this box's root every overwrite, rename and delete tried")
    except OSError as exc:
        return Proof(False, f"cannot be shown root-proof: {exc}")
    finally:
        os.close(dfd)


def check_and_sign(audit_dir: Path, secrets_dir: Path, targets: Sequence[Path], now: datetime, *,
                   probe: bool = False, refuse_open: bool = False,
                   fs: Callable[[Path], str | None] = fs_type) -> Night:  # fmt: skip
    """Steps 1 and 2. Reads the audit folder, writes only into the anchor folders. With ``probe`` (the signer on a
    site box, as root) each folder is judged root-proof or not (:func:`root_proof`): before the head is written, a
    folder on the box's own disk or of a type that cannot be told; after, the head just written, by name. With
    ``refuse_open`` (PRODUCTION) a folder judged not root-proof before writing gets no head."""
    _libs()
    from tb_common import audit
    from tb_common.crypto import KeyMissingError
    from tb_common.kek import KekError

    from tools.audit_verify import _load_pair

    if not targets:
        return Night(False, [f"no anchor folder: set {audit.ANCHOR_TARGETS_ENV} to a folder off the box"])
    for t in targets:
        if audit._inside(t, audit_dir):
            return Night(False, [f"the anchor folder {t} is inside the audit folder: it must be off the audit volume"])
    try:
        private_pem, public_pem = _load_pair(secrets_dir)
    except (KeyMissingError, FileNotFoundError, KekError) as exc:
        return Night(False, [f"the audit signing key cannot be read ({exc}): nothing was signed"])
    if not audit_dir.is_dir():
        return Night(False, [f"the audit folder {audit_dir} is not there: nothing was signed"])
    earlier = [h for t in targets if (t / "heads").is_dir() for h in audit.read_signed_heads(t)]
    try:
        with reading(audit_dir):
            made = _sign_where_it_stands(audit_dir, secrets_dir, earlier, private_pem, public_pem, now)
    except LockRefused as exc:
        return Night(False, [f"{exc}: nothing was signed"])
    if isinstance(made, Night):
        return made
    # after the lock: a slow share does not hold the box's audit writer
    return _publish(targets, made, public_pem, probe=probe, refuse_open=refuse_open, fs=fs)


def _sign_where_it_stands(audit_dir: Path, secrets_dir: Path, earlier: list[dict[str, Any]], private_pem: bytes,
                          public_pem: bytes, now: datetime) -> Night | dict[str, Any]:  # fmt: skip
    """Step 1 under the writer's lock: the chain checked; the signed head, or the Night that says why not."""
    _libs()
    from tb_common import audit

    try:
        head = audit.read_head(audit_dir)
    except ValueError as exc:
        return Night(False, [f"the head anchor of {audit_dir} cannot be read ({exc}): nothing was signed"])
    if head is None or not int(head.get("lines") or 0):
        # "no event yet" is true only of a chain nobody ever wrote or signed: with day files there, or with an
        # earlier signed head in a folder, a missing or empty anchor is what a removal looks like
        if earlier or any(audit_dir.glob("*.jsonl")):
            seen = f"{len(earlier)} earlier signed head(s)" if earlier else "day files"
            return Night(False, [f"the audit chain in {audit_dir} has no head anchor, and there are {seen}: the "
                                 "chain does not agree with them; nothing was signed"])  # fmt: skip
        return Night(True)  # no event yet: nothing to sign, and nothing wrong
    res = audit.verify(audit_dir, signed_heads=earlier or None, trusted_keys=own_keys(secrets_dir))
    if not res.ok:
        what = "an earlier signed head or its own head anchor" if earlier else "its own head anchor"
        why = "; ".join(res.errors[:3])
        return Night(False, [f"the audit chain does not agree with {what} ({why}): nothing was signed; look at it "
                             "with tools/audit_verify.py --heads before anything else"])  # fmt: skip
    files = sorted(p.name for p in audit_dir.glob("*.jsonl"))
    try:
        return audit.make_signed_head(res.lines, res.last_hash, files[-1] if files else None, private_pem,
                                      public_pem, ts=now)  # fmt: skip
    except audit.AuditSignError as exc:
        return Night(False, [str(exc)])


_FIX = (
    "Make TB_AUDIT_ANCHOR_TARGETS a folder on the hospital's share that refuses the box's root every overwrite, "
    "rename and delete (root squashed with create-only rights, or a WORM share) (RUNBOOK 02, D-1345)"
)


def _publish(targets: Sequence[Path], rec: dict[str, Any], public_pem: bytes, *, probe: bool, refuse_open: bool,
             fs: Callable[[Path], str | None]) -> Night:  # fmt: skip
    """Step 2: the head, write-once, to every folder; with ``probe`` each folder judged (see :func:`check_and_sign`)."""
    _libs()
    from tb_common import audit

    written, failed, judged, open_to_root = 0, [], {}, []
    for t in targets:
        before = root_proof(t, None, fs=fs) if probe else None
        if before is not None and refuse_open and fs(t) not in REMOTE_FS:  # the box's own disk, or a type not told
            judged[str(t)] = before.why
            open_to_root.append(f"the anchor folder {t} was refused a head: it {before.why}. {_FIX}")
            continue
        try:
            path = audit.publish_head(t, rec, public_pem)
            written += 1
        except (OSError, audit.AuditSignError) as exc:
            failed.append(f"{t}: {exc}")
            continue
        if probe:
            after = root_proof(t, path.name, fs=fs)
            judged[str(t)] = after.why
            if not after.ok:
                open_to_root.append(f"the anchor folder {t}: {after.why}; a head there does not count as root-proof. "
                                    f"{_FIX}")  # fmt: skip
    detail: dict[str, Any] = {"lines": rec["lines"], "head": rec["hash"], "key_id": rec["key_id"], "anchors": written}
    if failed or open_to_root:
        detail["failed"] = failed + open_to_root
    problems = [f"the signed head was not written to {f}" for f in failed] + open_to_root
    return Night(not problems, problems, rec if written else None, detail, open_to_root, judged if probe else None)


def sign_night(audit_dir: Path, secrets_dir: Path, targets: Sequence[Path], *, record: Recorder,
               now: datetime | None = None) -> Night:  # fmt: skip
    """The three steps. ``record`` writes the event where this box's events go (the journal, or the chain itself)."""
    _libs()
    from tb_common import audit

    night = check_and_sign(audit_dir, secrets_dir, targets, now or datetime.now(UTC))
    return _recorded(night, record, audit.SIGNED_EVENT)


def _recorded(night: Night, record: Recorder, event: str) -> Night:
    if night.detail is not None:
        try:
            record(event, ACTOR, night.detail)
        except Exception as exc:
            night.ok = False
            night.problems.append(f"the signed head was published but not recorded in the audit chain ({exc})")
    return night


# ------------------------------------------------------------------------------------------------ a site box
def _run(argv: Sequence[str], env: Mapping[str, str] | None = None) -> str:
    r = subprocess.run(list(argv), capture_output=True, text=True, check=False, env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise RuntimeError(f"{shlex.join(list(argv)[:4])} ... exit {r.returncode}: {r.stderr[-300:]}")
    return r.stdout


def host_dirs(env: Mapping[str, str]) -> tuple[Path, Path, list[Path]]:
    """The audit volume, the secrets volume and the anchor folders as the host sees them."""
    project = env.get("COMPOSE_PROJECT_NAME") or PROJECT
    volumes = env.get("TB_DOCKER_VOLUMES") or VOLUMES
    audit_dir = Path(env.get("TB_AUDIT_HOST_DIR") or f"{volumes}/{project}_audit-data/_data")
    secrets = Path(env.get("TB_SECRETS_HOST_DIR") or f"{volumes}/{project}_tb-secrets/_data")
    targets = [Path(p) for p in (env.get("TB_AUDIT_ANCHOR_TARGETS") or "").split(os.pathsep) if p.strip()]
    return audit_dir, secrets, targets


def sign_on_box(deploy: Path, env: Mapping[str, str], run: Run = _run) -> Night:
    """A site box, as root on the host: the signer in the box's image, the event through the orchestrator. The
    signer, as root in its container, judges each folder root-proof or not (:func:`root_proof`, 10G-2); the host
    never judges with its own account. A folder the signer did not judge counts as not shown root-proof."""
    audit_dir, secrets, wanted = host_dirs(env)
    # `docker run -v` makes a host folder that is not there, as root: a wrong audit path would look like an empty
    # chain, and a share that is not mounted would take the head on the box's own disk. So the host looks first.
    if not audit_dir.is_dir():
        return Night(False, [f"the audit folder {audit_dir} is not there (TB_AUDIT_HOST_DIR, TB_DOCKER_VOLUMES, "
                             "COMPOSE_PROJECT_NAME in deploy/.env): nothing was signed"])  # fmt: skip
    if not secrets.is_dir():
        return Night(False, [f"the secrets folder {secrets} is not there (TB_SECRETS_HOST_DIR): nothing was signed"])
    targets = [t for t in wanted if t.is_dir()]
    absent = [f"the anchor folder {t} is not there (not mounted?): no signed head was written to it"
              for t in wanted if not t.is_dir()]  # fmt: skip
    if not targets:
        return Night(False, absent or ["no anchor folder: set TB_AUDIT_ANCHOR_TARGETS to a folder off the box"])
    docker = shlex.split(env.get("TB_DOCKER") or "docker")
    mounts = ["-v", f"{audit_dir}:{audit_dir}:ro", "-v", f"{secrets}:{secrets}:ro"]
    if env.get("TB_KEK_HOST_DIR"):  # as the compose files and check_host.sh mount it (D-347)
        mounts += ["-v", f"{env['TB_KEK_HOST_DIR']}:{Path(KEK_FILE).parent}:ro"]
    elif (kek_dir := Path(env.get("TB_KEK_FILE") or KEK_FILE).parent).is_dir():
        mounts += ["-v", f"{kek_dir}:{kek_dir}:ro"]
    for t in targets:
        mounts += ["-v", f"{t}:{t}"]
    names = [x for name in PASSED for x in ("-e", name)]
    to = [x for t in targets for x in ("--to", str(t))]
    argv = [*docker, "run", "--rm", "--network", "none", "--user", "0:0", *names, *mounts,
            env.get("TB_IMAGE") or "trialbox-py:1.0.0", "python", "-m", "tools.trialbox.audit_heads", "--inner",
            "--audit", str(audit_dir), "--secrets", str(secrets), *to]  # fmt: skip
    try:
        out = run(argv, env={k: env[k] for k in PASSED if env.get(k)})
        doc = json.loads(out.strip().splitlines()[-1])
        night = Night(bool(doc["ok"]), list(doc["problems"]), doc.get("signed"), doc.get("detail"),
                      [str(x) for x in doc.get("open_to_root") or []], doc.get("root_proof"))  # fmt: skip
    except (RuntimeError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        return Night(False, [f"the signer did not answer ({exc}): nothing was recorded"])
    judged = night.root_proof if isinstance(night.root_proof, dict) else {}
    open_to_root = [f"the anchor folder {t} cannot be shown root-proof: the signer's answer has no root-proof "
                    "judgement for it, so its image is likely older than the host tools (an update not finished). "
                    "Finish the update (tools/apply_update.sh status) or load the image the tree pins "
                    f"({env.get('TB_IMAGE') or 'trialbox-py:1.0.0'}), then run python3 -m tools.trialbox audit-sign"
                    for t in targets if str(t) not in judged and night.signed]  # fmt: skip
    night.open_to_root += open_to_root
    if absent or open_to_root:
        night.ok = False
        night.problems += absent + open_to_root
        if night.detail is not None:
            night.detail["failed"] = [*night.detail.get("failed", []), *absent, *open_to_root]
    compose = shlex.split(env.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}")
    code = (
        "import json, sys\nfrom tb_common.audit_writer import open_audit\n"
        "open_audit().append(sys.argv[1], actor=sys.argv[2], detail=json.loads(sys.argv[3]))\n"
    )

    def record(event: str, actor: str, detail: dict[str, Any]) -> None:
        run([*compose, "exec", "-T", "orchestrator", "python", "-c", code, event, actor, json.dumps(detail)])

    return _recorded(night, record, "audit.head_signed")


def sign_local(env: Mapping[str, str]) -> Night:
    """An in-process box (file mode, no journal): the same steps here, the event appended to the chain itself."""
    _libs()
    from tb_common import audit

    audit_dir = Path(env.get("TB_AUDIT_HOST_DIR") or env.get("TB_AUDIT_DIR") or "data/audit")
    secrets = Path(env.get("TB_SECRETS_HOST_DIR") or env.get("TB_SECRETS_DIR") or "/run/secrets/trialbox")
    log = audit.AuditLog(audit_dir, env["TB_TZ"]) if env.get("TB_TZ") else audit.AuditLog(audit_dir)

    def record(event: str, actor: str, detail: dict[str, Any]) -> None:
        log.append(event, actor=actor, detail=detail)

    return sign_night(audit_dir, secrets, audit.anchor_targets(env), record=record)


# ------------------------------------------------------------------------------------------------ files, no links
def read_plain(folder: Path, name: str, limit: int = 1 << 20) -> bytes:
    """``folder/name`` read without following a link: the folder opened once, the name through it with O_NOFOLLOW,
    and anything but a regular file refused (``OSError``). ``FileNotFoundError`` when it is not there."""
    dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    finally:
        os.close(dfd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, f"{folder / name} is not a regular file")
        return os.read(fd, limit)
    finally:
        os.close(fd)


def replace_plain(folder: Path, name: str, data: bytes, mode: int) -> None:
    """``folder/name`` replaced by ``data`` without following a link: a new file ``.<name>.tmp`` made with O_EXCL and
    O_NOFOLLOW through the folder's descriptor (a stale one, or a link planted there, is removed first: the link
    itself, never what it names), then renamed over ``name`` (a rename replaces a link, it does not follow it)."""
    dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        tmp = f".{name}.tmp"
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp, dir_fd=dfd)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dfd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    finally:
        os.close(dfd)


# ------------------------------------------------------------------------------------------------ the schedule
CRON_NAME = "trialbox-retention"  # deploy/install.sh writes it; the update's pre-start step moves an old one on
CRON_LOG = "/var/log/trialbox-retention.log"
_NIGHTLY = re.compile(r"20 0 \* \* \* root cd (?P<root>\S+) && \{ python3 -m tools\.trialbox logs daily; "
                      r"python3 -m tools\.trialbox audit-sign; \} >> (?P<log>\S+) 2>&1")  # fmt: skip
_HOURLY = re.compile(r"50 \* \* \* \* root cd \S+ && python3 -m tools\.trialbox audit-sign >> \S+ 2>&1")


def cron_lines(root: str, log: str = CRON_LOG) -> list[str]:
    """The two jobs of ``trialbox-retention`` (10G-2, D-1345): the logs once a night at 00:20, the signed audit head
    every hour at :50. ``deploy/install.sh`` writes the same lines (a test holds the two equal)."""
    return [
        f"20 0 * * * root cd {root} && python3 -m tools.trialbox logs daily >> {log} 2>&1",
        f"50 * * * * root cd {root} && python3 -m tools.trialbox audit-sign >> {log} 2>&1",
    ]


def hourly_cron(cron_dir: Path) -> str:
    """Move a cron file written before 10G-2 (one 00:20 line running ``logs daily`` then ``audit-sign``) to the two
    lines of :func:`cron_lines`, with its own install folder and log. Only that line changes: every other line keeps
    its bytes. Safe to run again. It never raises: a file that is not there, cannot be read or written, or whose line
    this release does not know, is left as it is and the line returned says so (an update goes on)."""
    path = cron_dir / CRON_NAME
    try:
        lines = read_plain(cron_dir, CRON_NAME).decode("utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        return f"no {path}: deploy/install.sh writes it"
    except (OSError, UnicodeDecodeError) as exc:
        return f"{path} cannot be read ({type(exc).__name__}): left as it is; deploy/install.sh writes it again"
    bare = [ln.rstrip("\r\n") for ln in lines]
    if any(_HOURLY.fullmatch(ln) for ln in bare):
        return f"{path} signs the audit head every hour already"
    found = [(i, m) for i, ln in enumerate(bare) if (m := _NIGHTLY.fullmatch(ln))]
    if len(found) != 1:
        return f"{path} has no nightly line this release knows: left as it is (deploy/install.sh writes it again)"
    i, m = found[0]
    end = lines[i][len(bare[i]) :] or "\n"
    new = [*lines[:i], *(ln + end for ln in cron_lines(m["root"], m["log"])), *lines[i + 1 :]]
    try:
        replace_plain(cron_dir, CRON_NAME, "".join(new).encode("utf-8"), 0o644)  # cron reads no dotted name
    except OSError as exc:
        return f"{path} cannot be written ({type(exc).__name__}): left as it is; deploy/install.sh writes it again"
    return f"{path}: the audit head is now signed every hour (it was once a night)"


def report(night: Night, targets: int) -> int:
    if night.signed:
        head, took = night.signed, (night.detail or {}).get("anchors", 0)
        print(f"signed head: event {head['lines']} ({str(head['hash'])[:16]}…), key {head['key_id']}, "
              f"{took} of {targets} anchor folders")  # fmt: skip
    elif night.ok:
        print("signed head: the audit chain has no event yet; nothing to sign")
    for p in night.problems:
        print(f"audit-sign: {p}", file=sys.stderr)
    return 0 if night.ok else 1


def main_action(deploy: Path, local: bool) -> int:
    from tools.trialbox.logs import env_file

    env = {**env_file(deploy), **{k: v for k, v in os.environ.items() if k.startswith(("TB_", "COMPOSE_"))}}
    night = sign_local(env) if local else sign_on_box(deploy, env)
    write_state(state_file(deploy, env), night)
    return report(night, len(host_dirs(env)[2]))


def state_file(deploy: Path, env: Mapping[str, str]) -> Path:
    """Where the night leaves its result for ``doctor`` (check ``audit_heads``): the host's log folder."""
    return Path(env.get("TB_LOG_DIR") or deploy / "logs") / "audit-sign.json"


def kind(night: Night) -> str:
    """What the result file says the run was, for ``doctor``: ``ok``; ``open_to_root`` when the only problems are
    folders that cannot be shown root-proof (10G-2: FAIL in PRODUCTION, WARN elsewhere); ``refused`` for anything
    else (FAIL in VALIDATION and PRODUCTION). A file written before 10G-2 has no kind and reads as before."""
    if night.ok:
        return "ok"
    only_root = night.open_to_root and all(p in night.open_to_root for p in night.problems)
    return "open_to_root" if only_root else "refused"


def write_state(path: Path, night: Night) -> None:
    """The night's result, so that a refused night is a FAIL line of ``doctor`` and not only a line in a log."""
    doc = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "ok": night.ok, "problems": night.problems[:5],
           "lines": (night.signed or {}).get("lines"), "kind": kind(night)}  # fmt: skip
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        replace_plain(path.parent, path.name, (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8"), 0o644)
    except OSError as exc:
        print(f"audit-sign: the result was not kept in {path} ({exc})", file=sys.stderr)


#: the private audit key's files in the secrets folder: plain or wrapped, the key in use and the one waiting
_PRIVATE = re.compile(r"audit_sign(\.[a-z0-9]+)?\.key(\.wrapped)?")


def private_key_files(secrets_dir: Path) -> list[str]:
    """The names of the private audit key's files in the secrets folder (never a ``.pub``)."""
    try:
        return sorted(n for n in os.listdir(secrets_dir) if _PRIVATE.fullmatch(n))
    except OSError:
        return []


def key_root_only(secrets_dir: Path) -> str:
    """10G-2 (D-1345): the private audit key's files owned by root, mode 0600, so that the services' account (uid
    10001: the adapter and the orchestrator mount the secrets folder) cannot open them. Opened without following a
    link (a link or anything but a regular file is left and said). Safe to run again; never raises."""
    if os.geteuid() != 0:
        return f"not root: {secrets_dir} left as it is (doctor audit_key_root names a key that is not root's)"
    names = private_key_files(secrets_dir)
    if not names:
        return f"no private audit key in {secrets_dir}"
    done, left = [], []
    try:
        dfd = os.open(secrets_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        return f"{secrets_dir} cannot be opened as a folder ({exc}): left as it is"
    try:
        for name in names:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            except OSError as exc:
                left.append(f"{name} ({exc.strerror})")
                continue
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                    left.append(f"{name} (not a regular file with one link)")
                    continue
                os.fchown(fd, 0, 0)
                os.fchmod(fd, 0o600)
                done.append(name)
            finally:
                os.close(fd)
    finally:
        os.close(dfd)
    said = f"{', '.join(done)} root's, 0600" if done else "nothing changed"
    return said + (f"; left: {', '.join(left)}" if left else "")


def init_key(secrets_dir: Path) -> int:
    """Make the audit signing key once, beside the site keys and under their KEK; a key that is there is kept."""
    _libs()
    from tb_common import audit, kek

    from tools import audit_verify

    if kek.key_present(secrets_dir / audit.SIGN_KEY_FILE):
        print(f"audit signing key: already in {secrets_dir}; kept; {key_root_only(secrets_dir)}")
        return 0
    rc = audit_verify.init_key(secrets_dir)
    if rc == 0:
        print(f"audit signing key: {key_root_only(secrets_dir)}")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the signer's inner step and the key's making (see the module text)")
    ap.add_argument("--inner", action="store_true", help="check, sign and publish; print the result as JSON")
    ap.add_argument("--init-key", action="store_true", help="make the audit signing key if there is none")
    ap.add_argument("--audit", type=Path)
    ap.add_argument("--secrets", type=Path, required=True)
    ap.add_argument("--to", type=Path, action="append", default=[])
    a = ap.parse_args(argv)
    if a.init_key:
        return init_key(a.secrets)
    if not a.inner or a.audit is None:
        ap.error("--inner needs --audit")
    production = (os.environ.get("TB_ENV") or "PRODUCTION").strip().upper() == "PRODUCTION"
    night = check_and_sign(a.audit, a.secrets, a.to, datetime.now(UTC), probe=True, refuse_open=production)
    print(json.dumps(asdict(night), ensure_ascii=False))
    return 0  # the answer is the JSON: a non-zero exit means the signer itself broke


if __name__ == "__main__":
    raise SystemExit(main())

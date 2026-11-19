"""The update path (TB-PLAN-04 step 8, D-138): an offline signed bundle, backed up first, applied, migrated,
restarted, checked, and rolled back when anything fails.

``tools/apply_update.sh BUNDLE.tar`` verifies the bundle (Ed25519 signature of the manifest with the box's vendor
key, every payload's size and sha256: ``tools/verify_update.py``, D-77) and stages it; then it runs this module:

    python3 -m tools.trialbox update --stage <staged payloads> --summary <verify summary> [--target compose|demo]

1. **Backup first** (D-126). The box's own encrypted backup (``trialbox backup``) to ``TB_BACKUP_TARGETS``, to the
   hospital's public key (``deploy/secrets/backup.pub``). No key or no target: the update refuses and changes
   nothing (``--no-backup`` skips it, and the skip is audited; for a test box only). D-1321: on a PRODUCTION box
   the command line refuses ``--no-backup`` without ``--no-backup-reason REASON`` (exit 2, :func:`no_backup_refused`);
   the reason is audited as ``update.backup_skipped`` and written in the history.
2. **Rollback point**. The images the bundle replaces are tagged ``<repo>:rollback-<bundle>``; every model file
   it overwrites is copied aside; the trial database (and HAPI's) is dumped locally, 0600 under
   ``deploy/updates/<bundle>/rollback/``. The encrypted backup needs the hospital's private key, which the box does
   not hold (D-126), so the automatic rollback uses this local dump; it is removed after a good update.
3. **Apply**: the host tree (payload kind ``host``, T-631, D-367: the compose files, host tools and configuration,
   unpacked to ``<install>/releases/<bundle>`` and named by the ``<install>/current`` link, ``tools/host_tree.py``),
   images (``docker load``), models, other files; **migrate and restart**: the services run their
   versioned migrations at start (``tb_common.db``, D-126), so a restart on the new images is the migration;
   then the rulesets of the bundle (criteria-compiler import with the approval and equivalence gates) and its
   reference data pack (payload kind ``refdata``, ``trialbox-refdata-<date>.tar``: verified and loaded into the
   schema ``refdata`` of the trial database, ``tb_common.refdata``, D-140; the database dump of step 2 rolls it
   back with everything else).
4. **Check**: every service healthy (``up --wait``), plus ``TB_UPDATE_CHECK_CMD`` when set; the demo box runs
   ``e2e_simple`` in the updated container.
5. **Success**: ``update.applied`` in the hash-chained audit log, the history line, the local dump removed.
   **Any failure** after step 2: ``current`` names the previous release again, the old images are tagged back, the
   models put back, the database restored from the local dump, the services restarted and checked again;
   ``update.rolled_back`` is audited; exit 1.

Every step is written to ``deploy/updates/history.jsonl`` (no secret in it). Three boxes implement the steps:
:class:`ComposeBox` (a site box, ``docker compose``), :class:`DemoBox` (the one-container demo VM, D-111) and
:class:`InProcessBox` (the in-process box of ``e2e_simple``: ``tools/update_drill.py`` exercises the whole path on
it, with a real backup, a real ``pg_dump`` / ``pg_restore`` and real migrations). Standard library only at import.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from tools import host_tree, image_pins

ROOT = Path(__file__).resolve().parents[2]
PY_SERVICES = (
    "lake",
    "embed-service",
    "doc-parser",
    "criteria-compiler",
    "adapter",
    "orchestrator",
    "mail-gateway",
    "gateway",
    "console",
    "audit-writer",  # D-394: the one writer of the audit chain
)
# the backup container's folders and the volume each is read from (D-455: their size sets its time limit)
BACKUP_VOLUMES = {
    "lake": "lake-data",
    "objects": "objects-data",
    "audit": "audit-data",
    "rulesets": "rulesets-data",
    "orchestrator": "orch-data",
    "mail": "mail-data",
    "secrets": "tb-secrets",
    "console": "console-data",
    "terminology": "tb-terminology",  # D-991: the code systems loaded at install
}


FHIR_PW = "TB_DB_PW_FHIR_STORE"  # D-541: the FHIR store's own database role


class UpdateFailed(RuntimeError):
    pass


#: D-633: the environments of a site box (an unset TB_ENV is PRODUCTION, D-127)
STRICT_ENVS = ("PRODUCTION", "VALIDATION")


class UpdateRefused(UpdateFailed):
    """A preflight refusal: nothing on the box was changed (no marker, no backup, no service stopped)."""


# The steps, in order, as the marker (deploy/updates/IN_PROGRESS.json) names them (D-210).
STEPS = ("backup", "rollback point", "apply", "migrate and restart", "rulesets", "check", "refdata", "finish")
SPACE_MARGIN = 1.10


@dataclass
class Plan:
    bundle_id: str
    manifest_sha256: str
    signer: str
    files: list[dict[str, Any]]
    stage: Path
    release_seq: int | None = None  # None: a plan built by hand (tests); the CLI requires a D-210 summary
    min_installed_version: int = 0
    key_id: str = ""
    compat: dict[str, Any] | None = None
    trust_after: dict[str, Any] | None = None
    downgrade: dict[str, Any] | None = None
    release: dict[str, Any] | None = None
    trust_sha256: str | None = None  # the trust.json verify read (None: none, the deploy/keys files)
    no_backup_reason: str | None = None  # D-1321: why the backup is skipped (--no-backup-reason), audited

    @classmethod
    def load(cls, stage: Path, summary: dict[str, Any]) -> Plan:
        seq = summary.get("release_seq")
        return cls(
            str(summary["bundle_id"]),
            str(summary.get("manifest_sha256", "")),
            str(summary.get("signer", "")),
            list(summary.get("files") or []),
            stage,
            int(seq) if seq is not None else None,
            int(summary.get("min_installed_version") or 0),
            str(summary.get("key_id") or ""),
            summary.get("compat"),
            summary.get("trust_after"),
            summary.get("downgrade"),
            summary.get("release"),
            summary.get("trust_sha256"),
        )

    def kind(self, kind: str) -> Path:
        return self.stage / kind

    def payload_bytes(self, kind: str) -> int:
        d = self.kind(kind)
        return sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.is_dir() else 0


@dataclass
class Point:
    """What a rollback needs: retagged images, model files copied aside or new, the local database dumps (sealed),
    the rulesets repository's refs, the update state files as they were."""

    images: dict[str, str] = field(default_factory=dict)  # tag -> rollback tag ("" when the tag is new)
    models_saved: list[str] = field(default_factory=list)
    models_new: list[str] = field(default_factory=list)
    dumps: dict[str, str] = field(default_factory=dict)  # database -> dump file (sealed: <name>.dump.enc)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def read(cls, rb: Path) -> Point:
        data = json.loads((rb / "point.json").read_text(encoding="utf-8"))
        return cls(**{k: data[k] for k in ("images", "models_saved", "models_new", "dumps", "extra") if k in data})


def save_point(rb: Path, point: Point) -> None:
    """``rb/point.json`` rewritten atomically (after the rollback point and after every model file copied), so a
    rollback after a crash knows everything that was changed."""
    from tools.update_status import write_atomic

    write_atomic(rb / "point.json", point.__dict__)


STATE_BEFORE = "state.before.json"
FINISHED = "finished"


def record_state(updates: Path, rb: Path) -> None:
    """``rb/state.before.json``: installed.json and trust.json as they are (their text, or null when absent), written
    atomically before the marker exists."""
    from tools import update_status as us

    rec: dict[str, str | None] = {}
    for name in (us.INSTALLED, us.TRUST):
        try:
            rec[name] = (updates / name).read_text(encoding="utf-8")
        except FileNotFoundError:
            rec[name] = None
    us.write_atomic(rb / STATE_BEFORE, rec)


def drop_secrets(rb: Path) -> None:
    """The rollback dumps (sealed or not) and the key that opens them."""
    for p in [rb / SEAL_KEY, *rb.glob("*.dump"), *rb.glob("*.dump.enc"), *rb.glob("*.restore")]:
        p.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def image_tags(tar: Path) -> list[str]:
    """The repo:tag names a ``docker save`` archive carries (its manifest.json)."""
    try:
        with tarfile.open(tar, "r:*") as tf:
            m = tf.extractfile("manifest.json")
            data = json.loads(m.read()) if m else []
    except (tarfile.TarError, KeyError, OSError, ValueError):
        return []
    return [t for entry in data for t in (entry.get("RepoTags") or [])]


def tar_images(tar: Path) -> tuple[dict[str, str], set[str]]:
    """A ``docker save`` archive's ``{tag: config digest}`` (manifest.json ``Config``: ``<hex>.json`` or
    ``blobs/sha256/<hex>``) and the manifest digests of its index.json (an OCI layout, Docker 25 and later). The
    archive's sha256 is verified with the bundle, so these name exactly what ``docker load`` will load."""
    configs: dict[str, str] = {}
    manifests: set[str] = set()
    try:
        with tarfile.open(tar, "r:*") as tf:
            m = tf.extractfile("manifest.json")
            for entry in json.loads(m.read()) if m else []:
                name = PurePosixPath(str(entry.get("Config") or "")).name.removesuffix(".json")
                digest = f"sha256:{name}" if re.fullmatch(r"[0-9a-f]{64}", name) else ""
                for t in entry.get("RepoTags") or []:
                    configs[t] = digest
            try:
                ix = tf.extractfile("index.json")
            except KeyError:
                ix = None
            for d in (json.loads(ix.read()) if ix else {}).get("manifests") or []:
                if isinstance(d, dict) and isinstance(d.get("digest"), str):
                    manifests.add(d["digest"])
    except (tarfile.TarError, KeyError, OSError, ValueError, AttributeError):
        return {}, set()
    return configs, manifests


def rollback_tag(tag: str, bundle_id: str) -> str:
    repo = tag.rsplit(":", 1)[0] if ":" in tag.rsplit("/", 1)[-1] else tag
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in bundle_id)[:100]
    return f"{repo}:rollback-{safe}"


def copy_models(src: Path, dest: Path, rb: Path, point: Point) -> list[str]:
    """Copy the bundle's model files over ``dest``; every file it overwrites is kept in ``rb/models``."""
    done: list[str] = []
    if not src.is_dir():
        return done
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src).as_posix()
        target = dest / rel
        if target.exists():
            keep = rb / "models" / rel
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, keep)
            point.models_saved.append(rel)
        else:
            point.models_new.append(rel)
        save_point(rb, point)  # before the copy: a crash mid-copy still knows to put this file back
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        done.append(f"model {rel}")
    return done


def restore_models(dest: Path, rb: Path, point: Point) -> None:
    for rel in point.models_new:
        (dest / rel).unlink(missing_ok=True)
    for rel in point.models_saved:
        shutil.copy2(rb / "models" / rel, dest / rel)


def refdata_packs(plan: Plan) -> list[Path]:
    """The reference data packs of a bundle (payload kind ``refdata``), oldest date first."""
    rd = plan.kind("refdata")
    return sorted(p for p in rd.rglob("*.tar") if p.is_file()) if rd.is_dir() else []


def host_tars(plan: Plan) -> list[Path]:
    """The bundle's host tree (payload kind ``host``; verify_update.py allows at most one)."""
    d = plan.kind("host")
    return sorted(p for p in d.rglob("*.tar") if p.is_file()) if d.is_dir() else []


def apply_host(plan: Plan, base: Path, rb: Path, point: Point) -> list[str]:
    """T-631, D-367: the release's host tree to ``base/releases/<bundle>``, ``base/current`` switched to it. What a
    rollback needs is in the rollback point before anything moves (a crash mid-way still knows the previous release)."""
    tars = host_tars(plan)
    if not tars:
        return []
    point.extra["host"] = {"previous": host_tree.current(base), "release": plan.bundle_id,
                           "fresh": not (base / "releases" / plan.bundle_id).exists()}  # fmt: skip
    save_point(rb, point)
    try:
        info = host_tree.install(tars[0], base, plan.bundle_id)
    except host_tree.HostTreeError as exc:
        raise UpdateFailed(f"host tree: {exc}") from exc
    point.extra["host"] = info
    save_point(rb, point)
    return [f"host tree {plan.bundle_id}: {base / 'current'} -> releases/{plan.bundle_id} (previous: "
            f"{info['previous'] or 'none'}; {len(info['moved'])} copied files set aside)"]  # fmt: skip


def restore_host(base: Path, point: Point) -> None:
    info = point.extra.get("host")
    if info:
        host_tree.restore(base, info)


def copy_other(src: Path, dest: Path) -> list[str]:
    if not src.is_dir():
        return []
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return [f"other {p.relative_to(src).as_posix()}" for p in sorted(src.rglob("*")) if p.is_file()]


# ------------------------------------------------------------------------------------------------ sealed dumps
SEAL_MAGIC = b"TBDUMP1\n"
SEAL_KEY = "dump.key"
_CHUNK = 1 << 20


def seal(dump: Path, rb: Path) -> Path:
    """Encrypt a rollback dump in place (AES-256-GCM in 1 MiB chunks, a random key per update in ``rb/dump.key``,
    0600) and remove the plaintext. Without the ``cryptography`` package (a bare host python3) the dump stays as it is
    (0600 in a 0700 folder); either way it is deleted when the update or its rollback completes."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        os.chmod(dump, 0o600)
        return dump
    kf = rb / SEAL_KEY
    if not kf.is_file():
        fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(os.urandom(32))
    aes = AESGCM(kf.read_bytes())
    out = dump.with_name(dump.name + ".enc")
    prefix = os.urandom(8)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with dump.open("rb") as fin, os.fdopen(fd, "wb") as fout:
        fout.write(SEAL_MAGIC + prefix)
        i, chunk = 0, fin.read(_CHUNK)
        while True:
            nxt = fin.read(_CHUNK) if chunk else b""
            flag = b"\x01" if not nxt else b"\x00"
            ct = aes.encrypt(prefix + i.to_bytes(4, "big"), chunk, flag)
            fout.write(flag + len(ct).to_bytes(4, "big") + ct)
            i += 1
            if not nxt:
                break
            chunk = nxt
        fout.flush()
        os.fsync(fout.fileno())
    dump.unlink()
    return out


def unseal(sealed: Path, rb: Path, out: Path) -> Path:
    """The plaintext of a sealed dump in ``out`` (0600) for ``pg_restore``; a dump that was never sealed is itself."""
    if not sealed.name.endswith(".enc"):
        return sealed
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aes = AESGCM((rb / SEAL_KEY).read_bytes())
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with sealed.open("rb") as fin, os.fdopen(fd, "wb") as fout:
        if fin.read(len(SEAL_MAGIC)) != SEAL_MAGIC:
            raise UpdateFailed(f"{sealed} is not a sealed dump")
        prefix, i = fin.read(8), 0
        while True:
            head = fin.read(5)
            if len(head) != 5:
                raise UpdateFailed(f"{sealed} is truncated")
            flag, n = head[:1], int.from_bytes(head[1:], "big")
            fout.write(aes.decrypt(prefix + i.to_bytes(4, "big"), fin.read(n), flag))
            i += 1
            if flag == b"\x01":
                break
    return out


def _with_plain(sealed: Path, rb: Path, use: Callable[[Path], None]) -> None:
    plain = unseal(sealed, rb, rb / (sealed.name.removesuffix(".enc") + ".restore"))
    try:
        use(plain)
    finally:
        if plain != sealed:
            plain.unlink(missing_ok=True)


# 10G-1 review D3: the update's one-off runs into criteria-compiler, by name (removed before a run and after one that
# failed or ran out of time), and the folder a reference pack unpacks in: the objects volume, not the tmpfs /tmp.
# REFDATA_SWEEP_SH clears what a stopped load left there, by the loader's own folder prefix
# (``tb_common.refdata.opened``: ``mkdtemp(prefix="tb-refdata-")``); only these one-off runs set TMPDIR to it.
RULESET_RUN = "tb-ruleset-import"
REFDATA_RUN = "tb-refdata-load"
REFDATA_SWEEP = "tb-refdata-sweep"
REFDATA_TMPDIR = "/data/objects"
REFDATA_SWEEP_SH = 'rm -rf -- "${TMPDIR:?}"/tb-refdata-*'


# ------------------------------------------------------------------------------------------------ database restore
# The compose box's rollback restore (ComposeBox.restore_databases), run in the db container: $1 role, $2 database,
# $3 RESET_SQL; the dump on stdin. The script goes to a 0600 file (pg_restore from a pipe into psql would let psql
# commit a cut-off script), RESET_SQL and the script run as one transaction, the file is deleted whatever happens.
# 10G-1 (H10G1-05): the file is on the db volume, not in db's /tmp (a tmpfs: memory, capped at 64m): a folder of its
# own under PGDATA (the volume's mount point is PGDATA itself, so no sibling exists; the only other postgres-owned
# mount, the pgBackRest repository, is the hospital's off-box share when archiving is on, no place for a plaintext
# script). 0700, emptied first (a killed rollback's leftover) and removed on every exit. ``space_needs`` counts it.
RESTORE_DIR = "${PGDATA:?}/tb-rollback"
RESTORE_SH = (
    f'umask 077; d="{RESTORE_DIR}"; rm -rf -- "$d"; mkdir -m 0700 "$d" || exit 1; '
    "trap 'rm -rf -- \"$d\"' EXIT; trap 'exit 1' HUP INT TERM; "
    't=$(mktemp -p "$d") || exit 1; '
    'pg_restore --clean --if-exists --no-owner -f "$t" || exit 1; '
    '{ printf "%s\\n" "$3"; cat "$t"; } | psql -X -q -v ON_ERROR_STOP=1 --single-transaction -U "$1" -d "$2"'
)
# Everything the role owns that a later release could have added: its schemas (not public, not an extension's) and
# its relations in public (not an extension's). D-541: and what the database's owner owns (the FHIR store's own role
# owns `hapi`'s tables; the restore runs as the superuser). The dump's script then re-creates exactly what it holds.
RESET_SQL = """DO $tb$
DECLARE r record;
BEGIN
  FOR r IN SELECT n.nspname FROM pg_namespace n
           WHERE n.nspowner IN ((SELECT oid FROM pg_roles WHERE rolname = current_user),
                                (SELECT datdba FROM pg_database WHERE datname = current_database()))
             AND n.nspname <> 'public' AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_namespace'::regclass
                             AND d.objid = n.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('DROP SCHEMA %I CASCADE', r.nspname);
  END LOOP;
  FOR r IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
             AND c.relowner IN ((SELECT oid FROM pg_roles WHERE rolname = current_user),
                                (SELECT datdba FROM pg_database WHERE datname = current_database()))
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                             AND d.objid = c.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('DROP %s IF EXISTS public.%I CASCADE', CASE r.relkind WHEN 'v' THEN 'VIEW'
      WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'S' THEN 'SEQUENCE' WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END,
      r.relname);
  END LOOP;
END
$tb$;"""


# ------------------------------------------------------------------------------------------------ rulesets repo
# Run with the rulesets image's own python (dulwich; criteria_compiler.repo): "snapshot <tag>" prints every ref and
# tags main; "restore <refs-json>" puts every ref back, drops refs made since, and rewrites the working copy.
RULESETS_PY = r"""
import json, os, sys
from pathlib import Path
p = Path(os.environ.get("TB_RULESETS_DIR") or "/data/rulesets")
if not (p / ".git").exists():
    print("{}"); sys.exit(0)
from dulwich.repo import Repo
r = Repo(str(p))
if sys.argv[1] == "snapshot":
    refs = {k.decode(): v.decode() for k, v in r.get_refs().items() if k != b"HEAD"}
    if "refs/heads/main" in refs:
        r.refs[sys.argv[2].encode()] = refs["refs/heads/main"].encode()
    print(json.dumps(refs))
else:
    want = json.loads(sys.argv[2])
    keep = b"refs/tags/trialbox-update/"
    for k in list(r.get_refs()):
        if k != b"HEAD" and k.decode() not in want and not k.startswith(keep):
            del r.refs[k]
    for k, v in want.items():
        r.refs[k.encode()] = v.encode()
    from criteria_compiler.repo import RulesetRepo
    RulesetRepo(p).materialize_all("main")
    print("{}")
"""


def rulesets_tag(bundle_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in bundle_id)[:100]
    return f"refs/tags/trialbox-update/{safe}-before"


def _last_json(out: str) -> dict[str, Any]:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        return {}
    data = json.loads(lines[-1])
    return data if isinstance(data, dict) else {}


SCHEMA_SQL = (
    "SELECT table_schema, (xpath('/row/m/text()', query_to_xml(format('SELECT max(version) AS m FROM %I."
    "_schema_version', table_schema), false, true, '')))[1]::text FROM information_schema.tables "
    "WHERE table_name = '_schema_version'"
)


def _schema_rows(lines: Sequence[tuple[str, str | None]], prefix: str = "") -> dict[str, int]:
    out = {}
    for schema, v in lines:
        if prefix and not schema.startswith(prefix):
            continue
        out[schema[len(prefix) :]] = int(v or 0)
    return out


def _gb(n: float) -> str:
    return f"{n / 1e9:.2f} GB"


def _existing(p: Path) -> Path:
    p = p.absolute()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


class Box(Protocol):
    name: str

    def running(self) -> bool: ...
    def backup(self, plan: Plan, rb: Path) -> str: ...
    def snapshot(self, plan: Plan, rb: Path, point: Point) -> None: ...
    def apply(self, plan: Plan, rb: Path, point: Point) -> list[str]: ...
    def restart(self, plan: Plan) -> None: ...
    def post_apply(self, plan: Plan) -> list[str]: ...
    def check(self, plan: Plan) -> str: ...
    def rollback(self, plan: Plan, rb: Path, point: Point) -> None: ...
    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None: ...

    # D-210, optional on a box (the Updater falls back when a box lacks them): ``resume`` restarts what ``backup``
    # stopped; ``rulesets`` and ``refdata`` split ``post_apply``; ``space_needs`` lists (path, bytes, what) for the
    # free-space preflight; ``installed_state`` reads the schema versions from the database for compat.json;
    # ``preflight`` refuses a bundle the box can tell is wrong before anything changes (a changed migration).


class Updater:
    """Runs the steps on a :class:`Box` and keeps the update state (``deploy/updates/``, ``tools/update_status.py``):
    the history, the marker, the installed record and the trust."""

    def __init__(
        self,
        box: Box,
        updates_dir: Path,
        say: Callable[[str], None] = print,
        disk_free: Callable[[Path], int] | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> None:
        self.box = box
        self.dir = updates_dir
        self.say = say
        self.disk_free = disk_free or (lambda p: shutil.disk_usage(p).free)
        self.on_step = on_step  # called after the marker names a step, before the step runs (the kill -9 drill)

    def _history(self, plan: Plan, step: str, ok: bool, detail: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        line = {"at": _now(), "bundle": plan.bundle_id, "box": self.box.name, "step": step, "ok": ok, "detail": detail}
        with (self.dir / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.say(f"{'ok  ' if ok else 'FAIL'}  {step}" + (f": {detail}" if detail else ""))

    # -------------------------------------------------------------------------------------------- preflight
    def state(self) -> dict[str, Any]:
        """The box's state for compat.json: the recorded one, with the schema versions read from the database."""
        from tools.update_status import installed

        st = dict(installed(self.dir).get("state") or {})
        live = getattr(self.box, "installed_state", None)
        if live is not None:
            st["schema"] = live()
        return st

    def environment(self) -> str:
        """The box's environment as the box itself names it (``Box.environment``); a box that cannot say, or says a
        name that is none of the four, counts as PRODUCTION (D-633: the strict side)."""
        named = getattr(self.box, "environment", None)
        env = str(named()).strip().upper() if callable(named) else "PRODUCTION"
        return env if env in ("PRODUCTION", "VALIDATION", "DEV", "TEST") else "PRODUCTION"

    def _from_a_commit(self, plan: Plan) -> list[str]:
        """D-633 (the owner's decision of 2026-11-13): a PRODUCTION or VALIDATION box takes only a release built
        from a commit. ``release.json`` (signed with the bundle) says ``source.dirty`` when ``tools/make_bundle.sh``
        was run with ``--allow-dirty`` on a working tree (D-631), and names the commit. A bundle with no release
        record cannot say and is taken as before, with a note (the verifier refuses images without one; a host
        tree alone can come without one, see the decision record); a record that does not answer or names no
        commit is refused on such a box."""
        env = self.environment()
        strict = env in STRICT_ENVS
        if plan.release is None:
            return [
                "the bundle has no release record (release.json): it does not say whether it was built from a commit"
            ]
        if not strict:
            return []
        rehearsal_box = getattr(self.box, "rehearsal_box", None)
        if rehearsal_box is not None and env == "VALIDATION" and rehearsal_box():
            # D-887 (the integrator's (i)): a rehearsal box is VALIDATION, marked by deploy/install.sh --rehearsal
            # (deploy/site/rehearsal.json and TB_REHEARSAL=1): it takes the rehearsal bundle of a working tree. A
            # VALIDATION box without the mark refuses it below, as before; a PRODUCTION box always does
            return []
        if plan.release.get("rehearsal") is True:  # D-726: tools/make_bundle.sh --rehearsal
            raise UpdateRefused(
                f"{plan.bundle_id} is a rehearsal bundle (release.json says rehearsal; tools/make_bundle.sh "
                f"--rehearsal): a {env} box refuses it. It goes on a rehearsal box (deploy/install.sh --rehearsal)"
            )
        source = plan.release.get("source")
        dirty = source.get("dirty") if isinstance(source, dict) else None
        if dirty is True:
            raise UpdateRefused(
                f"{plan.bundle_id} was built from a working tree, not from a commit (release.json says dirty; "
                f"tools/make_bundle.sh --allow-dirty): a {env} box takes only a release built from a commit. A "
                "rehearsal bundle goes on a DEV or TEST box (TB_ENV in deploy/.env)"
            )
        if dirty is not False:
            raise UpdateRefused(
                f"{plan.bundle_id}: its release.json does not say whether it was built from a commit "
                f"(source.dirty is {dirty!r}): a {env} box refuses it"
            )
        commit = source.get("commit") if isinstance(source, dict) else None
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise UpdateRefused(
                f"{plan.bundle_id}: its release.json names no commit (source.commit is {commit!r}; a build outside "
                f"a git checkout): a {env} box takes only a release built from a commit"
            )
        return []

    def _tls_old_clients(self) -> list[str]:
        """H-48 (D-1328): a site box's update recreates Caddy from deploy/.env (``up -d``), so a TB_TLS_OLD_CLIENTS
        that is not off or cbc, or not the value deploy/install.sh last audited, is refused before anything changes:
        the operator runs deploy/install.sh, which checks it and sends the audit event."""
        deploy = getattr(self.box, "deploy", None)
        if getattr(self.box, "name", "") != "compose" or deploy is None:
            return []
        from tools.tls_policy import old_clients_state

        value, _audited, problem = old_clients_state(getattr(self.box, "env", {}), Path(deploy) / "site")
        if problem:
            raise UpdateRefused(f"{problem}; nothing was changed")
        return [] if value == "off" else [f"TB_TLS_OLD_CLIENTS={value} (audited): 443 serves the old-client suites"]

    def preflight(self, plan: Plan, backup: bool = True) -> list[str]:
        """Every refusal that needs nothing changed: compat.json against the live box, the release sequence, the
        box's own checks, the free space. Raises :class:`UpdateRefused`; returns notes."""
        from tools import update_status as us

        notes: list[str] = []
        notes += self._tls_old_clients()
        notes += self._from_a_commit(plan)
        if plan.release_seq is not None:
            inst = us.installed(self.dir)
            have = int(inst["release_seq"])
            if have < plan.min_installed_version:
                raise UpdateRefused(f"the box is at release_seq {have}; {plan.bundle_id} needs at least "
                                    f"{plan.min_installed_version} (min_installed_version)")  # fmt: skip
            if plan.release_seq <= have and not plan.downgrade:
                raise UpdateRefused(f"release_seq {plan.release_seq} is not above the installed {have}: refused "
                                    "(tools/apply_update.sh --allow-downgrade REASON, audited)")  # fmt: skip
            if plan.release_seq > have and plan.downgrade:
                plan.downgrade = None  # another update moved the box since verify: not a downgrade any more
            if plan.compat is None:
                raise UpdateRefused("the bundle has no compatibility table (compat.json)")
            now_sha = us.file_sha256(self.dir / us.TRUST)
            if now_sha != plan.trust_sha256:
                raise UpdateRefused(
                    "trust.json changed since this bundle was verified (another update or a key rotation in "
                    "between): run tools/apply_update.sh again; nothing was changed"
                )
        if plan.compat is not None:
            try:
                state = self.state()
            except Exception as exc:
                raise UpdateRefused(f"could not read the box's schema versions for compat.json: {exc}") from exc
            ok, why, cnotes = us.compat_check(plan.compat, state)
            if not ok:
                raise UpdateRefused(f"compatibility table (compat.json): {why}")
            notes += [why, *cnotes]
        ready = getattr(self.box, "backup_ready", None)
        if backup and ready is not None:
            try:
                notes.append(ready())
            except UpdateFailed as exc:
                raise UpdateRefused(f"backup not possible, nothing was changed: {exc}") from exc
        own = getattr(self.box, "preflight", None)
        if own is not None:
            notes += own(plan)
        needs = getattr(self.box, "space_needs", None)
        if needs is not None:
            notes += self.space(needs(plan, self.dir))
        return notes

    def space(self, needs: Sequence[tuple[Path, int, str]]) -> list[str]:
        """Sum the needs per file system (st_dev) and refuse with the numbers when one is short."""
        per: dict[int, dict[str, Any]] = {}
        for path, n, what in needs:
            if n <= 0:
                continue
            ex = _existing(path)
            d = per.setdefault(os.stat(ex).st_dev, {"path": ex, "need": 0, "what": []})
            d["need"] += n
            d["what"].append(f"{what} {_gb(n)}")
        short: list[str] = []
        notes: list[str] = []
        for d in per.values():
            need = int(d["need"] * SPACE_MARGIN)
            free = int(self.disk_free(d["path"]))
            line = (f"{d['path']}: needs {_gb(need)} ({', '.join(d['what'])}, + 10 %), free {_gb(free)}"
                    f" [{need} / {free} bytes]")  # fmt: skip
            (short if free < need else notes).append(line)
        if short:
            raise UpdateRefused("not enough disk space: " + "; ".join(short) + "; nothing was changed")
        return notes

    # -------------------------------------------------------------------------------------------- the run
    def run(self, plan: Plan, backup: bool = True) -> dict[str, Any]:
        from tools import update_status as us

        try:
            with us.locked(self.dir):
                if us.marker(self.dir) is not None:
                    m = us.marker(self.dir) or {}
                    who = m.get("bundle_id")
                    raise UpdateRefused(
                        f"update {who} is unfinished (step {m.get('step')!r}): "
                        f"tools/apply_update.sh status, then rollback {who}"
                    )
                notes = self.preflight(plan, backup)
                for n in notes:
                    self.say(f"      preflight: {n}")
                return self._run(plan, backup)
        except us.Busy as exc:
            raise UpdateRefused(str(exc)) from exc

    def _run(self, plan: Plan, backup: bool) -> dict[str, Any]:
        from tools import update_status as us

        rb = self.dir / plan.bundle_id / "rollback"
        if rb.exists():  # a left-over of an earlier, finished attempt of this bundle (dumps included)
            shutil.rmtree(rb)
        rb.mkdir(parents=True, exist_ok=True)
        os.chmod(rb, 0o700)
        record_state(self.dir, rb)  # before the marker: a marker never exists without the state it rolls back to
        m = us.create_marker(self.dir, {"bundle_id": plan.bundle_id, "manifest_sha256": plan.manifest_sha256,
                                        "release_seq": plan.release_seq, "target": self.box.name,
                                        "rollback_dir": str(rb), "stage": str(plan.stage), "step": None,
                                        "downgrade": plan.downgrade})  # fmt: skip
        steps: list[tuple[str, bool, str]] = []

        def enter(name: str) -> None:
            us.set_step(self.dir, m, name)
            if self.on_step:
                self.on_step(name)

        def step(name: str, ok: bool, detail: str = "") -> None:
            steps.append((name, ok, detail))
            self._history(plan, name, ok, detail)

        if plan.downgrade:
            self.box.audit("update.downgrade", plan, {"bundle_id": plan.bundle_id, **plan.downgrade})
            step("downgrade allowed (audited update.downgrade)", True, str(plan.downgrade.get("reason", "")))
        enter("backup")
        if backup:
            try:
                where = self.box.backup(plan, rb)
            except Exception as exc:
                step("backup (D-126)", False, f"{exc}; nothing was changed")
                self._abandon(plan, rb)
                raise UpdateFailed(f"backup failed, nothing was changed: {exc}") from exc
            step("backup (D-126)", True, where)
        elif plan.no_backup_reason:  # D-1321: the reason, audited as the downgrade's is
            self.box.audit("update.backup_skipped", plan,
                           {"bundle_id": plan.bundle_id, "reason": plan.no_backup_reason})  # fmt: skip
            step("backup skipped (--no-backup, audited update.backup_skipped)", True, plan.no_backup_reason)
        else:
            step("backup skipped (--no-backup)", True, "audited")
        enter("rollback point")
        point = Point()
        try:
            self.box.snapshot(plan, rb, point)
            save_point(rb, point)
        except Exception as exc:
            step("rollback point", False, f"{exc}; nothing was changed")
            self._abandon(plan, rb)
            raise UpdateFailed(f"could not take the rollback point, nothing was changed: {exc}") from exc
        step("rollback point", True, f"{len(point.images)} images, {len(point.dumps)} databases")
        failed: str | None = None
        try:
            enter("apply")
            applied = self.box.apply(plan, rb, point)
            save_point(rb, point)
            step("apply", True, f"{len(applied)} payloads")
            enter("migrate and restart")
            self.box.restart(plan)
            step("migrate and restart", True)
            enter("rulesets")
            rulesets = getattr(self.box, "rulesets", None)
            done = rulesets(plan) if rulesets is not None else self.box.post_apply(plan)
            step("rulesets", True, f"{len(done)} imported")
            enter("check")
            step("check", True, self.box.check(plan))
        except (Exception, KeyboardInterrupt) as exc:  # Ctrl-C rolls back too; kill -9 leaves the marker
            failed = f"{type(exc).__name__}: {exc}"
            step("update", False, failed)
        if failed is not None:
            rolled = self._rollback(plan, rb, point)
            self.box.audit("update.rolled_back", plan,
                           {"bundle_id": plan.bundle_id, "error": failed[:500], "rolled_back": rolled})  # fmt: skip
            if rolled:
                self._done(plan, rb)
            raise UpdateFailed(
                f"update {plan.bundle_id} failed ({failed}); "
                + ("rolled back" if rolled else "ROLLBACK FAILED (the marker stays: tools/apply_update.sh status)")
            )
        enter("refdata")
        refdata_note = ""
        refdata = getattr(self.box, "refdata", None)
        if refdata is not None:
            try:  # its own step: one transaction; a failure leaves the healthy release in place (D-17)
                loaded = refdata(plan)
                step("reference data", True, f"{len(loaded)} packs loaded")
            except Exception as exc:
                refdata_note = f"{type(exc).__name__}: {exc}"[:500]
                step("reference data", False, f"{refdata_note}; the release stays; load the pack again "
                                              "(python -m tb_common.refdata load)")  # fmt: skip
        enter("finish")
        self._record(plan)
        self.box.audit(
            "update.applied",
            plan,
            {"bundle_id": plan.bundle_id, "signer": plan.signer, "files": plan.files, "backup": backup,
             "release_seq": plan.release_seq, "key_id": plan.key_id,
             "rotation": plan.manifest_sha256 in (plan.trust_after or {}).get("rotations", []),
             "refdata_failed": refdata_note or None, "rollback_point_removed": True},
        )  # fmt: skip
        step("audited update.applied", True)
        self._done(plan, rb)
        return {"ok": True, "bundle_id": plan.bundle_id, "steps": steps, "refdata_failed": refdata_note or None}

    def _record(self, plan: Plan, live: bool = True) -> None:
        """installed.json and trust.json for the release just checked (atomic writes, under the marker)."""
        from tools import update_status as us

        if plan.release_seq is None:
            return
        prev = us.installed(self.dir).get("state") or {}
        state: dict[str, Any] = {k: prev.get(k) for k in us.DIMENSIONS}
        provides = (plan.compat or {}).get("provides") or {}
        for k in us.DIMENSIONS:
            if provides.get(k) is not None:
                state[k] = provides[k]
        read = getattr(self.box, "installed_state", None) if live else None
        state["schema"] = read() if read is not None else provides.get("schema")
        record = {
            "format": us.INSTALLED_FORMAT,
            "release_seq": plan.release_seq,
            "bundle_id": plan.bundle_id,
            "manifest_sha256": plan.manifest_sha256,
            "key_id": plan.key_id,
            "applied_at": _now(),
            "state": state,
        }
        source = (plan.release or {}).get("source")
        if isinstance(source, dict) and isinstance(source.get("dirty"), bool):
            record["dirty"] = source["dirty"]  # D-633: built from a working tree (a DEV or TEST box took it)
        if plan.release is not None:
            # D-994 (H-15 F1): the commit the release was built from, from the verified release record, so the
            # evidence gates can name the box's code by it (a 40-hex git sha, else null; never an image id)
            commit = source.get("commit") if isinstance(source, dict) else None
            record["commit"] = commit if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) else None
        if (plan.release or {}).get("rehearsal") is True:
            record["rehearsal"] = True  # D-887: the pin reads it (a site box refuses such a bundle)
        marked = getattr(self.box, "rehearsal_mark", None)
        if marked is not None and marked():
            record["rehearsal_box"] = True  # D-887 (i): install.sh --rehearsal's mark, recorded; the pin reads it
        mode = ((plan.release or {}).get("gates") or {}).get("vuln_mode")
        if isinstance(mode, str) and mode:
            record["vuln_mode"] = mode  # D-884: the release gates' mode, said by `apply_update.sh status` and install
        us.write_atomic(self.dir / us.INSTALLED, record)
        if plan.trust_after:
            us.write_atomic(self.dir / us.TRUST, plan.trust_after)

    def _rollback(self, plan: Plan, rb: Path, point: Point) -> bool:
        from tools import update_status as us

        us.set_step(self.dir, us.marker(self.dir) or {}, "rollback")
        try:
            self.box.rollback(plan, rb, point)
            self._restore_state(rb)
            put_back = "host tree, images, models, database, rulesets and update state put back"
            self._history(plan, "rollback", True, put_back)
            self._history(plan, "check after rollback", True, self.box.check(plan))
            return True
        except Exception as exc:
            us.set_step(self.dir, us.marker(self.dir) or {}, "rollback failed")
            self._history(plan, "rollback", False, f"{type(exc).__name__}: {exc} (restore from the backup: RUNBOOK §5)")
            return False

    def _restore_state(self, rb: Path) -> None:
        """installed.json and trust.json as :func:`record_state` recorded them. A file is deleted only when the record
        says it was absent; without a record nothing is touched (the state was never changed without one)."""
        from tools import update_status as us

        rec = us.read_json(rb / STATE_BEFORE)
        if rec is None:
            self.say(f"      update state: no record in {rb}; installed.json and trust.json left as they are")
            return
        for name in (us.INSTALLED, us.TRUST):
            if name not in rec:
                continue
            if rec[name] is None:
                (self.dir / name).unlink(missing_ok=True)
            else:
                us.write_atomic(self.dir / name, rec[name])

    def _abandon(self, plan: Plan, rb: Path) -> None:
        """The update stopped before it changed anything but the services (backup or rollback point failed): start
        the services ``backup`` stopped, then this counts as a completed rollback."""
        resume = getattr(self.box, "resume", None)
        try:
            if resume is not None:
                resume(plan)
            self._history(plan, "services started again", True)
        except Exception as exc:
            self._history(plan, "services started again", False, f"{exc} (the marker stays)")
            return
        self._done(plan, rb)

    def _done(self, plan: Plan, rb: Path) -> None:
        """A completed apply or rollback: the marker goes, then the rollback point (dumps, their key) and any
        left-over point of an earlier update."""
        from tools import update_status as us

        m = us.marker(self.dir)
        if m is not None:
            us.set_step(self.dir, m, FINISHED)  # a crash from here on: `rollback` only cleans up
        drop_secrets(rb)  # the sealed dumps and their key go before the marker does
        us.remove_marker(self.dir)
        shutil.rmtree(rb, ignore_errors=True)
        for old in us.stale_rollback_dirs(self.dir):
            shutil.rmtree(old, ignore_errors=True)

    # -------------------------------------------------------------------------------------------- recovery
    def recover(self, bundle_id: str) -> dict[str, Any]:
        """``tools/apply_update.sh rollback <bundle>``: an update interrupted (power cut, ``kill -9``) at any step is
        rolled back from its marker and ``point.json``; before the rollback point existed only the services are
        started again. Audited ``update.rolled_back``; the marker is removed only when the rollback completed."""
        from tools import update_status as us

        try:
            with us.locked(self.dir):
                m = us.marker(self.dir)
                if m is None:
                    raise UpdateFailed("no update is in progress (no deploy/updates/IN_PROGRESS.json)")
                if m.get("bundle_id") != bundle_id:
                    raise UpdateFailed(f"the unfinished update is {m.get('bundle_id')}, not {bundle_id}")
                rb = Path(str(m["rollback_dir"]))
                plan = Plan(bundle_id, str(m.get("manifest_sha256") or ""), "", [], Path(str(m.get("stage") or rb)))
                step = str(m.get("step"))
                self._history(plan, f"recover from step {step!r}", True, "tools/apply_update.sh rollback")
                if step == FINISHED:  # the apply or the rollback had completed; only the clean-up was cut short
                    self._done(plan, rb)
                    self._history(plan, "clean-up finished", True, "the update had completed; nothing rolled back")
                    return {"ok": True, "bundle_id": bundle_id, "from_step": step}
                if step in ("None", "backup", "rollback point") or not (rb / "point.json").is_file():
                    resume = getattr(self.box, "resume", None)
                    if resume is not None:
                        resume(plan)
                    self._restore_state(rb)
                    self._history(plan, "services started again", True, "nothing else had changed")
                    rolled = True
                else:
                    rolled = self._rollback(plan, rb, Point.read(rb))
                self.box.audit("update.rolled_back", plan, {"bundle_id": bundle_id, "rolled_back": rolled,
                                                            "error": f"interrupted at step {step!r}",
                                                            "recovered": True})  # fmt: skip
                if not rolled:
                    raise UpdateFailed(f"the rollback of {bundle_id} failed; the marker stays (RUNBOOK §5)")
                self._done(plan, rb)
                return {"ok": True, "bundle_id": bundle_id, "from_step": step}
        except us.Busy as exc:
            raise UpdateFailed(str(exc)) from exc


# ------------------------------------------------------------------------------------------------ commands
APPLY_FIXED_S = 3 * 3600  # the update's steps with fixed limits: the 3 h the whole update had before T-695
UP_WAIT_BEFORE_S = 900  # the wait before T-695, kept only where the compose files cannot be read (no PyYAML)
#: T-695 (D-921): the services whose stores are opened at start (each has ``<package>.migrate_stores``), in the
#: order the stack starts them; the host reads no service code, so the list is kept equal by a test
STORE_SERVICES = ("orchestrator", "mail-gateway", "gateway", "criteria-compiler", "console")
Runner = Callable[..., str]  # (argv, stdin_file=None, stdout_file=None, env=None, timeout=None) -> stdout


def run_cmd(
    argv: Sequence[str],
    stdin_file: Path | None = None,
    stdout_file: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> str:
    fin = stdin_file.open("rb") if stdin_file else None
    fout = None
    if stdout_file:
        fd = os.open(stdout_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        fout = os.fdopen(fd, "wb")
    try:
        from tools.trialbox import procgroup

        r = procgroup.run(  # T-695: the whole process group is killed on the limit, never an orphan left
            list(argv),
            stdin=fin,
            stdout=fout or subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
            timeout=timeout,
        )
    finally:
        for f in (fin, fout):
            if f:
                f.close()
    if r.returncode != 0:
        err = (r.stderr or b"").decode(errors="replace").strip()[-600:]
        raise UpdateFailed(f"{shlex.join(list(argv)[:8])} ... exit {r.returncode}: {err}")
    return "" if fout else (r.stdout or b"").decode(errors="replace")


def _env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _image_pins(plan: Plan) -> dict[str, str]:
    """release.json's pinned images: reference -> digest."""
    return {str(r.get("image")): str(r.get("digest")) for r in ((plan.release or {}).get("images") or {}).values()
            if isinstance(r, dict)}  # fmt: skip


class _DockerImages:
    """Shared by the compose and demo boxes: tag the images a bundle replaces, load, tag back."""

    run: Runner

    def snapshot_images(self, plan: Plan, point: Point) -> None:
        img = plan.kind("image")
        for tar in sorted(img.rglob("*")) if img.is_dir() else []:
            for tag in image_tags(tar):
                try:
                    have = self.run(["docker", "image", "inspect", "-f", "{{.Id}}", tag]).strip()
                except UpdateFailed:
                    have = ""
                if have:
                    rt = rollback_tag(tag, plan.bundle_id)
                    self.run(["docker", "tag", have, rt])
                    point.images[tag] = rt
                else:
                    point.images[tag] = ""

    def load_images(self, plan: Plan) -> list[str]:
        img = plan.kind("image")
        done = []
        pins = _image_pins(plan)
        checked: set[str] = set()
        for tar in sorted(p for p in img.rglob("*") if p.is_file()) if img.is_dir() else []:
            configs, manifests = tar_images(tar)
            tags = sorted(configs)
            unpinned = [t for t in tags if t not in pins]
            if plan.release is not None and (not tags or unpinned):  # every tag it would move is checked
                raise UpdateFailed(f"image {tar.name}: tags {unpinned or tags} are not pinned by release.json")
            for tag in tags:  # before loading: the archive's config digest is the pin (D-210)
                if tag in pins and configs[tag] != pins[tag]:
                    raise UpdateFailed(f"image {tar.name}: {tag} has config {configs[tag] or '(none)'}, "
                                       f"release.json pins {pins[tag]}; nothing loaded")  # fmt: skip
            self.run(["docker", "load", "-i", str(tar)], timeout=3600)
            done.append(f"image {tar.name}")
            for tag in tags:
                self.check_loaded(plan, tag, {configs[tag], *manifests} - {""})
                checked.add(tag)
        if done and plan.release is not None and set(pins) - checked:
            raise UpdateFailed(f"release.json pins images this bundle did not load: {sorted(set(pins) - checked)}")
        return done

    def check_loaded(self, plan: Plan, tag: str, accepted: set[str]) -> None:
        """After ``docker load``, the tag names what the archive held: its ``{{.Id}}`` is the archive's config digest
        (the classic store; checked equal to the pin before loading) or one of its index.json manifest digests (the
        containerd store). Anything else (the tag already pointed elsewhere and the load did not move it) fails the
        apply, which rolls back."""
        if tag not in _image_pins(plan):
            return
        have = self.run(["docker", "image", "inspect", "-f", "{{.Id}}", tag]).strip()
        if have not in accepted:
            raise UpdateFailed(f"image {tag}: loaded ID {have or '(none)'} is not the bundle's image "
                               f"({', '.join(sorted(accepted)) or 'none'})")  # fmt: skip

    def restore_images(self, point: Point) -> None:
        for tag, rt in point.images.items():
            if rt:
                self.run(["docker", "tag", rt, tag])
            else:
                self.run(["docker", "image", "rm", "-f", tag])


class ComposeBox(_DockerImages):
    """A site box: ``docker compose --project-directory deploy`` (the files from ``COMPOSE_FILE`` in deploy/.env)."""

    name = "compose"

    def __init__(self, deploy: Path, run: Runner = run_cmd) -> None:
        self.deploy = deploy
        self.run = run
        self.env = _env_file(deploy / ".env")
        self.compose = shlex.split(
            os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}"
        )
        self.models = Path(os.environ.get("TB_MODELS_DIR") or deploy / "models")
        self.docker = shlex.split(os.environ.get("TB_DOCKER") or "docker")

    def _c(self, *args: str) -> list[str]:
        return [*self.compose, *args]

    def environment(self) -> str:
        """D-633: ``TB_ENV`` of ``deploy/.env`` (its last line, as install.sh reads it), PRODUCTION when it is not
        set or there is no file yet (D-127). Never the process environment: a ``TB_ENV=DEV`` typed in front of the
        installer is not written to the box. D-726: a rehearsal box (``install.sh --rehearsal``) is TEST from before
        the bundle loads, by its mark ``deploy/site/rehearsal.json``, until deploy/.env says; deploy/.env wins."""
        named = _env_file(self.deploy / ".env").get("TB_ENV")
        if not named and (self.deploy / "site" / "rehearsal.json").is_file():
            return "TEST"
        return (named or "PRODUCTION").strip().upper()

    def rehearsal_mark(self) -> bool:
        """D-887 (the integrator's (i)): the mark only ``deploy/install.sh --rehearsal`` writes."""
        return (self.deploy / "site" / "rehearsal.json").is_file()

    def rehearsal_box(self) -> bool:
        """A rehearsal box: the mark, and deploy/.env says TB_REHEARSAL=1 (or names no environment yet: the first
        load, before the installer writes deploy/.env). The mark without TB_REHEARSAL is a box touched by hand."""
        if not self.rehearsal_mark():
            return False
        env = _env_file(self.deploy / ".env")
        return env.get("TB_REHEARSAL", "").strip() == "1" or not env.get("TB_ENV")

    def running_services(self) -> list[str] | None:
        """D-724: the compose services that run now; None when compose cannot answer."""
        try:
            # a service that is restarting (crash-looping under `restart: unless-stopped`) or paused comes back
            return self.run(self._c("ps", "--status", "running", "--status", "restarting", "--status", "paused",
                                    "--services")).split()  # fmt: skip
        except (UpdateFailed, OSError):
            return None

    def running(self) -> bool:
        try:
            return "orchestrator" in self.run(self._c("ps", "--status", "running", "--services")).split()
        except (UpdateFailed, OSError):  # no compose here: not running
            return False

    def data_volumes(self) -> list[str]:
        """The compose project's volumes, by Docker's own label (no compose file is read): a box that has run has
        them. Fails closed: when Docker cannot answer, the box counts as holding data (refused while stopped),
        unless it has no deploy at all (no ``docker-compose.yml``: nothing was ever installed here)."""
        project = os.environ.get("COMPOSE_PROJECT_NAME") or self.env.get("COMPOSE_PROJECT_NAME") or "trialbox"
        try:
            return self.run([*self.docker, "volume", "ls", "-q", "--filter",
                             f"label=com.docker.compose.project={project}"]).split()  # fmt: skip
        except (UpdateFailed, OSError) as exc:
            if not (self.deploy / "docker-compose.yml").is_file():
                return []
            return [f"(docker volume ls failed: {str(exc)[:80]}; counted as data)"]

    def _dump(self, db: str, user: str, out: Path, timeout: float | None = None) -> None:
        self.run(self._c("exec", "-T", "db", "pg_dump", "-Fc", "--no-owner", "-U", user, "-d", db), stdout_file=out,
                 timeout=timeout)  # fmt: skip

    def _backup_where(self) -> tuple[Path, list[str]]:
        pub = Path(os.environ.get("TB_BACKUP_PUBKEY") or self.deploy / "secrets" / "backup.pub")
        targets = [t for t in (self.env.get("TB_BACKUP_TARGETS") or "").replace(",", " ").split() if t]
        if not pub.is_file():
            raise UpdateFailed(f"no backup key {pub} (trialbox backup-keygen with hospital IT, RUNBOOK §5)")
        if not targets:
            raise UpdateFailed("no TB_BACKUP_TARGETS in deploy/.env (the NAS share, a USB disk ...)")
        return pub, targets

    def backup_ready(self) -> str:
        """The preflight's part of the backup: the key and a target exist (nothing is stopped yet)."""
        return "backup to " + ", ".join(self._backup_where()[1])

    def db_bytes(self, db: str, user: str) -> int | None:
        """``pg_database_size`` of ``db`` (D-455: a backup step's limit comes from it), or None when not known."""
        try:
            from tools.trialbox import backup_schedule as bsch

            out = self.run(self._c("exec", "-T", "db", "psql", "-X", "-At", "-U", user, "-d", db, "-c",
                                   "SELECT pg_database_size(current_database())"),
                           timeout=bsch.query_timeout(self.env))  # fmt: skip
            return int(out.strip())
        except Exception:  # no answer: no size, so no limit (never a fixed guess)
            return None

    def apply_limit_s(self) -> int | None:
        """T-695 (D-752, F-09): the whole update's limit, from the databases' size. The steps with fixed limits (the
        image load, the weights check, the reference data, the health waits) kept the 3 h they had; the dumps and the
        backup container (``backup_schedule.step_timeout``, D-455) and the rollback's restore of the same dumps are
        sized. A size that cannot be read: no limit (D-455: never a fixed guess); each step keeps its own."""
        from tools.trialbox import backup_schedule as bsch

        cfg = bsch.config(self.deploy, self.env)
        sizes = [self.db_bytes(db, user) for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi"))]
        vols = bsch.volume_bytes(self.env, None)
        if None in sizes or vols is None:
            return None
        steps = [cfg.timeout(n) for n in [*sizes, sum(s or 0 for s in sizes) + vols]]
        if any(t is None for t in steps):
            return None
        # D-921: and each service's start-time migrations, a restore's limit of the trial database each
        migrations = len(STORE_SERVICES) * (steps[0] or 0)
        return int(APPLY_FIXED_S + 2 * sum(t or 0 for t in steps) + migrations) + 3 * self.up_wait()

    def up_wait(self) -> int:
        """T-695 (D-752, F-24): seconds to wait for the services healthy: ``TB_INSTALL_UP_TIMEOUT`` when set, else the
        longest start period plus retries of the box's compose files (``tools.trialbox.bootwait``); 900 s, the wait of
        before, only when the files cannot be read here (no PyYAML on the host)."""
        if os.environ.get("TB_INSTALL_UP_TIMEOUT"):
            return int(os.environ["TB_INSTALL_UP_TIMEOUT"])
        try:
            from tools.trialbox import bootwait

            return (
                bootwait.start_wait_s(bootwait.services(bootwait.files(self.deploy, self.env), self.env))
                or UP_WAIT_BEFORE_S
            )
        except Exception:  # no PyYAML, a file not readable or not YAML: the wait of before, never no wait
            return UP_WAIT_BEFORE_S

    def running_jobs(self) -> int | None:
        """How many jobs the orchestrator runs now (D-455), or None when the database cannot be asked."""
        from tools.trialbox import backup_schedule as bsch

        try:
            out = self.run(self._c("exec", "-T", "db", "psql", "-X", "-At", "-U", "trialbox", "-d", "trialbox_wf",
                                   "-c", bsch.RUNNING_JOBS_SQL), timeout=bsch.query_timeout(self.env))  # fmt: skip
            return int(out.strip())
        except Exception:  # no answer: not known
            return None

    def backup(self, plan: Plan, rb: Path) -> str:
        from tools.trialbox import backup_schedule as bsch

        pub, targets = self._backup_where()
        cfg = bsch.config(self.deploy, self.env)
        sizes = {db: self.db_bytes(db, user) for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi"))}
        # T-695 (D-752, F-09): never a stop under a running job; a count that cannot be taken refuses too (D-455)
        jobs = self.running_jobs()
        if jobs != 0:
            what = "the jobs could not be counted" if jobs is None else f"{jobs} job(s) running or queued"
            raise UpdateFailed(
                f"not started: {what}, and the update stops the services; update in the quiet hour (the console's "
                "update waits for it and for no job) or when the jobs are done"
            )
        # a quiet box: the services stop (the database stays up), so the dump, the files and the row counts agree
        self.run(self._c("stop", *PY_SERVICES), timeout=600)
        try:
            for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):
                self._dump(db, user, rb / f"{db}.dump", timeout=cfg.timeout(sizes[db]))
            # D-455: the container reads the dumps and the volumes; without a size for the volumes, no limit
            vols = bsch.volume_bytes(self.env, None)
            limit = cfg.timeout(None if vols is None else (bsch.tree_bytes(rb) or 0) + vols)
            if os.environ.get("TB_UPDATE_BACKUP_CMD"):
                self.run(shlex.split(os.environ["TB_UPDATE_BACKUP_CMD"]), timeout=limit)
            else:
                self._backup_container(rb, pub, targets, timeout=limit)
        except Exception:
            self.run(self._c("start", *PY_SERVICES), timeout=900)
            raise
        return ", ".join(targets)

    def _backup_container(self, rb: Path, pub: Path, targets: list[str], keep: int | None = None,
                          timeout: float | None = None, restic: bool = False,
                          secrets: Path | None = None) -> None:  # fmt: skip
        """``trialbox backup`` in a one-off container on trialbox-net with every volume read-only and the dumps just
        taken (``TB_PG_DUMP_DIR``): the image has no pg_dump, the db container has no Python. Passwords travel in
        the environment (``-e NAME`` without a value), never on the command line. ``timeout``: from the size it
        reads (D-455, ``backup_schedule.step_timeout``); None: no limit. ``restic`` (D-977): the release's backup job
        image (``TB_BACKUP_IMAGE``, restic inside), the secrets volume and the unsealed KEK read-only, and
        ``--restic``: the lake's served files go to the restic repository beside each target. ``secrets`` (D-978): the
        host folder whose KEK the nightly checked and where it made ``restic.key``, mounted by path; None or the
        box's own folder: its secrets volume."""
        from_backup = BACKUP_VOLUMES
        image = (
            (self.env.get("TB_BACKUP_IMAGE") or "trialbox-backup:1.0.0")
            if restic
            else (self.env.get("TB_IMAGE") or "trialbox-py:1.0.0")
        )
        site = f"TB_SITE_ID={self.env.get('TB_SITE_ID', '')}"
        argv = ["docker", "run", "--rm", "--network", "trialbox-net", "--user", "0", "-e", "TB_DB_URL",
                "-e", "TB_HAPI_DB_URL", "-e", "TB_PG_DUMP_DIR=/dumps", "-e", site,
                "-v", f"{rb}:/dumps:ro", "-v", f"{pub}:/in/backup.pub:ro"]  # fmt: skip
        dirs = []
        for name, vol in from_backup.items():
            argv += ["-v", f"trialbox_{vol}:/v/{name}:ro"]
            dirs += ["--dir", f"{name}=/v/{name}"]
        tos = []
        for i, t in enumerate(targets):
            Path(t).mkdir(parents=True, exist_ok=True)
            argv += ["-v", f"{t}:/backup/{i}"]
            tos += ["--to", f"/backup/{i}"]
        if restic:  # D-968 (R2): restic.key opens only under the KEK, inside restic's own process environment
            from tools import keys as keys_cli

            kek_dir = self.env.get("TB_KEK_HOST_DIR") or "/run/trialbox"
            own = secrets is None or Path(secrets) == Path(keys_cli.HOST_SECRETS)
            sec = "trialbox_tb-secrets" if own else str(secrets)
            argv += ["-v", f"{sec}:/run/secrets/trialbox:ro", "-v", f"{kek_dir}:/run/trialbox:ro"]
        argv += [image, "python", "-m", "tools.trialbox", "backup", *tos, "--public", "/in/backup.pub", *dirs]
        argv += ["--keep", str(keep)] if keep is not None else []  # D-188: the schedule's TB_BACKUP_KEEP
        argv += ["--restic"] if restic else []
        hapi_pw = self.env.get("POSTGRES_PASSWORD", "")
        env = {
            "TB_DB_URL": self.env.get("TB_DB_URL", ""),
            "TB_HAPI_DB_URL": f"postgresql://hapi:{hapi_pw}@db:5432/hapi",
        }
        self.run(argv, env=env, timeout=timeout)

    def resume(self, plan: Plan) -> None:
        """Start the services ``backup`` stopped (a failed backup or rollback point, or a recovery before it)."""
        self.run(self._c("start", *PY_SERVICES), timeout=900)

    def _psql(self, sql: str) -> list[list[str]]:
        out = self.run(self._c("exec", "-T", "db", "psql", "-X", "-At", "-F", "|", "-U", "trialbox", "-d",
                               "trialbox_wf", "-c", sql))  # fmt: skip
        return [ln.split("|") for ln in out.splitlines() if ln.strip()]

    def installed_state(self) -> dict[str, int]:
        """Every store's applied schema version (``_schema_version`` per schema of trialbox_wf, D-204)."""
        rows = self._psql(SCHEMA_SQL)
        return _schema_rows([(r[0], r[1] if len(r) > 1 else None) for r in rows])

    def space_needs(self, plan: Plan, updates: Path) -> list[tuple[Path, int, str]]:
        """Images into Docker's data root, the models (and the ones kept aside), both databases dumped (and a
        decrypted copy during a rollback) under deploy/updates, and the backup on each target (at least the
        databases)."""
        sizes = largest = 0
        for db in ("trialbox_wf", "hapi"):
            rows = self._psql(f"SELECT pg_database_size('{db}')")
            n = int(rows[0][0]) if rows and rows[0][0].isdigit() else 0
            sizes, largest = sizes + n, max(largest, n)
        try:
            root = Path(self.run(["docker", "info", "-f", "{{.DockerRootDir}}"]).strip() or "/var/lib/docker")
        except UpdateFailed:
            root = Path("/var/lib/docker")
        kept = sum((self.models / p.relative_to(plan.kind("model"))).stat().st_size
                   for p in plan.kind("model").rglob("*")
                   if p.is_file() and (self.models / p.relative_to(plan.kind("model"))).is_file()) \
            if plan.kind("model").is_dir() else 0  # fmt: skip
        needs = [(root, plan.payload_bytes("image"), "images"), (self.models, plan.payload_bytes("model"), "models"),
                 (updates, kept, "models kept aside"), (updates, 2 * sizes, "database dumps"),
                 (updates, plan.payload_bytes("other"), "other files"),
                 (self.deploy.parent, 2 * plan.payload_bytes("host"), "host tree (unpacked)"),
                 # H10G1-05: a rollback writes one database's plain script on the db volume (RESTORE_DIR), under
                 # Docker's root on a box; a plain script is about the database's size or less (no indexes)
                 (root / "volumes", largest, "rollback script (largest database) on the db volume")]  # fmt: skip
        for t in [t for t in (self.env.get("TB_BACKUP_TARGETS") or "").replace(",", " ").split() if t]:
            needs.append((Path(t), sizes, "backup (at least the databases)"))
        return needs

    def snapshot(self, plan: Plan, rb: Path, point: Point) -> None:
        for db in ("trialbox_wf", "hapi"):  # taken by backup() on a quiet box; else now
            f = rb / f"{db}.dump"
            if not f.is_file():
                self._dump(db, "trialbox" if db == "trialbox_wf" else "hapi", f)
            point.dumps[db] = str(seal(f, rb))  # the backup container has read it; encrypted from here on
        point.extra["dump_encryption"] = "aes-256-gcm" if point.dumps["trialbox_wf"].endswith(".enc") else "none"
        save_point(rb, point)
        self.snapshot_images(plan, point)
        save_point(rb, point)
        out = self.run(self._c("run", "--rm", "--no-deps", "-T", "criteria-compiler", "python", "-c", RULESETS_PY,
                               "snapshot", rulesets_tag(plan.bundle_id)))  # fmt: skip
        point.extra["rulesets_refs"] = _last_json(out)  # rulesets-data at a tag (D-210, review D-16)

    def apply(self, plan: Plan, rb: Path, point: Point) -> list[str]:
        done = apply_host(plan, self.deploy.parent, rb, point)  # first: the restart runs the new compose files
        done += self.load_images(plan)
        done += copy_models(plan.kind("model"), self.models, rb, point)
        done += copy_other(plan.kind("other"), self.deploy / "updates" / plan.bundle_id / "files")
        pins = plan.kind("other") / image_pins.PINS
        if pins.is_file():  # D-176: the bundle's digest pins, for an image store that keeps no digests (overlay2)
            done.append(f"image pins: {image_pins.merge(pins, self.deploy)}")
        return done

    def resolve_pins(self) -> None:
        """Point compose at the bundle's images where the image store lost their digests (tools/image_pins.py)."""
        files = [f for f in (self.env.get("COMPOSE_FILE") or "").split(":") if f]
        if not files:
            return
        # D-834: only the images the stack runs (with the box's overrides), as install.sh asks: a pinned image no
        # service runs (Authelia without the overlay, vLLM under a model-server override) is not needed here
        listed = self.run(self._c("config", "--images")) or ""
        used = {line.strip() for line in listed.splitlines() if line.strip()} or None
        changes, _, missing = image_pins.resolve(self.deploy, [Path(f) for f in files], used=used)
        if missing:
            raise UpdateFailed("pinned images neither on the box nor in the bundle: " + "; ".join(missing))
        image_pins.write_env(self.deploy / ".env", changes)

    def gpu(self) -> bool:
        return "gpu" in (self.env.get("COMPOSE_PROFILES") or "").replace(",", " ").split()

    def ensure_model_key(self) -> bool:
        """D-177 on a box installed before the key: make TB_LLM_API_KEY (as install.sh does) so the model servers and
        model-guard never start open. True when it was made now."""
        made = False
        if self.gpu() and not self.env.get("TB_LLM_API_KEY"):
            key = secrets.token_urlsafe(36)
            image_pins.write_env(self.deploy / ".env", {"TB_LLM_API_KEY": key})
            self.env["TB_LLM_API_KEY"] = key
            made = True
        # T-212b (D-437): the gateway and model-guard read the key from deploy/secrets/model/llm.key (a compose secret
        # of the secrets overlay, which needs its file): a box updated from before it gets the file from .env's key.
        # T-212d (D-450): the vLLM servers read deploy/secrets/model/vllm.env, so every GPU box needs both files
        if self.gpu() or (self.deploy / "secrets" / "services" / "public" / "tokens.json").is_file():
            from tools.trialbox import svc_secrets

            try:
                svc_secrets.ensure_model_key(self.deploy)
            except svc_secrets.SecretsError as e:  # T-608 (D-445): two different model keys stop the update
                raise UpdateFailed(str(e)) from e
        return made

    def _pull(self) -> str:
        pull = os.environ.get("TB_INSTALL_PULL") or "never"  # as install.sh: every image from a bundle (D-176)
        if pull not in ("never", "missing"):
            raise UpdateFailed(f"TB_INSTALL_PULL must be never or missing, not {pull!r}")
        return pull

    def _db_scripts_are_this_releases(self) -> bool:
        """Whether the running ``db`` container's ``/docker-entrypoint-initdb.d`` is the db-init folder of the tree
        now in force. No container: yes (the next ``up`` makes it from this tree). Docker does not answer: no."""
        try:
            cid = self.run(self._c("ps", "-q", "db")).strip()
            if not cid:
                return True
            fmt = '{{range .Mounts}}{{if eq .Destination "/docker-entrypoint-initdb.d"}}{{.Source}}{{end}}{{end}}'
            src = self.run([*self.docker, "inspect", "-f", fmt, cid.split()[0]]).strip()
        except (UpdateFailed, OSError):
            return False
        return bool(src) and src == os.path.realpath(self.deploy / "docker" / "db-init")

    def db_on_new_settings(self) -> str:
        """D-624: the ``db`` service as the release now in force makes it, before anything is run in it. Two things
        of the container are still the previous release's until here. Its environment: the role script reads each
        service's password from it. Its script folder: ``deploy/docker`` is a link through ``current``, and a bind
        mount is resolved when the container is made, so the container holds the previous release's db-init folder.
        Compose recreates a container when its settings changed and leaves it otherwise; when the folder it holds
        is not this release's (or Docker cannot say), it is made again here. The final ``up`` recreated it before;
        what is still running then (``fhir-store`` always, every service with ``--no-backup``) loses its
        connections a little earlier and is recreated by that ``up``."""
        if not self.env.get("TB_DB_URL", ""):  # as set_roles
            return "no database step on this box"
        t = str(self.up_wait())
        again = [] if self._db_scripts_are_this_releases() else ["--force-recreate"]
        self.run(self._c("up", "-d", "--pull", self._pull(), *again, "--wait", "--wait-timeout", t, "db"),
                 timeout=int(t) + 120)  # fmt: skip
        return "made again: it held another release's scripts" if again else "on this release's settings"

    def fhir_password_set(self) -> bool:
        """Whether ``.env`` holds a password for the FHIR store's role: not empty and not the example file's
        placeholder, quoted or not (compose strips the quotes)."""
        fhir = self.env.get(FHIR_PW, "").strip().strip("'\"")
        return bool(fhir) and not fhir.startswith("change-me")

    def ensure_fhir_password(self) -> bool:
        """D-541 (NEW-TRUST-1): a box installed before the FHIR store had a role of its own has no password for it
        in ``.env``. Made here, a pre-start step (``tools/trialbox/prestart.py``): the database container is then
        put on this release's settings (D-624) and the role script reads the password from the container's
        environment, never from a command line. True when it was made now."""
        from tools.trialbox import svc_secrets

        if self.fhir_password_set():
            return False
        fhir = secrets.token_urlsafe(32)
        try:
            svc_secrets._set_env(self.deploy / ".env", {FHIR_PW: fhir})
        except OSError as e:
            raise UpdateFailed(f"the FHIR store's database password could not be written to .env: {e}") from e
        self.env[FHIR_PW] = fhir
        return True

    def ensure_actor_key(self) -> bool | None:
        """T-717 (D-485): the secrets overlay gives the console its signing key as a compose secret, which needs its
        file: a box with per-service tokens from before it gets the key (and the orchestrator's keys file) here.
        True: made now; False: in place; None: a box without per-service tokens, which has no such secret.
        T-717b (D-547): a pre-start step of its own (``tools/trialbox/prestart.py``), no longer inside the model
        key's."""
        if not (self.deploy / "secrets" / "services" / "public" / "tokens.json").is_file():
            return None
        from tools.trialbox import svc_secrets

        try:
            return svc_secrets.ensure_actor_sign_key(self.deploy)
        except (OSError, svc_secrets.SecretsError) as e:  # a step fails by UpdateFailed: the operator reads why
            raise UpdateFailed(f"the console's signing key could not be written: {e}") from e

    def set_roles(self) -> bool:
        """T-718 (D-486, the review's H1): the role script before the migrate step, as `install.sh` runs it. A box
        updated in place otherwise keeps a schema under its old group, with the service as its owner. The script
        is idempotent and reads the passwords from the database container's own environment."""
        if not self.env.get("TB_DB_URL", ""):  # as migrate_owned: a box that never ran install.sh's database step
            return False
        self.run(self._c("exec", "-T", "db", "/docker-entrypoint-initdb.d/30-service-roles.sh"),
                 timeout=self.up_wait())  # fmt: skip
        return True

    def migrate_owned(self) -> bool:
        """T-718 (D-486): the schemas no service owns are made by the box's admin before the services start, in a
        one-off orchestrator container of the new image (``python -m orchestrator.migrate``). The admin's URL
        travels in the environment (``-e NAME`` without a value), never on the command line. The database is up: an
        update stops the services only."""
        url = self.env.get("TB_DB_URL", "")
        if not url:  # a box that never ran install.sh's database step: nothing to do here
            return False
        self.run(self._c("run", "--rm", "--no-deps", "-T", "-e", "TB_DB_URL", "orchestrator",
                         "python", "-m", "orchestrator.migrate"), env={"TB_DB_URL": url}, timeout=900)  # fmt: skip
        return True

    def migrate_limit_s(self) -> int | None:
        """T-695 (D-921): one service's start-time migrations may rewrite its stores once, so their limit is the one
        a restore of the trial database has (``backup_schedule.step_timeout`` of its size, D-455); a size that cannot
        be read: no limit (never a fixed guess)."""
        from tools.trialbox import backup_schedule as bsch

        t = bsch.config(self.deploy, self.env).timeout(self.db_bytes("trialbox_wf", "trialbox"))
        return None if t is None else int(t)

    def migrate_stores(self) -> list[str]:
        """T-695 (D-921): each service's start-time migrations (``<package>.migrate_stores``) in a one-off
        container of the service, as its own role, before the services start: a long migration is never under a
        health wait. The services of :data:`STORE_SERVICES` this box runs (``compose config --services``); the
        database is up. Returns the services migrated; none on a box that never ran install.sh's database step."""
        if not self.env.get("TB_DB_URL", ""):
            return []
        limit = self.migrate_limit_s()
        runs = set(self.run(self._c("config", "--services"), timeout=self.up_wait()).split())
        done = []
        for svc in STORE_SERVICES:
            if svc not in runs:
                continue
            mod = f"{svc.replace('-', '_')}.migrate_stores"  # the service's own module: only its role's stores
            self.run(self._c("run", "--rm", "--no-deps", "-T", svc, "python", "-m", mod),
                     timeout=limit)  # fmt: skip
            done.append(svc)
        return done

    def pre_start(self) -> None:
        """The host-side steps before the stack starts, run by the release whose tree is now in force
        (``tools/trialbox/prestart.py``): this process is the installed, older release's, and a step the new release
        added is not in it. The command runs in the install folder, where ``tools/`` is the new tree since
        ``apply_host``. A tree without the command (a downgrade to a release from before it; a box with no host
        tree) gets the steps every such release ran, and this release's signing key, here."""
        # absolute, not resolved: the command changes into the install folder first, and the symlinked layout stays
        deploy = Path(os.path.abspath(self.deploy))
        root = deploy.parent
        if not (root / "tools" / "trialbox" / "prestart.py").is_file():
            self.resolve_pins()
            self.ensure_model_key()
            self.ensure_actor_key()  # T-717b: this release's own step, when the tree has no command to run it
            return
        self._new_tree("pre-start", root, deploy)

    def _new_tree(self, cmd: str, root: Path, deploy: Path) -> None:
        """``python3 -m tools.trialbox <cmd>`` of the tree now in force, as a process of its own in the install
        folder; its lines go to the operator's log, and a failure is the reason the step gave."""
        python = sys.executable or "python3"
        argv = ["sh", "-c", 'cd "$1" && shift && exec "$@"', f"tb-{cmd}", str(root),
                python, "-m", "tools.trialbox", cmd, "--deploy", str(deploy)]  # fmt: skip
        # never shorter than the steps' own limits (the database's wait, the role script, the migrate step); db-up's
        # service migrations (D-921) add theirs, one per service, and an unsized one leaves no limit (D-455)
        t = self.up_wait()
        base = max(3600, 2 * t + 1200)
        limit: int | None = base
        if cmd == "db-up":
            m = self.migrate_limit_s()
            limit = None if m is None else base + len(STORE_SERVICES) * (m + 120) + t
        try:
            out = self.run(argv, timeout=limit)
        except UpdateFailed as exc:
            # the reason the step gave, not the command line around it
            said = [ln.strip() for ln in str(exc).splitlines() if ln.strip().startswith(cmd)]
            raise UpdateFailed(said[-1] if said else f"{cmd} failed: {str(exc)[-400:]}") from exc
        finally:
            self.env = _env_file(self.deploy / ".env")  # a step may have written a setting the checks read
        for line in (out or "").splitlines():
            print(line)  # each step and what it did, in the operator's log

    def db_up(self) -> None:
        """D-624: what is done once the database is up and before the services start, run by the release whose
        tree is now in force (``DB_STEPS`` of its ``tools/trialbox/prestart.py``), as :meth:`pre_start`. A tree
        from before the command (its ``prestart.py`` has no ``DB_STEPS``, or there is none) gets the two commands
        every such release ran, here."""
        deploy = Path(os.path.abspath(self.deploy))
        root = deploy.parent
        mod = root / "tools" / "trialbox" / "prestart.py"
        if not (mod.is_file() and "DB_STEPS" in mod.read_text(encoding="utf-8")):
            self.set_roles()
            self.migrate_owned()
            return
        self._new_tree("db-up", root, deploy)

    def restart(self, plan: Plan) -> None:
        # new images: the containers are recreated; before they start, db-up makes the schemas with an owner role
        # (D-486) as the admin and runs each service's start-time migrations in a one-off container (D-921), so the
        # health wait finds them applied; a store a service opens later still migrates there (tb_common.db)
        self.pre_start()
        self.db_up()
        t = str(self.up_wait())
        self.run(self._c("up", "-d", "--pull", self._pull(), "--wait", "--wait-timeout", t), timeout=int(t) + 120)

    def check_serving(self) -> str:
        """``trialbox doctor --serving`` on the model network, as install.sh runs it (pinned names, the key, model-guard
        in front): a FAIL fails the update, which is then rolled back."""
        if not self.gpu():
            return ""
        image = self.env.get("TB_IMAGE") or "trialbox-py:1.0.0"
        # D-450: doctor reads the key file, as the gateway does
        argv = ["docker", "run", "--rm", "--network", "trialbox-model-net", "--env-file", str(self.deploy / ".env"),
                "-v", f"{self.deploy}:/app/deploy:ro", "-e", "TB_LLM_API_KEY_FILE=/app/deploy/secrets/model/llm.key",
                image, "python", "-m", "tools.trialbox", "doctor", "--serving"]  # fmt: skip
        self.run(argv, timeout=300)
        return "; model servers: pinned names and the key (doctor --serving)"

    def check_weights(self) -> str:
        """``trialbox doctor --weights`` after the restart (T-677, D-393; LLM-008): every pinned build's weights in the
        models folder against its pin. A mismatch writes the weights flag the gateway refuses on and fails the update,
        which is then rolled back; a pass removes a flag left from before."""
        if not self.gpu():
            return ""
        image = self.env.get("TB_IMAGE") or "trialbox-py:1.0.0"
        argv = ["docker", "run", "--rm", "--network", "none", "--env-file", str(self.deploy / ".env"),
                "-e", "TB_MODELS_DIR=/app/deploy/models",
                "-e", "TB_REGISTRY_OVERRIDE=/app/deploy/site/registry.site.yaml",
                "-v", f"{self.deploy}:/app/deploy", "-v", f"{self.models}:/app/deploy/models:ro", image,
                "python", "-m", "tools.trialbox", "doctor", "--weights"]  # fmt: skip
        self.run(argv, timeout=3600)
        return "; weights match their pins (doctor --weights)"

    def post_apply(self, plan: Plan) -> list[str]:
        return self.rulesets(plan) + self.refdata(plan)

    def _rm_run(self, name: str) -> None:
        """10G-1 review D3: a named one-off run removed (killed if it still runs). A limit that ran out kills only the
        compose CLI; the container it started would go on. Nothing there is an error."""
        with contextlib.suppress(Exception):
            self.run([*self.docker, "rm", "-f", name], timeout=120)

    def _sweep_unpack(self) -> None:
        """What a stopped load left of its unpacked pack on the objects volume (a backed-up volume, BACKUP_VOLUMES),
        removed by a one-off criteria-compiler: the loader's own folder names (``tb_common.refdata.opened``), never a
        host path."""
        with contextlib.suppress(Exception):
            self.run(self._c("run", "--rm", "--no-deps", "-T", "--name", REFDATA_SWEEP,
                             "-e", f"TMPDIR={REFDATA_TMPDIR}", "criteria-compiler",
                             "sh", "-c", REFDATA_SWEEP_SH, REFDATA_SWEEP), timeout=600)  # fmt: skip

    def rulesets(self, plan: Plan) -> list[str]:
        done = []
        rs = plan.kind("ruleset")
        for z in sorted(rs.rglob("*.zip")) if rs.is_dir() else []:
            # 10G-1 (D-1323): a one-off container with the file bind-mounted read-only; ``compose cp`` cannot write
            # into criteria-compiler, whose root is read-only and /tmp a tmpfs. Named, so one a failure left running
            # is removed (review D3)
            self._rm_run(RULESET_RUN)
            try:
                self.run(self._c("run", "--rm", "--no-deps", "-T", "--name", RULESET_RUN,
                                 "-v", f"{z.resolve()}:/in/ruleset.zip:ro",
                                 "criteria-compiler", "python", "-m", "criteria_compiler.import_ruleset",
                                 "/in/ruleset.zip", "--by", f"update:{plan.bundle_id}"))  # fmt: skip
            except (UpdateFailed, subprocess.TimeoutExpired):
                self._rm_run(RULESET_RUN)
                raise
            done.append(z.name)
        return done

    def refdata(self, plan: Plan) -> list[str]:
        """The reference data packs, after the release passed its check: each is one transaction (D-140), so a
        failure leaves the previous pack's rows and the healthy release; the pack waits in deploy/refdata/pending.
        10G-1 review D3: the one-off run is named and removed before a load and after one that failed or ran out of
        time, and a load first clears what an earlier one left unpacked on the objects volume (``REFDATA_SWEEP_SH``)."""
        done = []
        for pack in refdata_packs(plan):  # D-140: verified again inside, then one transaction
            self._rm_run(REFDATA_RUN)
            try:
                # 10G-1 (D-1323): as rulesets, a one-off container reads the pack bind-mounted read-only; it unpacks
                # on the objects volume (TMPDIR), not in the tmpfs /tmp that counts against the memory limit
                load = ["python", "-m", "tb_common.refdata", "load", "/in/refdata.tar"]
                self.run(self._c("run", "--rm", "--no-deps", "-T", "--name", REFDATA_RUN,
                                 "-e", f"TMPDIR={REFDATA_TMPDIR}", "-v", f"{pack.resolve()}:/in/refdata.tar:ro",
                                 "criteria-compiler", "sh", "-c", REFDATA_SWEEP_SH + '; exec "$@"', REFDATA_RUN,
                                 *load, "--by", f"update:{plan.bundle_id}"),
                         timeout=7200)  # fmt: skip
            except (UpdateFailed, subprocess.TimeoutExpired):
                self._rm_run(REFDATA_RUN)
                self._sweep_unpack()
                pend = self.deploy / "refdata" / "pending"
                pend.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pack, pend / pack.name)
                raise
            kept = self.deploy / "refdata" / "loaded"  # D-187: a restore loads the pack again from here
            kept.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pack, kept / pack.name)
            done.append(pack.name)
        return done

    def check(self, plan: Plan) -> str:
        weights = self.check_weights()  # first: a flag it writes makes the gateway unhealthy for the wait below
        self.run(self._c("up", "-d", "--wait", "--wait-timeout", "300"), timeout=420)  # every service healthy
        serving = weights + self.check_serving()
        cmd = os.environ.get("TB_UPDATE_CHECK_CMD")
        if cmd:
            self.run(shlex.split(cmd), timeout=3600)
            return "healthy; " + cmd + serving
        return "every service healthy" + serving

    def restore_databases(self, rb: Path, point: Point) -> None:
        """Each dump back as the database's own role (decrypted to a 0600 file in the rollback folder for the restore,
        deleted after). ``pg_restore --clean`` alone drops only what the dump holds: a table the new release's
        migration added to a schema of the dump blocks ``DROP SCHEMA`` and the rollback fails (found by the drill's
        db-image case). So the restore is one transaction in ``psql``: first every schema the role owns (but
        ``public`` and an extension's) and every relation it owns in ``public`` is dropped (``RESET_SQL``), then the
        dump's own script (``pg_restore --clean --if-exists -f``, written to a 0600 file on the db volume and
        deleted, ``RESTORE_DIR``). Any error rolls the whole of it back."""
        for db, f in point.dumps.items():
            user = "trialbox" if db == "trialbox_wf" else "hapi"
            argv = self._c("exec", "-T", "db", "sh", "-c", RESTORE_SH, "tb-restore", user, db, RESET_SQL)

            def restore(plain: Path, argv: list[str] = argv) -> None:
                self.run(argv, stdin_file=plain)

            _with_plain(Path(f), rb, restore)

    def rollback(self, plan: Plan, rb: Path, point: Point) -> None:
        self.run(self._c("stop", *PY_SERVICES, "fhir-store"), timeout=600)  # nobody holds the databases open
        self.restore_images(point)
        restore_models(self.models, rb, point)
        restore_host(self.deploy.parent, point)  # the previous release's compose files for the restart below
        self.restore_databases(rb, point)
        refs = point.extra.get("rulesets_refs")
        if refs:  # rulesets-data back to the tag of the rollback point (imports of this update dropped)
            self.run(self._c("run", "--rm", "--no-deps", "-T", "criteria-compiler", "python", "-c", RULESETS_PY,
                             "restore", json.dumps(refs)))  # fmt: skip
        self.restart(plan)
        try:  # the previous weights are back: a pass clears the flag the failed update may have set (D-393)
            self.check_weights()
        except Exception as exc:  # the rollback stands; the gateway keeps refusing until the weights match
            print(f"rollback: the weights check failed after the restore ({exc}): run trialbox doctor --verify-all",
                  file=sys.stderr)  # fmt: skip

    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None:
        code = (
            "import json, sys\nfrom tb_common.audit_writer import open_audit\ns = json.load(sys.stdin)\n"
            "open_audit().append(s['event'], actor='apply_update.sh', input_sha=s['sha'],\n"
            "    detail=s['detail'])\n"
        )
        f = self.deploy / "updates" / plan.bundle_id / f"{event}.json"
        f.write_text(json.dumps({"event": event, "sha": plan.manifest_sha256, "detail": detail}), encoding="utf-8")
        try:
            self.run(self._c("exec", "-T", "orchestrator", "python", "-c", code), stdin_file=f)
        except UpdateFailed:  # the orchestrator is down (a failed rollback): install.sh's pending audit takes it
            pend = self.deploy / "updates" / "pending_audit"
            pend.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, pend / f"{plan.bundle_id}.{event}.json")


class DemoBox(_DockerImages):
    """The one-container demo on the demo VM (D-111, ``deploy/gcp/demo-vm-startup.sh``): container ``trialbox-demo``
    from ``trialbox-demo:step5``, recreated by ``/etc/trialbox-demo/run.sh`` (written by the startup script; the
    password is in ``/etc/trialbox-demo/demo.env``, 0600, never on a command line)."""

    name = "demo"

    def environment(self) -> str:
        return "DEV"  # the demo VM: synthetic data, tools.demo sets TB_ENV=DEV itself

    def __init__(self, deploy: Path, run: Runner = run_cmd, wait_url: str = "http://127.0.0.1/login") -> None:
        self.deploy = deploy
        self.run = run
        self.container = os.environ.get("TB_DEMO_CONTAINER", "trialbox-demo")
        self.image = os.environ.get("TB_DEMO_IMAGE", "trialbox-demo:step5")
        self.run_script = Path(os.environ.get("TB_DEMO_RUN", "/etc/trialbox-demo/run.sh"))
        self.wait_url = wait_url
        self.models = Path(os.environ.get("TB_MODELS_DIR") or deploy / "models")
        self.docker = shlex.split(os.environ.get("TB_DOCKER") or "docker")

    def running(self) -> bool:
        try:
            return self.run(["docker", "inspect", "-f", "{{.State.Running}}", self.container]).strip() == "true"
        except (UpdateFailed, OSError):
            return False

    def backup(self, plan: Plan, rb: Path) -> str:
        # the demo's synthetic box, backed up by the image's own tool (a throwaway key pair: synthetic data only)
        self.run(["docker", "exec", self.container, "python", "-m", "tools.update_drill", "backup-work",
                  "--to", "/tmp/tb-update-backup"], timeout=1800)  # fmt: skip
        self.run(["docker", "cp", f"{self.container}:/tmp/tb-update-backup", str(rb / "backup")])
        return str(rb / "backup")

    def snapshot(self, plan: Plan, rb: Path, point: Point) -> None:
        self.snapshot_images(plan, point)
        if self.image not in point.images:  # the running image even when the bundle names another tag
            have = self.run(["docker", "image", "inspect", "-f", "{{.Id}}", self.image]).strip()
            rt = rollback_tag(self.image, plan.bundle_id)
            self.run(["docker", "tag", have, rt])
            point.images[self.image] = rt

    def apply(self, plan: Plan, rb: Path, point: Point) -> list[str]:
        return self.load_images(plan) + copy_other(
            plan.kind("other"), self.deploy / "updates" / plan.bundle_id / "files"
        )

    def _recreate(self) -> None:
        self.run(["docker", "rm", "-f", self.container])
        self.run(["sh", str(self.run_script), self.image])
        deadline = time.time() + float(os.environ.get("TB_DEMO_WAIT_S", "900"))
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(self.wait_url, timeout=5) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(5)
        raise UpdateFailed(f"the demo did not answer {self.wait_url}")

    def restart(self, plan: Plan) -> None:
        self._recreate()

    def post_apply(self, plan: Plan) -> list[str]:
        return []

    def resume(self, plan: Plan) -> None:
        if not self.running():
            self._recreate()

    def space_needs(self, plan: Plan, updates: Path) -> list[tuple[Path, int, str]]:
        try:
            root = Path(self.run(["docker", "info", "-f", "{{.DockerRootDir}}"]).strip() or "/var/lib/docker")
        except UpdateFailed:
            root = Path("/var/lib/docker")
        return [(root, plan.payload_bytes("image"), "images"),
                (updates, plan.payload_bytes("other"), "other files")]  # fmt: skip

    def check(self, plan: Plan) -> str:
        out = self.run(["docker", "exec", self.container, "python", "-m", "tools.e2e_simple",
                        "--dir", "/tmp/tb-update-e2e"], timeout=3600)  # fmt: skip
        last = [ln for ln in out.splitlines() if ln.strip()][-1:] or [""]
        return f"e2e_simple passed in the updated container ({last[0][:120]})"

    def rollback(self, plan: Plan, rb: Path, point: Point) -> None:
        self.restore_images(point)
        self._recreate()

    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None:
        # the demo's box is rebuilt at every start, so the durable record is the host's history and this chain
        from_dir = self.deploy / "updates" / "audit"
        _append_audit(from_dir, event, plan, detail)


def _append_audit(directory: Path, event: str, plan: Plan, detail: dict[str, Any]) -> None:
    """Append to a hash-chained log with the box's own audit code when it is importable, else a JSON line."""
    try:
        from tb_common.audit import AuditLog
    except ImportError:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": _now(), "event": event, "sha": plan.manifest_sha256, "detail": detail}) + "\n")
        return
    AuditLog(directory).append(event, actor="apply_update.sh", input_sha=plan.manifest_sha256, detail=detail)


class InProcessBox:
    """The in-process box of ``e2e_simple`` in ``work`` (``tools/update_drill.py``). Images cannot be loaded into a
    process, so an image payload sets the box's release (``work/RELEASE``); a bundle's migrations are
    ``other/migrations/NNN_*.sql``, applied by ``tb_common.db`` to the schema ``release`` of the box's trial database,
    exactly as a service applies its own at start. ``other/FAIL_CHECK`` makes the new release fail its check (an
    unhealthy service), for the rollback drill."""

    name = "in-process"

    def environment(self) -> str:
        return "TEST"  # the drills' box in one process (tools/update_drill.py)

    def __init__(self, work: Path, db_url: str, backup_to: Path) -> None:
        self.work = work
        self.url = db_url
        self.backup_to = backup_to
        self.models = work / "models"
        self.release = work / "RELEASE"
        self.before: dict[str, Any] = {}
        self.keys = backup_to / "keys"

    def dirs(self) -> dict[str, Path]:
        return {n: self.work / n for n in ("box", "console", "lake", "sec") if (self.work / n).exists()}

    def running(self) -> bool:
        return True

    def backup(self, plan: Plan, rb: Path) -> str:
        from tb_common.db import Database

        from tools.trialbox import backup as bk

        Database.connect(self.url, "release").close()  # the release schema exists from the first update on
        priv, pub = self.keys / "hospital-it.key", self.keys / "box.pub"
        if not pub.is_file():
            bk.keygen(priv, pub)
        files = bk.backup([self.backup_to / "nas"], pub, env={**os.environ, "TB_DB_URL": self.url}, dirs=self.dirs())
        bk.verify(files[0], priv)  # the hospital's key opens it and every hash is right
        return str(files[0])

    def state(self) -> dict[str, Any]:
        from tools import backup_drill as bd

        return {"marks": bd._marks(self.work), "lifecycle": bd._lifecycle(), "site": bd._sitesetup(),
                "terms": bd._terminology()}  # fmt: skip

    def _pg(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """A read on the box's database without creating any schema (a preflight changes nothing)."""
        import psycopg
        from tb_common.db import split_url

        with psycopg.connect(split_url(self.url)[0], autocommit=True) as con:
            return [tuple(r) for r in con.execute(sql, params or None).fetchall()]

    def installed_state(self) -> dict[str, int]:
        from tb_common.db import split_url

        prefix = split_url(self.url)[1]
        return _schema_rows([(str(r[0]), r[1]) for r in self._pg(SCHEMA_SQL)], prefix)

    def _migration_dir(self, plan: Plan) -> Path:
        return plan.kind("other") / "migrations"

    def preflight(self, plan: Plan) -> list[str]:
        """The bundle's migrations against the ones applied (T-104's checksums, ``Database.applied``): a changed
        script, or a schema newer than the bundle's scripts (old code on a newer schema), is refused here, before
        anything changes. ``db.py`` itself does not refuse fewer versions than applied: this is where it is."""
        from tb_common.db import Database, MigrationError, read_migration_dir, split_url

        mig = self._migration_dir(plan)
        try:
            scripts = read_migration_dir(mig, "release") if mig.is_dir() else []
        except MigrationError as exc:
            raise UpdateRefused(f"the bundle's migrations: {exc}") from exc
        schema = split_url(self.url)[1] + "release"
        if not self._pg("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)):
            return [f"release schema not created yet; {len(scripts)} migrations to run"]
        with Database.connect(self.url, "release") as db:
            applied = db.applied()
        if len(applied) > len(scripts):
            raise UpdateRefused(f"schema release is at version {len(applied)}, the bundle has {len(scripts)} "
                                "migrations: older code on a newer schema is refused")  # fmt: skip
        for row in applied:
            want = scripts[row.version - 1].sha256
            if row.sha256 is not None and row.sha256 != want:
                raise UpdateRefused(f"migration {row.version} of schema release differs from the one applied "
                                    f"(checksum {row.sha256[:12]}… vs {want[:12]}…, D-204)")  # fmt: skip
        return [f"migrations: {len(applied)} applied match the bundle, {len(scripts) - len(applied)} to run"]

    def space_needs(self, plan: Plan, updates: Path) -> list[tuple[Path, int, str]]:
        from tb_common.db import split_url

        prefix = split_url(self.url)[1]
        rows = self._pg("SELECT COALESCE(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c JOIN pg_namespace n "
                        "ON n.oid = c.relnamespace WHERE n.nspname LIKE %s AND c.relkind IN ('r', 'm')",
                        (f"{prefix}%" if prefix else "%",))  # fmt: skip
        db = int(rows[0][0] or 0)
        files = sum(f.stat().st_size for d in self.dirs().values() for f in d.rglob("*") if f.is_file())
        return [(updates, 2 * db, "database dump (and its decrypted copy in a rollback)"),
                (self.models, plan.payload_bytes("model"), "models"),
                (self.backup_to, db + files, "backup")]  # fmt: skip

    def resume(self, plan: Plan) -> None:
        self._open_stores()

    def snapshot(self, plan: Plan, rb: Path, point: Point) -> None:
        from tb_common.db import split_url

        from tools.trialbox import backup as bk

        dsn, prefix = split_url(self.url)
        f = rb / "trialbox_wf.dump"
        bk.dump(bk.DbSource("trialbox_wf", dsn, (f"{prefix}*",)), f, os.environ)
        point.dumps["trialbox_wf"] = str(seal(f, rb))
        point.extra["dump_encryption"] = "aes-256-gcm" if point.dumps["trialbox_wf"].endswith(".enc") else "none"
        point.extra["release"] = self.release.read_text(encoding="utf-8") if self.release.is_file() else ""
        self.before = self.state()

    def apply(self, plan: Plan, rb: Path, point: Point) -> list[str]:
        img = plan.kind("image")
        names = sorted(p.name for p in img.rglob("*") if p.is_file()) if img.is_dir() else []
        if names:
            self.release.write_text(f"{plan.bundle_id} {' '.join(names)}\n", encoding="utf-8")
        done = [f"image {n} (release)" for n in names]
        done += copy_models(plan.kind("model"), self.models, rb, point)
        done += copy_other(plan.kind("other"), self.work / "updates" / plan.bundle_id)
        return done

    def restart(self, plan: Plan) -> None:
        from tb_common.db import Database

        mig = self._migration_dir(plan)
        with Database.connect(self.url, "release") as db:
            if mig.is_dir():
                db.migrate_dir(mig)  # NNN_<name>.sql, checksummed (T-104, D-204)
            else:
                db.migrate([])
        self._open_stores()

    def _open_stores(self) -> None:
        """Every store of the box opened afresh, as the services do at start (their own migrations run)."""
        from adapter.licensed import TermStore
        from console.auth import UserStore
        from console.sitestore import SiteStore
        from datacore.store import DataCore
        from sitesetup.store import SetupStore

        SiteStore()
        UserStore()
        for s in (DataCore(), SetupStore(), TermStore()):
            s.close()

    def post_apply(self, plan: Plan) -> list[str]:
        return self.rulesets(plan) + self.refdata(plan)

    def rulesets(self, plan: Plan) -> list[str]:
        return []

    def refdata(self, plan: Plan) -> list[str]:
        from tb_common.refdata import RefStore, opened

        done = []
        for tar in refdata_packs(plan):
            with opened(tar) as pack, RefStore(self.url) as st:
                st.load(pack, by=f"update:{plan.bundle_id}")
            done.append(tar.name)
        return done

    def schema_version(self) -> int:
        from tb_common.db import Database

        with Database.connect(self.url, "release") as db:
            db.migrate([])
            return int(db.fetchval("SELECT COALESCE(MAX(version), 0) FROM _schema_version", default=0))

    def check(self, plan: Plan) -> str:
        if (self.work / "updates" / plan.bundle_id / "FAIL_CHECK").exists() and self.release.read_text(
            encoding="utf-8"
        ).startswith(plan.bundle_id):
            raise UpdateFailed("the new release did not become healthy (FAIL_CHECK)")
        if self.before and self.state() != self.before:
            raise UpdateFailed("the box's data changed across the update")
        return f"data unchanged; release schema version {self.schema_version()}"

    def rollback(self, plan: Plan, rb: Path, point: Point) -> None:
        from tb_common.db import split_url

        from tools.trialbox import backup as bk

        dsn, prefix = split_url(self.url)
        src = bk.DbSource("trialbox_wf", dsn, (f"{prefix}*",))
        _with_plain(Path(point.dumps["trialbox_wf"]), rb, lambda plain: bk.restore_db(src, plain, os.environ))
        self.release.write_text(str(point.extra.get("release", "")), encoding="utf-8")
        restore_models(self.models, rb, point)
        self._open_stores()

    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None:
        _append_audit(self.work / "box" / "audit", event, plan, detail)


def box_in_service(deploy: Path, box: Any = None) -> str:
    """What shows this box holds data ("" for none): its update records, or the compose project's volumes (a box
    in the field before D-210 that has run has them). install.sh's settings (``.env``, ``settings.yaml``,
    ``secrets/``) are not evidence: a first install stopped after writing them must be able to run again."""
    for rel in ("updates/installed.json", "updates/history.jsonl", "updates/trust.json"):
        if (deploy / rel).exists():
            return f"deploy/{rel}"
    volumes = getattr(box, "data_volumes", None)
    found = volumes() if volumes is not None else []
    return f"volumes {', '.join(found[:3])}" if found else ""


def no_backup_refused(target: str, deploy: Path) -> bool:
    """D-1321: ``--no-backup`` with no reason is refused on a PRODUCTION box (the box's own environment, as the
    update path reads it: ``deploy/.env``; unset or any other name counts as PRODUCTION, D-633). DEV, TEST and
    VALIDATION take it as before."""
    box: ComposeBox | DemoBox = DemoBox(deploy) if target == "demo" else ComposeBox(deploy)
    env = str(box.environment()).strip().upper()
    return env not in ("DEV", "TEST", "VALIDATION")


def main_apply(
    stage: Path, summary_file: Path, target: str, deploy: Path, backup: bool = True, no_backup_reason: str | None = None
) -> int:
    """``apply_update.sh`` after verify. A box never installed (no ``installed.json``) that is not running yet, or
    install.sh's first load (``TB_SKIP_AUDIT``), only loads the payloads; an installed box that is not running is
    refused (start it, then update: a crashed box never takes the path without marker, backup or compat check); a
    running installed box takes the whole path. The summary must come from a D-210 ``verify_update.py``, sit in
    the stage folder (0700) and name the staged manifest's sha256: anything else is refused."""
    from tools import update_status as us

    if summary_file.resolve().parent != stage.resolve():
        print(f"update REFUSED: the summary must be in the stage folder {stage} (not {summary_file})")
        return 1
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    if not isinstance(summary.get("release_seq"), int) or not isinstance(summary.get("compat"), dict) \
            or "trust_sha256" not in summary:  # fmt: skip
        print("update REFUSED: the summary has no release_seq, compatibility table or trust sha256 "
              "(verify_update.py, D-210)")  # fmt: skip
        return 1
    if us.file_sha256(stage / "manifest.json") != summary.get("manifest_sha256"):
        print("update REFUSED: the summary does not belong to the staged manifest.json (sha256 differs)")
        return 1
    plan = Plan.load(stage, summary)
    if not backup and no_backup_reason and no_backup_reason.strip():
        plan.no_backup_reason = no_backup_reason.strip()[:500]
    updates = deploy / "updates"
    box: ComposeBox | DemoBox = DemoBox(deploy) if target == "demo" else ComposeBox(deploy)
    try:
        inst = us.installed(updates)
    except ValueError as exc:  # a malformed record: never guessed
        print(f"update REFUSED: {updates / us.INSTALLED} is unreadable ({exc}); RUNBOOK §5; nothing was changed")
        return 1
    # D-633: a site box takes only a release built from a commit. Here, before either path: install.sh's first load
    # below never runs the preflight, and a fresh box (no deploy/.env yet) is PRODUCTION (TEST only with the mark of
    # a --rehearsal install, which install.sh refuses to leave behind for a site's install, D-726). Before the
    # "already installed" answer too (D-726, review F6): a box made a site box by hand does not keep a rehearsal
    # bundle by installing it again
    try:
        Updater(box, updates, say=print)._from_a_commit(plan)
    except UpdateRefused as exc:
        print(f"update REFUSED: {exc}; nothing was changed")
        return 1
    if inst.get("manifest_sha256") == plan.manifest_sha256 and us.marker(updates) is None:
        print(f"update {plan.bundle_id}: already installed (same manifest); nothing to do")
        return 0
    in_service = box_in_service(deploy, box)
    if not box.running():
        if in_service:
            print(f"update REFUSED: the box is installed ({in_service}) but not running (crashed, restarting, or its "
                  "compose ps failed); start it, then run the update again; nothing was changed")  # fmt: skip
            return 1
        if not os.environ.get("TB_SKIP_AUDIT"):
            print("update REFUSED: the box is not running and not installed; a first install is "
                  "deploy/install.sh; nothing was changed")  # fmt: skip
            return 1
    elif os.environ.get("TB_SKIP_AUDIT") and in_service:
        print(f"update: the box is installed ({in_service}) and running: the whole update path, not install.sh's load")
    if os.environ.get("TB_SKIP_AUDIT") and not in_service:
        try:
            with us.locked(updates):
                if us.marker(updates) is not None:
                    print("update REFUSED: an update is unfinished (tools/apply_update.sh status)")
                    return 1
                if us.file_sha256(updates / us.TRUST) != plan.trust_sha256:
                    print("update REFUSED: trust.json changed since this bundle was verified; run it again")
                    return 1
                inst = us.installed(updates)
                if plan.release_seq is not None and plan.release_seq <= int(inst["release_seq"]) \
                        and not plan.downgrade:  # fmt: skip
                    print(f"update REFUSED: release_seq {plan.release_seq} is not above the installed "
                          f"{inst['release_seq']}")  # fmt: skip
                    return 1
                if plan.kind("ruleset").is_dir():
                    print("rulesets: imported when the box runs (tools/apply_update.sh <bundle> again after the start)")
                for tar in refdata_packs(plan):  # install.sh loads deploy/refdata/pending/*.tar once the box runs
                    pend = deploy / "refdata" / "pending"
                    pend.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(tar, pend / tar.name)
                    print(f"reference data {tar.name}: loaded when the box runs (deploy/install.sh)")
                point = Point()
                rb = updates / plan.bundle_id / "rollback"
                rb.mkdir(parents=True, exist_ok=True)
                for line in box.apply(plan, rb, point):
                    print(line)
                shutil.rmtree(rb, ignore_errors=True)
                Updater(box, updates, say=lambda _m: None)._record(plan, live=False)
                pend = updates / "pending_audit"
                pend.mkdir(parents=True, exist_ok=True)
                (pend / f"{plan.bundle_id}.json").write_text(json.dumps(summary), encoding="utf-8")
        except us.Busy as exc:
            print(f"update REFUSED: {exc}")
            return 1
        print(f"update {plan.bundle_id} loaded; the box is not running, so install.sh starts it and audits it")
        return 0
    try:
        Updater(box, updates).run(plan, backup=backup)
    except UpdateFailed as exc:
        print(f"update FAILED: {exc}")
        return 1
    print(f"update {plan.bundle_id} applied, checked and audited")
    return 0

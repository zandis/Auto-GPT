"""The update path (TB-PLAN-04 step 8, D-138): an offline signed bundle, backed up first, applied, migrated,
restarted, checked, and rolled back when anything fails.

``tools/apply_update.sh BUNDLE.tar`` verifies the bundle (Ed25519 signature of the manifest with the box's vendor
key, every payload's size and sha256: ``tools/verify_update.py``, D-77) and stages it; then it runs this module:

    python3 -m tools.trialbox update --stage <staged payloads> --summary <verify summary> [--target compose|demo]

1. **Backup first** (D-126). The box's own encrypted backup (``trialbox backup``) to ``TB_BACKUP_TARGETS``, to the
   hospital's public key (``deploy/secrets/backup.pub``). No key or no target: the update refuses and changes
   nothing (``--no-backup`` skips it, and the skip is audited; for a test box only).
2. **Rollback point**. The images the bundle replaces are tagged ``<repo>:rollback-<bundle>``; every model file
   it overwrites is copied aside; the trial database (and HAPI's) is dumped locally, 0600 under
   ``deploy/updates/<bundle>/rollback/``. The encrypted backup needs the hospital's private key, which the box does
   not hold (D-126), so the automatic rollback uses this local dump; it is removed after a good update.
3. **Apply**: images (``docker load``), models, other files; **migrate and restart**: the services run their
   versioned migrations at start (``tb_common.db``, D-126), so a restart on the new images is the migration;
   then the rulesets of the bundle (criteria-compiler import with the approval and equivalence gates) and its
   reference data pack (payload kind ``refdata``, ``trialbox-refdata-<date>.tar``: verified and loaded into the
   schema ``refdata`` of the trial database, ``tb_common.refdata``, D-140; the database dump of step 2 rolls it
   back with everything else).
4. **Check**: every service healthy (``up --wait``), plus ``TB_UPDATE_CHECK_CMD`` when set; the demo box runs
   ``e2e_simple`` in the updated container.
5. **Success**: ``update.applied`` in the hash-chained audit log, the history line, the local dump removed.
   **Any failure** after step 2: the old images are tagged back, the models put back, the database restored from the
   local dump, the services restarted and checked again; ``update.rolled_back`` is audited; exit 1.

Every step is written to ``deploy/updates/history.jsonl`` (no secret in it). Three boxes implement the steps:
:class:`ComposeBox` (a site box, ``docker compose``), :class:`DemoBox` (the one-container demo VM, D-111) and
:class:`InProcessBox` (the in-process box of ``e2e_simple``: ``tools/update_drill.py`` exercises the whole path on
it, with a real backup, a real ``pg_dump`` / ``pg_restore`` and real migrations). Standard library only at import.
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import subprocess
import tarfile
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from tools import image_pins

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
)


class UpdateFailed(RuntimeError):
    pass


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


# ------------------------------------------------------------------------------------------------ database restore
# The compose box's rollback restore (ComposeBox.restore_databases), run in the db container: $1 role, $2 database,
# $3 RESET_SQL; the dump on stdin. The script goes to a 0600 file (pg_restore from a pipe into psql would let psql
# commit a cut-off script), RESET_SQL and the script run as one transaction, the file is deleted whatever happens.
RESTORE_SH = (
    "umask 077; t=$(mktemp) || exit 1; trap 'rm -f \"$t\"' EXIT; "
    'pg_restore --clean --if-exists --no-owner -f "$t" || exit 1; '
    '{ printf "%s\\n" "$3"; cat "$t"; } | psql -X -q -v ON_ERROR_STOP=1 --single-transaction -U "$1" -d "$2"'
)
# Everything the role owns that a later release could have added: its schemas (not public, not an extension's) and
# its relations in public (not an extension's). The dump's script then re-creates exactly what it holds.
RESET_SQL = """DO $tb$
DECLARE r record;
BEGIN
  FOR r IN SELECT n.nspname FROM pg_namespace n
           WHERE n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
             AND n.nspname <> 'public' AND n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
             AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_namespace'::regclass
                             AND d.objid = n.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('DROP SCHEMA %I CASCADE', r.nspname);
  END LOOP;
  FOR r IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
             AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
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

    def preflight(self, plan: Plan, backup: bool = True) -> list[str]:
        """Every refusal that needs nothing changed: compat.json against the live box, the release sequence, the
        box's own checks, the free space. Raises :class:`UpdateRefused`; returns notes."""
        from tools import update_status as us

        notes: list[str] = []
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
        m = us.create_marker(self.dir, {"bundle_id": plan.bundle_id, "manifest_sha256": plan.manifest_sha256,
                                        "release_seq": plan.release_seq, "target": self.box.name,
                                        "rollback_dir": str(rb), "stage": str(plan.stage), "step": None,
                                        "downgrade": plan.downgrade})  # fmt: skip
        rb.mkdir(parents=True, exist_ok=True)
        os.chmod(rb, 0o700)
        for name in (us.INSTALLED, us.TRUST):  # the state files as they were, for a rollback
            src = self.dir / name
            if src.is_file():
                shutil.copy2(src, rb / f"{name}.before")
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
        except Exception as exc:
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
        us.write_atomic(self.dir / us.INSTALLED, record)
        if plan.trust_after:
            us.write_atomic(self.dir / us.TRUST, plan.trust_after)

    def _rollback(self, plan: Plan, rb: Path, point: Point) -> bool:
        from tools import update_status as us

        us.set_step(self.dir, us.marker(self.dir) or {}, "rollback")
        try:
            self.box.rollback(plan, rb, point)
            self._restore_state(rb)
            self._history(plan, "rollback", True, "images, models, database, rulesets and update state put back")
            self._history(plan, "check after rollback", True, self.box.check(plan))
            return True
        except Exception as exc:
            us.set_step(self.dir, us.marker(self.dir) or {}, "rollback failed")
            self._history(plan, "rollback", False, f"{type(exc).__name__}: {exc} (restore from the backup: RUNBOOK §5)")
            return False

    def _restore_state(self, rb: Path) -> None:
        from tools import update_status as us

        for name in (us.INSTALLED, us.TRUST):
            before = rb / f"{name}.before"
            if before.is_file():
                us.write_atomic(self.dir / name, before.read_text(encoding="utf-8"))
            else:
                (self.dir / name).unlink(missing_ok=True)

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
        r = subprocess.run(
            list(argv),
            stdin=fin,
            stdout=fout or subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
            timeout=timeout,
            check=False,
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
        for tar in sorted(p for p in img.rglob("*") if p.is_file()) if img.is_dir() else []:
            self.run(["docker", "load", "-i", str(tar)], timeout=3600)
            done.append(f"image {tar.name}")
        return done

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

    def _c(self, *args: str) -> list[str]:
        return [*self.compose, *args]

    def running(self) -> bool:
        try:
            return "orchestrator" in self.run(self._c("ps", "--status", "running", "--services")).split()
        except UpdateFailed:
            return False

    def _dump(self, db: str, user: str, out: Path) -> None:
        self.run(self._c("exec", "-T", "db", "pg_dump", "-Fc", "--no-owner", "-U", user, "-d", db), stdout_file=out)

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

    def backup(self, plan: Plan, rb: Path) -> str:
        pub, targets = self._backup_where()
        # a quiet box: the services stop (the database stays up), so the dump, the files and the row counts agree
        self.run(self._c("stop", *PY_SERVICES), timeout=600)
        try:
            for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi")):
                self._dump(db, user, rb / f"{db}.dump")
            if os.environ.get("TB_UPDATE_BACKUP_CMD"):
                self.run(shlex.split(os.environ["TB_UPDATE_BACKUP_CMD"]), timeout=7200)
            else:
                self._backup_container(rb, pub, targets)
        except Exception:
            self.run(self._c("start", *PY_SERVICES), timeout=900)
            raise
        return ", ".join(targets)

    def _backup_container(self, rb: Path, pub: Path, targets: list[str], keep: int | None = None) -> None:
        """``trialbox backup`` in a one-off container on trialbox-net with every volume read-only and the dumps just
        taken (``TB_PG_DUMP_DIR``): the image has no pg_dump, the db container has no Python. Passwords travel in
        the environment (``-e NAME`` without a value), never on the command line."""
        from_backup = {
            "lake": "lake-data",
            "objects": "objects-data",
            "audit": "audit-data",
            "rulesets": "rulesets-data",
            "orchestrator": "orch-data",
            "mail": "mail-data",
            "secrets": "tb-secrets",
            "console": "console-data",
        }
        image = self.env.get("TB_IMAGE") or "trialbox-py:1.0.0"
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
        argv += [image, "python", "-m", "tools.trialbox", "backup", *tos, "--public", "/in/backup.pub", *dirs]
        argv += ["--keep", str(keep)] if keep is not None else []  # D-188: the schedule's TB_BACKUP_KEEP
        hapi_pw = self.env.get("POSTGRES_PASSWORD", "")
        env = {
            "TB_DB_URL": self.env.get("TB_DB_URL", ""),
            "TB_HAPI_DB_URL": f"postgresql://hapi:{hapi_pw}@db:5432/hapi",
        }
        self.run(argv, env=env, timeout=7200)

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
        sizes = 0
        for db in ("trialbox_wf", "hapi"):
            rows = self._psql(f"SELECT pg_database_size('{db}')")
            sizes += int(rows[0][0]) if rows and rows[0][0].isdigit() else 0
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
                 (updates, plan.payload_bytes("other"), "other files")]  # fmt: skip
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
        done = self.load_images(plan)
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
        changes, _, missing = image_pins.resolve(self.deploy, [Path(f) for f in files])
        if missing:
            raise UpdateFailed("pinned images neither on the box nor in the bundle: " + "; ".join(missing))
        image_pins.write_env(self.deploy / ".env", changes)

    def gpu(self) -> bool:
        return "gpu" in (self.env.get("COMPOSE_PROFILES") or "").replace(",", " ").split()

    def ensure_model_key(self) -> bool:
        """D-177 on a box installed before the key: make TB_LLM_API_KEY (as install.sh does) so the model servers and
        model-guard never start open. True when it was made now."""
        if not self.gpu() or self.env.get("TB_LLM_API_KEY"):
            return False
        key = secrets.token_urlsafe(36)
        image_pins.write_env(self.deploy / ".env", {"TB_LLM_API_KEY": key})
        self.env["TB_LLM_API_KEY"] = key
        return True

    def restart(self, plan: Plan) -> None:
        # new images: the containers are recreated and every service runs its migrations at start (tb_common.db)
        self.resolve_pins()
        self.ensure_model_key()
        t = os.environ.get("TB_INSTALL_UP_TIMEOUT", "900")
        pull = os.environ.get("TB_INSTALL_PULL") or "never"  # as install.sh: every image from a bundle (D-176)
        if pull not in ("never", "missing"):
            raise UpdateFailed(f"TB_INSTALL_PULL must be never or missing, not {pull!r}")
        self.run(self._c("up", "-d", "--pull", pull, "--wait", "--wait-timeout", t), timeout=int(t) + 120)

    def check_serving(self) -> str:
        """``trialbox doctor --serving`` on the model network, as install.sh runs it (pinned names, the key, model-guard
        in front): a FAIL fails the update, which is then rolled back."""
        if not self.gpu():
            return ""
        image = self.env.get("TB_IMAGE") or "trialbox-py:1.0.0"
        argv = ["docker", "run", "--rm", "--network", "trialbox-model-net", "--env-file", str(self.deploy / ".env"),
                "-v", f"{self.deploy}:/app/deploy:ro", image,
                "python", "-m", "tools.trialbox", "doctor", "--serving"]  # fmt: skip
        self.run(argv, timeout=300)
        return "; model servers: pinned names and the key (doctor --serving)"

    def post_apply(self, plan: Plan) -> list[str]:
        return self.rulesets(plan) + self.refdata(plan)

    def rulesets(self, plan: Plan) -> list[str]:
        done = []
        rs = plan.kind("ruleset")
        for z in sorted(rs.rglob("*.zip")) if rs.is_dir() else []:
            self.run(self._c("cp", str(z), "criteria-compiler:/tmp/ruleset-update.zip"))
            self.run(self._c("exec", "-T", "criteria-compiler", "python", "-m", "criteria_compiler.import_ruleset",
                             "/tmp/ruleset-update.zip", "--by", f"update:{plan.bundle_id}"))  # fmt: skip
            done.append(z.name)
        return done

    def refdata(self, plan: Plan) -> list[str]:
        """The reference data packs, after the release passed its check: each is one transaction (D-140), so a
        failure leaves the previous pack's rows and the healthy release; the pack waits in deploy/refdata/pending."""
        done = []
        for pack in refdata_packs(plan):  # D-140: verified again inside, then one transaction
            try:
                self.run(self._c("cp", str(pack), "criteria-compiler:/tmp/refdata-update.tar"))
                load = ["python", "-m", "tb_common.refdata", "load", "/tmp/refdata-update.tar"]
                self.run(self._c("exec", "-T", "criteria-compiler", *load, "--by", f"update:{plan.bundle_id}"),
                         timeout=7200)  # fmt: skip
            except UpdateFailed:
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
        self.run(self._c("up", "-d", "--wait", "--wait-timeout", "300"), timeout=420)  # every service healthy
        serving = self.check_serving()
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
        dump's own script (``pg_restore --clean --if-exists -f``, written to a 0600 file in the container and
        deleted). Any error rolls the whole of it back."""
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
        self.restore_databases(rb, point)
        refs = point.extra.get("rulesets_refs")
        if refs:  # rulesets-data back to the tag of the rollback point (imports of this update dropped)
            self.run(self._c("run", "--rm", "--no-deps", "-T", "criteria-compiler", "python", "-c", RULESETS_PY,
                             "restore", json.dumps(refs)))  # fmt: skip
        self.restart(plan)

    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None:
        code = (
            "import json, sys\nfrom tb_common.audit import AuditLog\ns = json.load(sys.stdin)\n"
            "AuditLog('/data/audit').append(s['event'], actor='apply_update.sh', input_sha=s['sha'],\n"
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

    def __init__(self, deploy: Path, run: Runner = run_cmd, wait_url: str = "http://127.0.0.1/login") -> None:
        self.deploy = deploy
        self.run = run
        self.container = os.environ.get("TB_DEMO_CONTAINER", "trialbox-demo")
        self.image = os.environ.get("TB_DEMO_IMAGE", "trialbox-demo:step5")
        self.run_script = Path(os.environ.get("TB_DEMO_RUN", "/etc/trialbox-demo/run.sh"))
        self.wait_url = wait_url
        self.models = Path(os.environ.get("TB_MODELS_DIR") or deploy / "models")

    def running(self) -> bool:
        try:
            return self.run(["docker", "inspect", "-f", "{{.State.Running}}", self.container]).strip() == "true"
        except UpdateFailed:
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


def main_apply(stage: Path, summary_file: Path, target: str, deploy: Path, backup: bool = True) -> int:
    """``apply_update.sh`` after verify: a box that is not running yet (first install) only loads the payloads, as
    before; a running box takes the whole path. The summary must come from a D-210 ``verify_update.py``
    (``release_seq``, the compatibility table, the trust after it): an older summary is refused."""
    from tools import update_status as us

    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    if not isinstance(summary.get("release_seq"), int) or not isinstance(summary.get("compat"), dict):
        print("update REFUSED: the summary has no release_seq or compatibility table (verify_update.py, D-210)")
        return 1
    plan = Plan.load(stage, summary)
    updates = deploy / "updates"
    box: ComposeBox | DemoBox = DemoBox(deploy) if target == "demo" else ComposeBox(deploy)
    if os.environ.get("TB_SKIP_AUDIT") or not box.running():
        try:
            with us.locked(updates):
                if us.marker(updates) is not None:
                    print("update REFUSED: an update is unfinished (tools/apply_update.sh status)")
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

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


@dataclass
class Plan:
    bundle_id: str
    manifest_sha256: str
    signer: str
    files: list[dict[str, Any]]
    stage: Path

    @classmethod
    def load(cls, stage: Path, summary: dict[str, Any]) -> Plan:
        return cls(
            str(summary["bundle_id"]),
            str(summary.get("manifest_sha256", "")),
            str(summary.get("signer", "")),
            list(summary.get("files") or []),
            stage,
        )

    def kind(self, kind: str) -> Path:
        return self.stage / kind


@dataclass
class Point:
    """What a rollback needs: retagged images, model files copied aside or new, the local database dumps."""

    images: dict[str, str] = field(default_factory=dict)  # tag -> rollback tag ("" when the tag is new)
    models_saved: list[str] = field(default_factory=list)
    models_new: list[str] = field(default_factory=list)
    dumps: dict[str, str] = field(default_factory=dict)  # database -> dump file
    extra: dict[str, Any] = field(default_factory=dict)


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


class Updater:
    """Runs the steps on a :class:`Box` and keeps the history (``deploy/updates/history.jsonl``)."""

    def __init__(self, box: Box, updates_dir: Path, say: Callable[[str], None] = print) -> None:
        self.box = box
        self.dir = updates_dir
        self.say = say

    def _history(self, plan: Plan, step: str, ok: bool, detail: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        line = {"at": _now(), "bundle": plan.bundle_id, "box": self.box.name, "step": step, "ok": ok, "detail": detail}
        with (self.dir / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.say(f"{'ok  ' if ok else 'FAIL'}  {step}" + (f": {detail}" if detail else ""))

    def run(self, plan: Plan, backup: bool = True) -> dict[str, Any]:
        rb = self.dir / plan.bundle_id / "rollback"
        rb.mkdir(parents=True, exist_ok=True)
        os.chmod(rb, 0o700)
        point = Point()
        steps: list[tuple[str, bool, str]] = []

        def step(name: str, ok: bool, detail: str = "") -> None:
            steps.append((name, ok, detail))
            self._history(plan, name, ok, detail)

        if backup:
            try:
                where = self.box.backup(plan, rb)
            except Exception as exc:
                step("backup (D-126)", False, f"{exc}; nothing was changed")
                raise UpdateFailed(f"backup failed, nothing was changed: {exc}") from exc
            step("backup (D-126)", True, where)
        else:
            step("backup skipped (--no-backup)", True, "audited")
        try:
            self.box.snapshot(plan, rb, point)
        except Exception as exc:
            step("rollback point", False, f"{exc}; nothing was changed")
            raise UpdateFailed(f"could not take the rollback point, nothing was changed: {exc}") from exc
        step("rollback point", True, f"{len(point.images)} images, {len(point.dumps)} databases")
        (rb / "point.json").write_text(json.dumps(point.__dict__, indent=1), encoding="utf-8")
        failed: str | None = None
        try:
            applied = self.box.apply(plan, rb, point)
            step("apply", True, f"{len(applied)} payloads")
            self.box.restart(plan)
            step("migrate and restart", True)
            done = self.box.post_apply(plan)
            step("rulesets", True, f"{len(done)} imported (rulesets and reference data)")
            step("check", True, self.box.check(plan))
        except Exception as exc:
            failed = f"{type(exc).__name__}: {exc}"
            step("update", False, failed)
        if failed is None:
            self.box.audit(
                "update.applied",
                plan,
                {"bundle_id": plan.bundle_id, "signer": plan.signer, "files": plan.files, "backup": backup},
            )
            for dump in point.dumps.values():
                if not os.environ.get("TB_UPDATE_KEEP_ROLLBACK"):
                    Path(dump).unlink(missing_ok=True)
            step("audited update.applied", True)
            return {"ok": True, "bundle_id": plan.bundle_id, "steps": steps}
        rolled = False
        try:
            self.box.rollback(plan, rb, point)
            step("rollback", True, "images, models and database put back")
            step("check after rollback", True, self.box.check(plan))
            rolled = True
        except Exception as exc:
            step("rollback", False, f"{type(exc).__name__}: {exc} (restore from the backup: RUNBOOK §5)")
        self.box.audit(
            "update.rolled_back",
            plan,
            {"bundle_id": plan.bundle_id, "error": failed[:500], "rolled_back": rolled},
        )
        raise UpdateFailed(
            f"update {plan.bundle_id} failed ({failed}); " + ("rolled back" if rolled else "ROLLBACK FAILED")
        )


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

    def backup(self, plan: Plan, rb: Path) -> str:
        pub = Path(os.environ.get("TB_BACKUP_PUBKEY") or self.deploy / "secrets" / "backup.pub")
        targets = [t for t in (self.env.get("TB_BACKUP_TARGETS") or "").replace(",", " ").split() if t]
        if not pub.is_file():
            raise UpdateFailed(f"no backup key {pub} (trialbox backup-keygen with hospital IT, RUNBOOK §5)")
        if not targets:
            raise UpdateFailed("no TB_BACKUP_TARGETS in deploy/.env (the NAS share, a USB disk ...)")
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

    def _backup_container(self, rb: Path, pub: Path, targets: list[str]) -> None:
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
        hapi_pw = self.env.get("POSTGRES_PASSWORD", "")
        env = {
            "TB_DB_URL": self.env.get("TB_DB_URL", ""),
            "TB_HAPI_DB_URL": f"postgresql://hapi:{hapi_pw}@db:5432/hapi",
        }
        self.run(argv, env=env, timeout=7200)

    def snapshot(self, plan: Plan, rb: Path, point: Point) -> None:
        for db in ("trialbox_wf", "hapi"):  # taken by backup() on a quiet box; else now
            f = rb / f"{db}.dump"
            if not f.is_file():
                self._dump(db, "trialbox" if db == "trialbox_wf" else "hapi", f)
            point.dumps[db] = str(f)
        self.snapshot_images(plan, point)

    def apply(self, plan: Plan, rb: Path, point: Point) -> list[str]:
        done = self.load_images(plan)
        done += copy_models(plan.kind("model"), self.models, rb, point)
        done += copy_other(plan.kind("other"), self.deploy / "updates" / plan.bundle_id / "files")
        return done

    def restart(self, plan: Plan) -> None:
        # new images: the containers are recreated and every service runs its migrations at start (tb_common.db)
        t = os.environ.get("TB_INSTALL_UP_TIMEOUT", "900")
        self.run(self._c("up", "-d", "--wait", "--wait-timeout", t), timeout=int(t) + 120)

    def post_apply(self, plan: Plan) -> list[str]:
        done = []
        rs = plan.kind("ruleset")
        for z in sorted(rs.rglob("*.zip")) if rs.is_dir() else []:
            self.run(self._c("cp", str(z), "criteria-compiler:/tmp/ruleset-update.zip"))
            self.run(self._c("exec", "-T", "criteria-compiler", "python", "-m", "criteria_compiler.import_ruleset",
                             "/tmp/ruleset-update.zip", "--by", f"update:{plan.bundle_id}"))  # fmt: skip
            done.append(z.name)
        for pack in refdata_packs(plan):  # D-140: verified again inside, then one transaction
            self.run(self._c("cp", str(pack), "criteria-compiler:/tmp/refdata-update.tar"))
            self.run(self._c("exec", "-T", "criteria-compiler", "python", "-m", "tb_common.refdata", "load",
                             "/tmp/refdata-update.tar", "--by", f"update:{plan.bundle_id}"), timeout=7200)  # fmt: skip
            done.append(pack.name)
        return done

    def check(self, plan: Plan) -> str:
        self.run(self._c("up", "-d", "--wait", "--wait-timeout", "300"), timeout=420)  # every service healthy
        cmd = os.environ.get("TB_UPDATE_CHECK_CMD")
        if cmd:
            self.run(shlex.split(cmd), timeout=3600)
            return "healthy; " + cmd
        return "every service healthy"

    def rollback(self, plan: Plan, rb: Path, point: Point) -> None:
        self.run(self._c("stop", *PY_SERVICES, "fhir-store"), timeout=600)  # nobody holds the databases open
        self.restore_images(point)
        restore_models(self.models, rb, point)
        for db, f in point.dumps.items():
            user = "trialbox" if db == "trialbox_wf" else "hapi"
            self.run(self._c("exec", "-T", "db", "pg_restore", "--clean", "--if-exists", "--no-owner",
                             "--single-transaction", "-U", user, "-d", db), stdin_file=Path(f))  # fmt: skip
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

    def snapshot(self, plan: Plan, rb: Path, point: Point) -> None:
        from tb_common.db import split_url

        from tools.trialbox import backup as bk

        dsn, prefix = split_url(self.url)
        f = rb / "trialbox_wf.dump"
        bk.dump(bk.DbSource("trialbox_wf", dsn, (f"{prefix}*",)), f, os.environ)
        os.chmod(f, 0o600)
        point.dumps["trialbox_wf"] = str(f)
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

    def _migrations(self, plan: Plan) -> list[str]:
        mig = plan.kind("other") / "migrations"
        return [p.read_text(encoding="utf-8") for p in sorted(mig.glob("*.sql"))] if mig.is_dir() else []

    def restart(self, plan: Plan) -> None:
        from tb_common.db import Database

        with Database.connect(self.url, "release") as db:
            db.migrate(self._migrations(plan))
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
        bk.restore_db(bk.DbSource("trialbox_wf", dsn, (f"{prefix}*",)), Path(point.dumps["trialbox_wf"]), os.environ)
        self.release.write_text(str(point.extra.get("release", "")), encoding="utf-8")
        restore_models(self.models, rb, point)
        self._open_stores()

    def audit(self, event: str, plan: Plan, detail: dict[str, Any]) -> None:
        _append_audit(self.work / "box" / "audit", event, plan, detail)


def main_apply(stage: Path, summary_file: Path, target: str, deploy: Path, backup: bool = True) -> int:
    """``apply_update.sh`` after verify: a box that is not running yet (first install) only loads the payloads, as
    before; a running box takes the whole path."""
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    plan = Plan.load(stage, summary)
    box: ComposeBox | DemoBox = DemoBox(deploy) if target == "demo" else ComposeBox(deploy)
    if os.environ.get("TB_SKIP_AUDIT") or not box.running():
        if plan.kind("ruleset").is_dir():
            print("rulesets: imported when the box runs (tools/apply_update.sh <bundle> again after the start)")
        for tar in refdata_packs(plan):  # install.sh loads deploy/refdata/pending/*.tar once the box runs
            pend = deploy / "refdata" / "pending"
            pend.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tar, pend / tar.name)
            print(f"reference data {tar.name}: loaded when the box runs (deploy/install.sh)")
        point = Point()
        rb = deploy / "updates" / plan.bundle_id / "rollback"
        rb.mkdir(parents=True, exist_ok=True)
        for line in box.apply(plan, rb, point):
            print(line)
        pend = deploy / "updates" / "pending_audit"
        pend.mkdir(parents=True, exist_ok=True)
        (pend / f"{plan.bundle_id}.json").write_text(json.dumps(summary), encoding="utf-8")
        print(f"update {plan.bundle_id} loaded; the box is not running, so install.sh starts it and audits it")
        return 0
    try:
        Updater(box, deploy / "updates").run(plan, backup=backup)
    except UpdateFailed as exc:
        print(f"update FAILED: {exc}")
        return 1
    print(f"update {plan.bundle_id} applied, checked and audited")
    return 0

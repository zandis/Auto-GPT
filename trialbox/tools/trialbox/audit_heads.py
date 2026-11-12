"""``trialbox audit-sign``: the nightly signed head of the audit chain (NEW-STD-2, D-562; STD-002, LIFE-010).

D-355 built the control: an Ed25519 key signs where the audit chain stands and the signed head is kept, write-once,
in a folder off the audit volume (``TB_AUDIT_ANCHOR_TARGETS``). This module is what runs it on a box, every night,
from the installer's cron file after ``logs daily``:

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
import fcntl
import json
import os
import shlex
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


def _libs() -> None:
    for p in (ROOT, ROOT / "libs"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


@contextlib.contextmanager
def reading(audit_dir: Path) -> Iterator[None]:
    """A shared lock on the audit writer's own lock file, so the chain and its anchor are read at one moment. The
    file is opened read-only and never made here; with no lock file no writer has run, and nothing is locked."""
    try:
        fd = os.open(audit_dir / ".lock", os.O_RDONLY)
    except OSError:
        yield
        return
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


def check_and_sign(audit_dir: Path, secrets_dir: Path, targets: Sequence[Path], now: datetime) -> Night:
    """Steps 1 and 2. Reads the audit folder, writes only into the anchor folders."""
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
    earlier = [h for t in targets if (t / "heads").is_dir() for h in audit.read_signed_heads(t)]
    with reading(audit_dir):
        try:
            head = audit.read_head(audit_dir)
        except ValueError as exc:
            return Night(False, [f"the head anchor of {audit_dir} cannot be read ({exc}): nothing was signed"])
        if head is None or not int(head.get("lines") or 0):
            return Night(True)  # no event yet: nothing to sign, and nothing wrong
        res = audit.verify(audit_dir, signed_heads=earlier or None, trusted_keys=own_keys(secrets_dir))
        if not res.ok:
            what = "an earlier signed head or its own head anchor" if earlier else "its own head anchor"
            why = "; ".join(res.errors[:3])
            return Night(False, [f"the audit chain does not agree with {what} ({why}): nothing was signed; look at it "
                                 "with tools/audit_verify.py --heads before anything else"])  # fmt: skip
        files = sorted(p.name for p in audit_dir.glob("*.jsonl"))
        try:
            rec = audit.make_signed_head(res.lines, res.last_hash, files[-1] if files else None, private_pem,
                                         public_pem, ts=now)  # fmt: skip
        except audit.AuditSignError as exc:
            return Night(False, [str(exc)])
    written, failed = 0, []
    for t in targets:  # after the lock: a slow share does not hold the box's audit writer
        try:
            audit.publish_head(t, rec, public_pem)
            written += 1
        except (OSError, audit.AuditSignError) as exc:
            failed.append(f"{t}: {exc}")
    detail: dict[str, Any] = {"lines": res.lines, "head": res.last_hash, "key_id": rec["key_id"], "anchors": written}
    if failed:
        detail["failed"] = failed
    problems = [f"the signed head was not written to {f}" for f in failed]
    return Night(not failed, problems, rec if written else None, detail)


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
    audit_dir = Path(env.get("TB_AUDIT_HOST_DIR") or f"{VOLUMES}/{project}_audit-data/_data")
    secrets = Path(env.get("TB_SECRETS_HOST_DIR") or f"{VOLUMES}/{project}_tb-secrets/_data")
    targets = [Path(p) for p in (env.get("TB_AUDIT_ANCHOR_TARGETS") or "").split(os.pathsep) if p.strip()]
    return audit_dir, secrets, targets


def sign_on_box(deploy: Path, env: Mapping[str, str], run: Run = _run) -> Night:
    """A site box, as root on the host: the signer in the box's image, the event through the orchestrator."""
    audit_dir, secrets, targets = host_dirs(env)
    kek_dir = Path(env.get("TB_KEK_FILE") or KEK_FILE).parent
    docker = shlex.split(env.get("TB_DOCKER") or "docker")
    mounts = ["-v", f"{audit_dir}:{audit_dir}:ro", "-v", f"{secrets}:{secrets}:ro"]
    if kek_dir.is_dir():
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
        night = Night(bool(doc["ok"]), list(doc["problems"]), doc.get("signed"), doc.get("detail"))
    except (RuntimeError, OSError, ValueError, KeyError, IndexError) as exc:
        return Night(False, [f"the signer did not answer ({exc}): nothing was recorded"])
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
    return report(night, len(host_dirs(env)[2]))


def init_key(secrets_dir: Path) -> int:
    """Make the audit signing key once, beside the site keys and under their KEK; a key that is there is kept."""
    _libs()
    from tb_common import audit, kek

    from tools import audit_verify

    if kek.key_present(secrets_dir / audit.SIGN_KEY_FILE):
        print(f"audit signing key: already in {secrets_dir}; kept")
        return 0
    return audit_verify.init_key(secrets_dir)


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
    night = check_and_sign(a.audit, a.secrets, a.to, datetime.now(UTC))
    print(json.dumps(asdict(night), ensure_ascii=False))
    return 0  # the answer is the JSON: a non-zero exit means the signer itself broke


if __name__ == "__main__":
    raise SystemExit(main())

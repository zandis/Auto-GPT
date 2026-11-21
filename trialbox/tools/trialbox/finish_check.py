"""10K-4 (D-1390): what a PRODUCTION install may not finish with.

    python3 -m tools.trialbox finish-check --deploy deploy                   # exit 1, each reason on stderr
    python3 -m tools.trialbox finish-check --deploy deploy --mount-anchors   # then the anchor folders into the console

A PRODUCTION box (``TB_ENV`` in ``deploy/.env``; no value is PRODUCTION, D-127) does not finish its install

* with its backups only on its own disks: no target of ``TB_BACKUP_TARGETS`` is off the box, judged by the rule the
  nightly backup judges a good backup by (``backup_schedule.Config.classify``: a network share, a USB disk, or a
  folder ``TB_BACKUP_OFFBOX`` declares that is on another device or carries ``.trialbox-offbox``). A folder that is
  not mounted is a folder of the box's own disk, so a second disk or a share not mounted yet is refused too;
* with an audit anchor folder that cannot be mounted: none named in ``TB_AUDIT_ANCHOR_TARGETS``, a name the
  installer's mount refuses (``anchors.plan``), or a folder that is not there.

Outside PRODUCTION nothing is refused here (``doctor`` and the preflight report the same facts). The check reads the
mount table and the folders and writes nothing. ``--mount-anchors`` (``deploy/box-install.sh`` after the owner's
answers are applied, where ``install.sh``'s ANCHOR-MOUNT block did not run) writes ``deploy/site/compose.anchors.yml``
as that block does (``anchors.write``) and keeps ``COMPOSE_FILE`` in ``deploy/.env`` naming it, or no longer naming it
when no folder is set (a ``deploy/.env`` without a ``COMPOSE_FILE`` line is left as it is, with a note). Standard
library and ``yaml`` only (the host's ``python3``, as ``anchors-compose``).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from tools.trialbox import anchors
from tools.trialbox import backup_schedule as bs


def production(env: dict[str, str]) -> bool:
    return (env.get("TB_ENV") or "PRODUCTION").strip().upper() == "PRODUCTION"


def problems(deploy: Path, env: dict[str, str]) -> list[str]:
    """Why this PRODUCTION install may not finish; empty outside PRODUCTION or when it may."""
    if not production(env):
        return []
    out: list[str] = []
    cfg = bs.config(deploy, env, process_env=False)
    if not cfg.targets:
        out.append("no backup target: TB_BACKUP_TARGETS in deploy/.env names none")
    else:
        kinds = [cfg.classify(t) for t in cfg.targets]
        if not any(k.offbox for k in kinds):
            said = "; ".join(f"{k.path}: {k.kind}" for k in kinds)
            out.append(
                f"every backup target is on the box's own disks ({said}): a lost box loses its backups. Mount the "
                "second disk or the hospital's share at the folder chosen (TB_BACKUP_TARGETS)"
            )
    try:
        folders = anchors.plan(env)
    except anchors.AnchorError as exc:
        out.append(f"the audit anchor folder cannot be mounted: {exc}")
    else:
        if not folders:
            out.append(f"no audit anchor folder: {anchors.ENV} in deploy/.env names none (the hospital's write-once "
                       "share, mounted on the box)")  # fmt: skip
        for folder in anchors.missing(folders):
            out.append(f"the audit anchor folder {folder} is not there: mount the hospital's share there first")
    return out


def _write_env(path: Path, lines: list[str]) -> None:
    """``deploy/.env`` replaced whole: a new file beside it, owner-only from its creation (``mkstemp``: 0600, a name
    nobody else can take), then renamed over the old one, so a failed write leaves the old file."""
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def mount_anchors(deploy: Path) -> str:
    """The anchor folders of ``deploy/.env`` into the console, as ``install.sh`` does it; an error, or empty."""
    env_file = deploy / ".env"
    env = anchors.read_env(env_file)
    try:
        folders = anchors.plan(env)
        gone = anchors.missing(folders)
    except anchors.AnchorError as exc:
        return str(exc)
    if gone:
        return f"{anchors.ENV}: no such folder {', '.join(gone)} (mount the hospital's share first)"
    lines = env_file.read_text(encoding="utf-8").splitlines()
    at = [i for i, ln in enumerate(lines) if ln.startswith("COMPOSE_FILE=")]
    if not at:  # not written by deploy/install.sh: nothing is guessed; doctor's anchor_mount check says it
        if folders:
            print("    note: the audit anchor folders are not mounted into the console: deploy/.env has no "
                  "COMPOSE_FILE line (deploy/install.sh writes it); run the install again (D-638)")  # fmt: skip
        return ""
    made = anchors.write(deploy, env)
    files = [f for f in lines[at[-1]].split("=", 1)[1].split(os.pathsep) if f.strip()]
    kept = [f for f in files if not anchors._same(deploy, f, deploy / anchors.NAME)]
    if made is not None:
        kept.append(str(made))
    line = "COMPOSE_FILE=" + os.pathsep.join(kept)
    if line != lines[at[-1]]:
        lines[at[-1]] = line
        _write_env(env_file, lines)
    return ""


def main_action(deploy: Path, mount: bool = False) -> int:
    env = anchors.read_env(deploy / ".env")
    found = problems(deploy, env)
    for p in found:
        print(f"finish-check: {p}", file=sys.stderr)
    if found:
        print("finish-check: a PRODUCTION install does not finish with backups only on the box or an audit anchor "
              "folder that cannot be mounted (RUNBOOK §5); fix the above, then run the install again",
              file=sys.stderr)  # fmt: skip
        return 1
    if production(env):
        print("    finish check: a backup target is off the box and every audit anchor folder is there")
    if mount:
        err = mount_anchors(deploy)
        if err:
            print(f"finish-check: {err}", file=sys.stderr)
            return 1
    return 0

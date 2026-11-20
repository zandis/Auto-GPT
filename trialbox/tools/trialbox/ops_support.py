"""10K-5 (D-1381): the support bundle as an operations action, the host's half.

The console's "Make a support bundle" button writes an ``support_bundle`` request into the operations folder like
every other operation (``tools/trialbox/ops.py``); the host's runner takes it and calls the SAME builder as
``trialbox support-bundle`` (:func:`tools.support_bundle.build`), with its scrubbers, the line scan and the last look
at the finished archive (D-405, D-723, D-747, D-962). Nothing is added to what the bundle holds: no ``--add`` file,
the default log days, and the request's ``args`` are never read (the console's user writes the request file).

A bundle that fails the scan raises :class:`tools.support_bundle.BundleRefused`; the builder has then written
nothing, and the result says ``BundleRefused: ...`` (pattern ids and member names, never a value), which the page
shows as "not handed out". A bundle that passes is written to ``<ops>/support/`` (folder 0750 root and the console's
group; file 0640), its file name, size and sha256 are the result's last three lines, and only the newest
:data:`KEEP` bundles stay. On a site box the runner also writes the audit event ``console.ops`` with
``support_bundle.made``, the file name, size and sha256 (never a line of the bundle).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ACTION = "support_bundle"
SUBDIR = "support"
KEEP = 3  # the newest bundles kept in <ops>/support/; an older one is removed when a new one is made
NAME = re.compile(r"trialbox-support-\d{8}T\d{6}Z\.tar\.gz", re.ASCII)  # the builder's file name, matched whole
LINE_FILE, LINE_BYTES, LINE_SHA = "file ", "bytes ", "sha256 "
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)


def support_dir(ops_root: Path) -> Path:
    return Path(ops_root) / SUBDIR


def sha256_of(fh: Any) -> tuple[str, int]:
    """The sha256 and the size of an open binary file, read from where it stands to its end."""
    h, n = hashlib.sha256(), 0
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
        n += len(chunk)
    return h.hexdigest(), n


def record(result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The bundle a finished ``support_bundle`` result names (file, bytes, sha256), from the last three lines the
    runner (root) wrote; None for any other result, a failed one, or lines that do not have that exact form."""
    if not result or result.get("action") != ACTION or result.get("ok") is not True:
        return None
    lines = [str(x) for x in result.get("lines") or []][-3:]
    if len(lines) != 3 or not (
        lines[0].startswith(LINE_FILE) and lines[1].startswith(LINE_BYTES) and lines[2].startswith(LINE_SHA)
    ):
        return None
    name, size, sha = lines[0][len(LINE_FILE) :], lines[1][len(LINE_BYTES) :], lines[2][len(LINE_SHA) :]
    if not NAME.fullmatch(name) or not size.isdigit() or not _SHA.fullmatch(sha):
        return None
    return {"file": name, "bytes": int(size), "sha256": sha}


def _prepare(d: Path, uid: int) -> None:
    d.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # the host's runner: root owns it, the console's group reads
        os.chown(d, 0, uid)
        os.chmod(d, 0o750)


def _prune(d: Path, keep: int) -> list[str]:
    old = sorted(p.name for p in d.iterdir() if NAME.fullmatch(p.name) and p.is_file())[:-keep]
    for name in old:
        with contextlib.suppress(OSError):
            (d / name).unlink()
    return old


def _audit_made(runner: Any, rec: Mapping[str, Any], rid: str) -> None:
    """On a site box: ``console.ops`` with ``support_bundle.made`` in the box's chain, written inside the
    orchestrator as :meth:`tools.trialbox.ops.OpsRunner.audit` writes the result's event. Best effort."""
    if runner.box.kind != "compose":
        return
    from tools.trialbox.update import ComposeBox

    detail = {"action": f"{ACTION}.made", "request": rid, **rec}
    code = (
        "import json, sys\nfrom tb_common.audit_writer import open_audit\n"
        "open_audit().append('console.ops', actor='trialbox-ops', detail=json.loads(sys.argv[1]))\n"
    )
    argv = [*ComposeBox(runner.box.deploy).compose, "exec", "-T", "orchestrator", "python", "-c", code,
            json.dumps(detail)]  # fmt: skip
    with contextlib.suppress(Exception):
        runner.box.run(argv, 120)


def do_support_bundle(runner: Any, args: Mapping[str, str]) -> tuple[str, list[str]]:
    """``OpsRunner.do_support_bundle``: the bundle, made by :func:`tools.support_bundle.build`; ``args`` unread."""
    from tools import support_bundle
    from tools.trialbox.ops import SERVICE_UID

    out = support_dir(runner.ops.root)
    _prepare(out, SERVICE_UID)
    said: list[str] = []
    # a site box runs doctor, docker, df and nvidia-smi as the command does; the in-process box has no docker
    target = support_bundle.build(runner.box.deploy, out, commands=runner.box.kind == "compose", say=said.append)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        os.chown(target, 0, SERVICE_UID)
        os.chmod(target, 0o640)
    with open(target, "rb") as fh:
        sha, size = sha256_of(fh)
    removed = _prune(out, KEEP)
    rec = {"file": target.name, "bytes": size, "sha256": sha}
    rid = next((str(r.get("id")) for r in runner.ops.running() if r.get("action") == ACTION), "")
    _audit_made(runner, rec, rid)
    lines = [x.replace(str(out) + os.sep, "") for x in said][-30:]
    if removed:
        lines.append(f"older bundles removed (the newest {KEEP} are kept): {', '.join(removed)}")
    lines += [f"{LINE_FILE}{target.name}", f"{LINE_BYTES}{size}", f"{LINE_SHA}{sha}"]
    return f"support bundle made: {target.name}, {size} bytes, sha256 {sha[:16]}", lines

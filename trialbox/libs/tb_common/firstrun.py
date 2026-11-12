"""The box's first-run folder and its one-time code (T-729, D-466).

The box installer (``deploy/box-install.sh``) makes a one-time code and shows it on the box's own screen; the
console's first-run pages (``console.firstrun``) open only with that code and only while the box has no account at
all. The folder is the host's ``/run/trialbox-firstrun`` (tmpfs), mounted into the console (``TB_FIRSTRUN_DIR``,
``deploy/docker-compose.box.yml``): what the owner types there never reaches a disk, and a restart forgets it.

Files in the folder (each 0600):

* ``code.json``: the code's SHA-256 and the failed tries. :data:`MAX_TRIES` wrong codes void it (the installer then
  shows a new one on the box's screen), the same count as a console sign-in (``console.auth.MAX_FAILURES``);
* ``hardware.json``: what the installer detected (the disks a backup may go to, whether the board has a TPM, the
  host's zone and name), so the wizard offers only what this machine has;
* ``answers.json``: the owner's answers (``tb_common.box_answers``), written by the console when the owner account
  is made, read and removed by the installer's apply step;
* ``pending.json``: the console's half-finished first run (the form token and the authenticator key being set up).

Standard library only (the installer runs it with the host's ``python3``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

CODE = "code.json"
HARDWARE = "hardware.json"
ANSWERS = "answers.json"
PENDING = "pending.json"
MAX_TRIES = 5  # as console.auth.MAX_FAILURES: five wrong codes void it
READABLE = "abcdefghjkmnpqrstuvwxyz23456789"  # read off a screen: no 0/o, 1/l/i (console.auth.READABLE)


def _sha(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _clean(typed: str) -> str:
    return "-".join(p for p in re.split(r"[\s-]+", (typed or "").strip().lower()) if p)


def write_private(path: Path, data: dict[str, Any]) -> None:
    """``data`` as JSON, readable by its owner only, replaced in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def read(path: Path) -> dict[str, Any]:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def make_code(folder: Path, groups: int = 4) -> str:
    """A new one-time code (four groups of four: about 79 bits); only its hash is kept. Replaces an earlier one."""
    code = "-".join("".join(secrets.choice(READABLE) for _ in range(4)) for _ in range(groups))
    write_private(folder / CODE, {"sha256": _sha(code), "failures": 0})
    return code


def is_open(folder: Path | None) -> bool:
    return folder is not None and (folder / CODE).is_file()


def check_code(folder: Path, typed: str) -> bool:
    """True when ``typed`` is the live code. A wrong code counts; the last allowed wrong one removes the code."""
    state = read(folder / CODE)
    if not state.get("sha256"):
        return False
    if hmac.compare_digest(str(state["sha256"]), _sha(_clean(typed))):
        return True
    failures = int(state.get("failures") or 0) + 1
    if failures >= MAX_TRIES:
        close(folder)
    else:
        write_private(folder / CODE, {**state, "failures": failures})
    return False


def close(folder: Path) -> None:
    """The code is used up (or void): the first-run pages answer 404 from now on."""
    for name in (CODE, PENDING):
        (folder / name).unlink(missing_ok=True)

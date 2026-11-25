"""H-136: the hold after a restore (``screening.after_restore``, D-522), read through the box. Standard library only.

``trialbox doctor`` is typed on the box's host, whose ``python3`` has no database client and no address of the box's
database (the database is on the compose network only). So the hold is read the way the host's other steps ask the
box (the backup's job count, the databases' sizes): ``docker compose --project-directory <deploy> exec -T db psql``,
as the database's owner role, in a read-only transaction that creates nothing. What decides where it is read:

* the box's own ``deploy/.env`` (``launch.box_file``: a file that cannot be trusted is no reading), its
  ``TB_COMPOSE`` and ``TB_DOCKER`` when it names them, else ``docker compose``; never the caller's;
* the engine's environment: ``PATH``, ``HOME`` and the engine variables the box file names, as the restore runs
  compose (``box_restore.engine_env``); a caller's ``COMPOSE_PROJECT_NAME``, ``COMPOSE_FILE``, ``DOCKER_HOST`` ...
  never reach compose, which reads the project from ``deploy/.env`` itself.

:func:`read` returns one of three readings, each its own doctor line: ``held`` (with who, when and the reason),
``released`` (or never set: no row, as the scheduler reads it), or ``unread`` with the cause. ``python3 -m
tools.trialbox.box_hold <deploy>`` prints the reading as one JSON line: the host check and the box rehearsal hand it
to a doctor that runs in the box image, which has no engine to ask (``TB_DOCTOR_RESTORE_HOLD``)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

FLAG = "screening.after_restore"  # tb_common.flags.DECLARED; scheduler.RESTORE_FLAG
VALUES = ("released", "held")  # its declared values; no row is "released" (the scheduler holds only on "held")
TIMEOUT_S = 30.0  # one small query; a box that does not answer in this time is no reading
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"  # box_restore.SAFE_PATH
ENGINE_KEYS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
#: the reading, in a read-only transaction; the store not installed yet (no service has started) reads as no row
SQL = f"""SET default_transaction_read_only = on;
SET statement_timeout = '20s';
SELECT to_regclass('app.flag') IS NOT NULL AS tb_has_flag \\gset
\\if :tb_has_flag
SELECT json_build_object('stored', f.value IS NOT NULL, 'value', f.value, 'by', f.changed_by,
  'at', to_char(f.changed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS "UTC"'), 'reason', f.reason)::text
  FROM (SELECT 1) AS one LEFT JOIN app.flag AS f ON f.name = '{FLAG}';
\\else
SELECT json_build_object('stored', false)::text;
\\endif
"""


def unread(cause: str) -> dict[str, Any]:
    return {"state": "unread", "cause": cause}


def engine(deploy: Path, box: Mapping[str, str]) -> tuple[list[str], dict[str, str]]:
    """The compose command and its environment, from the box file alone (never the caller's)."""
    import pwd

    docker = shlex.split(box.get("TB_DOCKER") or "docker")
    compose = shlex.split(box.get("TB_COMPOSE") or "") or [*docker, "compose", "--project-directory", str(deploy)]
    try:
        home = pwd.getpwuid(os.geteuid()).pw_dir
    except KeyError:
        home = "/root"
    env = {"PATH": os.environ.get("PATH") or SAFE_PATH, "HOME": home}
    env.update({k: box[k] for k in ENGINE_KEYS if box.get(k)})
    return compose, env


def argv(compose: list[str]) -> list[str]:
    return [
        *compose,
        "exec",
        "-T",
        "db",
        "psql",
        "-X",
        "-q",
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "trialbox",
        "-d",
        "trialbox_wf",
        "-f",
        "-",
    ]


def parse(out: str) -> dict[str, Any]:
    """The reading from psql's one line of JSON."""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    try:
        got = json.loads(lines[-1]) if lines else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return unread("the box's database gave no reading of the hold")
    if not got.get("stored"):
        return {"state": "released", "stored": False}
    value = str(got.get("value") or "")
    if value not in VALUES:
        return unread(f"the hold holds {value[:40]!r}, not a value the box declares (released, held)")
    return {"state": value, "stored": True, **{k: str(got.get(k) or "") for k in ("by", "at", "reason")}}


def read(deploy: Path, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """The hold of the box whose deploy folder is ``deploy``, asked of its ``db`` container; never raises."""
    from tools.trialbox import launch

    deploy = Path(os.path.abspath(deploy))
    try:
        box = launch.box_file(deploy)
    except launch.BoxFileError as e:
        return unread(str(e).replace(": nothing was run", ""))
    if not box:
        return unread(f"no box file at {deploy / '.env'}: the box's compose project cannot be named")
    compose, env = engine(deploy, box)
    try:
        r = subprocess.run(
            argv(compose), input=SQL, capture_output=True, text=True, env=env, timeout=timeout, cwd=deploy, check=False
        )
    except subprocess.TimeoutExpired:
        return unread(f"the box's database did not answer within {timeout:.0f} s (compose exec db)")
    except OSError as e:
        return unread(f"the container engine cannot be started here ({compose[0]}: {e.strerror or type(e).__name__})")
    if r.returncode != 0:
        err = " ".join((r.stderr or "").split())[-240:] or "no message"
        return unread(f"compose exec db psql ended {r.returncode}: {err}")
    return parse(r.stdout or "")


def main(args: list[str] | None = None) -> int:
    rest = sys.argv[1:] if args is None else args
    if len(rest) != 1:
        print("usage: python3 -m tools.trialbox.box_hold <the box's deploy folder>", file=sys.stderr)
        return 2
    print(json.dumps(read(Path(rest[0])), sort_keys=True))
    return 0  # the reading is the answer, "unread" included: the doctor that is handed it says FAIL


if __name__ == "__main__":
    raise SystemExit(main())

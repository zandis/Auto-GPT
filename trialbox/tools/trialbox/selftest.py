"""``trialbox selftest``: the pair canary on an installed box, without ``make`` (OPS-033, RUNBOOK §4 and §24).

It runs ``orchestrator.selftest`` (the 54-case pair canary) in the box's orchestrator container with the compose
files the box was installed with: ``COMPOSE_FILE`` in ``deploy/.env`` (install.sh writes it: the base file, the
secrets overlay, the GPU profile, the identity overlay and any site override), and the profiles of
``COMPOSE_PROFILES``. Without ``COMPOSE_FILE`` (a checkout that was never installed) it uses the base file and says
so. ``TB_COMPOSE`` replaces the ``docker compose --project-directory deploy`` command, as for ``secrets`` and
``update``. The exit code is the canary's: 0 when it passes, 2 when it could not reach a model (not run). The
result is the gate's (D-916): ``orchestrator.selftest`` writes ``selftest.json`` and the audit, and the running
orchestrator takes the newer result, so a pass opens the gate without a restart or the console.

Standard library only, so it runs with the host's ``python3`` from the install folder:
``sudo python3 -m tools.trialbox selftest``.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

Runner = Callable[[list[str]], int]

CANARY = ("exec", "-T", "orchestrator", "python", "-m", "orchestrator.selftest")


def read_env(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of ``deploy/.env``; quotes around a value are dropped. Missing file: empty."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def compose_files(deploy: Path, env: dict[str, str]) -> list[Path]:
    """The box's compose files from ``COMPOSE_FILE`` (relative entries are under the deploy folder)."""
    sep = env.get("COMPOSE_PATH_SEPARATOR") or os.pathsep
    files = [Path(f) for f in (env.get("COMPOSE_FILE") or "").split(sep) if f.strip()]
    return [f if f.is_absolute() else deploy / f for f in files]


def command(deploy: Path) -> tuple[list[str], str | None]:
    """The canary command, and a note when the box's compose files are not known."""
    env = read_env(deploy / ".env")
    base = shlex.split(os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}")
    files = compose_files(deploy, env)
    note = None
    if not files:
        files = [deploy / "docker-compose.yml"]
        note = f"no COMPOSE_FILE in {deploy / '.env'}: using the base compose file only (run install.sh first)"
    args = [a for f in files for a in ("-f", str(f))]
    for p in (env.get("COMPOSE_PROFILES") or "").split(","):
        if p.strip():
            args += ["--profile", p.strip()]
    return [*base, *args, *CANARY], note


def _run(cmd: list[str]) -> int:
    return subprocess.run(cmd, check=False).returncode  # a fixed argument list, no shell


def main(deploy: Path, *, dry_run: bool = False, run: Runner = _run) -> int:
    cmd, note = command(deploy)
    if note:
        print(f"selftest: note: {note}", file=sys.stderr)
    missing = [p for i, p in enumerate(cmd) if i and cmd[i - 1] == "-f" and not Path(p).is_file()]
    if missing:
        print(f"selftest: FAIL: compose file not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    if dry_run:
        print(shlex.join(cmd))
        return 0
    code = run(cmd)
    if code == 0:
        print("selftest: the pair canary passed; recorded as the gate's result (note answers may exclude again)")
    elif code == 2:  # D-915, D-916: a model could not be reached; nothing recorded
        print("selftest: not run: the canary could not reach a model (still loading?); wait a minute and run it again")
    else:
        print(f"selftest: FAIL: the pair canary exited {code}")
    return code

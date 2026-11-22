"""Whether ``deploy/install.sh`` may run ``docker compose down --remove-orphans`` on its project (F-19).

    python3 -m tools.trialbox.project_check --deploy "$ROOT/deploy" -- <the installer's compose command>

A re-run after a failed run met the failed run's containers and network at the database's start. The installer
cleans them up, but only what it can prove is this install's own, and never a stack that is running healthy:

* the project name is this install's (``COMPOSE_PROJECT_NAME`` in ``deploy/.env``, else the ``name:`` of
  ``deploy/docker-compose.yml``). A different ``COMPOSE_PROJECT_NAME`` inherited from the shell is refused, and so is
  a compose command that resolves another name;
* every container that carries the project's label was started from this ``deploy`` folder. One from any other
  folder is refused: the name is shared, so nothing is removed;
* a stack whose containers all run (healthy where they have a health check) or ended a one-shot job with exit 0 is
  kept. Its containers and their uncollected logs stay.

It prints ``down`` (clean up), ``keep`` (healthy, nothing removed) or ``none`` (no container of the project).
A refusal exits 2 with the reason and removes nothing. The command itself never removes anything.
Standard library only: the host's python3 runs it before the stack starts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

LABEL_PROJECT = "com.docker.compose.project"
LABEL_DIR = "com.docker.compose.project.working_dir"
NAME_RULE = re.compile(r"[a-z0-9][a-z0-9_-]*")
NOTHING = "nothing was removed / 未移除任何項目 / 何も削除していません"

Runner = Callable[[Sequence[str]], str]


class Refused(RuntimeError):
    pass


def _run(argv: Sequence[str]) -> str:
    r = subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=120)
    if r.returncode != 0:
        raise Refused(f"{' '.join(argv[:3])} failed (exit {r.returncode}): {NOTHING}")
    return r.stdout


def _setting(path: Path, key: str) -> str:
    value = ""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == key and not line.lstrip().startswith("#"):
                value = v.strip().strip("\"'")
    return value


def install_project(deploy: Path) -> str:
    """This install's compose project name, as compose reads it without an inherited variable."""
    name = _setting(deploy / ".env", "COMPOSE_PROJECT_NAME")
    if not name:
        compose = deploy / "docker-compose.yml"
        text = compose.read_text(encoding="utf-8") if compose.is_file() else ""
        m = re.search(r"^name:\s*['\"]?([^'\"\s#]+)", text, re.M)
        name = m.group(1) if m else ""
    if not NAME_RULE.fullmatch(name):
        raise Refused(f"this install's compose project name is not known ({name or 'none'}): {NOTHING}")
    return name


def healthy(state: Mapping[str, Any], restart: str) -> bool:
    """Running (healthy when it has a health check), or a one-shot job that ended with exit 0."""
    if state.get("Status") == "running":
        return (state.get("Health") or {}).get("Status") in (None, "healthy")
    return state.get("Status") == "exited" and state.get("ExitCode") == 0 and restart in ("", "no")


def _restart(container: Mapping[str, Any]) -> str:
    return str(((container.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or "")


def decide(deploy: Path, compose: Sequence[str], environ: Mapping[str, str], run: Runner = _run) -> tuple[str, str]:
    """``down``, ``keep`` or ``none`` with a line for the log; :class:`Refused` when it cannot prove the project."""
    name = install_project(deploy)
    inherited = environ.get("COMPOSE_PROJECT_NAME")
    if inherited is not None and inherited != name:
        raise Refused(f"COMPOSE_PROJECT_NAME={inherited} in this shell is not this install's project ({name}): "
                      f"unset it, then re-run; {NOTHING}")  # fmt: skip
    try:
        resolved = json.loads(run([*compose, "config", "--no-interpolate", "--format", "json"])).get("name")
    except (ValueError, AttributeError):
        resolved = None
    if resolved != name:
        raise Refused(f"the compose command resolves project {resolved!r}, not this install's {name!r}: {NOTHING}")
    docker = list(compose[: compose.index("compose")]) if "compose" in compose else ["docker"]
    ids = run([*docker, "ps", "-a", "-q", "--no-trunc", "--filter", f"label={LABEL_PROJECT}={name}"]).split()
    if not ids:
        return "none", f"no container of project {name}: nothing to clean up"
    info = json.loads(run([*docker, "inspect", *ids]))
    mine = os.path.realpath(deploy)
    dirs = [str(((c.get("Config") or {}).get("Labels") or {}).get(LABEL_DIR) or "") for c in info]
    foreign = sorted({d or "?" for d in dirs if not d or os.path.realpath(d) != mine})
    if foreign or len(info) != len(ids):
        raise Refused(f"project {name} has containers started from another folder ({', '.join(foreign) or '?'}), "
                      f"not {mine}: another install uses the name; {NOTHING}")  # fmt: skip
    sick = [str(c.get("Name", "?")).lstrip("/") for c in info if not healthy(c.get("State") or {}, _restart(c))]
    if not sick:
        return "keep", f"project {name} is running healthy: kept (its containers and logs stay)"
    return "down", f"project {name} (this install's) has stopped or unhealthy containers: {', '.join(sick)}"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    compose = args[args.index("--") + 1 :] if "--" in args else []
    p = argparse.ArgumentParser(prog="project_check")
    p.add_argument("--deploy", type=Path, required=True)
    a = p.parse_args(args[: args.index("--")] if "--" in args else args)
    if not compose:
        print("project_check: give the compose command after --", file=sys.stderr)
        return 2
    try:
        verdict, line = decide(a.deploy, compose, os.environ)
    except (Refused, OSError, ValueError) as e:
        print(f"project cleanup refused / 拒絕清理專案 / プロジェクトの整理を拒否しました: {e}", file=sys.stderr)
        return 2
    print(f"    {line}", file=sys.stderr)
    print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

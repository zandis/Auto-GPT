"""``trialbox eval qualify --box``: qualify on an installed box with the paths the box serves (BOX-QUALIFY, D-737).

Lane G's blocker 5: ``tools/qualify.py`` on a box needs ``--model-dir judge=/verifier=``, ``--server-log`` and
``--audit-dir``, and nothing on the box supplied them. This asks the running box, through ``docker compose ps -q``
and ``docker inspect`` (``TB_COMPOSE``, ``TB_DOCKER`` as the updater uses them), for what it really serves:

* each model server's weight folder: the host source of its ``/models`` mount joined with its ``--model=`` argument
  (``llm-service`` is the judge, ``llm-verifier`` the verifier);
* each model server's log file: Docker's json-file log (``.LogPath``; every service logs to json-file);
* the gateway's audit folder: the host source of its ``/data/audit`` mount.

An option the operator gave is kept and the box's value for it is not added. What the box cannot say is printed
and left out, never guessed; ``qualify`` then fails its own step for it. Run as root on the box::

    python3 -m tools.trialbox eval qualify --box --profile rtxpro6000 --gateway-url <url> --evidence ... --operator N
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVERS = (("llm-service", "judge"), ("llm-verifier", "verifier"))
FILLED = ("--model-dir", "--server-log", "--audit-dir")

Run = Callable[..., str]


def _inspect(run: Run, compose: list[str], docker: list[str], service: str) -> dict[str, Any] | None:
    cid = run([*compose, "ps", "-q", service]).strip().splitlines()
    if not cid:
        return None
    got = json.loads(run([*docker, "inspect", cid[0]]))
    return got[0] if isinstance(got, list) and got else None


def _mount(info: dict[str, Any], dest: str) -> str | None:
    return next((str(m["Source"]) for m in info.get("Mounts") or [] if m.get("Destination") == dest), None)


def _weights(info: dict[str, Any]) -> str | None:
    arg = next((a for a in info.get("Args") or [] if str(a).startswith("--model=")), None)
    src = _mount(info, "/models")
    if arg is None or src is None:
        return None
    rel = PurePosixPath(str(arg).removeprefix("--model=")).relative_to("/models")
    return str(PurePosixPath(src) / rel)


def discover(run: Run, compose: list[str], docker: list[str]) -> tuple[list[str], list[str]]:
    """The options the box can give, and what it could not say."""
    args: list[str] = []
    problems: list[str] = []
    for service, role in SERVERS:
        info = _inspect(run, compose, docker, service)
        if info is None:
            problems.append(f"{service} is not running: no {role} weight folder or log")
            continue
        folder = _weights(info)
        if folder is None:
            problems.append(f"{service} has no /models mount and --model= argument: no {role} weight folder")
        else:
            args += ["--model-dir", f"{role}={folder}"]
        if info.get("LogPath"):
            args += ["--server-log", str(info["LogPath"])]
        else:
            problems.append(f"{service} has no json-file log (.LogPath): no {role} server log")
    gw = _inspect(run, compose, docker, "gateway")
    audit = _mount(gw, "/data/audit") if gw is not None else None
    if audit:
        args += ["--audit-dir", audit]
    else:
        problems.append("gateway is not running or has no /data/audit mount: no audit folder")
    return args, problems


def _pairs(args: list[str]) -> list[tuple[str, str]]:
    return [(args[i], args[i + 1]) for i in range(0, len(args) - 1, 2)]


def fill(given: list[str], found: list[str]) -> list[str]:
    """``given`` and the box's options it does not already have: a role named by ``--model-dir`` is kept, and
    ``--server-log`` and ``--audit-dir`` given at all are kept whole."""
    roles = {given[i + 1].split("=", 1)[0] for i, a in enumerate(given[:-1]) if a == "--model-dir"}
    out = list(given)
    for opt, val in _pairs(found):
        if opt == "--model-dir" and val.split("=", 1)[0] in roles:
            continue
        if opt in ("--server-log", "--audit-dir") and opt in given:
            continue
        out += [opt, val]
    return out


def main(argv: list[str] | None = None) -> int:
    from tools import qualify
    from tools.trialbox.update import run_cmd

    given = list(sys.argv[1:] if argv is None else argv)
    deploy = ROOT / "deploy"
    compose = shlex.split(
        os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}"
    )
    docker = shlex.split(os.environ.get("TB_DOCKER") or "docker")
    found, problems = discover(run_cmd, compose, docker)
    for p in problems:
        print(f"qualify --box: {p}", file=sys.stderr)
    filled = fill(given, found)
    for opt, val in _pairs(filled[len(given) :]):
        print(f"qualify --box: {opt} {val}", file=sys.stderr)
    return qualify.main(filled)

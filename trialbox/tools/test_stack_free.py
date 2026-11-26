"""H-139: `make up-test` starts the compose test stack only where nothing else holds what it would take.

The test stack has its own compose project, ``trialbox-test`` (``TEST_PROJECT`` in the Makefile). Its containers,
networks and volumes carry that name. A box installed on the same host keeps the base file's ``trialbox`` name. But
the host ports the test stack publishes (``127.0.0.1:8010`` and the rest) are the box's ports too. On the bench host
the tests reached services that answered 401 to a test stack's unauthenticated calls, so they were not the test
stack's own.

Before ``up``, the stack's rendered configuration (``docker compose ... config --format json``, on stdin) is read.
The stack is refused, plainly, when:

* a container of another project publishes a host port the stack would publish;
* a container has the name a container of the stack would get, but belongs to another project;
* a host port the stack would publish is held by something that is not a container of the stack. This is checked by
  binding the port on its address.

A container of the test stack itself (an earlier ``make up-test``) is not a reason to refuse: ``up`` takes it over.

    docker compose ... config --format json | python -m tools.test_stack_free trialbox-test
"""

from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

PROJECT_LABEL = "com.docker.compose.project"


def wanted(config: Mapping[str, Any], project: str) -> tuple[set[str], set[tuple[str, int]]]:
    """The container names and the (address, port) pairs the stack would take."""
    names: set[str] = set()
    ports: set[tuple[str, int]] = set()
    for service, spec in (config.get("services") or {}).items():
        names.add(str(spec.get("container_name") or f"{project}-{service}-1"))
        for p in spec.get("ports") or []:
            if isinstance(p, Mapping) and p.get("published"):
                ports.add((str(p.get("host_ip") or ""), int(str(p["published"]).split("-")[0])))
    return names, ports


def _labels(row: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(row.get("Labels") or "").split(","):
        k, sep, v = part.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def _published(row: Mapping[str, Any]) -> set[tuple[str, int]]:
    """``127.0.0.1:8010->8010/tcp, [::]:8080->8080/tcp`` as (address, port) pairs."""
    out: set[tuple[str, int]] = set()
    for part in str(row.get("Ports") or "").split(","):
        left = part.strip().split("->")[0]
        if "->" not in part or ":" not in left:
            continue
        addr, _, port = left.rpartition(":")
        if port.isdigit():
            out.add((addr.strip("[]"), int(port)))
    return out


def _any(addr: str) -> bool:
    """An address that stands for every address of the host (none given, or the unspecified one)."""
    try:
        return not addr or ipaddress.ip_address(addr).is_unspecified
    except ValueError:
        return False


def _clash(a: tuple[str, int], b: tuple[str, int]) -> bool:
    return a[1] == b[1] and (a[0] == b[0] or _any(a[0]) or _any(b[0]))


def bindable(addr: str, port: int) -> bool:
    """Whether ``addr:port`` is free here: it can be bound now (and is let go at once)."""
    family = socket.AF_INET6 if ":" in addr else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((addr, port))
        except OSError:
            return False
    return True


def problems(config: Mapping[str, Any], containers: Iterable[Mapping[str, Any]], project: str,
             free: Callable[[str, int], bool] = bindable) -> list[str]:  # fmt: skip
    """What another project, or something outside Docker, holds of what the stack would take (empty: none)."""
    names, ports = wanted(config, project)
    out: list[str] = []
    ours: set[tuple[str, int]] = set()
    reported: set[tuple[str, int]] = set()
    for row in containers:
        name = str(row.get("Names") or "").lstrip("/")
        owner = _labels(row).get(PROJECT_LABEL, "")
        held = _published(row)
        if owner == project:
            ours |= held
            continue
        who = f"container {name} (compose project {owner!r})" if owner else f"container {name} (not a compose one)"
        if name in names:
            out.append(f"{who} has the name a container of the test stack would get")
        for want in sorted(ports):
            for got in sorted(held):
                if _clash(want, got):
                    out.append(f"{who} publishes {got[0] or '*'}:{got[1]}, which the test stack would publish")
                    reported.add(want)
    for addr, port in sorted(ports - reported):
        if any(_clash((addr, port), h) for h in ours):
            continue
        if not free(addr, port):
            out.append(f"{addr}:{port}, which the test stack would publish, is held by something that is not a "
                       f"container of the test stack")  # fmt: skip
    return out


def running_containers(docker: Sequence[str] = ("docker",)) -> list[dict[str, Any]]:
    """Every running container, as ``docker ps --format '{{json .}}'`` gives it."""
    r = subprocess.run([*docker, "ps", "--format", "{{json .}}"], capture_output=True, text=True, check=False,
                       timeout=60)  # fmt: skip
    if r.returncode != 0:
        raise RuntimeError(f"docker ps failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None, stdin: Any = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0]:
        print("usage: docker compose ... config --format json | python -m tools.test_stack_free <project>",
              file=sys.stderr)  # fmt: skip
        return 2
    project = args[0]
    text = (stdin or sys.stdin).read()
    try:
        config = json.loads(text)
    except ValueError:
        print("up-test: the test stack's configuration could not be read (docker compose config failed): "
              "nothing was started", file=sys.stderr)  # fmt: skip
        return 1
    try:
        found = problems(config, running_containers(), project)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"up-test: what runs on this host could not be read ({exc}): nothing was started", file=sys.stderr)
        return 1
    if found:
        print(f"up-test: the test stack (compose project {project}) was not started, as another stack or program "
              "holds what it would take:", file=sys.stderr)  # fmt: skip
        for p in found:
            print(f"  - {p}", file=sys.stderr)
        print("Stop that stack or program, or run the test stack on another host.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

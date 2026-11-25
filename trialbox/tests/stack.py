"""The compose test stack as seen from the host (deploy/docker-compose.test.yml).

Every published port can be moved when it is taken on the developer machine: set ``TB_HOST_<NAME>_PORT`` in the
environment or in ``deploy/.env`` (where compose reads it too) before ``make up-test``. ``ensure_ingested()`` loads
synthetic site A once, so the compose integration and e2e tests do not depend on a manual ingest or on test order.

H-139 (the integrator's 7159714024): a test takes a port from the running test stack itself, never from a constant or
a variable. The stack's compose file says which service and container port each ``TB_HOST_<NAME>_PORT`` publishes,
and the engine says where the container of compose project ``trialbox-test`` (the Makefile's TEST_PROJECT) publishes
it. With no such container, or with another project's container on the same host port, the test stops and names the
holder. It never talks to a service of another stack on the same host, which has its own keys."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "2026-10-04"  # synthetic fixtures' snapshot (tools/synth/generator.py: reference date minus one day)


PROJECT = "trialbox-test"  # the Makefile's TEST_PROJECT (tools/failure_drill_box.py: TEST_PROJECT)
#: the files the stacks are started from (the Makefile's COMPOSE_TEST; deploy/poc.sh adds the POC file)
COMPOSE_FILES = tuple(ROOT / "deploy" / f for f in ("docker-compose.yml", "docker-compose.test.yml",
                                                   "docker-compose.poc.yml"))  # fmt: skip
PROJECT_LABEL, SERVICE_LABEL = "com.docker.compose.project", "com.docker.compose.service"
_PUBLISH = re.compile(r"\$\{TB_HOST_([A-Z_]+)_PORT:-(\d+)\}:(\d+)")
_PORTS = re.compile(r"^\s*(?:\[?([0-9a-fA-F.:]*)\]?):(\d+)->(\d+)/tcp\s*$")


class StackNotRunning(RuntimeError):
    """The test stack does not publish this port: it is not up, or another project holds the port."""


def published_by_config(paths: Iterable[Path] = COMPOSE_FILES) -> dict[str, tuple[str, int]]:
    """``NAME`` of each ``TB_HOST_<NAME>_PORT`` -> (service, container port), as the stacks' compose files say."""
    import yaml

    out: dict[str, tuple[str, int]] = {}
    for path in paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for service, spec in (doc.get("services") or {}).items():
            for entry in (spec or {}).get("ports") or []:
                m = _PUBLISH.search(str(entry))
                if m:
                    out[m.group(1)] = (str(service), int(m.group(3)))
    return out


def _labels(row: Mapping[str, object]) -> dict[str, str]:
    pairs = (part.partition("=") for part in str(row.get("Labels") or "").split(","))
    return {k.strip(): v.strip() for k, sep, v in pairs if sep}


def _bindings(row: Mapping[str, object]) -> list[tuple[int, int]]:
    """``127.0.0.1:8016->8016/tcp, ...`` as (host port, container port) pairs."""
    out = []
    for part in str(row.get("Ports") or "").split(","):
        m = _PORTS.match(part)
        if m:
            out.append((int(m.group(2)), int(m.group(3))))
    return out


def running_containers(docker: tuple[str, ...] = ("docker",)) -> list[dict[str, object]]:
    """Every running container, as ``docker ps --format '{{json .}}'`` gives it."""
    try:
        r = subprocess.run([*docker, "ps", "--format", "{{json .}}"], capture_output=True, text=True, check=False,
                           timeout=60)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StackNotRunning(f"the container engine could not be asked ({exc})") from exc
    if r.returncode != 0:
        raise StackNotRunning(f"the container engine could not be asked: {(r.stderr or r.stdout).strip()[-300:]}")
    return [json.loads(line) for line in r.stdout.splitlines() if line.strip()]


def port_of(name: str, containers: Iterable[Mapping[str, object]], config: Mapping[str, tuple[str, int]],
            project: str = PROJECT) -> int:  # fmt: skip
    """The host port where ``project``'s container of ``name``'s service publishes its container port. Refused when
    the project has no such container, or when a container of another project publishes the same host port."""
    if name not in config:
        raise StackNotRunning(f"the stack's compose files publish no TB_HOST_{name}_PORT")
    service, inner = config[name]
    rows = list(containers)
    ours = [h for r in rows if _labels(r).get(PROJECT_LABEL) == project and _labels(r).get(SERVICE_LABEL) == service
            for h, c in _bindings(r) if c == inner]  # fmt: skip
    if not ours:
        held = [f"{r.get('Names')} (project {_labels(r).get(PROJECT_LABEL) or 'none'})" for r in rows
                if any(c == inner for _, c in _bindings(r)) and _labels(r).get(SERVICE_LABEL) == service]  # fmt: skip
        also = f"; the same service runs in {', '.join(held)}, which is not the test stack" if held else ""
        raise StackNotRunning(f"compose project {project} publishes no port for {service}:{inner} (make up-test){also}")
    port = ours[0]
    others = [f"{r.get('Names')} (project {_labels(r).get(PROJECT_LABEL) or 'none'})" for r in rows
              if _labels(r).get(PROJECT_LABEL) != project and any(h == port for h, _ in _bindings(r))]  # fmt: skip
    if others:
        raise StackNotRunning(f"host port {port} of {service} is also published by {', '.join(others)}: refused")
    return port


POC_FILE = "docker-compose.poc.yml"  # deploy/poc.sh starts the POC from it; a box never does
_poc: list[str] = []  # the POC's project, once found


def poc_project(ask: Callable[[], list[dict[str, object]]] = running_containers) -> str:
    """The POC stack's compose project, read from its own containers: the one project started from the POC file.
    Never a name guessed from the caller's environment, which on a host with a box is the box's own."""
    if _poc:
        return _poc[0]
    projects = {_labels(r).get(PROJECT_LABEL, "") for r in ask() if POC_FILE in str(r.get("Labels") or "")}
    projects.discard("")
    if len(projects) != 1:
        found = ", ".join(sorted(projects)) or "none"
        raise StackNotRunning(f"one POC stack (started from {POC_FILE}) must be running (make poc); found: {found}")
    _poc.append(projects.pop())
    return _poc[0]


_seen: dict[tuple[str, str], int] = {}


def host_port(name: str, project: str = PROJECT,
              ask: Callable[[], list[dict[str, object]]] = running_containers) -> int:  # fmt: skip
    """``name``'s host port, from ``project``'s running containers (once per process)."""
    if (project, name) not in _seen:
        _seen[project, name] = port_of(name, ask(), published_by_config(), project)
    return _seen[project, name]


def url(name: str, path: str = "", project: str = PROJECT) -> str:
    return f"http://127.0.0.1:{host_port(name, project)}{path}"


MAILPIT_LIST = "/api/v1/messages"  # Mailpit's API (deploy/docker-compose.test.yml, D-348)


def outbound_mail(limit: int = 500, project: str = PROJECT) -> list[EmailMessage]:
    """The box's outbound mail as Mailpit holds it, newest first: the list, then each message's raw source."""
    base = url("MAILHOG", project=project)
    listing = httpx.get(f"{base}{MAILPIT_LIST}", params={"limit": limit}, timeout=30).json()
    out = []
    for it in listing.get("messages") or []:
        raw = httpx.get(f"{base}/api/v1/message/{it['ID']}/raw", timeout=30)
        raw.raise_for_status()
        msg = message_from_bytes(raw.content, policy=policy.default)
        assert isinstance(msg, EmailMessage)
        out.append(msg)
    return out


def ensure_ingested(force: bool = False) -> dict[str, object] | None:
    """Run the adapter's CSV ingest unless the lake already has a snapshot; returns the adapter report if it ran."""
    if not force:
        health = httpx.get(url("LAKE", "/healthz"), timeout=30).json()
        if health.get("checks", {}).get("snapshot", "none") != "none":
            return None
    from tb_common.jobpoll import Poll

    resp = httpx.post(url("ADAPTER", "/run"), json={"source": "csv", "snapshot": SNAPSHOT}, timeout=60)
    resp.raise_for_status()  # T-690 (D-472): 202 and a run id; the night is followed, not timed
    run = resp.json()["run"]

    def read() -> dict[str, object]:
        r = httpx.get(url("ADAPTER", f"/run/{run}"), timeout=60)
        r.raise_for_status()
        body: dict[str, object] = r.json()
        return body

    st = Poll().until_done(read, "ingest")
    assert st["state"] == "done", st
    report = st["report"]
    assert isinstance(report, dict)
    return report


if __name__ == "__main__":  # `make ingest-test`
    rep = ensure_ingested(force=True)
    assert rep is not None
    print({k: rep.get(k) for k in ("passed", "counts", "fhir_loaded")})

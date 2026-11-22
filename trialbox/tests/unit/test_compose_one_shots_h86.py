"""H-86: every one-shot service of every stack is waited on, so ``docker compose up --wait`` can pass it.

``up --wait`` (install.sh, poc.sh, deploy/systemd/trialbox.service) fails on a container that has exited, even with
code 0 ("container ... exited (0)"), unless another service waits on it with ``condition:
service_completed_successfully``. The 32 GB profile's last start-up helper, ``judge-wake-init``, was waited on by
nothing, so every install on that profile stopped with "the stack did not become healthy".

The check, on the stacks tests/unit/test_compose_limits.py lints (its YAML merge, no Docker needed):

* a one-shot is a service with ``restart: "no"`` (test_compose_limits's own definition);
* each active one-shot is waited on with ``service_completed_successfully`` by another active service, and following
  those waiters always reaches a long-running service (a chain of helpers ends in a service that stays up);
* the ``depends_on`` graph of the active services has no cycle.

A one-shot whose every profile is a run-only profile (started by ``docker compose run``, never by ``up``) is not
held to it; the profile is run-only only while its file says so (``RUN_ONLY``).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_compose_limits import DEPLOY, LINTED_STACKS, LONG_RUNNING_RESTART, _active, _merge

#: profile -> (file, the line that shows the profile is started by `docker compose run`, not `up`)
RUN_ONLY = {"doctor": ("platform/docker-compose.platform.yml", "run --rm doctor")}
DONE = "service_completed_successfully"
IDS = ["+".join(s) for s, _ in LINTED_STACKS]


def _deps(body: dict[str, Any]) -> dict[str, str]:
    d = body.get("depends_on") or {}
    if isinstance(d, list):
        return dict.fromkeys(d, "service_started")
    return {k: str((v or {}).get("condition", "service_started")) for k, v in d.items()}


def _one_shot(body: dict[str, Any]) -> bool:
    return str(body.get("restart", "")) == "no"


def _run_only(body: dict[str, Any]) -> bool:
    p = set(body.get("profiles") or [])
    return bool(p) and p <= set(RUN_ONLY)


def problems(services: dict[str, dict[str, Any]], profiles: tuple[str, ...]) -> list[str]:
    act = {s: b for s, b in services.items() if _active(b, profiles)}
    deps = {s: _deps(b) for s, b in act.items()}
    bad: list[str] = []
    # no cycle (any condition): compose refuses one, and a wait on it would never end
    state: dict[str, int] = {}

    def visit(s: str, path: list[str]) -> None:
        state[s] = 1
        for d in deps.get(s, {}):
            if d not in act:
                continue
            if state.get(d) == 1:
                bad.append("cycle: " + " -> ".join([*path, s, d]))
            elif d not in state:
                visit(d, [*path, s])
        state[s] = 2

    for s in sorted(act):
        if s not in state:
            visit(s, [])
    waiters: dict[str, list[str]] = {}
    for s, ds in deps.items():
        for d, cond in ds.items():
            if cond == DONE:
                waiters.setdefault(d, []).append(s)

    def reaches_long_running(s: str, seen: frozenset[str]) -> bool:
        for w in waiters.get(s, []):
            if w in seen:
                continue
            if not _one_shot(act[w]) and act[w].get("restart") in LONG_RUNNING_RESTART:
                return True
            if _one_shot(act[w]) and reaches_long_running(w, seen | {w}):
                return True
        return False

    for s, b in sorted(act.items()):
        if not _one_shot(b) or _run_only(b):
            continue
        if not waiters.get(s):
            bad.append(f"{s}: one-shot, waited on by no service ({DONE}); `up --wait` fails on it")
        elif not reaches_long_running(s, frozenset({s})):
            bad.append(f"{s}: one-shot, its waiters reach no long-running service")
    return bad


@pytest.mark.parametrize(("stack", "profiles"), LINTED_STACKS, ids=IDS)
def test_every_one_shot_is_waited_on_and_no_cycle(stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    assert problems(_merge(stack), profiles) == []


def test_the_32gb_wake_helper_is_waited_on_by_the_guard() -> None:
    services = _merge(("docker-compose.yml", "docker-compose.secrets.yml", "docker-compose.rtx5090.yml"))
    assert _deps(services["model-guard"]).get("judge-wake-init") == DONE
    assert services["judge-wake-init"]["restart"] == "no"


def test_a_planted_one_shot_nobody_waits_on_fails() -> None:
    services = _merge(("docker-compose.yml", "docker-compose.secrets.yml", "docker-compose.rtx5090.yml"))
    services["planted-init"] = {"restart": "no", "profiles": ["gpu"], "depends_on": {"llm-service": {}}}
    assert problems(services, ("gpu",)) == [
        f"planted-init: one-shot, waited on by no service ({DONE}); `up --wait` fails on it"
    ]
    # the shape on master: the guard waits on nothing, and the wake helper is reported
    del services["planted-init"]
    services["model-guard"] = {k: v for k, v in services["model-guard"].items() if k != "depends_on"}
    assert problems(services, ("gpu",)) == [
        f"judge-wake-init: one-shot, waited on by no service ({DONE}); `up --wait` fails on it",
        "model-swap-init: one-shot, its waiters reach no long-running service",
    ]


def test_a_chain_of_helpers_only_is_not_enough_and_a_cycle_fails() -> None:
    services: dict[str, dict[str, Any]] = {
        "a": {"restart": "no"},
        "b": {"restart": "no", "depends_on": {"a": {"condition": DONE}}},
        "srv": {"restart": "unless-stopped", "depends_on": {"x": {"condition": "service_healthy"}}},
        "x": {"restart": "unless-stopped", "depends_on": {"srv": {"condition": "service_started"}}},
    }
    bad = problems(services, ())
    assert "a: one-shot, its waiters reach no long-running service" in bad
    assert f"b: one-shot, waited on by no service ({DONE}); `up --wait` fails on it" in bad
    assert any(p.startswith("cycle: ") for p in bad)


def test_a_run_only_profile_is_one_while_its_file_says_so() -> None:
    for file, line in RUN_ONLY.values():
        assert line in (DEPLOY / file).read_text(encoding="utf-8")

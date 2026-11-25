"""H-146 (D-1462): the judge and verifier model servers start without the prefix cache unless the box chooses it.

The integrator's bench (#1504, 7163554019): the same 58 extraction calls gave 9 and then 4 agreeing with the model
server's prefix cache on, and four identical results with ``--no-enable-prefix-caching`` the only change.

* The invariant: the compose the product renders (``tools.serving_profile.compose_argv``: deploy/.env and its
  COMPOSE_FILE, as install, update and the bench switch run compose) carries ``--no-enable-prefix-caching`` for every
  judge and verifier server of every GPU stack by default (setting absent, empty or ``no-enable``), once, and no
  ``--enable-prefix-caching``; the explicit choice ``enable`` drops it for ``--enable-prefix-caching``; any other
  value never renders the flag's off form silently on.
* The setting is declared (``tb_common.config.DECLARED``) with the default the compose files carry.
* doctor's ``prefix_cache`` line says off (PASS) or on (WARN: runs may differ), and FAILs a value that is neither or
  a rendered server without the flag.

Nothing is pulled or started; compose only renders.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_compose_limits import DEPLOY, DUMMY_ENV, STACKS, TWO_DEVICE_STACKS, _load, _merge
from tools import prefix_cache as pc
from tools import serving_profile as sp
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb

SERVERS = ("llm-service", "llm-verifier")
OFF, ON = "--no-enable-prefix-caching", "--enable-prefix-caching"
TWO_DEVICE = "TB_LINK_ADDR=192.0.2.1\nTB_LINK_PEER=192.0.2.2\n"  # documentation addresses (RFC 5737)
# every stack the product runs that starts a judge or verifier server (the bench-only second engine's overlay
# replaces the whole command with another engine's: not this setting's, D-1462)
GPU_STACKS = [
    s
    for s, p in [*STACKS, *TWO_DEVICE_STACKS]
    if "gpu" in p and sp.OVERLAY not in s and any(n in _merge(s) and "command" in _merge(s)[n] for n in SERVERS)
]


def _box(tmp: Path, stack: tuple[str, ...], extra: str = "") -> Path:
    """A box's deploy folder: its .env names the stack's real compose files (absolute, as install.sh writes)."""
    d = tmp / "deploy"
    d.mkdir(parents=True, exist_ok=True)
    files = ":".join(str(DEPLOY / f) for f in stack)
    two = TWO_DEVICE if any("two-device/" in f for f in stack) else ""
    (d / ".env").write_text(DUMMY_ENV + two + f"COMPOSE_FILE={files}\n" + extra, encoding="utf-8")
    return d


def _rendered(deploy: Path) -> dict[str, Any]:
    """The servers as the product renders them: compose_argv (deploy/.env, its COMPOSE_FILE), the gpu profile."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "TB_MEM_", "SERVING", "TB_LLM_"))}
    r = subprocess.run([*sp.compose_argv(deploy), "--profile", "gpu", "config", "--format", "json"],
                       capture_output=True, text=True, timeout=120, check=False, env=env)  # fmt: skip
    assert r.returncode == 0, r.stderr
    services: dict[str, Any] = json.loads(r.stdout)["services"]
    return {n: services[n] for n in SERVERS if n in services}


def _flags(body: dict[str, Any]) -> list[str]:
    return [a for a in body.get("command") or [] if str(a).endswith("prefix-caching")]


def test_the_stacks_cover_every_server_command() -> None:
    """Every compose file that gives a judge or verifier server its command is in a stack checked here (or is the
    bench-only second engine's overlay), so a new GPU overlay cannot start its servers unchecked."""
    covered = {f for s in GPU_STACKS for f in s}
    for path in sorted(DEPLOY.rglob("docker-compose*.yml")):
        rel = str(path.relative_to(DEPLOY))
        svcs = _load(rel).get("services") or {}
        if any("command" in (svcs.get(n) or {}) for n in SERVERS) and rel != sp.OVERLAY:
            assert rel in covered, rel
    assert len(GPU_STACKS) >= 7  # base, gb10, rtx5090, rtxpro6000, dgpu48, shared-quota+platform, spark


@pytest.mark.parametrize("stack", GPU_STACKS, ids="+".join)
@pytest.mark.parametrize("value", [None, "", "no-enable", '"no-enable"'])
def test_the_rendered_servers_start_without_the_prefix_cache(
    tmp_path: Path, stack: tuple[str, ...], value: str | None
) -> None:
    """The invariant (default: absent, empty or no-enable): each server renders the off flag once, never the on."""
    extra = "" if value is None else f"{pc.SETTING}={value}\n"
    servers = _rendered(_box(tmp_path, stack, extra))
    assert servers
    for name, body in servers.items():
        assert _flags(body) == [OFF], name


@pytest.mark.parametrize("stack", GPU_STACKS, ids="+".join)
def test_the_explicit_choice_alone_turns_the_cache_on(tmp_path: Path, stack: tuple[str, ...]) -> None:
    servers = _rendered(_box(tmp_path, stack, f"{pc.SETTING}=enable\n"))
    assert servers
    for name, body in servers.items():
        assert _flags(body) == [ON], name


@pytest.mark.parametrize("value", ["on", "off", "true", "1", "Enable"])
def test_another_value_never_renders_a_flag_the_server_takes(tmp_path: Path, value: str) -> None:
    """A value that is neither renders an argument the model server refuses at start (it stops; doctor names it):
    never the on flag, never a silent off."""
    stack = next(s for s in GPU_STACKS if "docker-compose.gb10.yml" in s)
    for name, body in _rendered(_box(tmp_path, stack, f"{pc.SETTING}={value}\n")).items():
        assert OFF not in _flags(body) and ON not in _flags(body), name
        assert _flags(body) == [f"--{value}-prefix-caching"], name


def test_the_setting_is_declared_with_the_compose_default() -> None:
    from tb_common import config

    row = config.DECLARED[pc.SETTING]
    assert row.default == pc.DEFAULT == "no-enable" and pc.VALUES == ("no-enable", "enable")
    assert "prefix" in row.doc and "compose" in row.doc
    want = f"--${{{pc.SETTING}:-{pc.DEFAULT}}}-prefix-caching"
    for path in sorted(DEPLOY.rglob("docker-compose*.yml")):
        text = path.read_text(encoding="utf-8")
        for line in re.findall(r"^\s*- (--\S*prefix-caching\S*)", text, re.M):
            assert line == want, path.name


@pytest.mark.parametrize(
    ("env", "word"),
    [({}, "off"), ({pc.SETTING: ""}, "off"), ({pc.SETTING: "no-enable"}, "off"), ({pc.SETTING: "'no-enable'"}, "off"),
     ({pc.SETTING: "enable"}, "on"), ({pc.SETTING: ' "enable" '}, "on")],
)  # fmt: skip
def test_the_state_reads_the_setting_as_compose_does(env: dict[str, str], word: str) -> None:
    assert pc.state(env) == word


@pytest.mark.parametrize("value", ["on", "off", "true", "Enable", "no_enable"])
def test_the_state_refuses_another_value(value: str) -> None:
    with pytest.raises(ValueError, match="no-enable or enable"):
        pc.state({pc.SETTING: value})


def _doctor(env: dict[str, str], compose: dict[str, Any] | None = None) -> doctor.Check:
    return doctor.check_prefix_cache(doctor.DoctorInputs(env=env, compose_config=compose))


def test_doctor_says_off_by_default() -> None:
    c = _doctor({})
    assert c.name == "prefix_cache" and c.status == "PASS" and "prefix caching off" in c.detail


def test_doctor_warns_when_the_cache_is_chosen() -> None:
    c = _doctor({pc.SETTING: "enable"})
    assert c.status == "WARN" and "prefix caching on" in c.detail and "runs may differ" in c.detail


@pytest.mark.parametrize("value", ["on", "off", "yes"])
def test_doctor_fails_another_value(value: str) -> None:
    c = _doctor({pc.SETTING: value})
    assert c.status == "FAIL" and pc.SETTING in c.detail and "refuse to start" in c.detail


def test_doctor_reads_the_rendered_servers_when_it_has_them(tmp_path: Path) -> None:
    stack = next(s for s in GPU_STACKS if "docker-compose.gb10.yml" in s)
    rendered = {"services": _rendered(_box(tmp_path, stack))}
    assert _doctor({}, rendered).status == "PASS"
    stripped = json.loads(json.dumps(rendered))
    stripped["services"]["llm-verifier"]["command"] = [
        a for a in stripped["services"]["llm-verifier"]["command"] if a != OFF
    ]
    c = _doctor({}, stripped)
    assert c.status == "FAIL" and "llm-verifier" in c.detail and "llm-service" not in c.detail
    turned = json.loads(json.dumps(rendered))
    turned["services"]["llm-service"]["command"] = [
        ON if a == OFF else a for a in turned["services"]["llm-service"]["command"]
    ]
    c = _doctor({}, turned)
    assert c.status == "FAIL" and "llm-service" in c.detail  # the files say on where the setting says off


def test_doctor_runs_the_line() -> None:
    assert doctor.check_prefix_cache in doctor.CHECKS

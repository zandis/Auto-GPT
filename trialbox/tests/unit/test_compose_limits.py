"""T-108a (D-360; CR-082, OPS-029): every service of every compose stack has limits, a capped log, a restart rule, a
health check and a watchdog label.

Two levels. The YAML level needs no Docker: each stack a box runs (the base file plus its overlays, in the order
install.sh and the RUNBOOK give) is merged here the way compose merges these keys, and every service is checked. The
rendered level asks ``docker compose config`` itself (skipped without the compose plugin; CI has it), so anchors,
``${VAR:-default}`` and overrides are resolved exactly as on a box. Nothing is pulled or started.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
BASE = "docker-compose.yml"
# the stacks a box or a developer runs: (files in order, profiles)
STACKS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    ((BASE,), ("stub", "gpu")),
    ((BASE, "docker-compose.test.yml"), ("stub", "test")),
    ((BASE, "docker-compose.test.yml", "docker-compose.poc.yml"), ("stub", "test")),
    ((BASE, "docker-compose.secrets.yml", "docker-compose.gb10.yml"), ("gpu",)),
    ((BASE, "docker-compose.secrets.yml", "docker-compose.rtx5090.yml"), ("gpu",)),
    ((BASE, "docker-compose.secrets.yml", "docker-compose.rtxpro6000.yml"), ("gpu",)),
    ((BASE, "docker-compose.secrets.yml", "docker-compose.dgpu48.yml"), ("gpu",)),  # the UNMEASURED draft (24-5)
    ((BASE, "docker-compose.secrets.yml", "docker-compose.identity.yml"), ("stub", "oidc")),
    ((BASE, "docker-compose.secrets.yml", "docker-compose.monitoring.yml"), ("stub",)),  # T-209a (D-379)
    ((BASE, "docker-compose.secrets.yml", "docker-compose.identity.yml", "docker-compose.box.yml"),
     ("stub",)),  # T-729 (D-466): the box's first-run folder
    ((BASE, "docker-compose.secrets.yml", "docker-compose.identity.yml", "docker-compose.acceptance.yml"),
     ("stub", "oidc")),  # T-213a (D-410)
    ((BASE, "docker-compose.secrets.yml", "docker-compose.shared-quota.yml", "platform/docker-compose.platform.yml"),
     ("gpu", "doctor")),
    (("docker-compose.testbench.yml",), ("dev",)),
]  # fmt: skip
TEST_PROFILES = {"test", "dev"}  # developer-only services: limits and log caps, no health or watchdog rule
IMAGE_HEALTHCHECK = {"authelia"}  # the image's own HEALTHCHECK (/app/healthcheck.sh) is the check
LONG_RUNNING_RESTART = {"unless-stopped", "always"}
SIZE = re.compile(r"^(?:\$\{[a-z0-9_]+:-)?(\d+(?:\.\d+)?)([kmg])\}?$")


class _Loader(yaml.SafeLoader):
    """SafeLoader plus compose's !reset and !override tags (their value is what the file says)."""


def _tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    assert isinstance(node, yaml.ScalarNode)
    return loader.construct_scalar(node)


for _tag in ("!reset", "!override"):
    _Loader.add_constructor(_tag, _tagged)


def _load(name: str) -> dict[str, Any]:
    doc = yaml.load((DEPLOY / name).read_text(encoding="utf-8"), Loader=_Loader)  # a SafeLoader subclass
    return doc if isinstance(doc, dict) else {}


def _merge(stack: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """The services of a stack, merged per key as compose does for the keys checked here (later file wins; labels
    and logging merged)."""
    out: dict[str, dict[str, Any]] = {}
    for name in stack:
        for svc, body in (_load(name).get("services") or {}).items():
            body = body or {}
            cur = out.setdefault(svc, {})
            for k, v in body.items():
                if k in ("labels", "logging") and isinstance(v, dict) and isinstance(cur.get(k), dict):
                    cur[k] = {**cur[k], **v}
                else:
                    cur[k] = v
    return out


def _active(body: dict[str, Any], profiles: tuple[str, ...]) -> bool:
    p = body.get("profiles")
    return not p or bool(set(p) & set(profiles))


def _bytes(v: object) -> int:
    if isinstance(v, int):
        return v
    m = SIZE.match(str(v).strip().lower())
    assert m, f"mem_limit {v!r} is not a size (or ${{VAR:-size}})"
    return int(float(m.group(1)) * {"k": 2**10, "m": 2**20, "g": 2**30}[m.group(2)])


def problems(services: dict[str, dict[str, Any]], profiles: tuple[str, ...]) -> list[str]:
    """The lint: a list of '<service>: <what is missing>'; empty when the stack is clean."""
    bad: list[str] = []
    for svc, body in sorted(services.items()):
        if not _active(body, profiles):
            continue
        if "mem_limit" not in body:
            bad.append(f"{svc}: no mem_limit")
        elif _bytes(body["mem_limit"]) < 64 * 2**20:
            bad.append(f"{svc}: mem_limit under 64m")
        pids = body.get("pids_limit")
        if not isinstance(pids, int) or pids <= 0:
            bad.append(f"{svc}: no positive pids_limit")
        log = body.get("logging") or {}
        if log.get("driver") != "json-file" or "max-size" not in (log.get("options") or {}):
            bad.append(f"{svc}: no capped json-file log")
        one_shot = str(body.get("restart", "")) == "no"
        dev_only = set(body.get("profiles") or []) <= TEST_PROFILES and bool(body.get("profiles"))
        if one_shot or dev_only:
            continue
        if body.get("restart") not in LONG_RUNNING_RESTART:
            bad.append(f"{svc}: restart is {body.get('restart')!r}, not unless-stopped")
        if "healthcheck" not in body and svc not in IMAGE_HEALTHCHECK:
            bad.append(f"{svc}: no health check")
        if (body.get("labels") or {}).get("tb.watchdog") not in ("restart", "report"):
            bad.append(f"{svc}: no tb.watchdog label (restart or report)")
    return bad


@pytest.mark.parametrize(("stack", "profiles"), STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x)
def test_every_service_of_every_stack_has_limits_health_and_a_watchdog_rule(
    stack: tuple[str, ...], profiles: tuple[str, ...]
) -> None:
    assert problems(_merge(stack), profiles) == []


def test_every_compose_file_is_in_a_linted_stack() -> None:
    files = {p.name for p in DEPLOY.glob("docker-compose*.yml")} | {"platform/docker-compose.platform.yml"}
    assert files <= {f for stack, _ in STACKS for f in stack}


def test_the_lint_catches_a_service_without_limits() -> None:
    """Negative: a planted service with no caps, no log cap, no check and no label is named for each."""
    services = _merge((BASE,))
    services["planted"] = {"image": "x", "restart": "unless-stopped"}
    found = [p for p in problems(services, ("stub",)) if p.startswith("planted:")]
    assert found == [
        "planted: no mem_limit",
        "planted: no positive pids_limit",
        "planted: no capped json-file log",
        "planted: no health check",
        "planted: no tb.watchdog label (restart or report)",
    ]
    services["planted"].update(mem_limit="1g", pids_limit=0)
    assert "planted: no positive pids_limit" in problems(services, ("stub",))


def test_the_database_is_reported_not_restarted_and_vllm_is_restarted() -> None:
    base = _merge((BASE,))
    assert base["db"]["labels"]["tb.watchdog"] == "report"
    assert base["llm-service"]["labels"]["tb.watchdog"] == "restart"
    assert "healthcheck" in base["llm-service"]  # the watchdog acts on Docker's health state
    for stack, _ in STACKS:
        for svc, body in _merge(stack).items():
            if svc.startswith("llm-") and svc != "llm-stub":
                assert _bytes(body["mem_limit"]) >= 32 * 2**30, (stack, svc)  # a sleeping judge's weights fit


def test_the_jvm_caps_are_above_their_heaps() -> None:
    """A cap under the heap kills the JVM at its first full collection: each cap leaves 1 GB over its -Xmx."""
    heap = re.compile(r"-Xmx\$\{HAPI_XMX:-(\d+)g\}")
    for stack in ((BASE,), (BASE, "docker-compose.gb10.yml")):
        fhir = _merge(stack)["fhir-store"]
        xmx = int(heap.search(fhir["environment"]["JAVA_TOOL_OPTIONS"]).group(1))  # type: ignore[union-attr]
        assert _bytes(fhir["mem_limit"]) >= (xmx + 1) * 2**30, stack
    adapter = _merge((BASE,))["adapter"]
    assert _bytes(adapter["mem_limit"]) >= (int(adapter["environment"]["TB_VALIDATOR_XMX"].rstrip("g")) + 1) * 2**30


def test_caddy_health_site_is_loopback_only() -> None:
    caddy = (DEPLOY / "identity" / "Caddyfile").read_text(encoding="utf-8")
    block = caddy[caddy.index("http://127.0.0.1:2020") : caddy.index("(tls_internal)")]
    assert "bind 127.0.0.1" in block and 'respond /healthz "ok" 200' in block
    assert "admin off" in caddy  # the admin API stays off
    identity = _load("docker-compose.identity.yml")["services"]["caddy"]
    assert "127.0.0.1:2020/healthz" in " ".join(identity["healthcheck"]["test"])
    assert all("2020" not in str(p) for p in identity.get("ports", []))  # never published


# ------------------------------------------------------------------------------------------ rendered by compose
DUMMY_ENV = """TB_TZ=Asia/Taipei
TB_TLS_HOSTNAME=box.hospa.test
TB_MIG_PROFILE=3g.48gb
TB_MIG_JUDGE_DEVICE=MIG-judge
TB_MIG_VERIFIER_DEVICE=MIG-verifier
JUDGE_GPU_MEM_UTIL=0.4
JUDGE_MAX_LEN=16384
JUDGE_MAX_SEQS=8
VERIFIER_GPU_MEM_UTIL=0.2
VERIFIER_MAX_LEN=16384
VERIFIER_MAX_SEQS=8
POSTGRES_PASSWORD=x
TB_IMAGE=trialbox-py:1.0.0
TB_EMBED_IMAGE=trialbox-py:1.0.0
TB_DOCPARSER_IMAGE=trialbox-py:1.0.0
TB_JVM_IMAGE=trialbox-jvm:1.0.0
POSTGRES_IMAGE=trialbox-postgres:16-1
HAPI_IMAGE=hapi:x
VLLM_IMAGE=vllm:x
TB_ACCEPTANCE_MAIL_PASSWORD=x
TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD=x
"""


def _compose() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


def _render(project: Path, stack: tuple[str, ...], profiles: tuple[str, ...], env: str = "") -> dict[str, Any]:
    (project / ".env").write_text(DUMMY_ENV + env, encoding="utf-8")
    files = [x for f in stack for x in ("-f", str(DEPLOY / f))]
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "TB_MEM_"))}
    r = subprocess.run(
        ["docker", "compose", "--project-directory", str(project), *files,
         *(x for p in profiles for x in ("--profile", p)), "config", "--format", "json"],
        capture_output=True, text=True, timeout=120, check=False, env=clean,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    doc: dict[str, Any] = json.loads(r.stdout)
    return doc


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
@pytest.mark.parametrize(("stack", "profiles"), STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x)
def test_compose_config_renders_the_limits(tmp_path: Path, stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    services = _render(tmp_path, stack, profiles)["services"]
    assert services
    for svc, body in services.items():
        assert int(body.get("mem_limit") or 0) >= 64 * 2**20, svc
        assert int(body.get("pids_limit") or 0) > 0, svc
        assert body.get("logging", {}).get("options", {}).get("max-size"), svc


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
def test_a_site_setting_moves_a_cap(tmp_path: Path) -> None:
    services = _render(tmp_path, (BASE,), ("gpu",), "TB_MEM_LLM=96g\nTB_MEM_LAKE=16g\n")["services"]
    assert int(services["llm-service"]["mem_limit"]) == 96 * 2**30
    assert int(services["lake"]["mem_limit"]) == 16 * 2**30
    assert int(services["db"]["mem_limit"]) == 4 * 2**30  # the default where nothing is set


# ------------------------------------------------------------------------------------------ the lake under a cap
def test_the_lake_sizes_duckdb_from_the_container_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With mem_limit set, 40 % of the host's memory would get the lake killed: it takes 40 % of the cap."""
    from lake import store

    monkeypatch.delenv("TB_LAKE_MEMORY_LIMIT", raising=False)
    cap = tmp_path / "memory.max"
    monkeypatch.setattr(store, "CGROUP_MEMORY_MAX", cap)
    cap.write_text("8589934592\n")  # 8g, the base file's cap
    phys_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    assert store.memory_limit() == f"{max(1, int(min(phys_bytes, 8 * 2**30) * 0.4 / 2**30))}GB"  # 3GB on a big host
    cap.write_text("max\n")  # no cap: physical memory, as before
    phys = store.memory_limit()
    cap.unlink()
    assert store.memory_limit() == phys
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", "5GB")
    assert store.memory_limit() == "5GB"  # the explicit setting still wins

"""10G-1 (D-1323; review 16-17, 9l-18): the four container controls on all 15 services of the base compose file.

Every one of the 15 services in deploy/docker-compose.yml drops every capability (``cap_drop: [ALL]``), cannot gain a
privilege (``no-new-privileges:true``), runs on a read-only root filesystem (``read_only: true``, a tmpfs for what it
writes) and as a fixed numeric non-root user (``user: "uid:gid"``), in every stack a box or a developer runs. A
service that cannot take a control is in EXCEPTIONS with the reason; a control missing without a line there fails,
and a line there whose control has since been applied fails too, so the ledger stays the truth. No capability is
added back (CAP_ADD is empty).

Two levels, as tests/unit/test_compose_limits.py: the YAML level needs no Docker; the rendered level asks
``docker compose config`` (skipped without the compose plugin; CI has it). Nothing is pulled or started: whether
each service still works under the controls is proved on a compose box (D-1323 lists the runs).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_compose_limits import BASE, DEPLOY, STACKS, _active, _merge, _render

CONTROLS = ("cap_drop", "no-new-privileges", "read_only", "user")
THE_15 = frozenset({
    "db", "fhir-store", "lake", "embed-service", "doc-parser", "criteria-compiler", "adapter", "audit-writer",
    "orchestrator", "mail-gateway", "gateway", "console", "llm-stub", "llm-service", "model-guard",
})  # fmt: skip
# (service, control) -> why it is not applied. Written in D-1323 and in the compose file beside the service.
EXCEPTIONS: dict[tuple[str, str], str] = {
    ("adapter", "read_only"): "the HL7 validator writes indexes into and renames packages in /opt/hl7/home (an image "
    "path, 399 MB); it fails on a read-only root; a fix is in the adapter's validator, not in deploy/",
    ("orchestrator", "read_only"): "runs the same HL7 validator for the TWPAS scenario (scenarios/twpas.py)",
    ("llm-service", "read_only"): "the upstream vLLM image writes compile and kernel caches under /root/.cache and "
    "/tmp, gigabytes a memory tmpfs would take from the model; to be proved on a GPU box",
    ("llm-service", "user"): "the upstream vLLM image runs as root with its caches under /root; to be proved on a "
    "GPU box with the caches moved",
}
CAP_ADD: dict[tuple[str, str], str] = {}  # (service, capability) -> why; none is needed
# Services of the overlay files that are not one of the 15 (10G-1 names the 15 of the base file). Listed so that a
# new service anywhere fails here until it is placed in THE_15 or here with its reason.
OUTSIDE_THE_15: dict[str, str] = {
    "greenmail": "test profile only (docker-compose.test.yml), a developer's mail server",
    "mailpit": "test profile only (docker-compose.test.yml), a developer's mail viewer",
    "testbench": "dev profile only; already read-only, no capabilities, no-new-privileges",
    "llm-verifier": "the GPU overlays' second vLLM server: the same image and exceptions as llm-service, not yet hardened",
    "judge-sleep-init": "rtx5090 overlay one-shot model swap helper, not yet hardened",
    "judge-wake-init": "rtx5090 overlay one-shot model swap helper, not yet hardened",
    "model-swap-init": "rtx5090 overlay one-shot model swap helper, not yet hardened",
    "caddy": "identity overlay's TLS front; binds 443, needs NET_BIND_SERVICE: not yet hardened",
    "authelia": "identity overlay's sign-in service, not yet hardened",
    "prometheus": "monitoring overlay, not yet hardened",
    "doctor": "platform overlay's doctor job, not yet hardened",
    "acceptance-directory": "acceptance overlay; already no capabilities and no-new-privileges",
    "acceptance-directory-seed": "acceptance overlay; already no capabilities and no-new-privileges",
    "acceptance-mail": "acceptance overlay; already no capabilities and no-new-privileges",
}
NUMERIC_USER = re.compile(r"^(\d+):(\d+)$")


def _has(body: dict[str, Any], control: str) -> bool:
    if control == "cap_drop":
        return "ALL" in [str(c).upper() for c in body.get("cap_drop") or []]
    if control == "no-new-privileges":
        return any(str(o).replace("=", ":") == "no-new-privileges:true" for o in body.get("security_opt") or [])
    if control == "read_only":
        return body.get("read_only") is True
    m = NUMERIC_USER.match(str(body.get("user") or ""))
    return bool(m) and m.group(1) != "0" and m.group(2) != "0"


def problems(services: dict[str, dict[str, Any]], profiles: tuple[str, ...]) -> list[str]:
    """The lint: '<service>: <what is wrong>' for every active service; empty when the stack is clean."""
    bad: list[str] = []
    for svc, body in sorted(services.items()):
        if not _active(body, profiles):
            continue
        if svc not in THE_15:
            if svc not in OUTSIDE_THE_15:
                bad.append(f"{svc}: not one of the 15 and not in OUTSIDE_THE_15")
            continue
        for control in CONTROLS:
            has, excused = _has(body, control), (svc, control) in EXCEPTIONS
            if not has and not excused:
                bad.append(f"{svc}: no {control}")
            elif has and excused:
                bad.append(f"{svc}: {control} applied but still in EXCEPTIONS")
        for cap in body.get("cap_add") or []:
            if (svc, str(cap).upper()) not in CAP_ADD:
                bad.append(f"{svc}: cap_add {cap} without a reason in CAP_ADD")
        if body.get("privileged"):
            bad.append(f"{svc}: privileged")
    return bad


def test_the_base_file_has_the_15_services_and_each_takes_the_four_controls() -> None:
    """Compose test 15 of 15: every service carries each control or its written exception."""
    base = _merge((BASE,))
    assert set(base) == THE_15
    assert problems(base, ("stub", "gpu")) == []
    clean = [s for s in sorted(base) if all(_has(base[s], c) or (s, c) in EXCEPTIONS for c in CONTROLS)]
    assert len(clean) == 15
    assert {s for s, _ in EXCEPTIONS} <= THE_15 and all(c in CONTROLS for _, c in EXCEPTIONS)
    assert all(_has(base[s], "cap_drop") and _has(base[s], "no-new-privileges") for s in THE_15)  # no exception


@pytest.mark.parametrize(("stack", "profiles"), STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x)
def test_every_stack_keeps_the_controls(stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    assert problems(_merge(stack), profiles) == []


def test_read_only_services_get_a_tmpfs_for_what_they_write() -> None:
    base = _merge((BASE,))
    for svc in THE_15 - {"model-guard", "llm-service"}:
        assert "/tmp" in [str(t).split(":")[0] for t in base[svc].get("tmpfs") or []], svc
    assert any(str(t).startswith("/var/run/postgresql:uid=999,gid=999") for t in base["db"]["tmpfs"])


def test_the_users_match_the_images_and_the_installer() -> None:
    """tb is uid 10001 in python.Dockerfile (the jvm and embed images build on it), and install.sh gives
    settings.yaml to group 10001; the db runs as postgres (999), which owns its volume already."""
    base = _merge((BASE,))
    py = {s for s in THE_15 if str(base[s].get("image", "")).startswith("${TB_")}
    assert {"lake", "console", "adapter", "embed-service"} <= py
    assert {base[s]["user"] for s in py} == {"10001:10001"}
    assert "--uid 10001" in (DEPLOY / "docker" / "python.Dockerfile").read_text(encoding="utf-8")
    assert 'chown "$(id -u):10001" deploy/settings.yaml' in (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert base["db"]["user"] == "999:999"
    assert base["fhir-store"]["user"] == "65532:65532"


def test_the_lint_names_a_service_without_the_controls() -> None:
    """Negative: a planted service missing each control is named for each; a stale exception and an unexplained
    cap_add are named too."""
    services = _merge((BASE,))
    services["lake"] = {**services["lake"], "read_only": False, "user": "0:0", "cap_drop": [], "security_opt": []}
    services["gateway"] = {**services["gateway"], "cap_add": ["NET_ADMIN"]}
    services["planted"] = {"image": "x"}
    services["adapter"] = {**services["adapter"], "read_only": True}
    found = problems(services, ("stub",))
    assert found == [
        "adapter: read_only applied but still in EXCEPTIONS",
        "gateway: cap_add NET_ADMIN without a reason in CAP_ADD",
        "lake: no cap_drop",
        "lake: no no-new-privileges",
        "lake: no read_only",
        "lake: no user",
        "planted: not one of the 15 and not in OUTSIDE_THE_15",
    ]


def _compose() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _compose(), reason="needs the docker compose plugin")
@pytest.mark.parametrize(("stack", "profiles"), STACKS, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x)
def test_compose_config_renders_the_controls(tmp_path: Path, stack: tuple[str, ...], profiles: tuple[str, ...]) -> None:
    services = _render(tmp_path, stack, profiles)["services"]
    assert problems(services, profiles) == []
    if stack == (BASE,):
        assert set(services) == THE_15  # both profiles: 15 of 15

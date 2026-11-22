"""H-80 (D-1359): no serving profile starts its model servers with ``--enforce-eager`` (CUDA graphs on).

The vendor's measured record of the RTX PRO 6000 was taken with the flag; it still passes ``measured`` (the card, the
context and the fractions are what it measured), and ``measured`` says on stderr that start time, memory and rate of
the new setting await the bench's run.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[2]
PROFILES = sorted((ROOT / "deploy").glob("docker-compose*.yml"))
MANIFEST = ROOT / "deploy/platform/components/gpu-pair/llm.yaml"
RUN_SCRIPTS = ("deploy/gcp/gpu-pro6000-run.sh", "deploy/gcp/complete-run-vm.sh")
RECORD = "deploy/measured/serving_config.rtxpro6000.json"


def _commands(node: yaml.Node, key: str = "") -> dict[str, list[str]]:
    """Every ``command`` or ``args`` list in a YAML node graph (compose's own tags need no constructor here),
    keyed by the path of names down to it."""
    out: dict[str, list[str]] = {}
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            name = f"{key}/{k.value}"
            if k.value in ("command", "args") and isinstance(v, yaml.SequenceNode):
                out[name] = [str(c.value) for c in v.value if isinstance(c, yaml.ScalarNode)]
            else:
                out.update(_commands(v, name))
    elif isinstance(node, yaml.SequenceNode):
        for i, v in enumerate(node.value):
            out.update(_commands(v, f"{key}[{i}]"))
    return out


def _all_commands(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, doc in enumerate(yaml.compose_all(path.read_text(encoding="utf-8"))):
        if doc is not None:
            out.update(_commands(doc, f"doc{i}"))
    return out


def _defaults(cmd: list[str]) -> list[str]:
    """``${VAR:-default}`` as compose renders it with nothing set."""
    return [re.sub(r"\$\{[A-Z0-9_]+:-([^}]*)\}", r"\1", c) for c in cmd]


def test_the_profiles_are_found() -> None:
    names = {p.name for p in PROFILES}
    assert {f"docker-compose.{g}.yml" for g in ("rtxpro6000", "rtx5090", "dgpu48", "shared-quota", "gb10")} <= names


@pytest.mark.parametrize("path", [*PROFILES, MANIFEST], ids=lambda p: p.name)
def test_no_serving_profile_runs_eager_by_default(path: Path) -> None:
    eager = [k for k, cmd in _all_commands(path).items() if any("--enforce-eager" in c for c in cmd)]
    assert eager == [], f"{path.name}: {eager}"


def test_the_model_servers_are_seen_by_the_walk() -> None:
    """The walk above reads the servers' command lines (a walk that saw nothing would pass vacuously)."""
    for name in ("rtxpro6000", "rtx5090", "dgpu48", "shared-quota", "gb10"):
        cmds = _all_commands(ROOT / f"deploy/docker-compose.{name}.yml")
        assert any(k.endswith("/llm-service/command") for k in cmds), name
        assert any(k.endswith("/llm-verifier/command") for k in cmds), name
    assert sum(any(c.startswith("--max-model-len") for c in v) for v in _all_commands(MANIFEST).values()) == 2


@pytest.mark.parametrize("script", RUN_SCRIPTS)
def test_the_measuring_runs_start_the_servers_without_eager(script: str) -> None:
    assert "--enforce-eager" not in (ROOT / script).read_text(encoding="utf-8")


def test_the_pro6000_profile_parses_to_graphs_on() -> None:
    cmds = _all_commands(ROOT / "deploy/docker-compose.rtxpro6000.yml")
    for name in ("llm-service", "llm-verifier"):
        (cmd,) = [v for k, v in cmds.items() if k.endswith(f"/{name}/command")]
        args = sc.parse_args(_defaults(cmd))
        assert args["enforce_eager"] is False and args["max_num_seqs"] == 16


def test_the_eager_record_still_measures_the_profile_and_says_what_awaits_the_bench() -> None:
    out = subprocess.run(
        [sys.executable, "tools/serving_config.py", "measured", "rtxpro6000", RECORD, "--mem-kib", "200000000"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 0 and out.stdout.strip() == "measured on rtxpro6000", out.stderr
    assert "--enforce-eager" in out.stderr and "D-1359" in out.stderr and "re-measured" in out.stderr


def test_a_record_without_eager_has_no_note() -> None:
    rec = json.loads((ROOT / RECORD).read_text(encoding="utf-8"))
    assert sc.setting_notes(rec)
    for srv in rec["servers"]:
        srv["enforce_eager"] = False
    assert sc.setting_notes(rec) == []

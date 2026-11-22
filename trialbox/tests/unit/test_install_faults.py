"""Regression tests for the commands and services a fresh rehearsal install sets up."""

from __future__ import annotations

import configparser
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tools import network_sheet, vllm_standin
from tools.trialbox import backup_schedule

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
BASE = "deploy/docker-compose.yml"
STANDINS = "tools/rehearse_box/standins.yml"


def test_standin_models_have_served_names_and_only_run_in_gpu_profile() -> None:
    base = network_sheet.load([BASE])["services"]
    overlay = network_sheet.load([STANDINS])["services"]
    models = {name: svc for name, svc in overlay.items() if "tools.vllm_standin" in svc.get("entrypoint", [])}
    assert {"llm-service", "llm-verifier"} <= models.keys()
    for name, svc in models.items():
        effective = {**base.get(name, {}), **svc}
        entry = effective["entrypoint"]
        args = [*entry[entry.index("tools.vllm_standin") + 1 :], *effective.get("command", [])]
        argv = [network_sheet.interpolate(arg) for arg in args]
        server, _, _ = vllm_standin.build(argv, {"VLLM_API_KEY": "fixture"})
        assert all(server.served), name
        assert effective["profiles"] == ["gpu"], name


def test_installed_nightly_command_imports_its_host_modules(tmp_path: Path) -> None:
    deploy = ROOT / "deploy"
    cron = tmp_path / "cron.d"
    backup_schedule.install_cron(backup_schedule.config(deploy, {"TB_ENV": "VALIDATION"}), cron, ROOT, has_mta=False)
    env = {"PATH": "/usr/bin:/bin"}
    for line in (cron / backup_schedule.CRON_NAME).read_text().splitlines():
        if re.match(r"^\w+=", line):
            key, value = line.split("=", 1)
            env[key] = shlex.split(value)[0]
        if line.startswith("45 4 "):
            command = line.split(None, 6)[6]
            break
    else:
        pytest.fail("04:45 job missing")
    # Keep the installed cd, shell settings and interpreter. Replace only the backup action with its import probe.
    launch, action, _ = command.partition("-m tools.trialbox backup-nightly")
    assert action
    probe = "from tools.trialbox import restic_repo; import tb_common"
    script = launch + "-S -c " + shlex.quote(probe)
    if "{" in shlex.split(launch):
        script += "; }"
    subprocess.run([env["SHELL"], "-ec", script], cwd=tmp_path, env=env, check=True)


@pytest.mark.parametrize("cores", [4, 256])
def test_lake_thread_budget(cores: int) -> None:
    lake = network_sheet.load([BASE])["services"]["lake"]
    workers = int(lake["command"][lake["command"].index("--workers") + 1])
    env = lake["environment"]
    pools = ("TB_LAKE_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "ARROW_IO_THREADS")
    caps = [int(network_sheet.interpolate(env.get(key, str(cores)))) for key in pools]
    # Both HTTP workers and the rebuild subprocess use these libraries.
    assert (workers + 1) * sum(caps) < lake["pids_limit"]
    assert all(key in env for key in pools) and min(caps) > 0


def test_lake_connection_uses_configured_pool(tmp_path: Path) -> None:
    settings = network_sheet.load([BASE])["services"]["lake"]["environment"]
    env = {**os.environ, "TB_LAKE_DIR": str(tmp_path)}
    for key in ("TB_LAKE_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "ARROW_IO_THREADS"):
        env[key] = network_sheet.interpolate(settings[key], {"TB_LAKE_THREADS": "1"})
    probe = """from lake.app import lake
import duckdb
import pyarrow as pa
assert pa.cpu_count() == pa.io_thread_count() == 1
assert duckdb.default_connection().execute("SELECT current_setting('threads')").fetchone() == (1,)
with lake()._cache(False) as con:
    assert con.execute("SELECT current_setting('threads')").fetchone() == (1,)
"""
    subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, check=True)


def test_stack_unit_stays_active_and_takes_down_its_compose_project() -> None:
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(ROOT / "deploy/systemd/trialbox.service")
    service = unit["Service"]
    assert service["Type"] == "oneshot" and service.getboolean("RemainAfterExit")
    up = shlex.split(service["ExecStart"])
    assert "compose" in up and "-d" in up
    assert shlex.split(service["ExecStop"]) == [*up[: up.index("up")], "down"]


def test_installer_starts_stack_unit_on_first_install() -> None:
    installer = (ROOT / "deploy/install.sh").read_text().replace("\\\n", " ")
    assert re.search(r"^\s*systemctl start\b[^\n]*\btrialbox\.service\b", installer, re.M)


def test_installed_unit_keeps_the_installers_scale(tmp_path: Path) -> None:
    # The single-model install scales the verifier to zero. The first systemd start must keep that choice.
    installer = (ROOT / "deploy/install.sh").read_text()
    loop = installer.split("for unit in deploy/systemd/*.service deploy/systemd/*.timer; do\n", 1)[1]
    render = loop.split("done", 1)[0]
    script = """
set -eu
ROOT=$1 SYSTEMD_DIR=$2 BOOT_WAIT=900 STOP_WAIT=120
unit=deploy/systemd/trialbox.service
UP_EXTRA=(--scale llm-verifier=0)
"""
    subprocess.run(["bash", "-c", script + render, "render", str(ROOT), str(tmp_path)], cwd=ROOT, check=True)
    unit = configparser.ConfigParser(interpolation=None)
    unit.read(tmp_path / "trialbox.service")
    start = shlex.split(unit["Service"]["ExecStart"])
    assert start[start.index("--scale") + 1] == "llm-verifier=0"


def test_rehearsal_uses_the_gpu_profiles_actual_model_command() -> None:
    tier = network_sheet.load(["deploy/docker-compose.rtxpro6000.yml"])["services"]
    standins = network_sheet.load([STANDINS])["services"]
    for name, override in standins.items():
        if "tools.vllm_standin" in override.get("entrypoint", []):
            effective = {**tier[name], **override}
            assert effective["command"] == tier[name]["command"]

"""T-673 (D-348): deploy/images.lock is the one digest list of the third-party images; no compose file pulls an image
by tag; the GPU host is checked against what the vLLM image needs (deploy/check_host.sh, tools/images_lock.py)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import images_lock as il
from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
COMPOSE = sorted(DEPLOY.glob("docker-compose*.yml"))
VLLM = "vllm/vllm-openai:v0.32.0@sha256:befccf0e7e4089aa23926bb6f887a85c0d46c2a99e6de5c5ffdf5cb7957c5b34"


@pytest.fixture(scope="module")
def lock() -> dict[str, Any]:
    return il.load()


# ------------------------------------------------------------------------------------------------ the lock itself
def test_the_lock_is_well_formed_and_keeps_the_db_entry(lock: dict[str, Any]) -> None:
    assert il.lock_problems(lock) == []
    assert lock["images"]["db"]["image"] == "trialbox-postgres:16-1"  # D-204's part is unchanged
    assert set(lock["third_party"]) == {"vllm", "hapi", "caddy", "authelia", "greenmail", "mailpit"}


def test_vllm_is_the_release_of_the_g1_run_by_digest(lock: dict[str, Any]) -> None:
    vllm = lock["third_party"]["vllm"]
    assert il.pinned(vllm) == VLLM
    measured = json.loads((DEPLOY / "measured" / "serving_config.rtxpro6000.json").read_text(encoding="utf-8"))
    assert {s["image"] for s in measured["servers"]} == {vllm["image"]}  # the version the measured run used
    assert vllm["gpu"]["structured_outputs_backend"] == "auto"
    assert set(vllm["platforms"]) == {"linux/amd64", "linux/arm64"}


# ------------------------------------------------------------------------------------------------ no image by tag
def test_no_compose_file_pulls_a_third_party_image_by_tag(lock: dict[str, Any]) -> None:
    problems, used = il.check_compose(lock, COMPOSE)
    assert problems == []
    assert used == set(lock["third_party"])  # every lock entry is used, and nothing outside it
    assert il.main(["check-compose", "--all", "--files", ":".join(str(p) for p in COMPOSE)]) == 0


def test_the_spark_runs_the_official_image_built_for_its_chip(lock: dict[str, Any]) -> None:
    text = (DEPLOY / "docker-compose.gb10.yml").read_text(encoding="utf-8")
    assert "eugr/" not in text and "station-" not in text
    assert text.count(f"${{VLLM_GB10_IMAGE:-{VLLM}}}") == 2
    arm = lock["third_party"]["vllm"]["platforms"]["linux/arm64"]["cuda_arch"]
    assert il.arch_covers(arm, "12.1")  # GB10 is sm_121: the sm_120 build runs on it


def test_mailhog_is_replaced_by_mailpit(lock: dict[str, Any]) -> None:
    text = (DEPLOY / "docker-compose.test.yml").read_text(encoding="utf-8")
    assert "mailhog/mailhog" not in text and "MAILHOG_IMAGE" not in text
    assert f"${{MAILPIT_IMAGE:-{il.pinned(lock['third_party']['mailpit'])}}}" in text
    assert "aliases: [mailhog]" in text  # an older deploy/.env with SMTP_HOST=mailhog still reaches the sink
    assert "SMTP_HOST=mailpit" in (ROOT / ".env.example").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("    image: ${VLLM_IMAGE:-vllm/vllm-openai:v0.32.0}", "by tag"),
        ("    image: vllm/vllm-openai:v0.32.0@sha256:" + "a" * 64, "is not ${VAR:-image@digest}"),
        ("    image: ${VLLM_IMAGE:-vllm/vllm-openai:v0.32.0@sha256:" + "a" * 64 + "}", "deploy/images.lock vllm is"),
        ("    image: ${OTHER_IMAGE:-busybox:1@sha256:" + "a" * 64 + "}", "is not in deploy/images.lock"),
    ],
)
def test_a_compose_line_outside_the_lock_is_refused(lock: dict[str, Any], tmp_path: Path, line: str, why: str) -> None:
    f = tmp_path / "docker-compose.x.yml"
    f.write_text("services:\n  a:\n" + line + "\n  b:\n    image: ${TB_IMAGE:-trialbox-py:1.0.0}\n", encoding="utf-8")
    problems, _ = il.check_compose(lock, [f])
    assert len(problems) == 1 and why in problems[0], problems
    assert il.main(["check-compose", "--files", str(f)]) == 1


def test_a_lock_entry_without_a_digest_or_with_a_shared_variable_is_refused(lock: dict[str, Any]) -> None:
    bad = copy.deepcopy(lock)
    bad["third_party"]["hapi"]["digest"] = None
    bad["third_party"]["caddy"]["variables"] = ["HAPI_IMAGE"]
    del bad["third_party"]["vllm"]["gpu"]["driver_min"]
    problems = il.lock_problems(bad)
    assert any("hapi: digest" in p for p in problems)
    assert any("variable HAPI_IMAGE" in p for p in problems)
    assert any("gpu.driver_min" in p for p in problems)


# ------------------------------------------------------------------------------------------------ the GPU host
@pytest.mark.parametrize(
    ("archs", "cap", "ok"),
    [
        (["8.0", "12.0"], "12.1", True),  # same major, newer minor
        (["8.0", "12.0"], "12.0", True),
        (["7.5", "8.0", "8.6", "8.9", "9.0", "10.0", "12.0"], "10.0", True),  # B200
        (["8.0", "12.0"], "11.0", False),
        (["8.0", "12.0"], "6.1", False),  # Pascal: no kernels
        (["10.3a"], "10.3", True),
        (["10.0a"], "10.3", False),  # an "a" build runs only on its own capability
        (["12.1"], "12.0", False),
    ],
)
def test_arch_cover_rule(archs: list[str], cap: str, ok: bool) -> None:
    assert il.arch_covers(archs, cap) is ok


def _levels(lines: list[tuple[str, str]]) -> list[str]:
    return [lvl for lvl, _ in lines]


def test_host_check_fails_on_a_low_driver(lock: dict[str, Any]) -> None:
    lines = il.host_check(lock, "x86_64", "575.57.08", "12.0")
    fails = [m for lvl, m in lines if lvl == "FAIL"]
    assert len(fails) == 1 and "575.57.08 is below 580.65.06" in fails[0] and "R580" in fails[0]
    assert "FAIL" not in _levels(il.host_check(lock, "x86_64", "580.178.04", "12.0"))
    assert "FAIL" in _levels(il.host_check(lock, "x86_64", "", "12.0"))  # no driver at all


def test_host_check_fails_on_an_arch_mismatch(lock: dict[str, Any]) -> None:
    amd_only = copy.deepcopy(lock)
    del amd_only["third_party"]["vllm"]["platforms"]["linux/arm64"]
    lines = il.host_check(amd_only, "aarch64", "580.142", "12.1")
    assert any(lvl == "FAIL" and "no linux/arm64 build" in m for lvl, m in lines)
    lines = il.host_check(lock, "aarch64", "580.142", "6.1")  # a device the build has no kernels for
    assert any(lvl == "FAIL" and "compute capability 6.1" in m for lvl, m in lines)
    assert "FAIL" not in _levels(il.host_check(lock, "aarch64", "580.142", "12.1"))  # the GB10


def test_host_check_names_the_backend_and_leaves_a_site_image_alone(lock: dict[str, Any]) -> None:
    lines = il.host_check(lock, "x86_64", "580.178.04", "12.0")
    assert any("structured output: vLLM backend auto" in m for _, m in lines)
    site = il.host_check(lock, "x86_64", "575.0", "12.0", image="registry.hospa.test/vllm:mirror")
    assert _levels(site) == ["WARN"]
    # an image id is the bundle's copy of the pinned image on the overlay2 store (tools/image_pins.py): checked
    assert "FAIL" in _levels(il.host_check(lock, "x86_64", "575.0", "12.0", image="sha256:" + "1" * 64))
    assert "FAIL" in _levels(il.host_check(lock, "x86_64", "575.0", "12.0", image=VLLM))


# ------------------------------------------------------------------------------------------------ check_host.sh
def _fake_bin(tmp_path: Path, arch: str, driver: str, cap: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    scripts = {
        "uname": f'[ "$1" = -m ] && echo {arch} || echo Linux\n',
        "nvidia-smi": (
            'case "$*" in\n'
            f'  *driver_version*) echo "{driver}" ;;\n'
            f'  *compute_cap*) echo "{cap}" ;;\n'
            '  *name*) echo "NVIDIA Test GPU, ' + driver + '" ;;\n'
            "  *) echo GPU 0 ;;\nesac\n"
        ),
        "apt-mark": "echo nvidia-driver-580\n",
        "docker": 'echo "Runtimes: nvidia runc"\n',
    }
    for name, body in scripts.items():
        p = bin_dir / name
        p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        p.chmod(0o755)
    return bin_dir


def _check_host(tmp_path: Path, *args: str, arch: str, driver: str, cap: str) -> subprocess.CompletedProcess[str]:
    bin_dir = _fake_bin(tmp_path, arch, driver, cap)
    py = Path(shutil.which("python3") or "/usr/bin/python3").parent
    env = {"PATH": f"{bin_dir}:{py}:/usr/bin:/bin", "HOME": str(tmp_path)}
    env.update({k: v for k, v in os.environ.items() if k.startswith("LC_")})
    return subprocess.run(
        ["sh", str(DEPLOY / "check_host.sh"), "--gpu-only", *args, "--env", str(tmp_path / "none.env")],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )  # fmt: skip


def test_check_host_passes_a_gb10_on_its_pinned_driver(tmp_path: Path) -> None:
    r = _check_host(tmp_path, "--gb10", arch="aarch64", driver="580.142", cap="12.1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (
        "PASS  aarch64 host" in r.stdout and "PASS  vLLM image vllm/vllm-openai:v0.32.0 has a linux/arm64" in r.stdout
    )
    assert "GPU host checks passed" in r.stdout


def test_check_host_fails_on_a_low_driver(tmp_path: Path) -> None:
    r = _check_host(tmp_path, "--gpu", "rtxpro6000", arch="x86_64", driver="575.57.08", cap="12.0")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL  NVIDIA driver 575.57.08 is below 580.65.06" in r.stdout
    assert "1 GPU check(s) failed" in r.stdout


def test_check_host_fails_on_an_arch_mismatch(tmp_path: Path) -> None:
    r = _check_host(tmp_path, "--gb10", arch="x86_64", driver="580.142", cap="12.1")
    assert r.returncode == 1 and "FAIL  GB10 profile on x86_64" in r.stdout, r.stdout + r.stderr
    r = _check_host(tmp_path / "b", "--gpu", "default", arch="ppc64le", driver="580.178.04", cap="12.0")
    assert r.returncode == 1 and "has no linux/ppc64le build" in r.stdout, r.stdout + r.stderr


def test_check_host_gpu_only_needs_a_profile(tmp_path: Path) -> None:
    r = _check_host(tmp_path, arch="x86_64", driver="580.178.04", cap="12.0")
    assert r.returncode == 2 and "needs --gpu" in r.stderr


def test_install_reads_the_lock() -> None:
    text = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    # before anything is loaded: the GPU host against the vLLM image; before compose up: the files against the lock
    first = text.index('check_host.sh" --gpu-only --gpu "$GPU"')
    assert first < text.index('tools/apply_update.sh" "$BUNDLE" --dry-run')
    assert 'tools.images_lock check-compose --files "$LOCK_FILES"' in text
    assert text.index("tools.images_lock check-compose") < text.index('"${COMPOSE[@]}" up -d')


# ------------------------------------------------------------------------------------------------ serving record
def test_the_serving_record_names_the_structured_output_backend() -> None:
    assert sc.parse_args(["--model=/m", "--enforce-eager"])["structured_outputs_backend"] == "auto"
    rec = sc.parse_args(["--structured-outputs-config.backend", "xgrammar"])
    assert rec["structured_outputs_backend"] == "xgrammar"
    assert rec["extra_args"] == ["--structured-outputs-config.backend", "xgrammar"]
    rec = sc.parse_args(['--structured-outputs-config={"backend":"guidance"}'])
    assert rec["structured_outputs_backend"] == "guidance"

"""Card H-61: three Low findings of lane H closed (H10E5-02, H10E5-03, H58-03).

* H10E5-02: ``tools/serving_config.measured_for(rec, "gb10")`` reads the host's memory (``MemTotal`` in kB, the rule
  of ``deploy/gpu_profile.sh memory-class``): under 96 GiB the host is the 64 GB class, which nothing measures
  (D-1335), so a gb10 record does not hold there. Unknown memory is not refused. The reader is a parameter, so no
  test reads this machine's memory.
* H10E5-03: ``deploy/check_host.sh --gb10`` FAILs such a host with install.sh's reason; ``TB_TEST_MEM_KIB`` stands in
  for ``MemTotal`` in tests.
* H58-03: ``tests/unit/test_compose_limits.py`` lints the two-device stacks too.

All memory figures are synthetic; no GPU, no Docker daemon.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_compose_limits as limits
from tests.unit.test_images_lock import _fake_bin
from tools import serving_config as sc

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
LINE_KIB = 96 * 1024 * 1024  # 96 GiB in kB
SMALL_KIB = 62_000_000  # a 64 GB Spark's MemTotal (synthetic)
BIG_KIB = 124_000_000  # a 128 GB Spark's (synthetic)


def _gb10_record() -> dict[str, Any]:
    files = [{"path": "config.json", "bytes": 1, "sha256": "0" * 64}]
    server = {
        "image": "vllm/vllm-openai:v0.32.0", "vllm_version": "0.32.0", "model": "m", "served_model_name": "local/m",
        "max_model_len": 16384, "max_num_seqs": 4, "enforce_eager": True, "gpu_memory_utilization": 0.3,
        "kv_cache_dtype": "auto", "extra_args": [], "model_files": files, "model_files_sha256": "1" * 64,
    }  # fmt: skip
    return {
        "schema": "tb-serving-config/1", "captured_at": "2026-11-19T00:00:00+00:00", "host": "synthetic",
        "card": {"name": "NVIDIA GB10", "memory_total_mib": 122000, "driver": "580.142", "cuda": "13.0", "count": 1,
                 "capped_to": None, "mig": False},
        "memory_used_mib": 1, "notes": "synthetic",
        "servers": [{**server, "role": "judge", "container": "j"}, {**server, "role": "verifier", "container": "v"}],
    }  # fmt: skip


# ------------------------------------------------------------------------------------------------ H10E5-02
def test_the_record_is_sound_on_a_big_or_unknown_host() -> None:
    rec = _gb10_record()
    assert sc.measured_for(rec, "gb10", lambda: BIG_KIB) == []
    assert sc.measured_for(rec, "gb10", lambda: LINE_KIB) == []  # the line itself is the 128 GB class
    assert sc.measured_for(rec, "gb10", lambda: None) == []  # unknown memory: as before


def test_a_gb10_record_does_not_hold_on_a_host_under_96_gib() -> None:
    for kib in (SMALL_KIB, LINE_KIB - 1):  # compared in kB, never rounded
        why = sc.measured_for(_gb10_record(), "gb10", lambda k=kib: k)
        assert len(why) == 1 and "64 GB Spark class (gb10-64)" in why[0] and "D-1335" in why[0], why


def test_the_line_is_gpu_profile_sh_s_line() -> None:
    text = (ROOT / "deploy/gpu_profile.sh").read_text(encoding="utf-8")
    assert f"SMALL_KIB={sc.SMALL_GB10_KIB}" in text and sc.SMALL_GB10_KIB == LINE_KIB


def test_the_default_reader_is_this_host_s_meminfo_and_only_gb10_reads_it(tmp_path: Path) -> None:
    assert inspect.signature(sc.measured_for).parameters["mem_kib"].default is sc.host_mem_kib
    info = tmp_path / "meminfo"
    info.write_text("MemFree:  1 kB\nMemTotal:       62000000 kB\n", encoding="utf-8")
    assert sc.host_mem_kib(info) == SMALL_KIB
    info.write_text("MemTotal: n/a\n", encoding="utf-8")
    assert sc.host_mem_kib(info) is None and sc.host_mem_kib(tmp_path / "missing") is None

    def never() -> int:
        raise AssertionError("read for a profile that is not gb10")

    rec = _gb10_record()
    rec["card"]["name"] = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
    for srv in rec["servers"]:
        srv["max_model_len"] = 32768
    assert sc.measured_for(rec, "rtxpro6000", never) == []


def test_the_cli_takes_the_memory(tmp_path: Path) -> None:
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_gb10_record()), encoding="utf-8")
    assert sc.main(["measured", "gb10", str(p), "--mem-kib", str(SMALL_KIB)]) == 1
    assert sc.main(["measured", "gb10", str(p), "--mem-kib", str(BIG_KIB)]) == 0


def test_the_tier_check_passes_its_memory_and_the_record_check_reads_none() -> None:
    assert "measured_for(rec, gpu, lambda: mem_kib)" in (ROOT / "tools/tiers.py").read_text(encoding="utf-8")
    assert "measured_for(rec, profile, lambda: None)" in (ROOT / "tools/tier_record.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------ H10E5-03
def _check_host(tmp: Path, *args: str, kib: str | None) -> subprocess.CompletedProcess[str]:
    bin_dir = _fake_bin(tmp, "aarch64", "580.142", "12.1")
    py = Path(shutil.which("python3") or "/usr/bin/python3").parent
    env = {"PATH": f"{bin_dir}:{py}:/usr/bin:/bin", "HOME": str(tmp)}
    env.update({k: v for k, v in os.environ.items() if k.startswith("LC_")})
    if kib is not None:
        env["TB_TEST_MEM_KIB"] = kib
    return subprocess.run(
        ["sh", str(ROOT / "deploy/check_host.sh"), *args, "--env", str(tmp / "none.env"), "--secrets", str(tmp)],
        capture_output=True, text=True, env=env, timeout=120, check=False,
    )  # fmt: skip


SMALL_FAIL = "FAIL  this DGX Spark has under 96 GiB of memory (the 64 GB class)"


@pytest.mark.parametrize("args", [("--gpu-only", "--gb10"), ("--gpu-only", "--gpu", "gb10")])
def test_check_host_fails_a_small_spark(tmp_path: Path, args: tuple[str, ...]) -> None:
    r = _check_host(tmp_path, *args, kib=str(SMALL_KIB))
    assert r.returncode == 1 and SMALL_FAIL in r.stdout, r.stdout + r.stderr
    assert "--mode stub" in r.stdout and "D-1335" in r.stdout


def test_check_host_passes_a_big_spark_and_unknown_memory(tmp_path: Path) -> None:
    for i, kib in enumerate((str(BIG_KIB), str(LINE_KIB), "n/a")):
        r = _check_host(tmp_path / str(i), "--gpu-only", "--gb10", kib=kib)
        assert r.returncode == 0 and "64 GB class" not in r.stdout, r.stdout + r.stderr


def test_the_full_gb10_check_fails_a_small_spark_too(tmp_path: Path) -> None:
    r = _check_host(tmp_path, "--gb10", kib=str(SMALL_KIB))
    assert SMALL_FAIL in r.stdout and r.returncode == 1, r.stdout + r.stderr
    big = _check_host(tmp_path / "big", "--gb10", kib=str(BIG_KIB))
    assert "64 GB class" not in big.stdout, big.stdout


def test_install_s_refusal_has_the_same_sense() -> None:
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    host = (ROOT / "deploy/check_host.sh").read_text(encoding="utf-8")
    for words in ("this DGX Spark has under 96 GiB of memory (the 64 GB class): TrialBox does not serve the model "
                  "pair on it", "no profile of the 64 GB class is measured, so none is guessed (card 10E-5, D-1335)",
                  "--mode stub"):  # fmt: skip
        assert words in install and words in host, words


# ------------------------------------------------------------------------------------------------ H58-03
def test_the_limits_lint_reads_the_two_device_stacks() -> None:
    linted = {f for stack, _ in limits.LINTED_STACKS for f in stack}
    assert {"two-device/docker-compose.spark.yml", "two-device/docker-compose.workstation.yml"} <= linted
    for stack, profiles in limits.TWO_DEVICE_STACKS:
        services = limits._merge(stack)
        assert "link" in services and limits.problems(services, profiles) == [], stack


def test_the_lint_would_name_the_link_without_its_rules() -> None:
    stack, profiles = limits.TWO_DEVICE_STACKS[0]
    services = limits._merge(stack)
    services["link"] = {k: v for k, v in services["link"].items() if k not in ("pids_limit", "labels")}
    assert [p for p in limits.problems(services, profiles) if p.startswith("link:")] == [
        "link: no positive pids_limit",
        "link: no tb.watchdog label (restart or report)",
    ]

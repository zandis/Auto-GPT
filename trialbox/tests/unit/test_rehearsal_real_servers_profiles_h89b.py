"""H-89b: the rehearsal with real servers on the 48 GB draft and on the 128 GB unified-memory class (the integrator's
ruling 7088891993, items 1 and 2).

Each is opened under the rehearsal mark only (``--rehearsal --rehearsal-real-servers``), held to its own class's memory
on the bench's card; without the mark the installer's behaviour for the profile is master's, byte for byte.
docs/handover/rehearsal-real-servers-h89b-2026-11-23.md says what each row does not prove.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.test_rehearsal_real_servers_h89 import GOOD, INSTALL, Bench, _plant
from tools import rehearsal_real

ROOT = Path(__file__).resolve().parents[2]
TOTAL = 183359  # the bench's card, as the stand-in reports it

# master's bytes (371c9857), the 48 GB draft without the mark: the profile step's refusal, whatever else is set
DGPU48_DIE = (
    "install: dgpu48 is a DRAFT, UNMEASURED 48 GB profile: no install serves it. Its one use is the measuring run "
    "(TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure, RUNBOOK §29)"
)
HOST_LINE = "\x1b[1m==> host\x1b[0m\n"
DGPU48_MASTER: list[tuple[str, list[str], dict[str, Any], dict[str, str]]] = [
    ("named", ["--mode", "gpu", "--gpu", "dgpu48"], {"driver": GOOD}, {}),
    ("a plain rehearsal", ["--rehearsal", "--gpu", "dgpu48"], {"driver": GOOD}, {}),
    ("low driver", ["--gpu", "dgpu48"], {}, {}),
    ("by the variable", ["--mode", "gpu"], {"driver": GOOD}, {"TB_GPU_PROFILE": "dgpu48"}),
    ("the measuring switch", ["--rehearsal", "--mode", "gpu", "--gpu", "dgpu48"], {"driver": GOOD},
     {"TB_UNMEASURED_DGPU48_MEASURING_RUN": "1"}),
]  # fmt: skip


def _same(tmp: Path, args: list[str], bench: dict[str, Any], env: dict[str, str]) -> tuple[Any, Any]:
    """The install with nothing planted, and with every rehearsal sign planted: (rc, stdout, stderr) of each."""
    clean = Bench(tmp / "clean", **bench).install(*args, **env)
    pb = Bench(tmp / "planted", **bench)
    planted = pb.install(*args, **{**_plant(pb), **env})
    got = [(r.returncode, r.stdout.replace(str(t), "<tmp>"), r.stderr.replace(str(t), "<tmp>"))
           for r, t in ((clean, tmp / "clean"), (planted, tmp / "planted"))]  # fmt: skip
    return got[0], got[1]


def real(b: Bench, profile: str, *more: str, **env: str) -> subprocess.CompletedProcess[str]:
    return b.install("--rehearsal", "--rehearsal-real-servers", "--gpu", profile, "--gpu-index", "1",
                     "--engine-probe", str(b.probe), *more, **env)  # fmt: skip


def _block(start: str, end: str) -> str:
    i = INSTALL.index(start)
    return INSTALL[i : INSTALL.index(end, i) + len(end)]


# ------------------------------------------------------------------------------------------------ 1. dgpu48 (48 GB)
@pytest.mark.parametrize(("what", "args", "bench", "env"), DGPU48_MASTER, ids=[m[0] for m in DGPU48_MASTER])
def test_dgpu48_without_the_mark_is_masters_refusal_byte_for_byte(
    tmp_path: Path, what: str, args: list[str], bench: dict[str, Any], env: dict[str, str]
) -> None:
    clean, planted = _same(tmp_path, args, bench, env)
    assert clean == (1, HOST_LINE, DGPU48_DIE + "\n"), clean
    assert planted == clean


def test_dgpu48_under_the_mark_goes_past_the_gpu_step_held_to_its_cap(tmp_path: Path) -> None:
    b = Bench(tmp_path)
    r = real(b, "dgpu48")
    need = rehearsal_real.record_need({}, TOTAL, "dgpu48")[0]
    assert f"card 1: NVIDIA B200, 180000 MiB free of {TOTAL} (the pair needs {need})" in r.stdout, r.stdout + r.stderr
    assert "WARN  NVIDIA driver 575.57.08" in r.stdout and "FAIL" not in r.stdout
    assert DGPU48_DIE not in r.stderr
    assert r.stderr.splitlines()[-1].startswith("install: vendor public key missing"), r.stderr


def test_dgpu48_cap_is_the_48gb_cards_memory() -> None:
    """Its overlay's own utilisations (both resident, 0.57 and 0.27 of 49,140 MiB), scaled to the bench's card."""
    got = rehearsal_real.caps("dgpu48", TOTAL)
    own = {"JUDGE_GPU_MEM_UTIL": 0.57, "VERIFIER_GPU_MEM_UTIL": 0.27}
    assert set(got) == set(own)
    for k, u in own.items():
        assert got[k] * TOTAL <= u * 49140 < (got[k] + 0.001) * TOTAL
    assert rehearsal_real.caps("dgpu48", 49140) == own
    need = rehearsal_real.record_need({}, TOTAL, "dgpu48")[0]
    assert need <= 49140 and need == -(-(got["JUDGE_GPU_MEM_UTIL"] + got["VERIFIER_GPU_MEM_UTIL"]) * TOTAL // 1)


def test_dgpu48_a_card_short_of_its_cap_is_refused(tmp_path: Path) -> None:
    need = rehearsal_real.record_need({}, TOTAL, "dgpu48")[0]
    r = real(Bench(tmp_path, free=need - 1), "dgpu48")
    assert r.returncode == 1 and f"has {need - 1} MiB free; the pair needs {need} MiB" in r.stderr, r.stderr
    assert "WARN" not in r.stdout


def test_dgpu48_write_records_the_profile_and_its_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, doc = rehearsal_real.write(b.deploy, "1", b.probe, None, "dgpu48")
    assert problems == [] and doc["card"]["profile"] == "dgpu48" and doc["valid_for_a_site"] is False
    assert doc["caps"] == rehearsal_real.caps("dgpu48", TOTAL) and doc["words"] == rehearsal_real.WORDS
    assert doc["card"]["this_profiles_card"] is False


def _later(tmp: Path, real_servers: int, env_lines: str) -> subprocess.CompletedProcess[str]:
    """install.sh's later steps for the 48 GB draft as they stand: the pins' profile, the record step's H-89b block,
    the box's label and its compose files."""
    pins = _block('  PIN_GPU="$GPU";', "|| PIN_GPU=rtxpro6000\n")
    rec = _block("# REHEARSAL-REAL-SERVERS (H-89b): the 48 GB draft has no record", "# ---- end of REHEARSAL-REAL-SERVERS (H-89b)\n")
    label = _block('case "$MODE:$GPU" in\n  # H-89b: the label', "esac\n")
    files = _block('COMPOSE=(docker compose --project-directory deploy', "esac\n")
    rh = _block("rehearsal_only() {", "\n}\n")
    site = tmp / "deploy" / "site"
    site.mkdir(parents=True, exist_ok=True)
    (site / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    (site / rehearsal_real.RECORD).write_text(json.dumps({"words": rehearsal_real.WORDS}), encoding="utf-8")
    (tmp / "deploy" / ".env").write_text(env_lines, encoding="utf-8")
    script = (
        f'set -euo pipefail\nROOT="{tmp}"\ncd "$ROOT"\nMODE=gpu\nGPU=dgpu48\nGPU_INDEX=1\nREAL_SERVERS={real_servers}\n'
        'die() { echo "install: $*" >&2; exit 1; }\nenvget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        f'TB_ENV_SITE="$(envget TB_ENV)"\n{rh}{pins}{rec}{label}{files}'
        'echo "PIN_GPU=$PIN_GPU PROFILE=$PROFILE"\necho "FILES=$FILES"\n'
    )  # fmt: skip
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)


def test_dgpu48_under_the_mark_pins_the_same_pair_starts_its_overlay_and_says_so(tmp_path: Path) -> None:
    r = _later(tmp_path, 1, "TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")
    assert r.returncode == 0, r.stderr
    assert "PIN_GPU=rtxpro6000 PROFILE=P-DGPU48-UNMEASURED" in r.stdout
    assert r.stdout.rstrip().endswith(f"{tmp_path}/deploy/docker-compose.dgpu48.yml")
    assert f"install: warning: {rehearsal_real.WORDS}: the dgpu48 profile is a DRAFT, UNMEASURED 48 GB profile" in r.stderr
    r = _later(tmp_path, 1, "TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n")
    assert r.returncode == 1 and "only on a rehearsal box" in r.stderr
    r = _later(tmp_path, 0, "TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")  # never reached without the mark; says nothing
    assert r.returncode == 0 and r.stderr == "" and "PIN_GPU=dgpu48 " in r.stdout


# ------------------------------------------------------------------------------------------------ 2. gb10 (128 GB)
BIG = {"TB_TEST_MEM_KIB": "134000000"}  # the bench host's memory: over 96 GiB, so the profile stays gb10
GB10_FAIL = "    FAIL  GB10 profile on x86_64"
STAND_IN = "x86 stand-in: memory budget only"
GB10_MASTER: list[tuple[str, list[str], dict[str, Any], dict[str, str], str]] = [
    ("named", ["--mode", "gpu", "--gpu", "gb10"], {"driver": GOOD}, BIG, GB10_FAIL),
    ("a plain rehearsal", ["--rehearsal", "--gpu", "gb10"], {"driver": GOOD}, BIG, GB10_FAIL),
    ("low driver", ["--gpu", "gb10"], {}, BIG, GB10_FAIL),
    ("by the variable", ["--mode", "gpu"], {"driver": GOOD}, {**BIG, "TB_GPU_PROFILE": "gb10"}, GB10_FAIL),
    ("the 64 GB class", ["--mode", "gpu", "--gpu", "gb10"], {"driver": GOOD}, {"TB_TEST_MEM_KIB": "60000000"},
     "install: this DGX Spark has under 96 GiB of memory (the 64 GB class)"),
]  # fmt: skip


@pytest.mark.parametrize(("what", "args", "bench", "env", "said"), GB10_MASTER, ids=[m[0] for m in GB10_MASTER])
def test_gb10_without_the_mark_is_masters_refusal_byte_for_byte(
    tmp_path: Path, what: str, args: list[str], bench: dict[str, Any], env: dict[str, str], said: str
) -> None:
    """Master (371c9857): the host check FAILs the profile on an x86 host and the install stops; the same bytes with
    or without a passing probe and every rehearsal sign planted, and no word of the stand-in."""
    clean, planted = _same(tmp_path, args, bench, env)
    assert clean[0] == 1 and said in clean[1] + clean[2], clean
    if said == GB10_FAIL:
        assert clean[2] == "install: this GPU host cannot run the vLLM image of deploy/images.lock (FAIL above); nothing was changed\n"
    assert planted == clean
    assert "stand-in" not in clean[1] + clean[2] and "rehearsal" not in clean[1] + clean[2]


def test_gb10_under_the_mark_goes_past_the_gpu_step_held_to_its_cap(tmp_path: Path) -> None:
    r = real(Bench(tmp_path), "gb10", **BIG)
    need = rehearsal_real.record_need({}, TOTAL, "gb10")[0]
    assert f"card 1: NVIDIA B200, 180000 MiB free of {TOTAL} (the pair needs {need})" in r.stdout, r.stdout + r.stderr
    assert f"    WARN  GB10 profile on x86_64: {STAND_IN} (a rehearsal with real servers, not valid for a site)" in r.stdout
    assert "WARN  NVIDIA driver 575.57.08" in r.stdout and "FAIL" not in r.stdout
    assert r.stderr.splitlines()[-1].startswith("install: vendor public key missing"), r.stderr


def test_gb10_the_64gb_class_is_refused_under_the_mark_too(tmp_path: Path) -> None:
    r = real(Bench(tmp_path), "gb10", TB_TEST_MEM_KIB="60000000")
    assert r.returncode == 1 and "this DGX Spark has under 96 GiB of memory (the 64 GB class)" in r.stderr
    assert "WARN" not in r.stdout


def test_gb10_cap_is_the_classs_memory() -> None:
    got = rehearsal_real.caps("gb10", TOTAL)
    own = {"JUDGE_GPU_MEM_UTIL": 0.30, "VERIFIER_GPU_MEM_UTIL": 0.15}
    assert set(got) == set(own)
    for k, u in own.items():
        assert got[k] * TOTAL <= u * 131072 < (got[k] + 0.001) * TOTAL
    assert rehearsal_real.caps("gb10", 131072) == own
    assert rehearsal_real.record_need({}, TOTAL, "gb10")[0] <= 0.45 * 131072


def test_gb10_write_overrides_the_arm64_pins_on_x86_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    monkeypatch.setattr(rehearsal_real.platform, "machine", lambda: "x86_64")
    problems, doc = rehearsal_real.write(b.deploy, "1", b.probe, None, "gb10")
    assert problems == [] and doc["caps"] == rehearsal_real.caps("gb10", TOTAL)
    assert doc["words"] == f"{rehearsal_real.WORDS} ({STAND_IN})" and doc["valid_for_a_site"] is False
    overlay = yaml.safe_load((ROOT / "deploy" / "docker-compose.gb10.yml").read_text(encoding="utf-8"))
    pinned = {n for n, svc in overlay["services"].items() if (svc or {}).get("platform") == "linux/arm64"}
    assert set(doc["platform_override"]["services"]) == pinned and len(pinned) >= 10
    text = (b.deploy / "site" / rehearsal_real.OVERRIDE).read_text(encoding="utf-8")
    assert text.count("platform: linux/amd64") == len(doc["platform_override"]["services"])
    assert text.count("device_ids: [\"GPU-11111111") == 2 and "arm64" not in text.replace("arm64 pins", "")
    for machine, want in (("aarch64", []), ("x86_64", doc["platform_override"]["services"])):
        assert rehearsal_real.platform_services("gb10", machine) == want
    assert rehearsal_real.platform_services("rtxpro6000", "x86_64") == []
    monkeypatch.setattr(rehearsal_real.platform, "machine", lambda: "ppc64le")
    (b.deploy / "site" / rehearsal_real.OVERRIDE).unlink()
    problems, doc = rehearsal_real.write(b.deploy, "1", b.probe, None, "gb10")
    assert doc == {} and "opened as an x86 stand-in only" in problems[0]
    assert not (b.deploy / "site" / rehearsal_real.OVERRIDE).exists()


def _check_host(tmp: Path, b: Bench, machine: str, *args: str) -> subprocess.CompletedProcess[str]:
    """deploy/check_host.sh --gpu-only, with uname a stand-in that names ``machine``."""
    (b.bin / "uname").write_text(f'#!/bin/sh\n[ "$1" = -m ] && echo {machine} || /bin/uname "$@"\n', encoding="utf-8")
    (b.bin / "uname").chmod(0o755)
    return subprocess.run(["sh", str(b.deploy / "check_host.sh"), "--gpu-only", *args], capture_output=True,
                          text=True, env=b.env(**BIG), timeout=120, check=False)  # fmt: skip


def test_gb10_the_host_check_keeps_failing_it_on_x86_outside_the_rehearsal(tmp_path: Path) -> None:
    b = Bench(tmp_path, driver=GOOD)
    rrs = ["--rehearsal-real-servers", "--engine-probe", str(b.probe), "--gpu-index", "1"]
    for args in (["--gpu", "gb10"], ["--gb10"]):
        r = _check_host(tmp_path, b, "x86_64", *args)
        assert r.returncode == 1 and "FAIL  GB10 profile on x86_64" in r.stdout and STAND_IN not in r.stdout
    r = _check_host(tmp_path, b, "aarch64", "--gpu", "gb10", *rrs)  # a real GB10 takes no rehearsal arguments
    assert r.returncode == 2 and r.stderr.startswith("--rehearsal-real-servers needs --engine-probe")
    r = _check_host(tmp_path, b, "x86_64", "--gpu", "gb10", *rrs)
    assert f"WARN  GB10 profile on x86_64: {STAND_IN}" in r.stdout and "FAIL  GB10" not in r.stdout

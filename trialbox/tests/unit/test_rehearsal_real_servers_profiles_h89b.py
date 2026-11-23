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


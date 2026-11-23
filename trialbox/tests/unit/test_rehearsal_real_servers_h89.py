"""H-89: the install walk with the real model servers on the bench host, a rehearsal box only (the integrator's ruling
of 2026-11-22 13:55 UTC). Three install refusals are each right for a hospital site: the driver below
deploy/images.lock gpu.driver_min, a card that is not the profile's, a serving record of another card. Under the
rehearsal mark (``--rehearsal --rehearsal-real-servers``, on a box that may be a rehearsal box) each becomes a loud
WARN; without it each fails exactly as before.

THE INVARIANT: :func:`test_without_the_mark_the_three_refusals_are_byte_identical`: whatever new options,
environment variables or files are planted, an install without the mark prints the same bytes and exits with the same
code as one without them, and those bytes are master's refusals (the literals below were taken from master
97048772e0bb at the card's start).

No GPU, no Docker: the installer runs in a folder laid out as an installer's, with stand-ins for docker and nvidia-smi.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_poc_stops_bench_h94 import stop_prelude
from tools import engine_probe, images_lock, rehearsal_real
from tools.trialbox import doctor, prestart
from tools.trialbox.update import UpdateFailed

pytestmark = [pytest.mark.nodb, pytest.mark.skipif(sys.platform != "linux", reason="bash and GNU tools")]

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
LOW = "575.57.08"
GOOD = "580.95.05"
B200 = "NVIDIA B200"
UUIDS = ["GPU-00000000-0000-0000-0000-000000000000", "GPU-11111111-1111-1111-1111-111111111111"]
PIN = images_lock.pinned(images_lock.load(images_lock.LOCK)["third_party"][images_lock.VLLM])
REC = ROOT / "deploy" / "measured" / "serving_config.rtxpro6000.json"
ENV_OUT = {"NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}
MACHINE_ID = "0123456789abcdef0123456789abcdef"
HOST_ID = hashlib.sha256(f"tb-engine-probe/1 host {MACHINE_ID}".encode()).hexdigest()[:32]


def probe_doc(**change: Any) -> dict[str, Any]:
    """An engine probe result (tb-engine-probe/1) that passed with the compatibility switch on a B200 and driver 575."""
    doc: dict[str, Any] = {
        "schema": "tb-engine-probe/1",
        "at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="seconds"),
        "host": {"arch": "x86_64", "card": B200, "driver": LOW, "compute_cap": "10.0", "gpu_index": 1,
                 "card_id": engine_probe.card_id(UUIDS[1]), "host_id": HOST_ID},
        "images": {"pinned": {"ref": PIN, "verified_in_lock": True, "digest_matches": True}},
        "tests": [
            {"name": "pinned", "status": "DRIVER", "probe": None},
            {"name": "pinned+compat", "status": "PASS", "probe": {"compat_libs": ["libcuda.so.1"], "matmul": 1.0}},
        ],
        "verdict": {"answer": "pass", "use": "pinned+compat", "image": "pinned", "pinned_engine": True,
                    "env": dict(ENV_OUT)},
    }  # fmt: skip
    doc.update(change)
    return doc


class Bench:
    """An installer's folder (install.sh, check_host.sh, gpu_profile.sh, the lock, the record; tools/ is the
    repository's) with stand-ins for docker and nvidia-smi: two cards, the second named by index."""

    def __init__(self, tmp: Path, *, driver: str = LOW, card: str = B200, mig: str = "Disabled",
                 free: int = 180000, total: int = 183359, record: bool = True, card0: str = "") -> None:  # fmt: skip
        self.tmp = tmp
        d = tmp / "deploy"
        (d / "site").mkdir(parents=True)
        for f in ("install.sh", "check_host.sh", "gpu_profile.sh", "images.lock"):
            shutil.copy(ROOT / "deploy" / f, d / f)
        if record:
            (d / "measured").mkdir()
            shutil.copy(REC, d / "measured" / REC.name)
        (tmp / "tools").symlink_to(ROOT / "tools")
        self.hostroot = tmp / "hostroot"
        (self.hostroot / "etc").mkdir(parents=True)
        (self.hostroot / "etc" / "machine-id").write_text(MACHINE_ID + "\n", encoding="utf-8")
        self.bin = tmp / "bin"
        self.bin.mkdir()
        (self.bin / "docker").write_text('#!/bin/sh\necho "$*" >> "$TB_TEST_LOG"\necho "Runtimes: nvidia runc"\n',
                                         encoding="utf-8")  # fmt: skip
        rows = [f"{card}|{u}|{driver}|{mig}|{mig}|{free}|{total}" for u in UUIDS]
        if card0:  # card 0 another model: the card named by index is the one judged, never the first by accident
            rows[0] = f"{card0}|{UUIDS[0]}|{driver}|Enabled|Enabled|1000|{total}"
        (tmp / "smi.rows").write_text("\n".join(rows) + "\n", encoding="utf-8")
        (self.bin / "nvidia-smi").write_text(SMI.replace("@ROWS@", str(tmp / "smi.rows")), encoding="utf-8")
        for exe in self.bin.iterdir():
            exe.chmod(0o755)
        self.probe = tmp / "tb-engine-probe.json"
        self.probe.write_text(json.dumps(probe_doc()), encoding="utf-8")
        (tmp / "b.tar").write_bytes(b"")

    @property
    def deploy(self) -> Path:
        return self.tmp / "deploy"

    def env(self, **extra: str) -> dict[str, str]:
        full = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "VLLM", "NVIDIA"))}
        full.update(PATH=f"{self.bin}:{os.environ['PATH']}", TB_TEST_LOG=str(self.tmp / "docker.log"),
                    TB_HOST_ROOT=str(self.hostroot), **extra)  # fmt: skip
        return full

    def install(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(self.deploy / "install.sh"), str(self.tmp / "b.tar"), *args],
                              capture_output=True, text=True, env=self.env(**extra), timeout=120, check=False)  # fmt: skip

    def real(self, *more: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return self.install("--rehearsal", "--rehearsal-real-servers", "--gpu", "rtxpro6000", "--gpu-index", "1",
                            "--engine-probe", str(self.probe), *more, **extra)  # fmt: skip


# nvidia-smi as the scripts ask it: -L, --query-gpu=<fields> for every card or for -i N, csv; rows are
# name|uuid|driver|mig now|mig pending|free|total
SMI = r"""#!/usr/bin/env python3
import sys
rows = [r.split("|") for r in open("@ROWS@").read().split("\n") if r]
a = sys.argv[1:]
if a == ["-L"]:
    print("\n".join(f"GPU {i}: {r[0]} (UUID: {r[1]})" for i, r in enumerate(rows))); sys.exit(0)
if "-i" in a:
    i = a[a.index("-i") + 1]
    if not i.isdigit() or int(i) >= len(rows):
        print(f"No devices were found"); sys.exit(6)
    rows = [rows[int(i)]]
q = next((x.split("=", 1)[1] for x in a if x.startswith("--query-gpu=")), "")
col = {"name": 0, "uuid": 1, "driver_version": 2, "mig.mode.current": 3, "mig.mode.pending": 4, "memory.free": 5,
       "memory.total": 6, "compute_cap": None, "memory.used": None}
for r in rows:
    print(", ".join("10.0" if f == "compute_cap" else "0" if col[f] is None else r[col[f]] for f in q.split(",")))
"""


def _plant(b: Bench, *, env_production: bool = True) -> dict[str, str]:
    """Everything that must open nothing without the mark: a passing probe where it would be looked for, a hand-made
    rehearsal.json, the real-servers record and compose file, deploy/.env's TB_REHEARSAL=1, and the variables."""
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    (b.deploy / "site" / rehearsal_real.RECORD).write_text('{"words": "x"}\n', encoding="utf-8")
    (b.deploy / "site" / rehearsal_real.OVERRIDE).write_text(rehearsal_real.OVERRIDE_MARK + "\n", encoding="utf-8")
    (b.tmp / "deploy" / "tb-engine-probe.json").write_text(b.probe.read_text(), encoding="utf-8")
    if env_production:
        (b.deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n", encoding="utf-8")
    return {"TB_ACCEPT_UNMEASURED_GPU": "1", "TB_REHEARSAL": "1", "TB_GPU_INDEX": "1", "TB_REHEARSAL_REAL_SERVERS": "1",
            "TB_ENGINE_PROBE": str(b.probe), "NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1",
            "TB_COMPOSE_OVERRIDE": ""}  # fmt: skip


# master's bytes (97048772e0bb), each refusal: (args, the bench's card and driver, exit code, its own lines)
DRIVER_FAIL = (f"    FAIL  NVIDIA driver {LOW} is below 580.65.06, the lowest that runs the vLLM image (CUDA 13.0.2): "
               "update the driver to the R580 line or newer")  # fmt: skip
DRIVER_DIE = "install: this GPU host cannot run the vLLM image of deploy/images.lock (FAIL above); nothing was changed"
REFUSALS: list[tuple[str, list[str], dict[str, Any], str]] = [
    ("driver", ["--mode", "gpu", "--gpu", "rtxpro6000"], {}, DRIVER_DIE),
    ("b200 whole card", ["--mode", "gpu"], {"driver": GOOD},
     "install: a B200 serves TrialBox only as two MIG instances: enable MIG, make the two instances, use deploy/platform (RUNBOOK §17)"),
    ("b200 MIG", ["--mode", "gpu"], {"driver": GOOD, "mig": "Enabled"},
     "install: this card has MIG on (shared-quota): install.sh does not serve it; use deploy/platform (RUNBOOK §17)"),
    ("b200-no-mig named", ["--mode", "gpu", "--gpu", "b200-no-mig"], {"driver": GOOD},
     "install: a B200 serves TrialBox only as two MIG instances: enable MIG, make the two instances, use deploy/platform (RUNBOOK §17)"),
    ("shared-quota named", ["--mode", "gpu", "--gpu", "shared-quota"], {"driver": GOOD},
     "install: this card has MIG on (shared-quota): install.sh does not serve it; use deploy/platform (RUNBOOK §17)"),
    ("dgpu48", ["--mode", "gpu", "--gpu", "dgpu48"], {"driver": GOOD},
     "install: dgpu48 is a DRAFT, UNMEASURED 48 GB profile: no install serves it. Its one use is the measuring run (TB_UNMEASURED_DGPU48_MEASURING_RUN=1 python3 tools/dgpu48.py measure, RUNBOOK §29)"),
    ("arm64-dgpu", ["--mode", "gpu", "--gpu", "arm64-dgpu"], {"driver": GOOD},
     "install: an Arm 64-bit host with a discrete card that is not a GB10 has no TrialBox profile (unmeasured, root review 24): install with --mode stub, or see RUNBOOK §28"),
    ("unknown profile", ["--mode", "gpu", "--gpu", "b200"], {"driver": GOOD},
     "install: --gpu must be rtxpro6000, gb10, rtx5090, rtx4090 or default"),
    # master does not refuse a named profile on another card at the profile step (finding H89-01): it goes on to
    # the vendor key, the same bytes with or without anything planted
    ("not the profile's card", ["--mode", "gpu", "--gpu", "rtxpro6000"], {"driver": GOOD}, "install: vendor public key missing"),
]  # fmt: skip


@pytest.mark.parametrize(("what", "args", "bench", "said"), REFUSALS, ids=[r[0] for r in REFUSALS])
def test_without_the_mark_the_three_refusals_are_byte_identical(
    tmp_path: Path, what: str, args: list[str], bench: dict[str, Any], said: str
) -> None:
    """THE INVARIANT (H-89, item 7)."""
    clean = Bench(tmp_path / "clean", **bench).install(*args)
    planted_bench = Bench(tmp_path / "planted", **bench)
    planted = planted_bench.install(*args, **_plant(planted_bench))
    assert clean.returncode == 1 and said in clean.stderr.splitlines()[-1], clean.stdout + clean.stderr
    if what == "driver":
        assert DRIVER_FAIL in clean.stdout.splitlines()
    got = [(r.returncode, r.stdout.replace(str(b), "<tmp>"), r.stderr.replace(str(b), "<tmp>"))
           for r, b in ((clean, tmp_path / "clean"), (planted, tmp_path / "planted"))]  # fmt: skip
    assert got[0] == got[1]
    assert "rehearsal" not in clean.stdout + clean.stderr


@pytest.mark.parametrize("opt", [["--rehearsal-real-servers"], ["--gpu-index", "1"], ["--engine-probe", "/x"]])
def test_the_new_options_without_rehearsal_are_refused_with_one_line(tmp_path: Path, opt: list[str]) -> None:
    r = Bench(tmp_path).install("--mode", "gpu", "--gpu", "rtxpro6000", *opt)
    assert r.returncode == 2 and r.stdout == "" and len(r.stderr.splitlines()) == 1
    assert opt[0] in r.stderr and "nothing was checked or written" in r.stderr
    assert not (tmp_path / "docker.log").exists()


@pytest.mark.parametrize("production", [True, False])
@pytest.mark.parametrize("opt", [["--gpu-index", "1"], ["--engine-probe", "/x"]])
def test_a_plain_rehearsal_refuses_the_card_options(tmp_path: Path, opt: list[str], production: bool) -> None:
    """On a box that records PRODUCTION: refused, exit 2, as before. H-94 (the owner's ruling 7092087958): a
    rehearsal box is a PoC box, so the options are a warning and a line of the list, ignored, and the install goes on
    (here to the driver below the minimum, kept refusal 2)."""
    b = Bench(tmp_path)
    if production:
        (b.deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    r = b.install("--rehearsal", "--mode", "gpu", "--gpu", "rtxpro6000", *opt)
    assert "go with --rehearsal-real-servers" in r.stderr
    if production:
        assert r.returncode == 2 and r.stderr.splitlines()[-1].startswith("install: --gpu-index and --engine-probe")
        return
    assert "warning (PoC box, H-94)" in r.stderr and r.returncode == 1 and r.stderr.splitlines()[-1] == DRIVER_DIE
    assert "install.sh/rrs-options-without-rrs" in (b.deploy / "site" / "poc-stops.jsonl").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------ 1. the driver
def test_under_the_mark_the_driver_is_a_loud_warn_and_the_install_goes_on(tmp_path: Path) -> None:
    b = Bench(tmp_path)
    r = b.real()
    out = r.stdout
    assert "    WARN  NVIDIA driver 575.57.08 is below 580.65.06" in out
    assert "rehearsal: driver below the minimum (found 575.57.08, minimum 580.65.06)" in out
    assert "not valid for a site" in out and "FAIL" not in out
    assert "card 1: NVIDIA B200, 180000 MiB free of 183359 (the pair needs 62574)" in out
    assert r.stderr.splitlines()[-1].startswith("install: vendor public key missing"), r.stderr  # past the GPU step


def test_the_card_named_by_index_is_the_one_judged(tmp_path: Path) -> None:
    r = Bench(tmp_path, card0="NVIDIA H100 80GB HBM3").real()
    assert "WARN  NVIDIA driver 575.57.08" in r.stdout and "FAIL" not in r.stdout, r.stdout
    assert "card 1: NVIDIA B200" in r.stdout and "H100" not in r.stdout + r.stderr


def test_the_summary_says_what_the_box_is(tmp_path: Path) -> None:
    marker = "# REHEARSAL-REAL-SERVERS (H-89): the summary says what the box is"
    start = INSTALL.index(marker)
    body = INSTALL[start : INSTALL.index("\n# ---- end of REHEARSAL-REAL-SERVERS (H-89)", start)]
    site = tmp_path / "deploy" / "site"
    site.mkdir(parents=True)
    (site / rehearsal_real.RECORD).write_text(json.dumps({"words": rehearsal_real.WORDS}), encoding="utf-8")
    for real, want in ((1, f"  REHEARSAL BOX:      {rehearsal_real.WORDS}\n"), (0, "")):
        r = subprocess.run(["bash", "-c", f'set -euo pipefail\ncd "{tmp_path}"\nREAL_SERVERS={real}\n{body}\n'],
                           capture_output=True, text=True, check=False)  # fmt: skip
        assert r.returncode == 0 and r.stdout == want


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"host": {"card": "NVIDIA H100", "driver": LOW}}, "this card is a NVIDIA B200"),
        ({"host": {"card": B200, "driver": "570.1"}}, "the probe ran on driver 570.1"),
        ({"images": {"pinned": {"ref": "vllm/vllm-openai:v0.31.0@sha256:00", "digest_matches": True}}}, "probe again"),
        ({"verdict": {"answer": "fail", "use": None, "pinned_engine": False, "env": {}}}, "did not pass"),
        ({"schema": "other"}, "not an engine probe result"),
    ],
)
def test_a_probe_of_another_card_driver_or_image_or_a_failed_one_is_refused(
    tmp_path: Path, change: dict[str, Any], why: str
) -> None:
    b = Bench(tmp_path)
    b.probe.write_text(json.dumps(probe_doc(**change)), encoding="utf-8")
    r = b.real()
    assert r.returncode == 1 and DRIVER_FAIL in r.stdout.splitlines() and why in r.stdout
    assert r.stderr.splitlines()[-1] == DRIVER_DIE


@pytest.mark.parametrize("production", [True, False])
def test_a_missing_probe_file_is_refused(tmp_path: Path, production: bool) -> None:
    """On a box that records PRODUCTION: refused before anything, as before. H-94 (ruling 7092087958): on a
    rehearsal box (a PoC box) the real servers are dropped with a warning and a line of the list, and the plain
    rehearsal goes on, to the driver below the minimum (kept refusal 2: no probe, no allowance)."""
    b = Bench(tmp_path)
    b.probe.unlink()
    if production:
        (b.deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    r = b.real()
    assert r.returncode == 1 and "--engine-probe FILE" in r.stderr
    if production:
        assert not (tmp_path / "docker.log").exists() and "PoC box" not in r.stderr
        return
    assert "warning (PoC box, H-94)" in r.stderr and r.stderr.splitlines()[-1] == DRIVER_DIE


def test_the_lock_tool_alone_grants_nothing_on_a_production_box(tmp_path: Path) -> None:
    """images_lock host with every rehearsal argument, run by hand on a PRODUCTION box: FAIL as before."""
    b = Bench(tmp_path)
    (b.deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "images_lock.py"), "host", "--arch", "x86_64", "--driver",
                        LOW, "--compute-cap", "10.0", "--rehearsal-real-servers", "--engine-probe", str(b.probe),
                        "--gpu-index", "1", "--deploy", str(b.deploy)], capture_output=True, text=True, timeout=60,
                       check=False, env=b.env())  # fmt: skip
    assert r.returncode == 1 and DRIVER_FAIL.strip() in r.stdout and "this box is PRODUCTION" in r.stdout
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "images_lock.py"), "host", "--arch", "x86_64", "--driver",
                        LOW, "--rehearsal-real-servers"], capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 2 and "needs --engine-probe, --gpu-index and --deploy" in r.stderr


def test_check_host_takes_the_rehearsal_arguments_only_whole() -> None:
    r = subprocess.run(["sh", str(ROOT / "deploy" / "check_host.sh"), "--gpu-only", "--gpu", "rtxpro6000",
                        "--rehearsal-real-servers"], capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 2 and "needs --engine-probe, --gpu-index" in r.stderr


@pytest.mark.parametrize(
    ("env_lines", "said"),
    [
        ("TB_ENV=PRODUCTION\n", "this box is PRODUCTION"),
        ("TB_ENV=VALIDATION\n", "VALIDATION (deploy/.env TB_ENV) with no rehearsal mark"),
    ],
)
def test_a_site_box_is_refused_before_the_gpu_check(tmp_path: Path, env_lines: str, said: str) -> None:
    b = Bench(tmp_path)
    (b.deploy / ".env").write_text(env_lines, encoding="utf-8")
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")  # planted by hand
    r = b.real()
    assert r.returncode == 1 and said in r.stderr and "WARN" not in r.stdout and "NVIDIA driver" not in r.stdout


def test_rehearsal_with_environment_production_is_refused(tmp_path: Path) -> None:
    r = Bench(tmp_path).real("--environment", "PRODUCTION")
    assert r.returncode == 1 and "--rehearsal makes a VALIDATION box, not PRODUCTION" in r.stderr


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (["--gpu", "b200-no-mig"], "--gpu rtxpro6000"),
        (["--tier", "large"], "--gpu rtxpro6000"),
        (["--gpu", "rtxpro6000", "--mode", "stub"], "drop --mode stub"),
        (["--gpu", "rtxpro6000", "--gpu-index", "all"], "never all"),
        (["--gpu", "rtxpro6000"], "never all"),  # no index: never the first card by accident
    ],
)
def test_the_real_servers_line_is_explicit(tmp_path: Path, args: list[str], said: str) -> None:
    b = Bench(tmp_path)
    r = b.install("--rehearsal", "--rehearsal-real-servers", "--engine-probe", str(b.probe), *args)
    assert r.returncode == 1 and said in r.stderr


def test_a_compose_override_of_the_operators_is_refused(tmp_path: Path) -> None:
    r = Bench(tmp_path).real(TB_COMPOSE_OVERRIDE="/tmp/x.yml")
    assert r.returncode == 1 and "unset TB_COMPOSE_OVERRIDE" in r.stderr


# ------------------------------------------------------------------------------------------------ 2. the card
@pytest.mark.parametrize(
    ("bench", "said"),
    [
        ({"mig": "Enabled"}, "has MIG on"),
        ({"free": 60000}, "has 60000 MiB free; the pair needs 62574 MiB (the record's 62574 MiB measured, and 0.319"),
    ],
)
def test_a_mig_card_or_one_short_of_memory_is_refused(tmp_path: Path, bench: dict[str, Any], said: str) -> None:
    r = Bench(tmp_path, **bench).real()
    assert r.returncode == 1 and said in r.stderr and "cannot carry the pair" in r.stderr


def test_a_card_index_that_is_not_there_is_refused(tmp_path: Path) -> None:
    b = Bench(tmp_path)
    r = b.install("--rehearsal", "--rehearsal-real-servers", "--gpu", "rtxpro6000", "--gpu-index", "7",
                  "--engine-probe", str(b.probe))  # fmt: skip
    assert r.returncode == 1 and "finds no card at index 7" in r.stderr


def test_the_need_is_the_larger_of_the_record_and_the_fractions() -> None:
    rec = json.loads(REC.read_text(encoding="utf-8"))
    assert rehearsal_real.record_need(rec, 97887) == (62574, 62574, 0.6)  # the record's own card: its own fractions
    # a B200: the profile is held to its 96 GB card (0.40 and 0.20 of 97,887 MiB, as fractions of 183,359 MiB)
    assert rehearsal_real.record_need(rec, 183359) == (62574, 62574, 0.319)


def test_the_compose_file_pins_one_card_by_uuid_with_the_probes_environment() -> None:
    text = rehearsal_real.override_text(UUIDS[1], dict(ENV_OUT))
    assert text.count(f'device_ids: ["{UUIDS[1]}"]') == 2 and text.count("!override") == 2
    devices = [ln for ln in text.splitlines() if "devices:" in ln]
    assert len(devices) == 2 and not any("count" in ln or "all" in ln for ln in devices)
    assert rehearsal_real.OVERRIDE_MARK in text.splitlines()
    for k, v in ENV_OUT.items():
        assert text.count(f'      {k}: "{v}"') == 2
    with pytest.raises(ValueError):
        rehearsal_real.override_text("all", {})
    with pytest.raises(ValueError):
        rehearsal_real.override_text(UUIDS[1], {"A": "1\nservices:"})


# ------------------------------------------------------------------------------------------------ 3 and 5: the record
def _marked(b: Bench) -> None:
    (b.deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")


def test_write_records_the_three_facts_and_the_probe_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    _marked(b)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, doc = rehearsal_real.write(b.deploy, "1", b.probe, b.deploy / "measured" / REC.name)
    assert problems == []
    assert doc["words"] == rehearsal_real.WORDS == ("rehearsal: driver below the minimum, not this profile's card, "
                                                    "not valid for a site")  # fmt: skip
    assert doc["valid_for_a_site"] is False
    assert doc["driver"] == {"found": LOW, "minimum": "580.65.06", "below_minimum": True}
    assert doc["card"]["found"] == B200 and "RTX PRO 6000" in doc["card"]["profile_card"]
    assert doc["engine_probe"]["env"] == ENV_OUT and len(doc["engine_probe"]["sha256"]) == 64
    assert json.loads((b.deploy / "site" / rehearsal_real.RECORD).read_text()) == doc
    assert (
        UUIDS[1] in (b.deploy / "site" / rehearsal_real.OVERRIDE).read_text()
        and UUIDS[0] not in (b.deploy / "site" / rehearsal_real.OVERRIDE).read_text()
    )


def test_write_without_the_mark_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, _ = rehearsal_real.write(b.deploy, "1", b.probe, b.deploy / "measured" / REC.name)
    assert problems and "no rehearsal mark" in problems[-1]
    assert not (b.deploy / "site" / rehearsal_real.RECORD).exists()
    assert not (b.deploy / "site" / rehearsal_real.OVERRIDE).exists()


def test_with_a_good_driver_no_environment_goes_to_the_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path, driver=GOOD)
    _marked(b)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, doc = rehearsal_real.write(b.deploy, "1", b.probe, b.deploy / "measured" / REC.name)
    assert (
        problems == []
        and doc["engine_probe"]["env"] == {}
        and "    environment:" not in (b.deploy / "site" / rehearsal_real.OVERRIDE).read_text()
    )
    assert doc["words"] == "rehearsal: not this profile's card, not valid for a site"


RECORD_STEP_START = 'case "$MODE:$GPU" in gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)'


def _record_step(tmp: Path, *, real: int, record: str | None, env_lines: str, unmeasured: str = "") -> Any:
    """install.sh's record step as it stands, with a stand-in for the record's docker check (passes when the record
    names an RTX PRO 6000, as tools/serving_config.py measured does)."""
    start = INSTALL.index(RECORD_STEP_START, INSTALL.index("# D-112, D-124: a pair profile starts only") - 200)
    body = INSTALL[start : INSTALL.index("\nesac\n", start) + 6]
    rh = INSTALL.index("rehearsal_only() {")
    rh_fn = INSTALL[rh : INSTALL.index("\n}\n", rh) + 3]
    d = tmp / "deploy"
    (d / "site").mkdir(parents=True, exist_ok=True)
    (d / "measured").mkdir(exist_ok=True)
    if record is not None:
        (d / "measured" / REC.name).write_text(json.dumps({"card": {"name": record}}), encoding="utf-8")
    (d / ".env").write_text(env_lines, encoding="utf-8")
    script = (
        f'set -euo pipefail\nROOT="{tmp}"\ncd "$ROOT"\nMODE=gpu\nGPU=rtxpro6000\nTIER=""\nREAL_SERVERS={real}\n'
        'die() { echo "install: $*" >&2; exit 1; }\ntree_args() { TREE_D=(); }\nIMAGE_PY=x\n'
        + stop_prelude(deploy='"$ROOT/deploy"')
        + 'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'TB_ENV_SITE="$(envget TB_ENV)"\n'
        "docker() { grep -q 'RTX PRO 6000' \"$ROOT/deploy/measured/serving_config.rtxpro6000.json\"; }\n"
        f"{rh_fn}{body}\necho done\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    if unmeasured:
        env["TB_ACCEPT_UNMEASURED_GPU"] = unmeasured
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)


@pytest.mark.parametrize(
    ("record", "unmeasured", "rc", "said"),
    [
        (None, "", 1, "install: the rtxpro6000 profile has no measurement on its own card (deploy/site/ or deploy/measured/serving_config.rtxpro6000.json). For a first trial boot re-run as a rehearsal box (TB_COMPOSE_OVERRIDE= deploy/install.sh <bundle> --gpu rtxpro6000 --rehearsal), then capture the record (RUNBOOK §1)"),
        (None, "1", 1, "install: TB_ACCEPT_UNMEASURED_GPU=1 (an unmeasured card's trial boot): only on a rehearsal box (TB_REHEARSAL=1 on TEST, or on VALIDATION with deploy/site/rehearsal.json: deploy/install.sh --rehearsal); this box is PRODUCTION"),
        ("NVIDIA B200", "1", 1, "install: deploy/measured/serving_config.rtxpro6000.json is not a measurement of the rtxpro6000 profile on its own card (see above)"),
        ("NVIDIA RTX PRO 6000 Blackwell Server Edition", "1", 0, "done"),
    ],
)  # fmt: skip
def test_without_the_mark_the_record_step_is_as_before(
    tmp_path: Path, record: str | None, unmeasured: str, rc: int, said: str
) -> None:
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    (tmp_path / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    r = _record_step(tmp_path, real=0, record=record, env_lines="TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n",
                     unmeasured=unmeasured)  # fmt: skip
    assert r.returncode == rc and (r.stderr if rc else r.stdout).splitlines()[-1] == said, r.stdout + r.stderr
    assert "rehearsal: " not in r.stderr


def test_under_the_mark_the_record_of_another_card_says_so(tmp_path: Path) -> None:
    site = tmp_path / "deploy" / "site"
    site.mkdir(parents=True)
    (site / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    (site / rehearsal_real.RECORD).write_text(json.dumps({"words": rehearsal_real.WORDS, "card": {
        "profile_card": "NVIDIA RTX PRO 6000 Blackwell Server Edition", "index": 1, "found": B200}}), encoding="utf-8")  # fmt: skip
    r = _record_step(tmp_path, real=1, record="NVIDIA RTX PRO 6000 Blackwell Server Edition",
                     env_lines="TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert f"install: warning: {rehearsal_real.WORDS}: the record " in r.stderr and "card 1, NVIDIA B200" in r.stderr
    r = _record_step(tmp_path, real=1, record="NVIDIA RTX PRO 6000", env_lines="TB_ENV=PRODUCTION\n")
    assert r.returncode == 1 and "only on a rehearsal box" in r.stderr


# ------------------------------------------------------------------------------------------------ 6. never PRODUCTION
WHOLE = "TB_ENV=VALIDATION\nTB_REHEARSAL=1\n"


def _box(tmp: Path, env_lines: str, *, mark: bool, record: bool, override: bool = False) -> Path:
    d = tmp / "deploy"
    (d / "site").mkdir(parents=True, exist_ok=True)
    if mark:
        (d / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    if record:
        (d / "site" / rehearsal_real.RECORD).write_text(json.dumps({"words": rehearsal_real.WORDS}), encoding="utf-8")
    if override:
        f = tmp / "elsewhere.yml"
        f.write_text(rehearsal_real.OVERRIDE_MARK + "\n", encoding="utf-8")
        env_lines += f"COMPOSE_FILE=/x/docker-compose.yml:{f}\n"
    (d / ".env").write_text(env_lines, encoding="utf-8")
    return d


class _Box:
    def __init__(self, deploy: Path) -> None:
        self.deploy = deploy
        self.env = rehearsal_real.env_file(deploy / ".env")


@pytest.mark.parametrize(
    ("env_lines", "mark", "record", "override", "said"),
    [
        ("TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n", True, True, False, "TB_ENV=PRODUCTION"),  # TB_ENV edited by hand
        ("TB_ENV=PRODUCTION\n", True, False, False, "TB_ENV=PRODUCTION"),  # a stand-ins rehearsal box, edited
        ("TB_ENV=PRODUCTION\n", False, True, False, "TB_ENV=PRODUCTION"),  # the mark and the flag removed by hand
        ("TB_ENV=VALIDATION\n", False, True, False, "no longer a whole rehearsal box"),
        ("TB_ENV=TEST\nTB_REHEARSAL=1\n", True, True, False, "no longer a whole rehearsal box"),
        ("TB_ENV=VALIDATION\n", False, False, True, "no longer a whole rehearsal box"),  # the record removed too
    ],
)
def test_the_start_refuses_a_rehearsal_box_turned_production(
    tmp_path: Path, env_lines: str, mark: bool, record: bool, override: bool, said: str
) -> None:
    deploy = _box(tmp_path, env_lines, mark=mark, record=record, override=override)
    with pytest.raises(UpdateFailed, match="refused to start") as exc:
        prestart.run(deploy, _Box(deploy))  # type: ignore[arg-type]
    assert said in str(exc.value)
    with pytest.raises(UpdateFailed, match="refused to start"):
        prestart.run_db(deploy, _Box(deploy))  # type: ignore[arg-type]
    chk = doctor.check_rehearsal(doctor.DoctorInputs(env=rehearsal_real.env_file(deploy / ".env"), deploy=deploy))
    assert chk.status == "FAIL"


def test_a_whole_real_servers_rehearsal_box_starts_and_says_so(tmp_path: Path) -> None:
    deploy = _box(tmp_path, WHOLE, mark=True, record=True)
    assert rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env")) == ""
    chk = doctor.check_rehearsal(doctor.DoctorInputs(env=rehearsal_real.env_file(deploy / ".env"), deploy=deploy))
    assert chk.status == "WARN" and rehearsal_real.WORDS in chk.detail


def test_a_site_box_and_a_stand_ins_rehearsal_box_start_as_before(tmp_path: Path) -> None:
    for name, env_lines, mark in (
        ("site", "TB_ENV=PRODUCTION\n", False),
        ("rh", WHOLE, True),
        ("t", "TB_ENV=TEST\n", True),
    ):
        deploy = _box(tmp_path / name, env_lines, mark=mark, record=False)
        assert rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env")) == ""


def test_an_install_without_the_options_refuses_a_box_that_ran_the_real_servers(tmp_path: Path) -> None:
    marker = "# REHEARSAL-REAL-SERVERS (H-89): after the mark"
    start = INSTALL.index(marker)
    body = INSTALL[start : INSTALL.index("\n# ---- end of REHEARSAL-REAL-SERVERS (H-89)", start)]
    for leftover in (rehearsal_real.RECORD, rehearsal_real.OVERRIDE):
        d = tmp_path / leftover / "deploy" / "site"
        d.mkdir(parents=True)
        (d / leftover).write_text("{}\n", encoding="utf-8")
        script = (f'set -euo pipefail\ncd "{d.parent.parent}"\nREAL_SERVERS=0\ndie() {{ echo "install: $*" >&2; exit 1; }}\n'
                  + stop_prelude(deploy='"$PWD/deploy"') + f"{body}\n")  # fmt: skip
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        assert r.returncode == 1 and "ran the real model servers as a rehearsal" in r.stderr


# ------------------------------------------------------------------------------- the review's M1, M2 and L1 (round 1)
def _allow(b: Bench, monkeypatch: pytest.MonkeyPatch, doc: dict[str, Any] | None = None) -> list[str]:
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    if doc is not None:
        b.probe.write_text(json.dumps(doc), encoding="utf-8")
    return rehearsal_real.driver_allowance(b.probe, "1", b.deploy)[0]


def _verdict(**change: Any) -> dict[str, Any]:
    v = dict(probe_doc()["verdict"])
    v.update(change)
    return v


LIBS_PASS = [{"name": "pinned", "status": "DRIVER", "probe": None}, {"name": "pinned+compat", "status": "FAIL"},
             {"name": "pinned+libs", "status": "PASS", "probe": {"compat_libs": ["libcuda.so.1"]}}]  # fmt: skip


def test_a_passing_probe_of_this_card_and_host_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _allow(Bench(tmp_path), monkeypatch) == []
    libs = probe_doc(tests=LIBS_PASS, verdict=_verdict(use="pinned+libs", env={
        "NVIDIA_DISABLE_REQUIRE": "1", "LD_LIBRARY_PATH": "/usr/local/cuda/compat:/usr/local/nvidia/lib64"}))  # fmt: skip
    assert _allow(Bench(tmp_path / "libs"), monkeypatch, libs) == []


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"verdict": _verdict(env={**ENV_OUT, "LD_PRELOAD": "/tmp/x.so"})}, "is not its form's"),  # M1
        ({"verdict": _verdict(env={"NVIDIA_DISABLE_REQUIRE": "1"})}, "is not its form's"),
        ({"verdict": _verdict(env={**ENV_OUT, "VLLM_ENABLE_CUDA_COMPATIBILITY": "0"})}, "is not its form's"),
        ({"tests": LIBS_PASS, "verdict": _verdict(use="pinned+libs", env={
            "NVIDIA_DISABLE_REQUIRE": "1", "LD_LIBRARY_PATH": "/tmp/evil:/usr/local/cuda/compat"})}, "image's own library folders"),
        ({"images": {"pinned": {"ref": PIN, "verified_in_lock": True}}}, "digest matched"),  # M2: missing is refused
        ({"at": "2019-01-01T00:00:00+00:00"}, "older than 7 days"),
        ({"at": "yesterday"}, "older than 7 days"),
        ({"host": {**probe_doc()["host"], "card_id": engine_probe.card_id(UUIDS[0])}}, "another card than card 1"),
        ({"host": {**probe_doc()["host"], "card_id": None}}, "another card than card 1"),
        ({"host": {**probe_doc()["host"], "host_id": "f" * 32}}, "another host"),
    ],
)  # fmt: skip
def test_the_probe_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], said: str
) -> None:
    problems = _allow(Bench(tmp_path), monkeypatch, probe_doc(**change))
    assert any(said in p for p in problems), problems


def test_a_probe_with_ld_preload_never_reaches_the_compose_file(tmp_path: Path) -> None:
    b = Bench(tmp_path)
    b.probe.write_text(json.dumps(probe_doc(verdict=_verdict(env={**ENV_OUT, "LD_PRELOAD": "/tmp/x.so"}))))
    r = b.real()
    assert r.returncode == 1 and DRIVER_FAIL in r.stdout.splitlines() and "is not its form's" in r.stdout
    assert not (b.deploy / "site" / rehearsal_real.OVERRIDE).exists()


def test_a_probe_without_this_hosts_machine_id_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    (b.hostroot / "etc" / "machine-id").unlink()
    assert any("another host" in p for p in _allow(b, monkeypatch))


def test_a_probe_file_others_may_write_or_own_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    b.probe.chmod(0o664)
    assert any("writable by group or others" in p for p in _allow(b, monkeypatch))
    b.probe.chmod(0o644)
    if os.geteuid() == 0:
        os.chown(b.probe, 4242, 4242)
    else:
        monkeypatch.setattr(os, "getuid", lambda: 4242)
    assert any("is owned by uid" in p for p in _allow(b, monkeypatch))


@pytest.mark.parametrize(
    "lines",
    ["TB_ENV=VALIDATION\nTB_REHEARSAL=1\nexport TB_ENV=PRODUCTION\n", "TB_ENV=PRODUCTION # site\nTB_REHEARSAL=1\n"],
)
def test_the_start_check_reads_env_as_compose_does(tmp_path: Path, lines: str) -> None:
    deploy = _box(tmp_path, lines, mark=True, record=False)
    assert "TB_ENV=PRODUCTION" in rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env"))


def test_the_engine_probe_records_the_cards_and_hosts_one_way_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "machine-id").write_text(MACHINE_ID, encoding="utf-8")
    monkeypatch.setenv("TB_HOST_ROOT", str(tmp_path))
    asked: list[list[str]] = []

    def run(cmd: list[str], _t: int) -> tuple[int, str, str]:
        asked.append(cmd)
        if "--query-gpu=uuid" in cmd:
            return 0, UUIDS[1] + "\n", ""
        if "--query-gpu=name,memory.total,driver_version,compute_cap" in cmd:
            return 0, f"{B200}, 183359, {LOW}, 10.0\n", ""
        return 0, "", ""

    facts = engine_probe.host_facts(run, "1")
    assert facts["card_id"] == engine_probe.card_id(UUIDS[1]) and facts["host_id"] == HOST_ID
    assert UUIDS[1] not in json.dumps(facts) and MACHINE_ID not in json.dumps(facts)
    assert all(c[1:3] == ["-i", "1"] for c in asked if c[0] == "nvidia-smi")
    assert "card_id" not in engine_probe.host_facts(run)  # without --gpu-index: as before


# ------------------------------------------------------------------------------- the boot path and the banner (H1, L5)
GUARD = ROOT / "deploy" / "settings_guard.sh"
GUARD_REFUSAL = ("TrialBox REFUSED to start on the example settings: {d}/settings.yaml is this site's, but compose would "
                 "mount ./settings.example.yaml (TB_SETTINGS_FILE). Add TB_SETTINGS_FILE=./settings.yaml to {d}/.env (or "
                 "run deploy/install.sh again, which writes it), then start again\n")  # fmt: skip


def _guard(deploy: Path, no_python: bool = False) -> subprocess.CompletedProcess[str]:
    (deploy.parent / "tools").symlink_to(ROOT / "tools") if not (deploy.parent / "tools").exists() else None
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env["PYTHONPATH"] = str(deploy.parent)
    if no_python:  # a python3 that fails: proves the guard does not ask it on a box without a sign
        stub = deploy.parent / "nopy"
        stub.mkdir()
        (stub / "python3").write_text("#!/bin/sh\necho python3 was asked >&2\nexit 9\n", encoding="utf-8")
        (stub / "python3").chmod(0o755)
        env["PATH"] = f"{stub}:{env['PATH']}"
    return subprocess.run(["sh", str(GUARD), str(deploy)], capture_output=True, text=True, env=env, check=False)


def test_without_a_sign_the_boot_guard_is_as_before(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    r = _guard(deploy, no_python=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    (deploy / "settings.yaml").write_text("site: {}\n", encoding="utf-8")
    r = _guard(deploy)
    assert (r.returncode, r.stdout, r.stderr) == (1, "", GUARD_REFUSAL.format(d=deploy))


@pytest.mark.parametrize(
    ("env_lines", "mark", "record"),
    [("TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n", True, True), ("TB_ENV=PRODUCTION\n", True, False),
     ("TB_ENV=PRODUCTION\n", False, True), ("export TB_ENV=PRODUCTION\nTB_REHEARSAL_REAL_SERVERS=1\n", False, False)],
)  # fmt: skip
def test_a_rehearsal_box_turned_production_is_refused_at_boot(
    tmp_path: Path, env_lines: str, mark: bool, record: bool
) -> None:
    r = _guard(_box(tmp_path, env_lines, mark=mark, record=record))
    assert r.returncode == 1 and "TrialBox REFUSED to start: this box carries a rehearsal sign" in r.stderr
    assert "TB_ENV=PRODUCTION" in r.stderr


def test_a_whole_rehearsal_box_boots(tmp_path: Path) -> None:
    r = _guard(_box(tmp_path, WHOLE + "TB_REHEARSAL_REAL_SERVERS=1\n", mark=True, record=True))
    assert (r.returncode, r.stderr) == (0, "")


def test_the_console_banner_says_the_sentence() -> None:
    from console.app import environment_banner

    real = {"TB_ENV": "VALIDATION", "TB_REHEARSAL": "1", "TB_REHEARSAL_REAL_SERVERS": "1"}
    assert environment_banner(real) == f"VALIDATION REHEARSAL: {rehearsal_real.WORDS}"
    assert environment_banner({"TB_ENV": "VALIDATION", "TB_REHEARSAL": "1"}) == "VALIDATION REHEARSAL"
    assert environment_banner({**real, "TB_ENV": "PRODUCTION"}) == "PRODUCTION"
    assert environment_banner({"TB_ENV": "VALIDATION", "TB_REHEARSAL_REAL_SERVERS": "1"}) == "VALIDATION"


# ------------------------------------------------------------------------------- the review's re-read (round 2): L1-L4
def test_a_renamed_override_named_by_compose_file_is_refused_at_boot(tmp_path: Path) -> None:
    """L1: no mark file, no record, no name in deploy/.env: only a file COMPOSE_FILE names carries the mark."""
    deploy = _box(tmp_path, "TB_ENV=PRODUCTION\n", mark=False, record=False, override=True)
    assert rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env"))
    r = _guard(deploy)
    assert r.returncode == 1 and "TrialBox REFUSED to start: this box carries a rehearsal sign" in r.stderr


def test_a_compose_file_without_the_mark_is_no_sign_at_boot(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (tmp_path / "plain.yml").write_text("services: {}\n", encoding="utf-8")
    (deploy / ".env").write_text(
        f"TB_ENV=PRODUCTION\nCOMPOSE_FILE=/x/base.yml:{tmp_path / 'plain.yml'}\n", encoding="utf-8"
    )
    r = _guard(deploy, no_python=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_a_probe_in_a_folder_others_may_write_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L2: the folder too: anyone who may write it could swap the file."""
    b = Bench(tmp_path)
    b.probe.parent.chmod(0o777)
    try:
        assert any("its folder" in p and "writable by group or others" in p for p in _allow(b, monkeypatch))
    finally:
        b.probe.parent.chmod(0o755)


def test_a_probe_given_as_a_link_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(b.probe)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems = rehearsal_real.driver_allowance(link, "1", b.deploy)[0]
    assert any("is a link" in p for p in problems)


def test_the_probe_is_read_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    opened: list[str] = []
    real_open = os.open

    def counting(path: Any, *a: Any, **k: Any) -> int:
        if str(path) == str(b.probe):
            opened.append(str(path))
        return real_open(path, *a, **k)

    assert _allow(b, monkeypatch) == []
    monkeypatch.setattr(os, "open", counting)
    opened.clear()
    problems, rec = rehearsal_real.driver_allowance(b.probe, "1", b.deploy)
    assert problems == [] and opened == [str(b.probe)]
    assert rec["probe_sha256"] == hashlib.sha256(b.probe.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "lib",
    ["/usr/local/cuda/compat:/models/x", "/usr/local/cuda/compat:/data/lib", "/usr/local/cuda/compat:/usr/lib/../../models",
     "/usr/local/cuda/compat:/usr/lib/x\n"],
)  # fmt: skip
def test_after_the_compatibility_folder_only_the_images_own_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lib: str
) -> None:
    """L3: never a mounted folder (the host's models folder is mounted at /models)."""
    doc = probe_doc(
        tests=LIBS_PASS,
        verdict=_verdict(use="pinned+libs", env={"NVIDIA_DISABLE_REQUIRE": "1", "LD_LIBRARY_PATH": lib}),
    )
    assert any("image's own library folders" in p for p in _allow(Bench(tmp_path), monkeypatch, doc))


def test_a_probe_without_a_host_id_is_refused_on_a_host_that_has_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4 (the surviving mutant): the host has /etc/machine-id, the probe names no host."""
    host = {k: v for k, v in probe_doc()["host"].items() if k != "host_id"}
    assert any("another host" in p for p in _allow(Bench(tmp_path), monkeypatch, probe_doc(host=host)))


# ------------------------------------------------------------------------------- the last look (round 3): R1, R2
PAGE = ROOT / "docs" / "handover" / "rehearsal-real-servers-h89-2026-11-22.md"
PROBE_DIR = "/var/lib/trialbox/rehearsal"


def _page_steps() -> list[str]:
    """The bench's commands as the page writes them, in order (continuation lines joined)."""
    text = PAGE.read_text(encoding="utf-8")
    block = text[text.index("### The bench's command lines, in order") : text.index("### What changes for a site")]
    out: list[str] = []
    for line in block.splitlines():
        if not line.startswith("       ") or not line.strip():
            continue
        cmd = line.strip()
        if out and out[-1].endswith("\\"):
            out[-1] = out[-1][:-1].rstrip() + " " + cmd
        else:
            out.append(cmd)
    return out


def test_the_pages_own_steps_pass_in_order(tmp_path: Path) -> None:
    """R1: the probe is written as root into a folder only root may write; the install, as root, takes it. Run here
    with the folder moved under tmp_path and without sudo (as this test's user, who is then the installer)."""
    steps = _page_steps()
    mkdir = next(i for i, c in enumerate(steps) if c.startswith(f"sudo install -d -m 0700 -o root -g root {PROBE_DIR}"))
    probe = next(i for i, c in enumerate(steps) if c.startswith("sudo python3 tools/engine_probe.py run --gpu-index 1"))
    inst = next(i for i, c in enumerate(steps) if c.startswith("sudo deploy/install.sh"))
    assert mkdir < probe < inst
    out = f"{PROBE_DIR}/engine-probe.json"
    assert f"--out {out}" in steps[probe] and f"--engine-probe {out} " in steps[inst] + " "
    assert "~" not in " ".join(steps[mkdir : inst + 1])
    b = Bench(tmp_path)
    folder = tmp_path / "var-lib-trialbox-rehearsal"
    subprocess.run(["install", "-d", "-m", "0700", str(folder)], check=True)  # step 2a, without -o root as a user
    (folder / "engine-probe.json").write_text(json.dumps(probe_doc()), encoding="utf-8")  # step 2b's file (umask)
    args = steps[inst].replace(out, str(folder / "engine-probe.json")).split()[3:]  # past sudo, the script, the bundle
    r = b.install(*args)
    assert "WARN  NVIDIA driver 575.57.08 is below 580.65.06" in r.stdout and "FAIL" not in r.stdout, r.stdout
    assert r.stderr.splitlines()[-1].startswith("install: vendor public key missing"), r.stderr


def test_the_invoking_users_uid_is_never_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))
    monkeypatch.setattr(os, "getuid", lambda: 4242 if os.geteuid() != 0 else 0)
    if os.geteuid() == 0:
        os.chown(b.probe, 1000, 1000)
    assert any("is owned by uid" in p for p in _allow(b, monkeypatch))


@pytest.mark.parametrize("line", ["COMPOSE_FILE=/x/base.yml # note\n", "COMPOSE_FILE=/x/base.yml\r\n"])
def test_a_compose_file_line_the_guard_cannot_read_is_refused_at_boot(tmp_path: Path, line: str) -> None:
    """R2: fail closed, whatever else the box holds."""
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n" + line, encoding="utf-8")
    r = _guard(deploy, no_python=True)
    assert r.returncode == 1 and "COMPOSE_FILE in" in r.stderr and "python3 was asked" not in r.stderr


def test_an_override_with_carriage_returns_is_a_sign_at_boot(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    f = tmp_path / "elsewhere.yml"
    f.write_bytes((rehearsal_real.OVERRIDE_MARK + "\r\nservices: {}\r\n").encode())
    (deploy / ".env").write_text(f"TB_ENV=PRODUCTION\nCOMPOSE_FILE=/x/base.yml:{f}\n", encoding="utf-8")
    r = _guard(deploy)
    assert r.returncode == 1 and "this box carries a rehearsal sign" in r.stderr


# ------------------------------------------------------------------------------- the shipped rehearsal's order of writes
def _start_ok(deploy: Path) -> None:
    assert rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env")) == ""
    prestart._rehearsal_guard(deploy, _Box(deploy))  # type: ignore[arg-type]
    r = _guard(deploy)
    assert (r.returncode, r.stderr) == (0, ""), r.stderr


def _start_refused(deploy: Path) -> None:
    assert "PRODUCTION" in rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env"))
    with pytest.raises(UpdateFailed, match="refused to start"):
        prestart._rehearsal_guard(deploy, _Box(deploy))  # type: ignore[arg-type]
    r = _guard(deploy)
    assert r.returncode == 1 and "TrialBox REFUSED to start: this box carries a rehearsal sign" in r.stderr


@pytest.mark.parametrize("real", [False, True])
def test_the_install_order_of_a_rehearsal_box_is_never_refused_and_a_hand_edit_is(tmp_path: Path, real: bool) -> None:
    """The red rehearse jobs of #1370: install.sh --rehearsal writes the mark (and, with real servers, the record),
    then loads the bundle, whose update path runs the boot guard before the settings step writes TB_ENV; the vendor's
    deploy/.env then holds only TB_TZ and TB_TLS_HOSTNAME. Then the settings, then a second install over the box."""
    deploy = tmp_path / "deploy"
    site = deploy / "site"
    site.mkdir(parents=True)
    (deploy / ".env").write_text("TB_TZ=Asia/Taipei\nTB_TLS_HOSTNAME=box.invalid\n", encoding="utf-8")  # vendor cfg
    (site / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")  # REHEARSAL, before the load
    if real:
        (site / rehearsal_real.RECORD).write_text(json.dumps({"words": rehearsal_real.WORDS}), encoding="utf-8")
        (site / rehearsal_real.OVERRIDE).write_text(rehearsal_real.OVERRIDE_MARK + "\n", encoding="utf-8")
    _start_ok(deploy)  # the bundle load (apply_update.sh: settings_guard.sh), the first install
    (deploy / "settings.yaml").write_text("site: {}\n", encoding="utf-8")  # the settings step
    with (deploy / ".env").open("a", encoding="utf-8") as fh:
        fh.write("TB_SETTINGS_FILE=./settings.yaml\nTB_ENV=VALIDATION\nTB_REHEARSAL=1\n")
        if real:
            fh.write("TB_REHEARSAL_REAL_SERVERS=1\n")
    _start_ok(deploy)  # the install's own start (pre-start), then the boot
    (site / rehearsal_real.COMPLETE).write_text('{"rehearsal_install_complete": true}\n', encoding="utf-8")  # its end
    _start_ok(deploy)  # a second install over it (the rehearsal's re-run), its bundle load and start
    text = (deploy / ".env").read_text(encoding="utf-8")
    (deploy / ".env").write_text(text.replace("TB_ENV=VALIDATION", "TB_ENV=PRODUCTION"), encoding="utf-8")
    _start_refused(deploy)  # a hand edit to PRODUCTION: refused at boot and at start
    (deploy / ".env").write_text(text.replace("TB_ENV=VALIDATION\n", ""), encoding="utf-8")
    _start_refused(deploy)  # TB_ENV removed by hand after the install completed: PRODUCTION (7087751791), refused


@pytest.mark.parametrize("env_text", [None, "", "TB_TZ=Asia/Taipei\n"])
@pytest.mark.parametrize("real", [False, True])
def test_no_env_file_or_no_tb_env_on_a_signed_box_is_a_rehearsal(
    tmp_path: Path, env_text: str | None, real: bool
) -> None:
    """The ruling (7087297960): a fresh rehearsal box's bundle load has no deploy/.env, or one without TB_ENV."""
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    if real:
        (deploy / "site" / rehearsal_real.RECORD).write_text("{}\n", encoding="utf-8")
    if env_text is not None:
        (deploy / ".env").write_text(env_text, encoding="utf-8")
    _start_ok(deploy)  # the load (the boot guard), the start (pre-start)
    (deploy / ".env").write_text((env_text or "") + "TB_ENV=PRODUCTION\n", encoding="utf-8")
    _start_refused(deploy)  # an explicit PRODUCTION: refused at load, at start and at boot


# ------------------------------------------------------------------------------- round 5: part 1 (7087751791)
def test_a_missing_tb_env_after_the_install_completed_is_refused(tmp_path: Path) -> None:
    """(a): the completion mark is written by install.sh alone, at its end; after it a missing TB_ENV is PRODUCTION."""
    deploy = _box(tmp_path, "TB_TZ=Asia/Taipei\n", mark=True, record=False)
    _start_ok(deploy)  # an install in progress
    (deploy / "site" / rehearsal_real.COMPLETE).write_text("{}\n", encoding="utf-8")
    _start_refused(deploy)  # at start and at boot
    assert rehearsal_real.COMPLETE in rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env"))
    assert "deploy/site/rehearsal-install-complete.json" in INSTALL and INSTALL.count(rehearsal_real.COMPLETE) == 1


@pytest.mark.parametrize("complete", [False, True])
def test_the_real_servers_checks_run_without_tb_env(tmp_path: Path, complete: bool) -> None:
    """(b): a box with the real-servers record and no TB_ENV still needs the mark (and, installed, a whole box)."""
    deploy = _box(tmp_path, "TB_TZ=Asia/Taipei\n", mark=False, record=True)
    if complete:
        (deploy / "site" / rehearsal_real.COMPLETE).write_text("{}\n", encoding="utf-8")
    why = rehearsal_real.start_refusal(deploy, rehearsal_real.env_file(deploy / ".env"))
    assert why and ("mark missing" in why or "PRODUCTION" in why)
    r = _guard(deploy)
    assert r.returncode == 1


def test_the_installer_writes_the_completion_mark_only_after_a_clean_end() -> None:
    tail = INSTALL[INSTALL.index("# REHEARSAL-REAL-SERVERS (H-89): a rehearsal box's install is complete") :]
    assert 'if [ "$REHEARSAL" = 1 ] && [ "${#FAILS[@]}" -eq 0 ]; then' in tail
    assert tail.index(rehearsal_real.COMPLETE) < tail.index('if [ "${#FAILS[@]}" -gt 0 ]; then')


# ------------------------------------------------------------------------------- round 5: part 2, every profile
@pytest.mark.parametrize(
    ("profile", "need"),
    [("rtxpro6000", "62574"), ("rtx5090", "26404")],
)
def test_each_opened_profile_goes_past_the_gpu_step_held_to_its_own_card(
    tmp_path: Path, profile: str, need: str
) -> None:
    b = Bench(tmp_path)
    r = b.install("--rehearsal", "--rehearsal-real-servers", "--gpu", profile, "--gpu-index", "1",
                  "--engine-probe", str(b.probe))  # fmt: skip
    assert f"card 1: NVIDIA B200, 180000 MiB free of 183359 (the pair needs {need})" in r.stdout, r.stdout + r.stderr
    assert "WARN  NVIDIA driver 575.57.08" in r.stdout and "FAIL" not in r.stdout
    assert r.stderr.splitlines()[-1].startswith("install: vendor public key missing"), r.stderr


@pytest.mark.parametrize(
    ("profile", "budget", "keys"),
    [("rtxpro6000", 97887, {"JUDGE_GPU_MEM_UTIL": 0.40, "VERIFIER_GPU_MEM_UTIL": 0.20}),
     ("rtx5090", 32607, {"JUDGE_GPU_MEM_UTIL": 0.81, "VERIFIER_GPU_MEM_UTIL": 0.81})],
)  # fmt: skip
def test_each_profiles_cap_is_its_own_cards_memory(profile: str, budget: int, keys: dict[str, float]) -> None:
    """The compose file's own utilisations, scaled by the ballast tool's rule: never more MiB than on its own card."""
    got = rehearsal_real.caps(profile, 183359)
    assert set(got) == set(keys)
    for k, u in keys.items():
        assert got[k] * 183359 <= u * budget < (got[k] + 0.001) * 183359
    assert rehearsal_real.caps(profile, budget) == keys  # on its own card: unchanged


def test_write_records_the_profile_and_its_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    b = Bench(tmp_path)
    _marked(b)
    monkeypatch.setenv("PATH", b.env()["PATH"])
    monkeypatch.setenv("TB_HOST_ROOT", str(b.hostroot))
    problems, doc = rehearsal_real.write(b.deploy, "1", b.probe, None, "rtx5090")
    assert (
        problems == [] and doc["card"]["profile"] == "rtx5090" and doc["caps"] == rehearsal_real.caps("rtx5090", 183359)
    )
    assert (
        doc["serving_record"] is None and "5090" in doc["card"]["profile_card"] and doc["words"] == rehearsal_real.WORDS
    )


def test_the_install_writes_the_caps_into_deploy_env(tmp_path: Path) -> None:
    marker = "# REHEARSAL-REAL-SERVERS (H-89): deploy/.env says the box ran the real servers"
    start = INSTALL.index(marker)
    body = INSTALL[start : INSTALL.index("\n# ---- end of REHEARSAL-REAL-SERVERS (H-89)", start)]
    site = tmp_path / "deploy" / "site"
    site.mkdir(parents=True)
    (tmp_path / "deploy" / ".env").write_text("TB_ENV=VALIDATION\nJUDGE_GPU_MEM_UTIL=0.9\n", encoding="utf-8")
    (site / rehearsal_real.RECORD).write_text(
        json.dumps({"caps": {"JUDGE_GPU_MEM_UTIL": 0.144, "VERIFIER_GPU_MEM_UTIL": 0.144}})
    )
    script = (
        f'set -euo pipefail\ncd "{tmp_path}"\nREAL_SERVERS=1\ndie() {{ echo "install: $*" >&2; exit 1; }}\n{body}\n'
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    lines = (tmp_path / "deploy" / ".env").read_text().splitlines()
    assert r.returncode == 0, r.stderr
    assert (
        "JUDGE_GPU_MEM_UTIL=0.144" in lines
        and "VERIFIER_GPU_MEM_UTIL=0.144" in lines
        and "JUDGE_GPU_MEM_UTIL=0.9" not in lines
    )
    assert "TB_REHEARSAL_REAL_SERVERS=1" in lines and not (site / ".rehearsal-caps").exists()


@pytest.mark.parametrize("profile", ["dgpu48", "gb10"])
def test_the_profiles_not_opened_are_refused_by_name(tmp_path: Path, profile: str) -> None:
    b = Bench(tmp_path)
    r = b.install("--rehearsal", "--rehearsal-real-servers", "--gpu", profile, "--gpu-index", "1",
                  "--engine-probe", str(b.probe))  # fmt: skip
    assert r.returncode == 1 and f"the {profile} profile is not opened for a rehearsal with real servers" in r.stderr
    assert "WARN" not in r.stdout


@pytest.mark.parametrize("profile", ["rtx4090", "default", "b200-no-mig"])
def test_other_profiles_are_refused(tmp_path: Path, profile: str) -> None:
    b = Bench(tmp_path)
    r = b.install("--rehearsal", "--rehearsal-real-servers", "--gpu", profile, "--gpu-index", "1",
                  "--engine-probe", str(b.probe))  # fmt: skip
    assert r.returncode == 1 and "name the profile: --gpu rtxpro6000 or --gpu rtx5090" in r.stderr

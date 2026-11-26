"""M9: the 96 GB class's profile record, detection, caps, the Docker Engine's tested range, the proof script."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools.trialbox import doctor
from tools.trialbox import profile_m9 as pm

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
PRO = "NVIDIA RTX PRO 6000 Blackwell Server Edition"


@pytest.mark.parametrize(
    ("arch", "card", "ok", "profile", "words"),
    [
        ("x86_64", PRO, True, "rtxpro6000", ("96 GB", "16 concurrent")),
        ("x86_64", "NVIDIA GeForce RTX 5090", True, "rtx5090", ("another class",)),
        ("x86_64", "", True, "stub", ("simulated",)),
        ("x86_64", "[N/A]", True, "stub", ("simulated",)),
        ("x86_64", "NVIDIA L4", False, "", ("unknown machine", "card=NVIDIA L4", "--gpu")),
        ("x86_64", "NVIDIA B200", False, "b200-no-mig", ("refused",)),
        ("aarch64", "NVIDIA GB10", True, "gb10", ()),
        ("aarch64", "NVIDIA GB10", False, "gb10-64", ("refused",)),
    ],
)
def test_detection_on_recorded_machines(arch: str, card: str, ok: bool, profile: str, words: tuple[str, ...]) -> None:
    mem = "67108864" if profile == "gb10-64" else ""
    d = pm.detect(arch, card, "", mem)
    assert (d["ok"], d["profile"]) == (ok, profile)
    assert all(w in d["line"] for w in words), d["line"]


def test_mig_card_is_refused_and_an_override_is_the_only_way_past_an_unknown_one() -> None:
    assert pm.detect("x86_64", PRO, "Enabled")["profile"] == "shared-quota"
    assert pm.detect("x86_64", "NVIDIA L4", override="rtxpro6000")["ok"]
    assert not pm.detect("x86_64", "NVIDIA L4", override="nonsense")["ok"]


def test_the_gb10_record_is_its_overlay_and_unmeasured() -> None:
    rec = pm.record("gb10")
    assert rec is not None and rec["measured"]["patients_per_night"] is None and rec["status"] == "unmeasured"
    text = (ROOT / "deploy" / "docker-compose.gb10.yml").read_text(encoding="utf-8")
    for key, value in rec["caps"].items():
        assert key == "TB_LLM_PREFIX_CACHING" or f"${{{key}:-{value}}}" in text, key
    assert pm.caps_row({"TB_MEM_VERIFIER": "64g"}, rec)[1] == "FAIL"
    assert "gb10 (128 GB unified class)" in pm.detect("aarch64", "NVIDIA GB10", "", "125000000")["line"]


def test_the_record_is_the_overlay_it_describes() -> None:
    rec = pm.record()
    assert rec is not None and rec["measured"]["seconds_per_1000_patients"] is None  # never filled by hand
    text = (ROOT / "deploy" / "docker-compose.rtxpro6000.yml").read_text(encoding="utf-8")
    for key, value in rec["caps"].items():
        assert key == "TB_LLM_PREFIX_CACHING" or f"${{{key}:-{value}}}" in text, key
    assert (
        "${TB_LLM_PREFIX_CACHING:-no-enable}-prefix-caching" in text
        and rec["caps"]["TB_LLM_PREFIX_CACHING"] == "no-enable"
    )
    assert re.search(r"--enforce-eager", text) and "off" in rec["serving"]["cuda_graphs"]
    mib = (ROOT / "deploy/measured/serving_config.rtxpro6000.json").read_text(encoding="utf-8")
    assert f'"memory_total_mib": {rec["hardware_seen"]["memory_total_mib"]}' in mib


def test_a_hand_edited_cap_is_reported() -> None:
    rec = pm.record()
    assert rec is not None
    assert pm.caps_row({}, rec)[1] == "PASS" and pm.caps_row(dict(rec["caps"]), rec)[1] == "PASS"
    row = pm.caps_row({"TB_MEM_LLM": "64g"}, rec)
    assert row[1] == "FAIL" and "TB_MEM_LLM=64g (measured 48g)" in row[2]


@pytest.mark.parametrize(
    ("version", "state"),
    [("27.0.0", "PASS"), ("27.3.1", "PASS"), ("28.5.2", "PASS"), ("29.0.1", "PASS"), ("26.1.4", "FAIL"),
     ("30.0.0", "FAIL"), (None, "WARN"), ("", "WARN"), ("snap", "WARN")],
)  # fmt: skip
def test_engine_range_rule(version: str | None, state: str) -> None:
    assert pm.engine_row(version)[1] == state
    assert pm.engine_range_text() in pm.engine_row(version)[2]  # doctor shows the one range


def test_installer_asks_the_one_range(tmp_path: Path) -> None:
    def run(v: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, "-m", "tools.trialbox.profile_m9", "engine", v]
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)

    assert (run("28.1.0").returncode, run("25.0.0").returncode, run("x").returncode) == (0, 2, 3)
    assert "profile_m9 engine" in (ROOT / "deploy/install.sh").read_text(encoding="utf-8")


def test_doctor_rows_come_through_the_hook(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pm, "server_info", lambda: ("26.0.0", "Docker Desktop"))
    (tmp_path / "meminfo").write_text("MemTotal:  527000000 kB\n", encoding="utf-8")
    rec = pm.record()
    assert rec is not None
    inp = doctor.DoctorInputs(
        env={"TB_LLM_MODE": "gpu", "TB_MEM_LLM": "64g"}, deploy=tmp_path, proc=tmp_path, gpu_query=lambda: (PRO, "580")
    )
    rows = {c.name: c for c in doctor.module_rows(inp, [])}
    assert (
        rows["docker_engine"].status == "FAIL"
        and "Docker Desktop's engine" in rows["docker_engine"].detail
        and rows["profile"].status == "PASS"
    )
    assert rows["profile_caps"].status == "FAIL" and "hand-edited" in rows["profile_caps"].detail
    stub = doctor.DoctorInputs(env={"TB_LLM_MODE": "stub"}, deploy=tmp_path)
    assert {c.name for c in doctor.module_rows(stub, [])} >= {"docker_engine"}


def test_doctor_refuses_the_profile_with_mig_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pm, "server_info", lambda: ("26.0.0", "Docker Engine"))
    monkeypatch.setattr(pm, "_mig", lambda inp: "Enabled")
    (tmp_path / "meminfo").write_text("MemTotal:  527000000 kB\n", encoding="utf-8")
    inp = doctor.DoctorInputs(
        env={"TB_LLM_MODE": "gpu"}, deploy=tmp_path, proc=tmp_path, gpu_query=lambda: (PRO, "580")
    )
    rows = {c.name: c for c in doctor.module_rows(inp, [])}
    assert rows["profile"].status == "FAIL" and "refused" in rows["profile"].detail


def test_proof_script_is_runnable_and_refuses_without_its_steps() -> None:
    f = ROOT / "tools/prove_profile_96gb.sh"
    assert os.access(f, os.X_OK)
    assert subprocess.run(["bash", "-n", str(f)], check=False).returncode == 0
    assert subprocess.run([str(f)], capture_output=True, check=False).returncode == 2


def test_windows_proof_runs_the_same_script_inside_wsl() -> None:
    ps = (ROOT / "tools/prove_profile_96gb.ps1").read_text(encoding="utf-8")
    assert "prove_profile_96gb.sh" in ps and "wsl.exe" in ps and ".wslconfig" in ps


def test_no_rows_without_a_boxs_own_files() -> None:
    assert pm.doctor_checks(doctor.DoctorInputs()) == []

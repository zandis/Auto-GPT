"""HOST-GPU (D-889, lane G's probe): qualify's serving_record step read the NVIDIA driver with nvidia-smi inside the
trialbox-py container, which has no GPU ("no NVIDIA driver visible there"). The driver is the host's: the box wrapper
reads it there and hands it in as TB_HOST_GPU; inside the image qualify takes it from there, and says so."""

from __future__ import annotations

import json
import shutil
from typing import Any

import pytest

from tools import box_qualify as bq
from tools import qualify as q

pytestmark = pytest.mark.nodb

HOST = {"driver": "580.65.06", "cuda": "13.0", "gpu": "NVIDIA RTX PRO 6000 Blackwell Server Edition"}


def test_inside_the_image_the_hosts_versions_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)  # no nvidia-smi in the container
    monkeypatch.setenv("TB_HOST_GPU", json.dumps(HOST))
    assert q.gpu_versions() == {**HOST, "driver_source": "host (TB_HOST_GPU)"}


def test_without_either_there_is_no_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.delenv("TB_HOST_GPU", raising=False)
    assert q.gpu_versions()["driver"] == "none"


@pytest.mark.parametrize("bad", ["not json", "[]", '{"driver": ""}', '{"cuda": "13.0"}'])
def test_a_malformed_value_is_no_driver(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setenv("TB_HOST_GPU", bad)
    assert q.gpu_versions()["driver"] == "none"


def _run(smi: bool) -> Any:
    def run(cmd: list[str]) -> str:
        if cmd[0] == "nvidia-smi":
            if not smi:
                raise RuntimeError("nvidia-smi: not found")
            if len(cmd) > 1:
                return f"{HOST['driver']}, {HOST['gpu']}\n"
            return (
                f"| NVIDIA-SMI {HOST['driver']}   Driver Version: {HOST['driver']}   CUDA Version: {HOST['cuda']}  |\n"
            )
        return "sha256:" + "a" * 64 if "inspect" in cmd and "-f" in cmd else ""

    return run


def test_the_box_wrapper_reads_the_hosts_versions_with_nvidia_smi() -> None:
    assert bq.host_gpu_versions(_run(True)) == HOST
    assert bq.host_gpu_versions(_run(False)) == {}


@pytest.mark.parametrize("smi", [True, False])
def test_the_box_wrapper_hands_them_in(tmp_path: Any, smi: bool) -> None:
    (tmp_path / "deploy").mkdir()
    cmd = bq.relaunch_command(["--profile", "rtxpro6000"], tmp_path, _run(smi), env={"PATH": "/usr/bin"})
    got = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e" and cmd[i + 1].startswith("TB_HOST_GPU=")]
    assert ([json.loads(g.split("=", 1)[1]) for g in got] == [HOST]) if smi else got == []

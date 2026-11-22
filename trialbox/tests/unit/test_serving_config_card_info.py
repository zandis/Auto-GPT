from typing import Any

from pytest import MonkeyPatch

from tools.serving_config import card_info


def test_card_info_multiple_gpus(monkeypatch: MonkeyPatch) -> None:
    """card_info() should report MIG=True if any GPU has MIG enabled and sum memory_used across all GPUs."""

    def fake_run(cmd: list[str], check: bool = True, capture_output: bool = True, text: bool = True) -> Any:
        class Result:
            def __init__(self, stdout: str):
                self.stdout = stdout

        # Query for name,memory,total,driver_version (two GPUs)
        if cmd[:2] == ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version"]:
            return Result("GPU0, 16000, 2000, 525.85\nGPU1, 24000, 3000, 525.85")
        # General nvidia-smi output containing CUDA version
        if cmd[:2] == ["nvidia-smi"]:
            return Result("NVIDIA-SMI 525.85    Driver Version: 525.85    CUDA Version: 12.2")
        # MIG mode per GPU (first disabled, second enabled)
        if cmd[:2] == ["nvidia-smi", "--query-gpu=mig.mode.current"]:
            return Result("Disabled\nEnabled")
        raise RuntimeError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("subprocess.run", fake_run)

    card, used = card_info()
    assert card["mig"] is True, "MIG should be True when any GPU reports enabled"
    assert used == 2000 + 3000, "memory_used should be summed across all GPUs"

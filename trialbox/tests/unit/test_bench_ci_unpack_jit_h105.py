"""H-105, the security review of #1448, F9: the one-job runner configuration reaches the runner as files, never as
an argument (tools/bench_ci/unpack_jit.py, called by the container's entry point)."""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path

import pytest

from tools.bench_ci import unpack_jit

pytestmark = pytest.mark.nodb


def _config(files: dict[str, bytes]) -> str:
    inner = {k: base64.b64encode(v).decode() for k, v in files.items()}
    return base64.b64encode(json.dumps(inner).encode()).decode()


GOOD = {".runner": b'{"agentId": 1}', ".credentials": b'{"scheme": "x"}', ".credentials_rsaparams": b'{"d": "y"}'}


def test_the_configuration_becomes_the_runners_three_files(tmp_path: Path) -> None:
    cfg = tmp_path / "runner.jit"
    cfg.write_text(_config(GOOD) + "\n", encoding="utf-8")
    runner = tmp_path / "runner"
    runner.mkdir()
    assert unpack_jit.main([str(cfg), str(runner)]) == 0
    for name, data in GOOD.items():
        assert (runner / name).read_bytes() == data
        assert stat.S_IMODE((runner / name).stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "config",
    [
        "not base64 at all!",
        base64.b64encode(b"[1, 2]").decode(),
        _config({**GOOD, "extra": b"x"}),
        _config({k: v for k, v in GOOD.items() if k != ".credentials"}),
        _config({**GOOD, "../escape": b"x"}),
    ],
)
def test_any_other_form_is_refused_and_nothing_is_written(tmp_path: Path, config: str) -> None:
    cfg = tmp_path / "runner.jit"
    cfg.write_text(config, encoding="utf-8")
    runner = tmp_path / "runner"
    runner.mkdir()
    assert unpack_jit.main([str(cfg), str(runner)]) == 2
    assert list(runner.iterdir()) == []

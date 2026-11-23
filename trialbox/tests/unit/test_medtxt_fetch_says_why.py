"""rc1 line 1: a corpus fetch (`make public-data`, for the eval that still needs the Real-MedNLP XML) that cannot reach
its source stops with one line that names the cause. Synthetic data only."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tools import medtxt_eval


def test_an_unreachable_source_stops_the_fetch_with_the_cause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(medtxt_eval, "CACHE", tmp_path / "medtxt")

    def down(*a: object, **k: object) -> None:
        raise httpx.ConnectError("[Errno 101] Network is unreachable")

    monkeypatch.setattr(httpx, "get", down)
    with pytest.raises(SystemExit) as stop:
        medtxt_eval.fetch()
    msg = str(stop.value)
    assert "could not be fetched" in msg and "ConnectError" in msg and "Network is unreachable" in msg
    assert "\n" not in msg and not (tmp_path / "medtxt" / "Test collection").exists()

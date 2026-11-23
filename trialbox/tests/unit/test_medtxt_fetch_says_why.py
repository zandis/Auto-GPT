"""rc1 line 1: a corpus fetch that cannot reach its source stops with one line that names the cause, and the nightly's
cache key is the corpus version, not the code that fetches it. Synthetic data only."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tools import medtxt_eval

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-e2e.yml"


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


def test_the_corpus_cache_key_is_the_corpus_version_in_both_jobs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    keys = [ln for ln in text.splitlines() if "key: tb-medtxt-" in ln]
    assert len(keys) == 2 and all("hashFiles('trialbox/tools/medtxt.version')" in k for k in keys)
    assert (ROOT / "tools" / "medtxt.version").read_text(encoding="utf-8").strip().isdigit()

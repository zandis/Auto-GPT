"""The body of ``adapter.run_job`` (D-663), run in this process.

``tests/unit/test_adapter_run_process.py`` runs the night as the box does, in a child process; a line a child runs is
not counted by the test run's coverage (the gate fell on ``services/lake`` for the same reason when its build left
the service's thread). These tests call the child's own ``main`` here, with a lock handed over as the service hands
it, so every line of it is run where it is counted, and its endings are asserted one by one."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from adapter import run_job, runs

from tests.unit.test_site_inputs import site  # noqa: F401 (a fixture: a site configured from the environment)

NIGHT = "2026-10-04"


@pytest.fixture
def lake_dir(site: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    """A site whose configuration is in the environment, and this process stood in for the night's: the two things
    a night's process does to ITSELF (its logging, its own out-of-memory score) are kept away from the test run."""
    import lake.build
    import tb_common.logging
    from adapter import cli

    assert cli.main(["keys-init"]) == 0
    monkeypatch.setattr(tb_common.logging, "setup_logging", lambda service, level="INFO": None)
    monkeypatch.setattr(lake.build, "prefer_me_when_memory_runs_out", lambda: None)
    return site["tmp"] / "lake"


def _handed(lake_dir: Path, rid: str = "ab12", **request: Any) -> tuple[list[str], dict[str, Any]]:
    """What the service hands a night's process: the run it wrote as ``running`` and the open file of the run lock."""
    lock = runs.RunLock(lake_dir)
    state = {"run": rid, "state": "running", "started": "2026-10-04T17:00:00+00:00", "ended": None, "detail": ""}
    runs.hold(lake_dir, rid)
    runs.write(lake_dir, state)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    req = {"source": "csv", "path": "", "since": None, "snapshot": NIGHT, "load_fhir": False, "rebuild_lake": True,
           "validate": False, **request}  # fmt: skip
    return [str(fd), json.dumps({"state": state, "lake_dir": str(lake_dir), "request": req})], state


def test_the_night_runs_writes_its_report_and_frees_the_lock(lake_dir: Path, site: dict[str, Path]) -> None:  # noqa: F811
    argv, state = _handed(lake_dir, path=str(site["feed"]))
    assert runs.running(lake_dir) and runs.holder(lake_dir) == state["run"]
    assert run_job.main(argv) == 0
    end = runs.read(lake_dir, state["run"])
    assert end is not None
    assert end["state"] == "done" and end["ended"], end.get("detail")
    assert end["report"]["passed"] and end["report"]["counts"]["Patient"] > 0
    assert (lake_dir / "CURRENT").read_text().strip() == NIGHT and not runs.running(lake_dir)


def test_a_night_that_fails_is_the_runs_end_with_the_errors_type(lake_dir: Path, tmp_path: Path) -> None:
    argv, state = _handed(lake_dir, path=str(tmp_path / "no-such-feed"), source="no-such-source")
    assert run_job.main(argv) == 0  # the run's end says what happened; the process itself did its work
    end = runs.read(lake_dir, state["run"])
    assert end is not None and end["state"] == "failed" and end["detail"] and end["ended"]
    assert not runs.running(lake_dir) and not (lake_dir / "CURRENT").exists()


def test_a_night_refused_for_its_site_key_is_refused_not_failed(
    lake_dir: Path,
    site: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapter import pipeline

    def refuse(*a: Any, **kw: Any) -> Any:
        raise pipeline.SiteKeyError("the site key changed")

    monkeypatch.setattr(pipeline, "run_ingest", refuse)
    argv, state = _handed(lake_dir, path=str(site["feed"]))
    assert run_job.main(argv) == 0
    end = runs.read(lake_dir, state["run"])
    assert end is not None and end["state"] == "refused" and end["detail"] == "night refused: the site key changed"


def test_a_wrong_call_is_refused_before_anything_is_touched(lake_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_job.main([]) == 2 and run_job.main(["1", "{}", "x"]) == 2
    assert "python -m adapter.run_job" in capsys.readouterr().err
    argv, state = _handed(lake_dir)
    other = os.open(lake_dir / "another-file", os.O_CREAT | os.O_RDWR)
    with pytest.raises(runs.RunLockHeld, match="not the adapter's run lock"):
        run_job.main([str(other), argv[1]])  # a file that is not the run lock: no night without its lock
    os.close(int(argv[0]))
    end = runs.read(lake_dir, state["run"])
    assert end is not None and end["state"] == "failed" and "ended without an answer" in end["detail"]

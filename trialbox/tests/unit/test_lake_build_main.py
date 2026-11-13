"""The body of ``lake.build`` (D-539), run in this process.

``tests/unit/test_lake_build_process.py`` runs the build as the box does, in a child process; a line a child runs is
not counted by the test run's coverage, and the coverage gate saw ``services/lake`` fall when the build left the
service's thread. These tests call the child's own ``main`` here, with a lock handed over as the service hands it,
so every line of it is run where it is counted, and its endings are asserted one by one."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake import build
from lake.store import BuildLock, Lake, SnapshotBuilding, build_running, read_rebuild_job, write_rebuild_job

NIGHT, NEXT = "2026-10-04", "2026-10-05"
TZ = "Asia/Taipei"


def _patients(lake_dir: Path, snap: str, n: int) -> None:
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
    pats = [{"resourceType": "Patient", "id": f"syn-{i:03d}", "gender": "female"} for i in range(n)]
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in pats), encoding="utf-8")


@pytest.fixture
def asked() -> list[str]:
    """What the build asked of the kernel for itself (kept away from this process: see ``lake_dir``)."""
    return []


@pytest.fixture
def lake_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str]) -> Path:
    """A lake that serves one night, and this process stood in for the build's: its settings in the environment,
    and the two things a build's process does to ITSELF kept away from the test run's own process."""
    d = tmp_path / "lake"
    _patients(d, NIGHT, 3)
    Lake(d, TZ).rebuild(NIGHT, HashEmbedder())
    monkeypatch.setenv("TB_LAKE_EMBEDDER", "hash")
    monkeypatch.setenv("TB_TZ", TZ)
    import tb_common.logging

    monkeypatch.setattr(tb_common.logging, "setup_logging", lambda service, level="INFO": None)
    monkeypatch.setattr(build, "prefer_me_when_memory_runs_out", lambda: asked.append("first"))
    return d


def _handed(lake_dir: Path, snap: str, **spec: Any) -> tuple[list[str], dict[str, Any]]:
    """What the service hands a build: the job it wrote as ``running`` and the open file of its build lock."""
    lock = BuildLock(lake_dir, snap)
    job = {"job": "j1", "snapshot": snap, "state": "running", "started": 1.0, "ended": None, "result": None,
           "busy": None, "detail": ""}  # fmt: skip
    write_rebuild_job(lake_dir, job)
    fd = os.dup(lock.fileno())
    lock.hand_over()
    return [str(fd), json.dumps({"job": job, "lake_dir": str(lake_dir), **spec})], job


def test_the_build_runs_the_job_writes_its_end_and_frees_the_lock(lake_dir: Path, asked: list[str]) -> None:
    _patients(lake_dir, NEXT, 5)
    argv, job = _handed(lake_dir, NEXT)
    assert build_running(lake_dir, NEXT)
    assert build.main(argv) == 0
    end = read_rebuild_job(lake_dir, NEXT)
    assert end is not None and end["state"] == "done" and end["job"] == job["job"]
    assert end["result"]["tables"]["patient"] == 5 and end["result"]["promoted"] is True
    assert Lake(lake_dir, TZ).current() == NEXT and not build_running(lake_dir, NEXT)
    assert asked == ["first"]  # it asked the kernel to be killed first


def test_a_build_without_promote_from_a_folder_of_its_own_is_built_and_not_served(lake_dir: Path) -> None:
    other = lake_dir.parent / "feed" / NEXT
    other.mkdir(parents=True)
    (other / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n")
    argv, _ = _handed(lake_dir, NEXT, ndjson_dir=str(other), promote=False, check=True)
    assert build.main(argv) == 0
    end = read_rebuild_job(lake_dir, NEXT)
    assert end is not None and end["state"] == "done" and end["result"]["promoted"] is False
    assert end["result"]["tables"]["patient"] == 1 and Lake(lake_dir, TZ).current() == NIGHT


def test_a_refusal_found_in_the_build_is_the_jobs_end_and_the_process_ends_well(lake_dir: Path) -> None:
    nd = lake_dir / "ndjson" / NEXT
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text("\n")
    argv, _ = _handed(lake_dir, NEXT)
    assert build.main(argv) == 0  # the job's end says what happened; the process itself did its work
    end = read_rebuild_job(lake_dir, NEXT)
    assert end is not None and end["state"] == "refused" and "holds no patient or clinical record" in end["detail"]
    assert not build_running(lake_dir, NEXT)


def test_a_build_that_cannot_begin_writes_failed_with_the_errors_type_and_frees_the_lock(
    lake_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patients(lake_dir, NEXT, 5)
    monkeypatch.setenv("TB_LAKE_EMBEDDER", "no-such-embedder")
    argv, _ = _handed(lake_dir, NEXT)
    assert build.main(argv) == 1
    end = read_rebuild_job(lake_dir, NEXT)
    assert end is not None and end["state"] == "failed"
    assert end["detail"] == "the build's process could not begin (ValueError)" and end["ended"]
    assert "could not begin" in caplog.text and "no-such-embedder" in caplog.text  # which setting: in the log
    assert not build_running(lake_dir, NEXT) and Lake(lake_dir, TZ).current() == NIGHT


def test_a_wrong_call_is_refused_before_anything_is_touched(lake_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert build.main([]) == 2 and build.main(["1", "{}", "x"]) == 2
    assert "python -m lake.build" in capsys.readouterr().err
    _patients(lake_dir, NEXT, 5)
    argv, _ = _handed(lake_dir, NEXT)
    other = os.open(lake_dir / "another-file", os.O_CREAT | os.O_RDWR)
    with pytest.raises(SnapshotBuilding, match="not the build lock"):
        build.main([str(other), argv[1]])  # a file that is not the snapshot's lock: no build without its lock
    job = read_rebuild_job(lake_dir, NEXT)
    assert job is not None and job["state"] == "running"  # nothing was written; the starter's own waiting ends it
    os.close(int(argv[0]))
    assert not build_running(lake_dir, NEXT)


def test_the_build_asks_the_kernel_to_be_killed_first_and_bears_a_system_without_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real function, pointed at a file of the test's: the test run's own process is not marked."""
    written: list[tuple[str, str]] = []

    class Proc:
        def __init__(self, path: str) -> None:
            self.path = path

        def write_text(self, text: str, encoding: str = "") -> int:
            if self.path.startswith("/nowhere"):
                raise OSError("no such file")
            written.append((self.path, text))
            return len(text)

    monkeypatch.setattr(build, "Path", Proc)
    build.prefer_me_when_memory_runs_out()
    assert written == [("/proc/self/oom_score_adj", "1000")]
    monkeypatch.setattr(build, "Path", lambda path: Proc("/nowhere"))
    build.prefer_me_when_memory_runs_out()  # not Linux: nothing is done, nothing is raised
    assert len(written) == 1

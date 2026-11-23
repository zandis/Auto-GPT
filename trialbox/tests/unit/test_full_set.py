"""tools/full_set.py: the whole test set, three runs in a row, a log for every stage of every run (rc1 line 1).
The commands are not run here: a fake runner stands in. Synthetic data only."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from tools import full_set as fs

ROOT = Path(__file__).resolve().parents[2]
URL = ("--llm-url", "http://127.0.0.1:8000/v1", "--llm-model", "served-name")


class Fake:
    def __init__(self, red: set[tuple[int, str]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.red = red or set()
        self.run = 1

    def __call__(self, argv: Sequence[str], log: Path, env: dict[str, str]) -> int:
        self.calls.append(tuple(argv))
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write("$ " + " ".join(argv) + "\n")
        m = re.search(r"run-(\d+)", str(log))
        assert m
        run = int(m.group(1))
        stage = log.stem
        return 1 if (run, stage) in self.red and "test" in " ".join(argv) else 0


def test_three_green_runs_in_a_row_keep_a_log_for_every_stage(tmp_path: Path) -> None:
    fake = Fake()
    assert fs.main(["--out", str(tmp_path), *URL], fake) == 0
    for n in (1, 2, 3):
        for s in fs.STAGES:
            assert (tmp_path / f"run-{n}" / f"{s.name}.log").read_text().startswith("$"), (n, s.name)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["runs_green_in_a_row"] == 3 and summary["partial"] is False
    assert (tmp_path / "summary.md").read_text().startswith("# The whole set, 3 of 3")


def test_a_red_stage_makes_the_run_red_and_the_runner_stops_there(tmp_path: Path) -> None:
    fake = Fake(red={(2, "walks")})
    assert fs.main(["--out", str(tmp_path), *URL], fake) == 1
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["runs_green_in_a_row"] == 1 and len(summary["runs"]) == 2
    assert not (tmp_path / "run-3").exists()
    by = {s["stage"]: s["result"] for s in summary["runs"][1]["stages"]}
    assert by["walks"] == fs.RED and by["unit"] == fs.GREEN  # every stage of the red run still ran


def test_a_stack_that_was_started_is_stopped_even_when_its_tests_fail(tmp_path: Path) -> None:
    fake = Fake(red={(1, "compose")})
    fs.main(["--out", str(tmp_path), "--only", "compose", "--runs", "1"], fake)
    assert ("make", "--no-print-directory", "down") in fake.calls


def test_the_gpu_stage_without_a_model_endpoint_is_not_run_and_the_run_is_red(tmp_path: Path) -> None:
    fake = Fake()
    assert fs.main(["--out", str(tmp_path), "--runs", "1"], fake) == 1
    summary = json.loads((tmp_path / "summary.json").read_text())
    gpu = next(s for s in summary["runs"][0]["stages"] if s["stage"] == "gpu")
    assert gpu["result"] == fs.NOT_RUN and summary["runs"][0]["green"] is False
    assert not any("llm" in c for c in fake.calls)


def test_a_partial_run_never_counts_as_the_set(tmp_path: Path) -> None:
    assert fs.main(["--out", str(tmp_path), "--only", "unit", "--runs", "1"], Fake()) == 1
    assert json.loads((tmp_path / "summary.json").read_text())["partial"] is True


def test_every_make_target_a_stage_runs_exists() -> None:
    mk = (ROOT / "Makefile").read_text()
    targets = set(re.findall(r"^([A-Za-z0-9_.-]+):", mk, re.M))
    named = {c[2] for s in fs.STAGES for c in (*s.commands, *s.always) if c[0] == "make"}
    assert named and named <= targets, sorted(named - targets)

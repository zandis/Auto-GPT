"""The nightly quality's mutation shards end inside 90 minutes, and the scale gate says the model's share (D-973).

D-537 (the owner): no CI job over 90 minutes, and no ceiling raised to get there; the work is shrunk instead. The
mutation shard ``engine-1`` took 207 minutes on 2026-11-16 (``engine-2`` 149): ``engine.py``'s 563 mutants in two parts.
They now run in six parts, every mutant in exactly one (``tools/mutation.py --part K/6``), each with a budget that
leaves the job's set-up inside 90 minutes. The scale gate's report also says how much of the screen and of the whole
night was the slow model stand-in waiting (calls x seconds per call), so its 68 to 74 minutes can be read.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tools import scale_gate

REPO = Path(__file__).resolve().parents[3]
QUALITY = REPO / ".github" / "workflows" / "trialbox-nightly-quality.yml"
CEILING_MIN = 90


def _mutation_job() -> dict[str, Any]:
    wf = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    job: dict[str, Any] = wf["jobs"]["mutation"]
    return job


def test_the_mutation_job_ends_inside_the_ceiling() -> None:
    job = _mutation_job()
    assert int(job["timeout-minutes"]) <= CEILING_MIN
    run = next(s["run"] for s in job["steps"] if s.get("name") == "Mutants of the shard")
    budget = int(re.search(r"--budget-minutes (\d+)", run).group(1))  # type: ignore[union-attr]
    # the runner starts no mutant after the budget; set-up (venv, JVM, PostgreSQL) took about 7 minutes
    assert budget + 10 <= int(job["timeout-minutes"]), "no room left for the set-up and the last mutants"


def test_engine_py_runs_in_parts_that_cover_every_mutant_once() -> None:
    shards = _mutation_job()["strategy"]["matrix"]["include"]
    parts = [re.search(r"--part (\d+)/(\d+)", s["targets"]) for s in shards if "cascade/engine.py" in s["targets"]]
    assert all(parts), "an engine.py shard without --part runs every mutant again"
    got = sorted((int(m.group(1)), int(m.group(2))) for m in parts if m)
    n = got[0][1]
    assert got == [(k, n) for k in range(1, n + 1)], f"engine.py parts {got}: each of 1..N exactly once"
    # 356 minutes of engine.py mutants on 2026-11-16 (207 + 149): at most about 60 minutes a part
    assert n >= 6
    names = [s["shard"] for s in shards if "cascade/engine.py" in s["targets"]]
    assert len(set(names)) == len(names)


def test_the_score_job_counts_every_shard() -> None:
    """The score job refuses a run with a missing shard report: its count is the matrix's size, whatever it is."""
    wf = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    shards = wf["jobs"]["mutation"]["strategy"]["matrix"]["include"]
    runs = " ".join(str(s.get("run", "")) for s in wf["jobs"]["mutation-score"]["steps"])
    counts = [int(n) for n in re.findall(r'"\$\{#reports\[@\]\}" -eq (\d+)\b', runs)]
    assert counts == [len(shards)], f"the score job counts {counts} reports, the matrix has {len(shards)} shards"


def test_the_latency_share_line() -> None:
    line = scale_gate.latency_share(calls=1362, latency_s=2.0, screen_s=3000.0, night_s=4440.0)
    assert "1,362 calls x 2 s = 2,724 s" in line
    assert "91 % of the screen's 3,000 s" in line and "61 % of the night's 4,440 s" in line
    assert "upper bound" in line  # calls that overlap wait at the same time


def test_no_latency_no_line() -> None:
    assert scale_gate.latency_share(calls=10, latency_s=0.0, screen_s=10.0, night_s=20.0) == ""
    assert scale_gate.latency_share(calls=0, latency_s=2.0, screen_s=10.0, night_s=20.0) == ""


def test_the_gate_writes_the_line_into_its_report() -> None:
    src = Path(scale_gate.__file__).read_text(encoding="utf-8")
    assert "latency_share(" in src.split("def latency_share", 1)[1], "the report never calls latency_share"

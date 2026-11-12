"""T-747 (D-475): the unit suite in N shards. Every test file is in exactly one shard, chosen by a hash of its path
(stable when files are added); the shard records prove that the shards together ran exactly the collected suite; CI
runs N shards with fail-fast off, combines their coverage before the unchanged ratchet, and keeps the required check
``unit`` as the gate over them; the cross-card tests run first in a job of their own."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import test_shard
from tools.test_shard import Record, Shard

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"
MAKEFILE = ROOT / "Makefile"


def _test_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("test_*.py"))


# ---------------------------------------------------------------------------------------------- the split
@pytest.mark.parametrize("text", ["0/3", "4/3", "3", "a/b", "1/0", "-1/2", ""])
def test_a_bad_shard_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        test_shard.parse(text)


def test_a_shard_is_i_of_n() -> None:
    assert test_shard.parse(" 2/6 ") == Shard(2, 6) and str(Shard(2, 6)) == "2/6"


def test_the_hash_is_pinned() -> None:
    """A change of the function moves every file: it must be a deliberate change of this test."""
    assert test_shard.shard_of("tests/unit/test_migrations.py", 6) == 4
    assert test_shard.shard_of("tests\\unit\\test_migrations.py", 6) == 4
    assert [test_shard.shard_of(f"tests/unit/test_{n}.py", 6) for n in "abcdef"] == [6, 5, 4, 3, 5, 2]
    assert test_shard.shard_of("x", 1) == 1
    with pytest.raises(ValueError):
        test_shard.shard_of("x", 0)


@pytest.mark.parametrize("n", [1, 2, 3, 6, 8])
def test_every_test_file_is_in_exactly_one_shard(n: int) -> None:
    files = _test_files()
    assert len(files) > 100
    per = [set(test_shard.keep(files, Shard(i, n))) for i in range(1, n + 1)]
    assert sum(len(s) for s in per) == len(files) and set().union(*per) == set(files)
    if n > 1:
        assert all(per), "an empty shard: N is larger than the suite needs"


def test_a_new_file_moves_no_other_file() -> None:
    files = _test_files()
    before = {f: test_shard.shard_of(f, 6) for f in files}
    after = {f: test_shard.shard_of(f, 6) for f in [*files, "tests/unit/test_brand_new_card.py"]}
    assert all(after[f] == s for f, s in before.items())


def test_the_tests_of_one_file_stay_together() -> None:
    ids = ["tests/unit/test_x.py::test_a", "tests/unit/test_x.py::TestK::test_b[1]", "tests/unit/test_x.py::test_c"]
    shards = {test_shard.shard_of(test_shard.file_of(i), 6) for i in ids}
    assert len(shards) == 1


def test_the_long_tests_start_first_and_nothing_else_moves() -> None:
    ids = ["tests/unit/test_a.py::t1", "tests/integration/test_rc_demo.py::t", "tests/unit/test_a.py::t2",
           "tests/integration/test_e2e_simple.py::t", "tests/unit/test_b.py::t"]  # fmt: skip
    order = [ids[i] for i in test_shard.long_first(ids)]
    assert order == [ids[3], ids[1], ids[0], ids[2], ids[4]]
    assert sorted(test_shard.long_first(ids)) == list(range(len(ids)))
    for f in test_shard.LONG_FIRST:
        assert (ROOT / f).is_file(), f"{f}: gone; take it out of LONG_FIRST"


# ---------------------------------------------------------------------------------------------- the union check
def _records(ids: list[str], n: int) -> list[Record]:
    return [Record(i, n, tuple(ids), tuple(test_shard.keep(ids, Shard(i, n)))) for i in range(1, n + 1)]


IDS = [f"tests/unit/test_{c}.py::test_{k}" for c in "abcdefghij" for k in range(3)]


def test_the_check_passes_a_complete_run() -> None:
    assert test_shard.check(_records(IDS, 4)) == []


def test_the_check_finds_a_missing_shard() -> None:
    recs = _records(IDS, 4)
    assert any("shards present [1, 2, 4]" in p for p in test_shard.check([recs[0], recs[1], recs[3]]))


def test_the_check_finds_a_dropped_test() -> None:
    recs = _records(IDS, 3)
    lost = recs[1].kept[0]
    recs[1] = Record(2, 3, recs[1].collected, recs[1].kept[1:])
    assert any("ran in no shard" in p and lost in p for p in test_shard.check(recs))


def test_the_check_finds_a_test_in_two_shards() -> None:
    recs = _records(IDS, 3)
    recs[0] = Record(1, 3, recs[0].collected, (*recs[0].kept, recs[1].kept[0]))
    assert any("ran in shards" in p for p in test_shard.check(recs))


def test_the_check_finds_shards_that_collected_different_suites() -> None:
    recs = _records(IDS, 3)
    recs[2] = Record(3, 3, recs[2].collected[:-1], recs[2].kept)
    assert any("another suite" in p for p in test_shard.check(recs))
    assert test_shard.check([]) == ["no shard record"]
    mixed = [_records(IDS, 3)[0], _records(IDS, 4)[1]]
    assert test_shard.check(mixed) == ["the shards disagree on N: [3, 4]"]


def test_the_cli_checks_records_and_lists_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = []
    for r in _records(IDS, 3):
        r.write(tmp_path / f"shard-{r.shard}.json")
        paths.append(str(tmp_path / f"shard-{r.shard}.json"))
    assert test_shard.main(["check", *paths]) == 0
    assert "30 tests, each in exactly one of 3 shards" in capsys.readouterr().out
    assert test_shard.main(["check", *paths[:2]]) == 1
    assert "shards present [1, 2]" in capsys.readouterr().err
    assert test_shard.main(["files", "1/1"]) == 0
    assert capsys.readouterr().out.split() == _test_files()


def test_pytest_shards_partition_a_real_collection(tmp_path: Path) -> None:
    """End to end through pytest and tests/conftest.py: three shards of three real (pure) test files, collected with
    --shard and --shard-record; the records pass the check and the shards' tests add up to the whole collection."""
    files = ["tests/unit/test_test_shard.py", "tests/unit/test_wording.py", "tests/unit/test_site_tz.py"]
    n = 3
    for i in range(1, n + 1):
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "--collect-only",
             "--shard", f"{i}/{n}", "--shard-record", str(tmp_path / f"s{i}.json"), *files],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert r.returncode in (0, 5), r.stdout[-2000:] + r.stderr[-2000:]  # 5: this shard kept no test
    recs = [Record.load(tmp_path / f"s{i}.json") for i in range(1, n + 1)]
    assert test_shard.check(recs) == []
    whole = set(recs[0].collected)
    assert any(x.startswith("tests/unit/test_test_shard.py::") for x in whole)
    assert {test_shard.file_of(x) for x in whole} == set(files)
    assert json.loads((tmp_path / "s1.json").read_text())["count"] == n


def test_a_bad_shard_option_is_a_usage_error() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "--collect-only", "--shard", "7/3",
         "tests/unit/test_site_tz.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert r.returncode == 4 and "between 1 and N" in r.stderr, r.stderr[-1000:]


# ---------------------------------------------------------------------------------------------- the Makefile
def _make_var(name: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    m = re.search(rf"^{re.escape(name)} \??= ?(.*)$", text, re.M)
    assert m, name
    return m.group(1)


def test_make_test_takes_a_shard() -> None:
    assert _make_var("SHARD") == "" and _make_var("SHARD_RECORD") == ""
    text = MAKEFILE.read_text(encoding="utf-8")
    locked = text[text.index("\ntest-locked:") :].split("\n\n", 1)[0]
    assert "$(SHARD_ARGS)" in locked and "--shard $(SHARD)" in _make_var("SHARD_ARGS")


def test_the_cross_card_list_names_existing_tests() -> None:
    names = _make_var("CROSS_CARD_TESTS").split()
    assert len(names) >= 13
    for n in names:
        assert (ROOT / test_shard.file_of(n)).is_file(), n
    for must in ("test_audit_browser.py::test_every_event_the_code_writes_has_a_label", "test_test_isolation.py",
                 "test_role_route_matrix.py", "test_migrations.py", "test_record_inventory.py"):  # fmt: skip
        assert any(n.endswith(must) for n in names), must


# ---------------------------------------------------------------------------------------------- the workflow
def _jobs() -> dict[str, Any]:
    if not WORKFLOW.is_file():
        pytest.skip("workflows not in this checkout")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]  # type: ignore[no-any-return]


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_the_shards_run_every_shard_with_fail_fast_off() -> None:
    job = _jobs()["unit-shard"]
    strategy = job["strategy"]
    assert isinstance(strategy, dict) and strategy["fail-fast"] is False
    shards = strategy["matrix"]["shard"]
    assert shards == list(range(1, len(shards) + 1)) and len(shards) >= 2
    assert "unit" not in {str(job.get("name"))} and "unit-shard (" in str(job["name"])
    assert job["if"] == "needs.changes.outputs.trialbox == 'true'"
    runs = _runs(job)
    assert "SHARD=${{ matrix.shard }}/${{ strategy.job-total }}" in runs and "SHARD_RECORD=" in runs
    assert "tools/ci_postgres.sh" in runs and "make data-scan" in runs


def test_unit_is_the_gate_over_every_shard_and_the_combined_coverage() -> None:
    jobs = _jobs()
    unit = jobs["unit"]
    assert "name" not in unit or unit["name"] == "unit"
    assert set(unit["needs"]) >= {"changes", "unit-shard"}
    cond = str(unit["if"])
    assert "!cancelled()" in cond and "needs.changes.outputs.trialbox == 'true'" in cond
    runs = _runs(unit)
    assert "needs.unit-shard.result" in runs and '!= "success"' in runs
    assert "python -m tools.test_shard check" in runs
    assert "coverage combine" in runs and "coverage json" in runs
    # the ratchet itself, unchanged, on the combined report; no tolerance or baseline flag
    (ratchet,) = [ln for ln in runs.splitlines() if "tools.coverage_ratchet" in ln]
    assert ratchet.strip() == '.venv/bin/python -m tools.coverage_ratchet "$RUNNER_TEMP/coverage.json"'
    shard_env = jobs["unit-shard"]["steps"]
    addopts = [s["env"]["PYTEST_ADDOPTS"] for s in shard_env if "PYTEST_ADDOPTS" in s.get("env", {})]
    assert addopts and "--cov" in addopts[0]


def test_the_cross_card_job_runs_first_and_fast() -> None:
    job = _jobs()["cross-card"]
    assert int(str(job["timeout-minutes"])) <= 10
    runs = _runs(job)
    assert "make cross-card" in runs and "--cov" not in runs
    assert job["if"] == "needs.changes.outputs.trialbox == 'true'"

"""tools.trace_dry (card V-15): the check passes on the committed record and fails on each planted fault.

The record is of one commit; these tests check it against itself only, never against today's tree (``--live`` is
not called here), so renaming a test elsewhere cannot turn them red.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools import trace_dry as td


@pytest.fixture
def copy(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "m"
    shutil.copytree(td.OUT, out)
    page = tmp_path / "m.md"
    shutil.copy(td.PAGE, page)
    return out, page


def _edit(path: Path, fn: Callable[[Any], object]) -> None:
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_the_committed_record_is_clean(copy: tuple[Path, Path]) -> None:
    out, page = copy
    assert td.check(out, page) == []


def test_a_number_changed_on_the_page_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    text = page.read_text()
    n = json.loads((out / "trace.json").read_text())["counts"]["requirements_neither"]
    old = f"| requirements neither | {n} |"
    assert old in text
    page.write_text(text.replace(old, f"| requirements neither | {n - 1} |"))
    assert any("block counts" in e for e in td.check(out, page))


def test_a_count_that_does_not_match_its_rows_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "trace.json", lambda t: t["counts"].__setitem__("requirements_marked", 0))
    assert any("count requirements_marked" in e for e in td.check(out, page))


def test_a_status_changed_in_json_and_page_alike_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    trace = json.loads((out / "trace.json").read_text())
    row = trace["criteria"][5]
    old = row["status"]
    row["status"] = "has passing tests that show part of it"
    (out / "trace.json").write_text(json.dumps(trace))
    page.write_text(
        page.read_text().replace(f"| 6 | {row['title']} | {old} |", f"| 6 | {row['title']} | {row['status']} |")
    )
    errors = td.check(out, page)
    assert not any("block verdict" in e for e in errors)  # the page and the json agree with each other
    assert any(e.startswith("criterion 6: status") for e in errors)  # but not with the results


def test_a_rewritten_results_summary_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "results-summary.json", lambda s: s["outcomes"].update({k: "passed" for k in s["outcomes"]}))
    errors = td.check(out, page)
    assert any("outcomes differ from results-summary.json" in e for e in errors)


def test_a_test_file_not_in_the_collection_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "trace.json", lambda t: t["criteria"][7]["test_files"].append("tests/unit/test_no_such_file_v15.py"))
    assert any("test_no_such_file_v15.py is not in the collection" in e for e in td.check(out, page))


def test_a_result_for_a_test_not_in_the_collection_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(
        out / "results-summary.json",
        lambda s: s["outcomes"].__setitem__("tests/unit/test_authz_matrix.py::gone", "passed"),
    )
    assert any("test_authz_matrix.py::gone is not in the collection" in e for e in td.check(out, page))


def test_the_check_reads_the_kept_collection_not_the_tree(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "collection.json", lambda c: c["files"].pop(next(iter(c["files"]))))
    assert any("is not in the collection" in e for e in td.check(out, page))


def test_a_finding_without_a_basis_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "findings.json", lambda f: f[0].__setitem__("basis", "likely"))
    assert any("basis likely" in e for e in td.check(out, page))


def test_a_finding_id_in_the_old_form_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "findings.json", lambda f: f[0].__setitem__("id", "V15-F01"))
    assert any("finding id V15-F01" in e for e in td.check(out, page))


def test_a_sampled_decision_outside_the_list_is_caught(copy: tuple[Path, Path]) -> None:
    out, page = copy
    _edit(out / "sample-check.json", lambda s: s[0].__setitem__("decision", "D-1"))
    assert any("sample D-1: not in the top 40" in e for e in td.check(out, page))


def test_write_refuses_to_drop_kept_outcomes(copy: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    out, _ = copy
    before = (out / "results-summary.json").read_text()
    assert td.main(["--write", "--out", str(out), "--collection", str(out / "none.txt")]) == 2
    assert "--no-results" in capsys.readouterr().out
    assert (out / "results-summary.json").read_text() == before


def test_the_collection_drops_parameters_and_counts_items() -> None:
    text = (
        "tests/unit/test_a.py::test_x[1]\ntests/unit/test_a.py::test_x[2]\ntests/b.py::C::test_y\n\n3 tests collected\n"
    )
    got = td.parse_collection(text)
    assert got == {"items": 3, "files": {"tests/b.py": ["C::test_y"], "tests/unit/test_a.py": ["test_x"]}}


def test_junit_outcomes_are_read_not_guessed(tmp_path: Path) -> None:
    xml = tmp_path / "r.xml"
    xml.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="tests.unit.test_a" name="test_ok"/>'
        '<testcase classname="tests.unit.test_a" name="test_bad"><failure message="x"/></testcase>'
        '<testcase classname="tests.unit.test_a.TestK" name="test_skip"><skipped type="pytest.skip" message="s"/></testcase>'
        '<testcase classname="tests.unit.test_a" name="test_xf"><skipped type="pytest.xfail" message="s"/></testcase>'
        "</testsuite></testsuites>"
    )
    assert td.read_junit([xml]) == {
        "tests/unit/test_a.py::test_ok": "passed",
        "tests/unit/test_a.py::test_bad": "failed",
        "tests/unit/test_a.py::TestK::test_skip": "skipped",
        "tests/unit/test_a.py::test_xf": "xfailed",
    }


def test_a_test_with_no_result_is_never_a_pass() -> None:
    o = td.outcomes_for(["tests/unit/test_a.py"], {})
    assert td.criterion_status("tests", ["tests/unit/test_a.py"], o) == "has tests; collected, result not run here"
    o = td.outcomes_for(["tests/unit/test_a.py", "tests/unit/test_b.py"], {"tests/unit/test_a.py::t": "passed"})
    assert td.criterion_status("tests", ["tests/unit/test_a.py", "tests/unit/test_b.py"], o).startswith(
        "has tests, some"
    )
    o = td.outcomes_for(["tests/unit/test_a.py"], {"tests/unit/test_a.py::t": "xfailed"})
    assert td.criterion_status("tests", ["tests/unit/test_a.py"], o).startswith("has tests, some")
    assert td.criterion_status("untestable", [], td.outcomes_for([], {})) == "not testable in the repository"


def test_a_failing_own_command_overrides_passing_tests() -> None:
    o = td.outcomes_for(["tests/unit/test_a.py"], {"tests/unit/test_a.py::t": "passed"})
    m = {"command": "x", "answer": "y", "exit": 1, "verdict": "fails"}
    assert td.criterion_status("tests", ["tests/unit/test_a.py"], o, m) == "fails today by its own command"


def test_marker_ids_are_read_from_the_text() -> None:
    m = "mark" + ".req("  # split, so this file does not count as a marked test in the measurement
    text = f'@pytest.{m}"X1-01", "X1-02")\npytestmark = pytest.{m}\n    "X1-03",\n)\n'
    assert td.marker_ids(text) == {"X1-01", "X1-02", "X1-03"}
    assert not re.search("mark", "".join(td.marker_ids("no markers here")))

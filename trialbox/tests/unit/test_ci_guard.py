"""D-1119: the guard step of the `checks` job. The test files marked ``guard`` (their module's ``pytestmark``) are
static readers of the tree that fail when something that must not be there is; they run on every tier, as the last
steps of `checks`, with no database and no service. This file keeps it so: a marked file is ``nodb`` and asks for
no database fixture, so the step can never grow a PostgreSQL start; the workflow runs the step exactly once, the way
``make guard`` and ``make test-pure`` do; and the collection check runs over a pull request's changed test files."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"
GUARD_RUN = "-m pytest -m guard -q -n 2 tests/unit"
NO_DB = ("env -u TB_TEST_DB_URL", "TB_PG_BIN=/nonexistent")
#: the fixtures that start or reach the test PostgreSQL (tests/conftest.py); every database fixture asks for one
DB_FIXTURES = {"pg_cluster_url", "db_url"}

pytestmark = pytest.mark.nodb

#: writes, for every test the run collects, its file, whether it is ``nodb`` and the fixtures it asks for
LISTER = """\
import json, os

def pytest_collection_finish(session):
    rows = [{"file": str(i.path), "nodb": i.get_closest_marker("nodb") is not None,
             "guard": i.get_closest_marker("guard") is not None,
             "fixtures": sorted(getattr(i, "fixturenames", ()))} for i in session.items]
    with open(os.environ["TB_GUARD_LIST"], "w", encoding="utf-8") as fh:
        json.dump(rows, fh)
"""


def _module_marks(path: Path) -> set[str]:
    """The marks a module's own ``pytestmark`` names (``pytest.mark.<name>``, alone or in a list)."""
    out: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in node.targets):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Attribute) and sub.value.attr == "mark":
                    out.add(sub.attr)
    return out


def _marked_files() -> list[Path]:
    return sorted(p for p in (ROOT / "tests").rglob("test_*.py") if "guard" in _module_marks(p))


def test_the_marker_is_put_on_whole_files_and_only_under_tests_unit() -> None:
    """The list lives with the tests, one ``pytestmark`` line per file; a single test is never marked alone."""
    files = _marked_files()
    assert len(files) >= 14
    assert all(p.parent == ROOT / "tests" / "unit" for p in files), files
    for p in (ROOT / "tests").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if "mark.guard" in text and p != Path(__file__):
            assert p in files, f"{p}: pytest.mark.guard outside the module's pytestmark"


def test_a_guard_file_is_nodb_and_asks_for_no_database(tmp_path: Path) -> None:
    """The guard step needs no PostgreSQL (D-1119): every test it collects is ``nodb`` (TB_DB_URL refuses; by the
    file's own pytestmark, or PURE_MODULES of tests/conftest.py) and none asks for a fixture that starts or reaches
    the test cluster, directly or through another fixture. Collected the way the step collects them."""
    (tmp_path / "tb_guard_lister.py").write_text(LISTER, encoding="utf-8")
    out = tmp_path / "rows.json"
    env = {k: v for k, v in os.environ.items() if k not in {"TB_TEST_DB_URL", "PYTEST_ADDOPTS"}}
    env.update({"TB_PG_BIN": "/nonexistent", "TB_ENV": "TEST", "TB_GUARD_LIST": str(out),
                "PYTHONPATH": os.pathsep.join(["libs", "services", ".", str(tmp_path)])})  # fmt: skip
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "tb_guard_lister", "-m", "guard",
                        "tests/unit"], cwd=ROOT, env=env, capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    rows: list[dict[str, Any]] = json.loads(out.read_text(encoding="utf-8"))
    assert rows and all(row["guard"] for row in rows)
    assert {Path(row["file"]) for row in rows} == set(_marked_files())  # every marked file, and only those
    not_pure = sorted({row["file"] for row in rows if not row["nodb"]})
    assert not not_pure, f"a guard file must be nodb (pytestmark = [pytest.mark.guard, pytest.mark.nodb]): {not_pure}"
    with_db = sorted({f"{row['file']}: {sorted(DB_FIXTURES & set(row['fixtures']))}"
                      for row in rows if DB_FIXTURES & set(row["fixtures"])})  # fmt: skip
    assert not with_db, f"a guard test asks for the database: {with_db}"


def _checks_steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return list(doc["jobs"]["checks"]["steps"])


def test_the_checks_job_runs_the_guard_step_once_at_its_end_with_no_database() -> None:
    steps = _checks_steps()
    guard = [s for s in steps if "-m guard" in str(s.get("run", ""))]
    assert len(guard) == 1, "the guard step, exactly once"
    (step,) = guard
    run = " ".join(str(step["run"]).replace("\\\n", " ").split())
    assert GUARD_RUN in run
    for needed in NO_DB:
        assert needed in run, needed  # as `make test-pure`: no cluster can start, none is reached
    assert step.get("if") == "${{ !cancelled() }}" and not step.get("continue-on-error")
    collection = [s for s in steps if "tools.collect_stable" in str(s.get("run", ""))]
    assert len(collection) == 1
    assert steps[-2:] == [step, collection[0]]  # the last two steps of `checks`
    assert CI.read_text(encoding="utf-8").count("-m guard") == 1  # no other job or step runs it


def test_make_guard_and_make_test_pure_run_it_the_same_way() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8").replace("\\\n", " ")
    guard = text.split("\nguard:", 1)[1].split("\n\n", 1)[0]
    pure = text.split("\ntest-pure:", 1)[1].split("\n\n", 1)[0]
    for needed in NO_DB:
        assert needed in guard and needed in pure, needed
    assert "-m guard" in guard and "tests/unit" in guard and "-n 2" in guard


def _collection_script(tmp_path: Path, event: str) -> subprocess.CompletedProcess[str]:
    """The collection step's script, run in a repository of its own: the base holds one test file; the pull request
    changes it, adds one whose id carries random bytes and deletes another."""
    origin, work = tmp_path / "origin", tmp_path / "work"
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main"]
    tests = origin / "trialbox" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_kept.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tests / "test_gone.py").write_text("def test_g():\n    pass\n", encoding="utf-8")
    subprocess.run([*git, "init", "-q", str(origin)], check=True)
    subprocess.run([*git, "-C", str(origin), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(origin), "commit", "-qm", "base"], check=True)
    base = subprocess.run([*git, "-C", str(origin), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip
    subprocess.run([*git, "clone", "-q", str(origin), str(work)], check=True)
    wt = work / "trialbox"
    (wt / "tests" / "test_kept.py").write_text("def test_a():\n    pass\n\ndef test_b():\n    pass\n", "utf-8")
    (wt / "tests" / "test_new.py").write_text(
        "import os\nimport pytest\n\n@pytest.mark.parametrize('t', [os.urandom(8).hex()])\ndef test_t(t):\n"
        "    pass\n", encoding="utf-8")  # fmt: skip
    (wt / "tests" / "test_gone.py").unlink()
    subprocess.run([*git, "-C", str(work), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(work), "commit", "-qm", "card"], check=True)
    # the job's .venv and the tool, as the checked-out trialbox/ holds them
    venv = wt / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    (venv / "python").chmod(0o755)
    (wt / "tools").symlink_to(ROOT / "tools")
    (step,) = [s for s in _checks_steps() if "tools.collect_stable" in str(s.get("run", ""))]
    assert step["env"] == {"EVENT": "${{ github.event_name }}", "BASE": "${{ github.event.pull_request.base.sha }}"}
    runner = tmp_path / "runner"
    runner.mkdir()
    env = {"EVENT": event, "BASE": base if event == "pull_request" else "", "RUNNER_TEMP": str(runner),
           "PATH": os.environ["PATH"], "HOME": str(tmp_path)}  # fmt: skip
    return subprocess.run(["bash", "-eo", "pipefail", "-c", step["run"]], cwd=wt, env=env, capture_output=True,
                          text=True, check=False)  # fmt: skip


def test_the_collection_step_checks_a_pull_requests_changed_test_files(tmp_path: Path) -> None:
    r = _collection_script(tmp_path, "pull_request")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tests/test_new.py::test_t[" in r.stderr  # the unstable id is named
    assert "test_kept" not in r.stderr and "test_gone" not in r.stdout + r.stderr  # the deleted file is left out
    changed = (tmp_path / "runner" / "tests-changed").read_text(encoding="utf-8").split()
    assert changed == ["tests/test_kept.py", "tests/test_new.py"]  # relative to trialbox/, as the tool is run there


def test_the_collection_step_says_why_a_push_has_nothing_to_compare(tmp_path: Path) -> None:
    r = _collection_script(tmp_path, "push")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "not a pull request" in r.stdout and "tools.test_shard check" in r.stdout

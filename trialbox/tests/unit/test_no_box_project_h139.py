"""H-139 (the integrator's 7161352305): no test or drill that drives a real engine names the box's own compose project
(``trialbox``) or its volumes (``trialbox_<volume>``).

A test stack and a box can share one host, as on the bench host. Push 5 moved the test stack to its own project
(``trialbox-test``), but the restore drill went on reading and removing ``trialbox_<volume>``: on such a host, those
are the box's own volumes. The files below talk to a real engine: the drills, the stack helpers, and the e2e and
integration tests. Their code (not their docstrings or comments) may name no box project and no box volume. The unit
tests are outside this rule: they hand the product fakes, and a box called ``trialbox`` is the very case they check.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]

#: a box volume (``trialbox_db-data``, ``trialbox_{v}``, ``trialbox_<v>``; never a database such as ``trialbox_wf``),
#: and the box's project given to compose (``-p``, ``--project-name``, COMPOSE_PROJECT_NAME)
NAMES = tuple(re.compile(p) for p in (
    r"\btrialbox_(?:\{|<|[a-z0-9]+-[a-z0-9-]*)",
    r"-p[\"',\s]+trialbox(?![-\w])",
    r"--project-name[\"',=\s]+trialbox(?![-\w])",
    r"COMPOSE_PROJECT_NAME[^\n]{0,40}?[\"'=]trialbox(?![-\w])",
))  # fmt: skip

#: push 5's restore drill (d5fb59cbc), the lines that named the box's volumes
PUSH5_RESTORE_DRILL = '''
def vol(self, name):
    """The volume's data folder."""
    return DOCKER_VOLUMES / f"trialbox_{name}" / "_data"

def wipe(self):
    by_name = [v for v in VOLUMES if (DOCKER_VOLUMES / f"trialbox_{v}").exists()]  # a box's, on a shared host
    for v in by_name:
        self.sh(f"docker volume rm -f trialbox_{v}", timeout=120)
    left = [v for v in VOLUMES if (DOCKER_VOLUMES / f"trialbox_{v}").exists()]
'''


def engine_files() -> list[Path]:
    """The tests and drills that drive a real engine."""
    files = [ROOT / "tests" / "stack.py", ROOT / "tests" / "conftest.py", *sorted((ROOT / "tools").glob("*drill*.py"))]
    for folder in ("e2e", "integration"):
        files += sorted((ROOT / "tests" / folder).rglob("*.py"))
    return [f for f in files if "__pycache__" not in f.parts]


def code_lines(src: str) -> list[tuple[int, str]]:
    """Each line of ``src`` without its docstrings and comments, by line number."""
    docs: set[int] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docs.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    comments = {t.start[0]: t.start[1] for t in tokenize.generate_tokens(io.StringIO(src).readline)
                if t.type == tokenize.COMMENT}  # fmt: skip
    return [(n, line[: comments.get(n, len(line))]) for n, line in enumerate(src.splitlines(), 1) if n not in docs]


def box_names(src: str) -> list[str]:
    return [f"{n}: {line.strip()}" for n, line in code_lines(src) if any(p.search(line) for p in NAMES)]


def test_no_test_or_drill_that_drives_an_engine_names_the_boxs_project_or_volumes() -> None:
    found = {
        str(f.relative_to(ROOT)): hits for f in engine_files() if (hits := box_names(f.read_text(encoding="utf-8")))
    }
    assert found == {}


def test_the_check_would_have_stopped_push_5s_restore_drill() -> None:
    hits = box_names(PUSH5_RESTORE_DRILL)
    assert len(hits) == 4 and all("trialbox_{" in h for h in hits), hits


@pytest.mark.parametrize("line", ['["docker", "compose", "-p", "trialbox", "ps"]', '"docker compose -p trialbox ps"',
                                  'os.environ.get("COMPOSE_PROJECT_NAME") or "trialbox"', "f'--project-name={x}'",
                                  '"COMPOSE_PROJECT_NAME=trialbox make up"', '"docker volume rm trialbox_db-data"'])  # fmt: skip
def test_each_way_of_naming_the_box_is_seen(line: str) -> None:
    expected = 0 if "{x}" in line else 1
    assert len(box_names(f"x = {line}\n")) == expected, line


@pytest.mark.parametrize("line", ['"-p", "trialbox-test"', '"trialbox_wf"', 'f"{TEST_PROJECT}_{name}"',
                                  '{"POSTGRES_USER": "trialbox"}'])  # fmt: skip
def test_the_test_project_a_database_and_text_are_not_the_box(line: str) -> None:
    assert box_names(f"x = {line}  # trialbox_{{v}} in a comment\n") == [], line


def test_a_docstring_may_name_the_box() -> None:
    assert box_names('def f():\n    """reads trialbox_{v}, a box\'s own"""\n') == []


def test_the_rule_covers_the_drills_and_the_stack_helpers() -> None:
    names = {f.name for f in engine_files()}
    assert {
        "restore_drill.py",
        "failure_drill_box.py",
        "stack.py",
        "test_mail_compose.py",
        "test_compose_data.py",
    } <= names

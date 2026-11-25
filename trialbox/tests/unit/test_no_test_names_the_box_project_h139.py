"""H-139 (the integrator's 7161352305, OCR 1498-1): no test or drill reaches the box's own compose project
(``trialbox``) or its volumes (``trialbox_<volume>``).

A test stack and a box can share one host, as on the bench host. Push 5 moved the test stack to its own project
(``trialbox-test``), but the restore drill went on reading and removing ``trialbox_<volume>``. Push 6 fixed the drill's
own commands, but the nightly backup the drill runs still read ``trialbox_<volume>`` written into the product: on such
a host, the box's sign-in data and TLS keys. Three guards:

- (a) behaviour: the nightly backup's host part reads the volumes of the project its box file names, never a
  caller's, never the box's when the box file names the test stack's (``restore_drill.prepare`` writes it);
- (b) every compose command the suite runs (``subprocess`` in the tests; the drills' own runners; the Makefile's test
  recipes) names a project;
- (c) the files that drive a real engine (the drills, ``tools/full_set.py``, the stack helpers, the e2e and
  integration tests) name no box project and no box volume in their code (not their docstrings or comments).

The unit tests' text is outside (c): they build fake ``trialbox_<volume>`` trees under their own temporary folder
and check what the product does on a box called ``trialbox``, the default. (b) covers what they run.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

from tools import restore_drill as rd
from tools.trialbox import backup_schedule as bs

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
    files = [ROOT / "tests" / "stack.py", ROOT / "tests" / "conftest.py", ROOT / "tools" / "full_set.py",
             *sorted((ROOT / "tools").glob("*drill*.py"))]  # fmt: skip
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


# --------------------------------------------------------------------------------------------- (a) the behaviour
def test_the_drills_backup_reads_the_test_stacks_volumes_never_the_boxs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OCR 1498-1's test: the nightly's host part, on a host that holds both projects' volumes."""
    vols = tmp_path / "volumes"
    for project in ("trialbox", "trialbox-test"):
        (vols / f"{project}_caddy-data" / "_data").mkdir(parents=True)
        (vols / f"{project}_caddy-data" / "_data" / f"{project}.key").write_text("synthetic", encoding="utf-8")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=TEST\nCOMPOSE_PROJECT_NAME=trialbox-test\n", encoding="utf-8")
    monkeypatch.setenv("TB_DOCKER_VOLUMES", str(vols))
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "trialbox-test")  # what restore_drill.shell exports
    bs.ComposeOps(deploy, run=lambda *a, **k: "").host_files(tmp_path / "dest")
    assert sorted(p.name for p in (tmp_path / "dest").rglob("*.key")) == ["trialbox-test.key"]


def test_a_callers_project_never_moves_the_boxs_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F1: the box file decides. A box whose file names no project reads ``trialbox_<volume>``, whatever is exported."""
    vols = tmp_path / "volumes"
    for project in ("trialbox", "tbfullset"):
        (vols / f"{project}_caddy-data" / "_data").mkdir(parents=True)
        (vols / f"{project}_caddy-data" / "_data" / f"{project}.key").write_text("synthetic", encoding="utf-8")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    monkeypatch.setenv("TB_DOCKER_VOLUMES", str(vols))
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "tbfullset")  # the bench runner's export
    bs.ComposeOps(deploy, run=lambda *a, **k: "").host_files(tmp_path / "dest")
    assert sorted(p.name for p in (tmp_path / "dest").rglob("*.key")) == ["trialbox.key"]
    env = {"COMPOSE_PROJECT_NAME": "trialbox-test", "TB_DOCKER_VOLUMES": str(vols)}
    assert bs.host_volume(env, "lake-data") == vols / "trialbox-test_lake-data" / "_data"
    assert bs.host_volume({"TB_DOCKER_VOLUMES": str(vols)}, "lake-data") == vols / "trialbox_lake-data" / "_data"


def test_the_drill_writes_the_test_stacks_project_into_its_box_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "deploy").mkdir()
    test_file = "docker-compose.test.yml"
    (tmp_path / "deploy" / test_file).write_bytes((ROOT / "deploy" / test_file).read_bytes())  # the objects setting
    (tmp_path / ".env.example").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    monkeypatch.setattr(rd, "ROOT", tmp_path)  # prepare makes deploy/.env from .env.example: never the checkout's
    got: dict[str, str] = {}

    def set_env(_file: Path, key: str, value: str) -> None:
        got[key] = value

    assert "COMPOSE_PROJECT_NAME" in rd.prepare(set_env)
    assert got["COMPOSE_PROJECT_NAME"] == rd.TEST_PROJECT == "trialbox-test"


# ------------------------------------------------------------------------- (b) every compose command names a project
RUNNERS_IN_TESTS = {"run", "Popen", "check_output", "check_call", "call"}  # as subprocess.<name>
RUNNERS_IN_DRILLS = RUNNERS_IN_TESTS | {"sh", "shell", "run_cmd", "compose"}
PROJECT_WORDS = ("-p", "--project-name")
PROJECT_NAMES = ("COMPOSE_PROJECT_NAME", "TEST_PROJECT", "COMPOSE_TEST")
READ_ONLY = ("config", "version")  # render or report: no container, no volume


def _words(node: ast.AST) -> list[str]:
    out: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out += n.value.split()
        elif isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
    return out


def unnamed_compose_runs(src: str, drill: bool) -> list[str]:
    """Each call in ``src`` that runs ``docker compose`` with no project named in its arguments or environment."""
    hits = []
    for n in ast.walk(ast.parse(src)):
        if not (isinstance(n, ast.Call) and n.args):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        real = (drill and name in RUNNERS_IN_DRILLS) or (
            isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "subprocess"
            and name in RUNNERS_IN_TESTS)  # fmt: skip
        first = _words(n.args[0])
        if not real or "docker" not in first or "compose" not in first or any(w in first for w in READ_ONLY):
            continue
        every = _words(n)
        if not any(w in every for w in PROJECT_WORDS) and not any(p in every for p in PROJECT_NAMES):
            hits.append(f"{n.lineno}: {ast.unparse(n)[:140]}")
    return hits


def _suite_files() -> list[tuple[Path, bool]]:
    tests = [(f, False) for f in sorted((ROOT / "tests").rglob("*.py")) if "__pycache__" not in f.parts]
    drills = [(f, True) for f in [ROOT / "tools" / "full_set.py", *sorted((ROOT / "tools").glob("*drill*.py"))]]
    return tests + drills


def test_every_compose_command_the_suite_runs_names_a_project() -> None:
    found = {str(f.relative_to(ROOT)): hits for f, drill in _suite_files()
             if (hits := unnamed_compose_runs(f.read_text(encoding="utf-8"), drill))}  # fmt: skip
    assert found == {}


def test_the_makefiles_test_recipes_run_compose_only_as_the_test_stack() -> None:
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^TEST_PROJECT := (trialbox-[a-z0-9-]+)$", mk, re.M)
    assert re.search(r"^COMPOSE_TEST := .*-p \$\(TEST_PROJECT\)", mk, re.M)
    target, bad = "", []
    for line in mk.splitlines():
        if m := re.match(r"^([A-Za-z0-9_.-]+):", line):
            target = m.group(1)
        elif line.startswith("\t") and ("test" in target or "$(COMPOSE_TEST)" in line):
            runs = "$(COMPOSE)" in line or re.search(r"docker[ -]compose", line)
            if runs and "$(COMPOSE_TEST)" not in line and not re.search(r"(-p|--project-name)[ =]", line):
                bad.append(f"{target}: {line.strip()[:120]}")
    assert bad == []


@pytest.mark.parametrize(("src", "drill", "seen"), [
    ('subprocess.run(["docker", "compose", "up", "-d"])', False, 1),
    ('subprocess.run(["docker", "compose", "-p", "trialbox-test", "up"])', False, 0),
    ('subprocess.run(["docker", "compose", "config"])', False, 0),
    ('run(["docker", "compose", "up"])', False, 0),  # a test's own fake runner
    ('self.sh("docker compose down --volumes")', True, 1),
    ('self.sh(f"docker compose -p {TEST_PROJECT} down")', True, 0),
    ('subprocess.run("docker compose ps", shell=True, env={"COMPOSE_PROJECT_NAME": TEST_PROJECT})', False, 0),
])  # fmt: skip
def test_each_form_of_a_compose_run_is_judged(src: str, drill: bool, seen: int) -> None:
    assert len(unnamed_compose_runs(src, drill)) == seen, src


# ------------------------------------------------------------------- (c) no box project or volume in the engine files
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

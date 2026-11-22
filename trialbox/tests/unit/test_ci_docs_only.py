"""CI-DOCS (D-969): a card's pull request that changes only documents runs the fast tier; the tests that read the
changed documents run in the fast tier's `cross-card` job; a merge train runs everything, whatever it holds.
CI throughput, measured on #639 on 2026-11-16: a docs-only pull request ran all 24 jobs, about 133 runner-minutes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import ci_docs_only as cdo

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize(
    ("paths", "docs_only"),
    [
        (["trialbox/docs/runbook/21-support-model-and-the-supervised-remote-session.md"], True),
        (["trialbox/docs/decisions/D-1-x.md", "trialbox/docs/decisions/REGISTRY.md"], True),
        (["trialbox/README.md", "README.md"], True),
        (["trialbox/docs/plan/sites/archive/commitments.csv"], True),  # any file under docs/
        (["trialbox/docs/licences/register.csv"], False),  # read by the licence check and copied into the image
        (["trialbox/docs/runbook/x.md", "trialbox/tools/keys.py"], False),
        (["trialbox/NOTICE"], False),
        (["trialbox/tests/unit/test_wording.py"], False),
        (["trialbox/docs/validation/model-change-protocol.md"], False),  # the image carries it; qualify reads it
        ([".github/workflows/trialbox-ci.yml"], False),
        ([], False),  # nothing changed: not a docs-only change (the normal rules decide)
    ],
)
def test_what_is_docs_only(paths: list[str], docs_only: bool) -> None:
    assert cdo.docs_only(paths) is docs_only


def test_the_documents_the_image_carries_are_not_docs_only() -> None:
    """A document copied into an image is read by code there: its change runs the full tier."""
    dockerfiles = [ROOT / "deploy/docker/python.Dockerfile", ROOT / "demo/Dockerfile"]
    carried = set()
    for f in dockerfiles:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("COPY") and " docs/" in line:
                carried |= {w for w in line.split() if w.startswith("docs/")}
    for doc in carried:
        assert not cdo.docs_only([f"trialbox/{doc.rstrip('/')}"]), doc


def test_the_tests_that_read_a_changed_document(tmp_path: Path) -> None:
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_a.py").write_text('PAGE = "docs/runbook/21-support.md"\n', encoding="utf-8")
    (tests / "test_b.py").write_text('RUNBOOK = ROOT / "docs/runbook"\n', encoding="utf-8")
    (tests / "test_c.py").write_text('X = "21-support.md"\n', encoding="utf-8")
    (tests / "test_d.py").write_text('Y = "docs/plan/33-plan-v7.md"\n', encoding="utf-8")
    (tests / "helper.py").write_text('Z = "docs/runbook/21-support.md"\n', encoding="utf-8")  # not a test file
    got = cdo.tests_for(["trialbox/docs/runbook/21-support.md"], tmp_path)
    assert got == ["tests/unit/test_a.py", "tests/unit/test_b.py", "tests/unit/test_c.py"]
    assert cdo.tests_for(["trialbox/docs/plan/33-plan-v7.md"], tmp_path) == ["tests/unit/test_d.py"]
    # "docs" alone (a document at the top of docs/) is not a folder needle: it would name every test
    (tests / "test_e.py").write_text('W = ROOT / "docs"\n', encoding="utf-8")
    assert cdo.tests_for(["trialbox/docs/GLOSSARY.md"], tmp_path) == []


def test_on_this_tree_a_runbook_page_has_its_tests() -> None:
    got = cdo.tests_for(["trialbox/docs/runbook/21-support-model-and-the-supervised-remote-session.md"], ROOT)
    assert "tests/unit/test_operations_docs.py" in got


def test_a_folder_is_named_by_itself_not_by_another_document_in_it(tmp_path: Path) -> None:
    """H-81: a test that names ``docs/reviews/<another page>`` does not read a new page beside it; one that names the
    folder (alone, as a glob, or with a name to fill in) may."""
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_cites.py").write_text('"""Card AD-5 of ``docs/reviews/2026-11-12-architecture.md``."""\n', "utf-8")
    (tests / "test_folder.py").write_text('PAGES = ROOT / "docs/reviews"\n', encoding="utf-8")
    (tests / "test_glob.py").write_text('PAGES = ROOT.glob("docs/reviews/*.md")\n', encoding="utf-8")
    (tests / "test_fstr.py").write_text('PAGE = f"docs/reviews/{name}"\n', encoding="utf-8")
    (tests / "test_page.py").write_text('PAGE = "docs/reviews/2026-11-22-new.md"\n', encoding="utf-8")
    got = cdo.tests_for(["trialbox/docs/reviews/2026-11-22-new.md"], tmp_path)
    assert got == ["tests/unit/test_folder.py", "tests/unit/test_fstr.py", "tests/unit/test_glob.py",
                   "tests/unit/test_page.py"]  # fmt: skip


def test_on_this_tree_a_review_page_selects_no_property_test() -> None:
    """H-81: #1327 and #1332 added a page under ``docs/reviews/``; the folder needle pulled in
    ``tests/property/test_path_independence.py`` (its docstring cites a review), which the `cross-card` job, without
    fonts, cannot run. The pages that read a folder's documents keep their tests."""
    got = cdo.tests_for(["trialbox/docs/reviews/2026-11-22-a-new-review.md"], ROOT)
    assert not [t for t in got if t.startswith(("tests/property/", "tests/e2e/", "tests/perf/"))], got
    handover = cdo.tests_for(["trialbox/docs/handover/findings-register.md"], ROOT)
    assert "tests/unit/test_findings_register.py" in handover


def test_only_the_strings_of_a_tests_code_select_it(tmp_path: Path) -> None:
    """H-87: a docstring (of the module, a class or a function) or a comment that cites a page does not make a test
    of that page; a string of the code that names it does, an f-string's literal part too. A file that does not
    parse is matched on its whole text, never left out."""
    page = "docs/reviews/2026-11-12-architecture/decision.md"
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    files = {
        "test_module_doc.py": f'"""Card AD-5 of ``{page}``."""\nX = 1\n',
        "test_class_doc.py": f'class TestA:\n    """As ``{page}`` says."""\n',
        "test_func_doc.py": f'def test_a() -> None:\n    """As ``{page}`` says."""\n',
        "test_async_doc.py": f'async def test_a() -> None:\n    """As ``{page}`` says."""\n',
        "test_comment.py": f"X = 1  # {page}\n",
        "test_reads.py": f'"""A page of the architecture review."""\nPAGE = ROOT / "{page}"\n',
        "test_reads_in_func.py": f'def test_a() -> None:\n    """Reads it."""\n    read("{page}")\n',
        "test_fstring.py": f'PAGE = f"{page}?{{n}}"\n',
        "test_no_parse.py": f'PAGE = "{page}"\ndef broken(:\n',
    }
    for name, text in files.items():
        (tests / name).write_text(text, encoding="utf-8")
    got = cdo.tests_for([f"trialbox/{page}"], tmp_path)
    assert got == [f"tests/unit/{n}" for n in ("test_fstring.py", "test_no_parse.py", "test_reads.py",
                                                "test_reads_in_func.py")]  # fmt: skip
    assert cdo.code_strings('"""doc"""\nX = "a"  # b\n') == "a"


def test_on_this_tree_a_review_page_cited_in_a_docstring_selects_no_property_test() -> None:
    """H-87: ``tests/property`` cites ``docs/reviews/2026-11-12-architecture/decision.md`` in docstrings only, so a
    change to that page does not select them (the `cross-card` job, without fonts, cannot run them)."""
    got = cdo.tests_for(["trialbox/docs/reviews/2026-11-12-architecture/decision.md"], ROOT)
    assert not [t for t in got if t.startswith("tests/property/")], got


def test_the_command_line() -> None:
    def run(*args: str, stdin: str) -> str:
        r = subprocess.run([sys.executable, str(ROOT / "tools/ci_docs_only.py"), *args], input=stdin, text=True,
                           capture_output=True, check=True, cwd=ROOT.parent)  # fmt: skip
        return r.stdout.strip()

    page = "trialbox/docs/runbook/21-support-model-and-the-supervised-remote-session.md\n"
    assert run("docs-only", stdin=page) == "true"
    assert run("docs-only", stdin=page + "trialbox/tools/keys.py\n") == "false"
    assert "tests/unit/test_operations_docs.py" in run("tests", stdin=page).split()
    assert run("tests", stdin="trialbox/tools/keys.py\n") == ""  # not docs-only: no list (the full tier runs them)


def test_the_tool_needs_only_the_standard_library() -> None:
    """It runs in the `changes` job with the runner's python3, before any environment is made."""
    text = (ROOT / "tools/ci_docs_only.py").read_text(encoding="utf-8")
    imports = {ln.split()[1].split(".")[0] for ln in text.splitlines() if ln.startswith(("import ", "from "))}
    assert imports <= {"__future__", "ast", "re", "sys", "pathlib", "collections"}, imports


def _wf() -> dict[Any, Any]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_the_workflow_wires_it() -> None:
    jobs = _wf()["jobs"]
    changes = jobs["changes"]
    assert changes["outputs"]["docs_tests"] == "${{ steps.diff.outputs.docs_tests }}"
    diff = next(s for s in changes["steps"] if s.get("id") == "diff")["run"]
    assert "tools/ci_docs_only.py docs-only" in diff and "tools/ci_docs_only.py tests" in diff
    tier = next(s for s in changes["steps"] if s.get("id") == "tier")
    assert tier["env"]["DOCS_ONLY"] == "${{ steps.diff.outputs.docs_only }}"
    step = next(s for s in jobs["cross-card"]["steps"] if "DOCS_TESTS" in s.get("env", {}))
    assert step["env"]["DOCS_TESTS"] == "${{ needs.changes.outputs.docs_tests }}"
    assert 'CROSS_CARD_TESTS="$DOCS_TESTS"' in step["run"] and "make cross-card" in step["run"]

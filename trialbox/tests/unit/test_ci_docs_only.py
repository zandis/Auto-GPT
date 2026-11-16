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
    assert imports <= {"__future__", "re", "sys", "pathlib", "collections"}, imports


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

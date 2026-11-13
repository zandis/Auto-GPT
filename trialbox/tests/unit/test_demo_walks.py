"""DEMO-WALKS (D-626): the demo walks (``tools.cgmh_demo``) state their own environment, as the served demo does,
and CI runs every one of them. Found by running: in the demo image, which sets no ``TB_ENV``, the registry walk's
box counted as PRODUCTION and the study's EDC page refused to make its key; CI ran one walk of three."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tools import cgmh_demo

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"

pytestmark = pytest.mark.nodb


def test_a_walk_with_no_environment_set_is_a_dev_box_and_says_so() -> None:
    env: dict[str, str] = {}
    line = cgmh_demo.state_environment(env)
    assert env["TB_ENV"] == "DEV"
    assert "DEV" in line and "synthetic" in line


@pytest.mark.parametrize("name", ["PRODUCTION", "VALIDATION", "TEST"])
def test_a_caller_that_names_an_environment_is_obeyed(name: str) -> None:
    """The walk must not hide the PRODUCTION rules from someone who asks for them."""
    env = {"TB_ENV": name}
    line = cgmh_demo.state_environment(env)
    assert env["TB_ENV"] == name and name in line


def test_the_environment_is_stated_before_the_box_is_built() -> None:
    src = Path(cgmh_demo.__file__).read_text(encoding="utf-8")
    main = src[src.index("def main(") :]
    assert main.index("state_environment(os.environ)") < main.index("run(a.dir")


def test_the_image_does_not_decide_the_environment_for_everything_run_in_it() -> None:
    """An ENV TB_ENV in the image would make a product path run in it DEV as well."""
    text = (ROOT / "demo" / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^\s*ENV\b.*\bTB_ENV\b", text, re.M)


def _demo_boot_runs() -> str:
    if not WORKFLOW.is_file():
        pytest.skip("workflows not in this checkout")
    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["demo-boot"]
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_ci_runs_every_walk_the_tool_has_in_every_language() -> None:
    runs = _demo_boot_runs()
    walks = re.search(r"for walk in ([^;\n]+);", runs)
    langs = re.search(r"for lang in ([^;\n]+);", runs)
    assert walks and langs, "the demo-boot job loops over the walks and the languages"
    assert set(walks.group(1).split()) == set(cgmh_demo.WALKS)
    assert set(langs.group(1).split()) == {"ja", "zh-TW", "en"}
    assert '--walk "$walk" --lang "$lang"' in runs
    assert "TB_ENV" not in runs  # CI runs the walks as a guest would: nothing set from outside

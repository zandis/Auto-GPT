"""ENG-003 (D-563): the release gates on the embed image. The image holds no packaging tool the service never
calls (torch names setuptools for its compile helpers; setuptools carries an LGPL part and Windows launchers); the
licence reader knows the names the embedder's libraries use for permissive licences; the three wheels that carry
no licence field are in the reviewed list with the licence their own files state."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from tools.supply_chain import allowlist, licences

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def test_the_image_does_not_keep_setuptools() -> None:
    df = (ROOT / "deploy" / "docker" / "embed.Dockerfile").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in df.splitlines() if not ln.lstrip().startswith("#"))
    run = code[code.index("RUN ") : code.index("\nENV ")]
    assert "--require-hashes" in run and "pip uninstall -y setuptools" in run  # one layer: it never ships in one
    assert code.count("RUN ") == 1


@pytest.mark.parametrize("name", ["BSD", "Apache 2.0 License", "Apache-2.0 AND CNRI-Python", "CNRI-Python"])
def test_the_reader_knows_these_names_of_permissive_licences(name: str) -> None:
    assert licences.classify(name).flags <= {"ok"}, name


def test_cnri_python_is_accepted_and_is_not_offered_as_a_choice() -> None:
    assert "cnri-python" in licences.OTHER_OK and "cnri-python" not in licences.PERMISSIVE


@pytest.mark.parametrize(
    ("package", "licence"),
    [("markdown-it-py", "MIT"), ("safetensors", "Apache-2.0"), ("tokenizers", "Apache-2.0")],
)
def test_wheels_without_a_licence_field_are_in_the_reviewed_list(package: str, licence: str) -> None:
    allow, problems = allowlist.load(ROOT / "deploy" / "supply-chain-allowlist.yaml", today=dt.date(2026, 11, 12))
    assert problems == []
    doc = {
        "metadata": {"component": {"name": "trialbox-embed:1.0.0"}},
        "components": [{"type": "library", "name": package, "version": "1", "purl": f"pkg:pypi/{package}@1"}],
    }
    gate = licences.evaluate({"trialbox-embed:1.0.0": doc}, allow)
    assert gate.ok, licences.render(gate)
    text = (ROOT / "deploy" / "supply-chain-allowlist.yaml").read_text(encoding="utf-8")
    entry = text[text.index(f"  - package: {package}\n") :].split("\n  - ", 1)[0]
    assert f"licence: {licence} " in entry and "trialbox-embed" in entry

"""CI-TIER (D-970): which tier a CI run gets. A card's pull request runs the fast tier unless it changes a path on
``FULL_TIER`` (decides about a patient, guards patient data, sends files out, seals keys, the contracts, the gate) or
carries the label ``ci:full``; a train, master and a run by hand run everything. ``CARD_TIER=touched`` reverts the
trial to D. The workflow's step is run as the runner runs it in test_ci_tiers.py; this file checks the list and the
rule."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import ci_tier as ct

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.nodb


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT.parent, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def test_every_pattern_still_matches_a_file() -> None:
    """A renamed folder fails here instead of silently leaving the list."""
    files = _tracked()
    dead = [pat for pat in ct.FULL_TIER if not any(ct.matches(f, pat) for f in files)]
    assert not dead, f"no tracked file matches: {dead}"
    assert len(set(ct.FULL_TIER)) == len(ct.FULL_TIER)


def test_the_list_guards_itself() -> None:
    assert ct.on_full_tier(["trialbox/tools/ci_tier.py", ".github/workflows/trialbox-ci.yml"]) == [
        "trialbox/tools/ci_tier.py",
        ".github/workflows/trialbox-ci.yml",
    ]


def test_a_folder_pattern_takes_the_folder_only() -> None:
    assert ct.matches("trialbox/services/edc/client.py", "trialbox/services/edc/**")
    assert ct.matches("trialbox/services/edc/a/b.py", "trialbox/services/edc/**")
    assert not ct.matches("trialbox/services/edcx/client.py", "trialbox/services/edc/**")
    assert not ct.matches("trialbox/services/lake/build.py", "trialbox/services/lake/store.py")


def _env(**kw: str) -> dict[str, str]:
    return {"EVENT": "pull_request", "DRAFT": "false", "HEAD_REF": "agent/T-1-x", "CARD_TIER": "fast", **kw}


@pytest.mark.parametrize(
    ("env", "paths", "full", "scenarios"),
    [
        (_env(), ["trialbox/services/lake/build.py"], False, False),
        (_env(), ["trialbox/services/matching/engine.py"], True, True),
        (_env(LABELS="bug\nci:full\n"), ["trialbox/services/lake/build.py"], True, True),
        (_env(DOCS_ONLY="true"), ["trialbox/docs/x.md"], False, False),
        (_env(DOCS_ONLY="true", LABELS="ci:full"), ["trialbox/docs/x.md"], True, True),
        (_env(DRAFT="true"), ["trialbox/services/matching/engine.py"], False, False),
        (_env(HEAD_REF="train/12"), [], True, True),
        (_env(EVENT="push"), [], True, True),
        (_env(EVENT="push", PROVED="true"), [], False, False),
        (_env(EVENT="workflow_dispatch"), [], True, True),
        (_env(CARD_TIER="touched"), ["trialbox/services/lake/build.py"], True, True),
        (_env(CARD_TIER="touched"), ["trialbox/deploy/install.sh", ".github/x.yml"], True, False),
        (_env(CARD_TIER="touched"), ["trialbox/tools/keys.py"], True, True),  # on the list
        (_env(CARD_TIER="touched"), [], True, True),  # no paths read: never a reduced run
        (_env(CARD_TIER="Fast"), ["trialbox/services/lake/build.py"], True, True),  # unknown: the full tier
        (_env(CARD_TIER=""), ["trialbox/services/lake/build.py"], False, False),  # unset: the trial
    ],
)
def test_the_rule(env: dict[str, str], paths: list[str], full: bool, scenarios: bool) -> None:
    got = ct.decide(env, paths)
    assert got[:2] == (full, scenarios), got[2]
    assert got[2]  # the log says why


def test_the_command_line(tmp_path: Path) -> None:
    import os
    import sys

    env = {**os.environ, **_env(), "LABELS": ""}
    res = subprocess.run([sys.executable, str(ROOT / "tools/ci_tier.py")], input="trialbox/services/edc/a.py\n",
                         env=env, capture_output=True, text=True, check=True)  # fmt: skip
    assert res.stdout.split() == ["full=true", "scenarios=true", "unit=true"]  # H-120 (D-1357): unit on every PR
    assert "full-tier list" in res.stderr
    assert "guard tests" in res.stderr  # D-1119: the log names the guard step every tier runs


def test_the_wording_names_the_guard_step_and_the_rule_is_unchanged() -> None:
    """D-1119 changed the words, not the rule: the fast tier's `checks` ends with the guard step."""
    assert ct.__doc__ is not None and "guard" in ct.__doc__ and "make guard" in ct.__doc__
    assert "checks" in ct.GUARD_NOTE and "D-1119" in ct.GUARD_NOTE
    assert ct.decide(_env(), ["trialbox/tests/unit/test_site_tz.py"])[:2] == (False, False)  # a marked file: fast

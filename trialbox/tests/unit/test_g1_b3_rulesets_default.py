"""G1 B3 (D-469): the compiler never writes the source ``rulesets/`` folder.

With no ``TB_RULESETS_DIR`` the services' ruleset folder is ``<TB_DATA_DIR>/rulesets``, seeded from the checkout's
``rulesets/`` (which stays as it was). One default, the same one the settings table declares.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from criteria_compiler.repo import RulesetRepo
from tb_common.config import DECLARED, REPO_ROOT, Env, get_config

from tests.rulesets_guard import RULESETS, describe, snapshot


@pytest.fixture
def _fresh() -> object:
    get_config.cache_clear()
    yield None
    get_config.cache_clear()


def test_default_is_under_the_data_dir_not_the_checkout(tmp_path: Path) -> None:
    env = Env(data_dir=str(tmp_path))
    assert env.rulesets_path == tmp_path / "rulesets"
    assert REPO_ROOT not in env.rulesets_path.parents


def test_declared_default_is_the_code_default() -> None:
    assert DECLARED["TB_RULESETS_DIR"].default == "/data/rulesets"
    assert Env().rulesets_path == Path("/data/rulesets")


def test_an_explicit_folder_still_wins(tmp_path: Path) -> None:
    assert Env(data_dir="/data", rulesets_dir=str(tmp_path / "x")).rulesets_path == tmp_path / "x"


@pytest.mark.usefixtures("_fresh")
def test_a_compile_with_the_default_folder_leaves_the_checkout_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compiler's repository on the default folder: seeded, a ruleset re-materialised, the checkout untouched."""
    monkeypatch.delenv("TB_RULESETS_DIR", raising=False)
    monkeypatch.setenv("TB_DATA_DIR", str(tmp_path))
    get_config.cache_clear()
    path = get_config().env.rulesets_path
    before = snapshot(RULESETS)
    repo = RulesetRepo(path, RULESETS)
    repo.materialize("GOUT-COH", "main")
    after = snapshot(RULESETS)
    assert after == before, describe(before, after)
    assert not (RULESETS / ".git").exists()
    assert (path / ".git").exists()
    assert (path / "GOUT-COH" / "manifest.yaml").is_file()

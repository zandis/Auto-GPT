"""D-1119: the collection check. pytest collects the same test files twice; an id that differs (the clock or random
bytes rendered into a parametrize id) fails in seconds, naming the id, instead of in ``tools.test_shard check`` after
the shards of the full tier."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import collect_stable as cs

pytestmark = pytest.mark.nodb

STABLE = """\
import pytest

@pytest.mark.parametrize("word", ["alpha", "beta"])
def test_word(word):
    assert word
"""
#: a deliberately unstable id: the random bytes are rendered into the id of the one case
UNSTABLE = """\
import os

import pytest

@pytest.mark.parametrize("token", [os.urandom(8).hex()])
def test_token(token):
    assert token

def test_plain():
    pass
"""


@pytest.fixture
def here(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder of its own, outside the repository (no conftest, no ini), as the working directory; the shards'
    PYTEST_ADDOPTS (coverage, durations) is not for the collections this test starts."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    return tmp_path


def test_an_id_that_carries_random_bytes_fails_and_is_named(here: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (here / "test_unstable.py").write_text(UNSTABLE, encoding="utf-8")
    (here / "test_stable.py").write_text(STABLE, encoding="utf-8")
    assert cs.main(["test_stable.py", "test_unstable.py"]) == 1
    err = capsys.readouterr().err
    named = [ln.strip() for ln in err.splitlines() if ln.startswith("  ")]
    assert len(named) == 2 and all(n.startswith("test_unstable.py::test_token[") for n in named)  # one per run
    assert "test_plain" not in err and "test_word" not in err  # the stable ids are not named


def test_stable_ids_pass(here: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (here / "test_stable.py").write_text(STABLE, encoding="utf-8")
    assert cs.main(["test_stable.py"]) == 0
    assert "2 test id(s) of 1 file(s), the same in two collections" in capsys.readouterr().out


def test_paths_that_are_no_test_file_are_left_out(here: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A deleted test, a helper module, a fixture file: nothing to collect, and it says so."""
    (here / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    (here / "test_data.json").write_text("{}", encoding="utf-8")
    assert cs.test_files(["helpers.py", "test_gone.py", "test_data.json"]) == []
    assert cs.main(["helpers.py", "test_gone.py"]) == 0
    assert "nothing to compare" in capsys.readouterr().out
    assert cs.main([]) == 0


def test_the_same_file_given_twice_is_collected_once(here: Path) -> None:
    (here / "test_stable.py").write_text(STABLE, encoding="utf-8")
    assert cs.test_files(["test_stable.py", "test_stable.py"]) == ["test_stable.py"]


def test_a_collection_that_fails_is_an_error_not_a_pass(here: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (here / "test_broken.py").write_text("def test_x(:\n", encoding="utf-8")
    assert cs.main(["test_broken.py"]) == 2
    assert "pytest --collect-only exited" in capsys.readouterr().err


def test_differences_counts_a_doubled_id() -> None:
    assert cs.differences(["a::t", "a::u"], ["a::u", "a::t"]) == []
    assert cs.differences(["a::t", "a::t"], ["a::t"]) == ["a::t"]
    assert cs.differences(["a::t[1]"], ["a::t[2]"]) == ["a::t[1]", "a::t[2]"]

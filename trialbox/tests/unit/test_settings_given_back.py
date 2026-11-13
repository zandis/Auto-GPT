"""BREAKER-TEST (D-637): a test gives the settings it changed back. A test that drove tools/complete_run.py in
process left TB_SCREEN_LLM_CONCURRENCY=4 in the environment, and the breaker test that ran after it in the same
worker saw a threshold of 8 where it sets 3."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.nodb

_WAS = {"set": os.environ.get("TB_D637_SET_BY_A_TEST"), "kept": os.environ.get("TB_ENV")}


def test_1_a_test_that_leaves_settings_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SCREEN_LLM_CONCURRENCY", raising=False)  # not set: monkeypatch has nothing to remember
    os.environ["TB_SCREEN_LLM_CONCURRENCY"] = "4"  # as tools/complete_run.py does when it is driven in process
    monkeypatch.delenv("TB_SCREEN_LLM_CONCURRENCY")  # ... so this remembers 4, and puts 4 back when the test ends
    os.environ["TB_D637_SET_BY_A_TEST"] = "4"
    os.environ["TB_ENV"] = "PRODUCTION"  # changed


def test_2_the_next_test_finds_them_as_they_were() -> None:
    assert "TB_SCREEN_LLM_CONCURRENCY" not in os.environ
    assert os.environ.get("TB_D637_SET_BY_A_TEST") == _WAS["set"]
    assert os.environ.get("TB_ENV") == _WAS["kept"]


@pytest.fixture(scope="module")
def wide() -> Iterator[str]:
    os.environ["TB_D637_WIDE"] = "set for the module"
    yield "wide"
    del os.environ["TB_D637_WIDE"]


def test_2a_what_a_wider_fixture_set_stays(wide: str) -> None:
    assert os.environ["TB_D637_WIDE"] == "set for the module"
    os.environ["TB_D637_WIDE"] = "changed by the test"


def test_2b_for_the_tests_that_share_it(wide: str) -> None:
    assert os.environ["TB_D637_WIDE"] == "set for the module"


def test_3_the_order_that_failed_the_breaker_test() -> None:
    """The breaker's threshold for a test that sets 3, after a test left four calls in flight in the environment."""
    from orchestrator.jobs import BreakerSettings

    assert BreakerSettings.from_env({**os.environ, "TB_SCREEN_BREAKER_FAILURES": "3"}).failures == 3


def test_4_only_our_settings_are_given_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.settings_kept import give_back, settings

    before = settings()
    monkeypatch.setenv("NOT_A_TB_SETTING_D637", "x")
    monkeypatch.setenv("TB_D637_NEW", "1")
    monkeypatch.delenv("TB_ENV", raising=False)
    assert give_back(before) == ["TB_D637_NEW", *(["TB_ENV"] if "TB_ENV" in before else [])]
    assert settings() == before and os.environ["NOT_A_TB_SETTING_D637"] == "x"

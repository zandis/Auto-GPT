"""D-637: after each test every ``TB_*`` environment variable is what it was before the test.

A tool driven in process sets its own environment, as a command-line tool may (``tools/complete_run.py`` sets
``TB_SCREEN_LLM_CONCURRENCY``). One test took the value away with ``monkeypatch.delenv`` after the tool had set it,
and monkeypatch then put the tool's value back when the test ended: every later test of that worker ran with four
calls in flight, which made the breaker's threshold 8 in a test that sets 3.

The plugin is registered for the whole session (``pytest_configure`` in ``tests/conftest.py``), not for a folder, so
its fixture is set up first and ends last of the test's own fixtures: after monkeypatch has undone its changes, before a wider fixture ends. What a wider fixture
(module, session) sets while it is set up is part of "before" and stays for the tests that share it.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from typing import Any

import pytest

PREFIX = "TB_"


def settings() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith(PREFIX)}


def give_back(before: dict[str, str]) -> list[str]:
    """Make the ``TB_*`` environment ``before`` again; the names that were changed."""
    now = settings()
    changed = sorted(k for k in now.keys() | before.keys() if now.get(k) != before.get(k))
    for k in changed:
        if k in before:
            os.environ[k] = before[k]
        else:
            del os.environ[k]
    return changed


class SettingsKept:
    def __init__(self) -> None:
        self.before: dict[str, str] | None = None

    @pytest.fixture(autouse=True)
    def _settings_given_back(self) -> Iterator[None]:
        self.before = settings()
        try:
            yield
        finally:
            before, self.before = self.before, None
            give_back(before)

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef: Any, request: pytest.FixtureRequest) -> Generator[None, Any, Any]:
        if self.before is None or fixturedef.scope == "function":
            return (yield)
        was = settings()
        try:
            return (yield)
        finally:
            now = settings()
            for k in now.keys() | was.keys():
                if now.get(k) != was.get(k):  # a wider fixture's setting: the later tests that share it need it
                    if k in now:
                        self.before[k] = now[k]
                    else:
                        self.before.pop(k, None)

"""9k-7 (D-1388): the second half of ``test_nothing_is_written_before_the_confirming_post`` (``test_acts_9k7.py``):
the participant's final steps (withdrawn, screen failed) and the study's close, walked by the tests that already reach
their confirmation pages, under the guard that nothing in the database or the folder (the audit trail) changes
before the confirming POST. In a module of its own because their fixtures share a name (``sb``) with the other
walks' fixtures."""

from __future__ import annotations

import importlib

import pytest

from tests.console.acts_9k7 import run_guarded
from tests.console.test_close_only_an_empty_study import clock  # noqa: F401 - the fixture is used by name
from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_sdv import sb  # noqa: F401 - the fixture is used by name

WALKS: list[tuple[str, str, set[str]]] = [
    ("test_walk1_final_steps", "test_a_withdrawal_names_what_becomes_final_before_it_is_recorded",
     {"/studies/{rs}/subjects/{record}/step"}),
    ("test_walk1_final_steps", "test_a_close_names_what_becomes_final_before_it_is_made", {"/studies/{rs}/state"}),
]  # fmt: skip


@pytest.mark.parametrize(("module", "name", "routes"), WALKS, ids=[w[1] for w in WALKS])
def test_nothing_is_written_before_the_confirming_post(
    module: str, name: str, routes: set[str], request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-1388: for every confirm-first act, nothing is written to the database or the audit trail before the
    confirming POST (the life-cycle half)."""
    fn = getattr(importlib.import_module(f"tests.console.{module}"), name)
    reached = run_guarded(fn, request, monkeypatch)
    assert routes <= set(reached), f"the confirmation page of {sorted(routes - set(reached))} was not reached"
    written = {r: w for r, w in reached.items() if w}
    assert not written, f"written before the confirming POST: {written}"

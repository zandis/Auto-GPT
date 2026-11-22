"""An actor module without `may_read` is denied the subject rows: the check narrows, never widens (integrator, 2026-11-22)."""

import types

import pytest
from console import person_state


def test_actor_without_may_read_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    import console

    monkeypatch.setattr(console, "actor", types.SimpleNamespace(), raising=False)
    monkeypatch.setitem(__import__("sys").modules, "console.actor", types.SimpleNamespace())
    assert person_state.may_read_rows("RS-1") is False


def test_actor_with_may_read_is_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    import console

    actor = types.SimpleNamespace(may_read=lambda rs: rs == "RS-1")
    monkeypatch.setattr(console, "actor", actor, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "console.actor", actor)
    assert person_state.may_read_rows("RS-1") is True
    assert person_state.may_read_rows("RS-2") is False

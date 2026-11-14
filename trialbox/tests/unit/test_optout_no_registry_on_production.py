"""D-654 (the owner's decision of 2026-11-13): on a PRODUCTION box a lake snapshot without a consent table refuses.

``registry_state`` answered None, "no registry", for a snapshot the lake says has no ``consent`` table, and every
caller takes None for "no opt-out to apply". A snapshot built by this software always has the table (empty when
there is no Consent feed), so on a production box one without it was made by hand or by other software: running
on it would list patients with no opt-out applied. There the run stops and says so. On a DEV or TEST box the old
reading stays, so tests and tools that build small lakes keep working."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.clients import StepFailed
from orchestrator.decision_context import DecisionContext
from tb_common import optout
from tb_common.optout import NoRegistryTable, registry_state

from tests.unit.test_optout_registry_probe import _Lake

DAY = "2026-11-13"


@pytest.mark.parametrize("env", [None, "PRODUCTION", "production", " Production ", "STAGING", "VALIDATION", ""])
def test_a_snapshot_without_a_consent_table_refuses_unless_the_box_is_dev_or_test(
    env: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset is PRODUCTION (the one rule for TB_ENV); any name that is not DEV or TEST refuses too."""
    monkeypatch.delenv("TB_ENV", raising=False)
    if env is not None:
        monkeypatch.setenv("TB_ENV", env)
    with pytest.raises(NoRegistryTable) as got:
        registry_state(_Lake(consent=False), "2026-11-01", DAY)
    said = str(got.value)
    assert said == optout.NO_REGISTRY_TABLE and "consent table" in said and "2026-11-01" not in said


@pytest.mark.parametrize("env", ["DEV", "TEST", "test", " dev "])
def test_on_a_dev_or_test_box_it_is_no_registry_as_before(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", env)
    assert registry_state(_Lake(consent=False), "2026-11-01", DAY) is None


def test_a_snapshot_that_has_the_table_is_read_the_same_on_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    state = registry_state(_Lake(consent=True), "2026-11-01", DAY)  # the table is there and empty: nobody refused
    assert state is not None and state.refused == frozenset()
    down = RuntimeError("lake query failed (503): upstream connect error")
    with pytest.raises(RuntimeError, match="503"):  # another failure is that failure, not the refusal
        registry_state(_Lake(consent=True, fail=down), "2026-11-01", DAY)


def test_the_job_stops_with_the_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The decision context is what every scenario and the cascade read the registry through: the job fails with a
    step failure whose message is the sentence (a general error would show only "Internal error")."""
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    ctx: Any = SimpleNamespace(services=SimpleNamespace(lake=_Lake(consent=False)), today=lambda: date(2026, 11, 13))
    d = DecisionContext(ctx)
    for read in (d.refused, d.no_contact, d.consent):
        with pytest.raises(StepFailed) as got:
            read()
        assert got.value.message == optout.NO_REGISTRY_TABLE and got.value.step == "running"
    # the step is the one the job is in (CASE reads the registry while it is still parsing)
    ctx.job = SimpleNamespace(state="parsing")
    with pytest.raises(StepFailed) as got:
        DecisionContext(ctx).consent()
    assert got.value.step == "parsing"
    del ctx.job
    monkeypatch.setenv("TB_ENV", "TEST")
    test_box = DecisionContext(ctx)
    assert test_box.consent() is None and test_box.refused() == frozenset()


def test_the_opt_out_worker_names_the_registry_as_not_read_and_still_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lane E's worker, unchanged: it catches the refusal like any failure of the read."""
    from datacore import optout_worker

    monkeypatch.setenv("TB_ENV", "PRODUCTION")

    class Register:
        def effective(self) -> set[str]:
            return {"P-KEPT"}

    cleared: list[frozenset[str]] = []

    def clear(pids: frozenset[str], _env: Any) -> dict[str, int]:
        cleared.append(pids)
        return {"t": 1}

    one = SimpleNamespace(name="a-store", resolve=lambda: (clear, lambda pids, _env: {"t": 0}))
    monkeypatch.setattr("tb_common.erasure.clears", lambda: [one])
    env = optout_worker.WorkerEnv(
        register=Register(),  # type: ignore[arg-type]
        audit=SimpleNamespace(append=lambda *a, **k: None),
        now=datetime(2026, 11, 13, 3, 0, tzinfo=UTC),
        lake=_Lake(consent=False),
    )
    out = optout_worker.run_once(env)
    assert out["failed"] == ["registry"] and out["registry"] is None
    assert cleared == [frozenset({"P-KEPT"})]
    monkeypatch.setenv("TB_ENV", "TEST")
    assert optout_worker.run_once(env)["failed"] == []  # a test box: no registry, nothing failed, as before

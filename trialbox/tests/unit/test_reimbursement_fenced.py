"""Card 9e-9 (plan 9 decision 8, path (ii)): reimbursement is fenced off in 1.0.

NAV, its TWPAS bundles and SUBMIT sit behind the audited flag ``reimbursement.paths``: off by default, switched on
with a reason on a test box only. The row's proof: a PRODUCTION box refuses the setting (so do an unset ``TB_ENV``,
which is PRODUCTION, and a VALIDATION box). With it off each of the three is refused at its one place and the night
passes over NAV; on a TEST box with it on they run."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import reimbursement
from orchestrator.clients import StepFailed
from orchestrator.scenarios import nav, submit, twpas
from tb_common import flags
from tb_common.audit import AuditLog

from tests.unit.test_t726_night_runner import MON, Box

FLAG = reimbursement.FLAG
REAL_IS_OPEN = reimbursement.is_open


def _flags(tmp_path: Path) -> flags.Flags:
    return flags.Flags(audit=AuditLog(tmp_path / "audit"))


def _switch_on(tmp_path: Path) -> None:
    _flags(tmp_path).set(FLAG, "on", actor="console:admin", reason="card 9e-9: a test box tries NAV")


def test_the_flag_is_declared_off_and_for_a_test_box_only() -> None:
    d = flags.DECLARED[FLAG]
    assert d.default == "off" and d.values == ("off", "on") and d.seed_env is None
    assert FLAG in flags.TEST_BOX_ONLY


@pytest.mark.parametrize("env", ["PRODUCTION", None, "VALIDATION"])
def test_a_production_box_refuses_the_setting(env: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if env is None:
        monkeypatch.delenv("TB_ENV", raising=False)  # unset is PRODUCTION (D-127)
    else:
        monkeypatch.setenv("TB_ENV", env)
    with pytest.raises(ValueError, match="test box only"):
        _switch_on(tmp_path)
    assert _flags(tmp_path).row(FLAG) is None  # nothing was written
    assert not reimbursement.is_open()


@pytest.mark.parametrize("env", ["PRODUCTION", None, "VALIDATION"])
def test_a_row_that_says_on_opens_nothing_off_a_test_box(
    env: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database switched on on a test box and restored onto a production box: the box's TB_ENV still fences it."""
    _switch_on(tmp_path)
    assert reimbursement.is_open()
    flags.clear_cache()
    if env is None:
        monkeypatch.delenv("TB_ENV", raising=False)
    else:
        monkeypatch.setenv("TB_ENV", env)
    assert not reimbursement.is_open()
    with pytest.raises(StepFailed) as refused:
        submit.run(_ctx())
    assert refused.value.step == "reimbursement"


@pytest.mark.parametrize("env", ["STAGING", "", "  ", "prod"])
def test_an_unknown_environment_is_not_a_test_box(env: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails closed: a name that is not DEV or TEST (a made-up one, an empty one) opens nothing, even with the row on."""
    _switch_on(tmp_path)
    flags.clear_cache()
    monkeypatch.setenv("TB_ENV", env)
    assert not reimbursement.is_open()
    with pytest.raises(StepFailed) as refused:
        reimbursement.require_open()
    assert refused.value.step == "reimbursement"


def test_a_flag_store_that_cannot_be_read_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails closed: on a test box with the row on, a store that raises when read keeps the fence shut."""
    _switch_on(tmp_path)
    assert reimbursement.is_open()
    flags.clear_cache()

    def unreadable(self: flags.Flags, name: str) -> str | None:
        raise RuntimeError("the flag store is down")

    monkeypatch.setattr(flags.Flags, "row", unreadable)
    assert not reimbursement.is_open()
    with pytest.raises(StepFailed) as refused:
        reimbursement.require_open()
    assert refused.value.step == "reimbursement"


# ----------------------------------------------------------------------- off (the default): each refused at its place
def _ctx(twpas_on: bool = True) -> Any:
    settings = SimpleNamespace(twpas=SimpleNamespace(enabled=twpas_on, dry_run=True), permissions=None)
    return SimpleNamespace(job=SimpleNamespace(ruleset="ONC-OSI", options={}, requested_by="dr@hospa.test"),
                           cfg=SimpleNamespace(settings=settings))  # fmt: skip


def _ruleset() -> Any:
    return SimpleNamespace(manifest=SimpleNamespace(twpas=SimpleNamespace(enabled=True)))


def test_off_by_default_nav_is_refused_at_its_first_step() -> None:
    assert not reimbursement.is_open()
    with pytest.raises(StepFailed) as refused:
        nav.run(_ctx())
    assert refused.value.step == "reimbursement" and "not part of this release" in refused.value.message


def test_off_by_default_submit_is_refused_at_its_first_step() -> None:
    with pytest.raises(StepFailed) as refused:
        submit.run(_ctx())
    assert refused.value.step == "reimbursement" and "not part of this release" in refused.value.message


def test_off_by_default_no_twpas_bundle_is_built() -> None:
    assert twpas.enabled(_ctx(), _ruleset()) is False


def test_off_by_default_the_night_passes_over_nav_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(tmp_path, monkeypatch)
    monkeypatch.setattr(reimbursement, "is_open", REAL_IS_OPEN)  # the box's own flag, not the night tests' stand-in
    said: list[tuple[str, dict[str, Any]]] = []
    real_append = box.orch.audit.append

    def append(event: str, **kw: Any) -> dict[str, Any]:
        said.append((event, dict(kw.get("detail") or {})))
        return real_append(event, **kw)

    monkeypatch.setattr(box.orch.audit, "append", append)
    box.timer_ingest(MON)
    box.orch.drain()
    assert box.chain() == [("MICROBATCH", "ADX"), ("MICROBATCH", "GZQO"), ("RETENTION", None)]
    held = [d for e, d in said if e == "scheduler.held"]
    assert held == [{"job": "NAV", "state": "reimbursement off", "night": MON.isoformat()}]


# ------------------------------------------------------------------------------- on, on a TEST box: the three run
def test_on_a_test_box_with_it_on_nav_and_submit_go_past_the_fence(tmp_path: Path) -> None:
    _switch_on(tmp_path)
    assert reimbursement.is_open()
    with pytest.raises(Exception) as went_on:  # NAV goes past the fence (and stops on this bare stand-in)
        nav.run(_ctx())
    assert getattr(went_on.value, "step", None) != "reimbursement"
    with pytest.raises(StepFailed) as next_check:  # SUBMIT's next check is the patient
        submit.run(_ctx())
    assert next_check.value.step == "received" and "Give the patient" in next_check.value.message
    assert twpas.enabled(_ctx(), _ruleset()) is True
    assert twpas.enabled(_ctx(twpas_on=False), _ruleset()) is False  # the site's setting still decides


def test_on_a_test_box_with_it_on_the_night_runs_nav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = Box(tmp_path, monkeypatch)
    monkeypatch.setattr(reimbursement, "is_open", REAL_IS_OPEN)
    _switch_on(tmp_path)
    box.timer_ingest(MON)
    box.orch.drain()
    assert box.chain() == [("MICROBATCH", "ADX"), ("MICROBATCH", "GZQO"), ("NAV", "NHI1"), ("RETENTION", None)]
    assert box.orch.db.find(type_="NAV")[0].state == "done"
    assert date.fromisoformat((box.orch.db.find(type_="NAV")[0].options or {})["night_day"]) == MON

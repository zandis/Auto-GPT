"""FR-OPS-12 on-demand schedule in DEV and the ethics_gate setting (20-build-map F6-03, F6-30)."""

from __future__ import annotations

from pathlib import Path

from tb_common.config import Env, ethics_gate_on, load_settings, schedule_on_demand, tb_env

ROOT = Path(__file__).resolve().parents[2]


def _settings(**upd: object):  # type: ignore[no-untyped-def]
    s = load_settings(ROOT / "deploy/settings.example.yaml")
    return s.model_copy(update=upd)


def test_ethics_gate_is_off_in_dev_and_test_and_on_by_default_elsewhere() -> None:
    s = _settings()
    assert s.ethics_gate is None
    assert not ethics_gate_on(s, "DEV") and not ethics_gate_on(s, "test")
    assert ethics_gate_on(s, "PRODUCTION") and ethics_gate_on(s, "VALIDATION")
    on = _settings(ethics_gate=True)
    off = _settings(ethics_gate=False)
    assert not ethics_gate_on(on, "DEV")
    assert not ethics_gate_on(off, "PRODUCTION")


def test_schedule_is_on_demand_in_dev_only_by_default() -> None:
    s = _settings()
    assert s.schedule.mode == "auto"
    assert schedule_on_demand(s, "DEV") and not schedule_on_demand(s, "TEST")
    assert not schedule_on_demand(s, "PRODUCTION")
    forced = _settings(schedule=s.schedule.model_copy(update={"mode": "nightly"}))
    assert not schedule_on_demand(forced, "DEV")
    od = _settings(schedule=s.schedule.model_copy(update={"mode": "on_demand"}))
    assert schedule_on_demand(od, "PRODUCTION")


def test_tb_env_defaults_to_production() -> None:
    assert tb_env(Env()) == "PRODUCTION"
    assert tb_env(Env(extra={"TB_ENV": "dev"})) == "DEV"


def test_scheduler_starts_no_timed_jobs_in_dev() -> None:
    from types import SimpleNamespace

    from orchestrator.scheduler import start

    orch = SimpleNamespace(cfg=SimpleNamespace(settings=_settings(), env=Env(extra={"TB_ENV": "DEV"})))
    assert start(orch) is None  # type: ignore[arg-type]

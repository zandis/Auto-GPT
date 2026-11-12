"""DOCTOR-CHARTNO (D-621): every service that makes a pseudonym runs under the chart-number rule the pid map was
built with. The adapter refuses a night under another rule (D-595); the orchestrator's set-up and opt-out desk,
candidates, the data core API and the key tool make pseudonyms under their own process's ``TB_CHARTNO_RULE`` and
ask nobody. ``trialbox doctor`` reads the rule of every service (the rendered compose files, the running
containers) and the pid map's record, and fails when they are not one rule."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb

OURS = ("adapter", "orchestrator", "console", "lake")


def _config(default: str | None = "digits:8", **over: str | None) -> dict[str, Any]:
    services: dict[str, Any] = {"db": {"environment": {"POSTGRES_USER": "trialbox"}}}  # not ours: never judged
    for name in OURS:
        rule = over.get(name, default)
        env = {"TB_SITE_ID": "SITE", **({"TB_CHARTNO_RULE": rule} if rule is not None else {})}
        services[name] = {"environment": env}
    return {"services": services}


def _check(config: dict[str, Any] | None, stored: Any = "digits:8", running: Any = None, **env: str) -> doctor.Check:
    inp = doctor.DoctorInputs(
        env={"TB_ENV": "PRODUCTION", "TB_DB_URL": "postgresql://x", **env},
        settings={"site": {"id": "SITE"}},
        compose_config=config,
    )

    def pid_map(_url: str, _site: str) -> str | None:
        if isinstance(stored, Exception):
            raise stored
        return stored  # type: ignore[no-any-return]

    return doctor.check_chartno_rule(inp, running=lambda _project: running, pid_map_rule=pid_map)


def test_one_rule_everywhere_and_in_the_pid_map_passes() -> None:
    c = _check(_config())
    assert (c.name, c.status) == ("chartno_rule", "PASS")
    assert "digits:8" in c.detail and "4 services" in c.detail and "the pid map" in c.detail


def test_no_rule_and_asis_are_one_rule_and_a_box_before_its_first_night_passes() -> None:
    c = _check(_config(default=None, console="asis"), stored=None)
    assert c.status == "PASS" and "asis" in c.detail and "no night has recorded" in c.detail


def test_a_service_under_another_rule_fails_and_is_named() -> None:
    c = _check(_config(orchestrator="asis"))
    assert c.status == "FAIL" and "orchestrator" in c.detail and "asis" in c.detail and "digits:8" in c.detail
    assert "opt-out" in c.detail  # what it means, in the box's words


def test_services_that_agree_with_each_other_but_not_with_the_pid_map_fail() -> None:
    c = _check(_config(default="hex:8"), stored="digits:8")
    assert c.status == "FAIL" and "the pid map" in c.detail and "hex:8" in c.detail and "digits:8" in c.detail


def test_a_running_container_started_under_an_older_rule_fails() -> None:
    c = _check(_config(), running=_config(console="asis"))
    assert c.status == "FAIL" and "running" in c.detail and "console" in c.detail
    ok = _check(_config(), running=_config())
    assert ok.status == "PASS" and "running container" in ok.detail


def test_a_rule_that_cannot_be_read_fails() -> None:
    c = _check(_config(lake="digit"))
    assert c.status == "FAIL" and "lake" in c.detail


def test_the_spelling_does_not_matter_only_the_rule() -> None:
    assert _check(_config(console="DIGITS:8"), stored="digits:8").status == "PASS"
    assert _check(_config(default="hex:8:upper"), stored="hex:8").status == "PASS"


def test_a_pid_map_that_cannot_be_read_is_said_not_passed() -> None:
    c = _check(_config(), stored=RuntimeError("no database"))
    assert c.status == "WARN" and "pid map" in c.detail and "RuntimeError" in c.detail


@pytest.mark.parametrize(("env_name", "status"), [("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("DEV", "WARN")])
def test_a_box_whose_services_were_not_read_is_not_a_pass(env_name: str, status: str) -> None:
    inp = doctor.DoctorInputs(env={"TB_ENV": env_name}, settings={"site": {"id": "SITE"}})
    c = doctor.check_chartno_rule(inp, running=lambda _p: None, pid_map_rule=lambda _u, _s: None)
    assert c.status == status and "--env-file" in c.detail


def test_the_check_is_one_of_doctors_and_is_described() -> None:
    assert doctor.check_chartno_rule in doctor.CHECKS
    assert "``chartno_rule``" in (doctor.__doc__ or "")


def test_compose_gives_the_rule_from_one_place() -> None:
    """Every service of ours gets ``TB_CHARTNO_RULE`` from ``deploy/.env`` through the env file; no compose file
    sets it for one service, which is how two services would come to differ."""
    for path in sorted((ROOT / "deploy").rglob("docker-compose*.yml")):
        code = "\n".join(ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").splitlines())
        assert "TB_CHARTNO_RULE" not in code, path.name
    base = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("adapter", "orchestrator", "console", "lake", "criteria-compiler"):
        assert base["services"][name]["env_file"] == [".env"], name

"""T-695's rest (D-921): each service's start-time migrations run as a step of their own, before the services start.

A service migrates the stores it opens at start before it answers ``/healthz`` (an app factory or a lifespan start);
a migration longer than the health wait (20 s start period and ten 15 s retries) failed ``up --wait`` and the update
was rolled back (F-10 of docs/reviews/2026-11-11-scale-timeouts.md). ``db-up``'s step "service stores" runs them in
a one-off container of each service first, under a limit sized from the database."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import prestart
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
DB_ENV = "TB_DB_URL=postgresql://trialbox:pw@db:5432/trialbox_wf\nTB_DB_PW_FHIR_STORE=x\n"


def _role_lists() -> dict[str, set[str]]:
    text = (ROOT / "deploy" / "docker" / "db-init" / "30-service-roles.sh").read_text(encoding="utf-8")
    block = text[text.index("access CONSTANT jsonb := '") + len("access CONSTANT jsonb := '") :]
    return {k: set(v) for k, v in json.loads(block[: block.index("}'") + 1]).items()}


def _compose() -> dict[str, Any]:
    services: dict[str, Any] = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))[
        "services"
    ]
    return services


# ------------------------------------------------------------------------------------------------- the lists
def test_the_update_runs_the_services_whose_stores_open_at_start() -> None:
    from orchestrator.migrate_stores import AT_START

    assert set(up.STORE_SERVICES) == set(AT_START)


def test_each_store_is_one_its_service_may_reach_and_the_service_has_a_database() -> None:
    from orchestrator.migrate_stores import AT_START

    roles, svcs = _role_lists(), _compose()
    for svc, stores in AT_START.items():
        env = svcs[svc]["environment"]
        assert env["TB_SERVICE_NAME"] == svc and env.get("TB_DB_URL"), svc
        role = re.search(r"//(tb_[a-z_]+):", env["TB_DB_URL"])
        assert role, svc
        assert {schema for schema, _ in stores} <= roles[role.group(1)], svc


# ------------------------------------------------------------------------------------------------- the step
def _box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, services: str, size: str = "1000000") -> Any:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(DB_ENV, encoding="utf-8")
    calls: list[tuple[list[str], Any]] = []

    def fake(argv: Sequence[str], **kw: Any) -> str:
        calls.append((list(argv), kw.get("timeout")))
        if "--services" in argv:
            return services
        if "pg_database_size" in " ".join(argv):
            return size
        return ""

    monkeypatch.setenv("TB_COMPOSE", "dc")
    return up.ComposeBox(deploy, run=fake), calls


def test_db_up_migrates_each_service_in_a_one_off_container_after_the_owned_schemas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, calls = _box(tmp_path, monkeypatch, "db\norchestrator\nconsole\ngateway\nlake\n")
    lines = prestart.run_db(box.deploy, box)
    assert lines[-1] == "db-up: service stores: migrated in a one-off container each: orchestrator, gateway, console"
    argvs = [c for c, _ in calls]
    owned = next(i for i, c in enumerate(argvs) if "orchestrator.migrate" in c)
    runs = [i for i, c in enumerate(argvs) if "orchestrator.migrate_stores" in c]
    assert len(runs) == 3 and owned < runs[0]
    for i in runs:
        assert argvs[i][:6] == ["dc", "run", "--rm", "--no-deps", "-T", argvs[i][5]]
        assert "-e" not in argvs[i]  # the service's own settings and role: no admin URL passed in
    assert [argvs[i][5] for i in runs] == ["orchestrator", "gateway", "console"]  # the box's services only


def test_a_long_migration_has_a_limit_sized_from_the_database_never_the_health_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup_schedule as bsch

    size = 400 * 10**9  # 400 GB: a sized limit far above any health wait
    box, calls = _box(tmp_path, monkeypatch, "orchestrator\n", str(size))
    box.migrate_stores()
    want = bsch.config(box.deploy, box.env).timeout(size)
    limit = next(t for c, t in calls if "orchestrator.migrate_stores" in c)
    assert want and limit == int(want) and limit > 600 and limit > box.up_wait()


def test_a_size_that_cannot_be_read_leaves_the_step_no_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box, calls = _box(tmp_path, monkeypatch, "orchestrator\n", "not a number")
    box.migrate_stores()
    assert next(t for c, t in calls if "orchestrator.migrate_stores" in c) is None  # D-455: never a fixed guess


def test_the_parent_waits_for_the_migrations_and_the_whole_update_counts_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The updater runs the new tree's db-up under a limit: it must not stop a sized migration (one per service)."""
    box, _ = _box(tmp_path, monkeypatch, "orchestrator\n", str(400 * 10**9))
    m = box.migrate_limit_s()
    seen: list[Any] = []
    deploy = box.deploy
    (deploy.parent / "tools" / "trialbox").mkdir(parents=True)
    (deploy.parent / "tools" / "trialbox" / "prestart.py").write_text("DB_STEPS = []\n", encoding="utf-8")
    inner = box.run

    def fake(argv: Sequence[str], **kw: Any) -> str:
        if "db-up" in argv:
            seen.append(kw.get("timeout"))
            return ""
        return str(inner(argv, **kw))

    box.run = fake
    box.db_up()
    assert m and seen and seen[0] >= len(up.STORE_SERVICES) * m


def test_a_box_without_the_database_step_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box, calls = _box(tmp_path, monkeypatch, "orchestrator\n")
    box.env = {"TB_SITE_ID": "T"}
    assert box.migrate_stores() == [] and calls == []


def test_a_failed_migration_names_the_step_and_stops_before_the_services_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    box, _ = _box(tmp_path, monkeypatch, "console\n")
    inner = box.run

    def fake(argv: Sequence[str], **kw: Any) -> str:
        if "orchestrator.migrate_stores" in argv:
            raise up.UpdateFailed("dc run exit 1: migrate-stores: console: boom")
        return str(inner(argv, **kw))

    box.run = fake
    with pytest.raises(up.UpdateFailed, match=r"^service stores: .*boom"):
        prestart.run_db(box.deploy, box)


# --------------------------------------------------------------------------- the step leaves nothing to the start
def _versions(url: str) -> dict[str, int]:
    from tb_common.db import Database

    db = Database.connect(url, "app")
    try:
        prefix = db.schema[: -len("app")]
        with db.transaction() as tx:
            schemas = [
                str(r[0])
                for r in tx.fetchall(
                    "SELECT table_schema FROM information_schema.tables WHERE table_name = '_schema_version' "
                    "AND table_schema LIKE ?",
                    (prefix + "%",),
                )
            ]
            return {s[len(prefix) :]: int(tx.fetchval(f'SELECT count(*) FROM "{s}"._schema_version')) for s in schemas}
    finally:
        db.close()


def test_after_the_step_the_consoles_start_applies_no_migration(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from console.app import create_app
    from orchestrator import migrate_stores
    from tb_common.audit import AuditLog

    from tests.console.test_console_app import PILOT_ENV, FakeBackend

    monkeypatch.setenv("TB_SERVICE_NAME", "console")
    lines: list[str] = []
    assert migrate_stores.run("console", lines.append) == 0
    before = _versions(db_url)
    assert {schema for schema, _ in migrate_stores.AT_START["console"]} <= set(before)
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "console"), "TB_DB_URL": db_url}
    create_app(env, backend=backend, audit=AuditLog(backend.audit_dir))
    assert _versions(db_url) == before  # every store the start opened was at its version already


@pytest.mark.parametrize("service", ["orchestrator", "mail-gateway", "gateway"])
def test_after_the_step_the_services_start_time_store_is_at_its_version(
    db_url: str, monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    from orchestrator import migrate_stores

    monkeypatch.setenv("TB_TRACESTORE", "on")
    assert migrate_stores.run(service, lambda _s: None) == 0
    before = _versions(db_url)
    assert {schema for schema, _ in migrate_stores.AT_START[service]} <= set(before)
    for _schema, open_ in migrate_stores.AT_START[service]:
        open_()  # the start opens the same store: nothing left to apply
    assert _versions(db_url) == before


def test_a_service_with_no_store_at_start_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import migrate_stores

    said: list[str] = []
    assert migrate_stores.run("lake", said.append) == 0 and said == ["lake: no store opened at start"]
    monkeypatch.setenv("TB_TERMINOLOGY_SOURCE", "parquet")
    said.clear()
    assert migrate_stores.run("criteria-compiler", said.append) == 0
    assert said == ["criteria-compiler: omop: the compiler reads its terminology files"]

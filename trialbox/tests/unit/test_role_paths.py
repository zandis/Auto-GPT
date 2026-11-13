"""ROLE-PATHS (D-720): the drill runs each service's real write paths under the role script, as the service's own
role. The check of D-573 opened every store and passed on a box where the opt-out worker failed at every tick and
no role could load the OMOP store (the nightly of 2026-11-13)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from tools import backup_drill, pglocal, role_paths

ROOT = Path(__file__).resolve().parents[2]


def _pg() -> None:
    if shutil.which("sh") is None:
        pytest.skip("no sh")
    try:
        pglocal.bindir()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def test_every_real_write_path_runs_under_the_role_script(tmp_path: Path) -> None:
    _pg()
    name, ok, detail = role_paths.check(tmp_path / "cluster")
    assert ok, detail
    assert "real write paths" in name
    for path, _ in role_paths.PATHS:
        assert path in detail
    assert "a temporary table on" in detail


def test_a_role_script_that_gives_the_groups_no_temporary_tables_fails_the_check_by_name(tmp_path: Path) -> None:
    """The script as it was on 2026-11-13 (before D-683): TEMPORARY for the service roles only. After ``SET ROLE``
    to a store's group the session has the group's rights, and the group had none."""
    _pg()
    text = role_paths.ROLES_SCRIPT.read_text(encoding="utf-8")
    grant = "      EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO %I', current_database(), grp);\n"
    assert text.count(grant) == 1, "the script no longer grants TEMPORARY to a store's group on this one line"
    old = tmp_path / "30-service-roles.sh"
    old.write_text(text.replace(grant, "      NULL;\n"), encoding="utf-8")
    _name, ok, detail = role_paths.check(tmp_path / "cluster", script=old)
    assert not ok
    assert "a temporary table: tb_adapter on app: InsufficientPrivilege" in detail
    assert "the OMOP load as tb_adapter: InsufficientPrivilege" in detail
    assert "the OMOP export as of a time as tb_lake" in detail
    assert "more store connections the same" in detail
    assert "the opt-out tick" not in detail  # that one was the worker's own fault, not the script's


def test_the_export_path_reaches_the_temporary_table_of_the_wind_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path is there for the wind-back's temporary table: an export that winds nothing back makes none, and
    the line would pass without ever asking for the right."""
    _pg()
    from tb_common import db as tb_db

    seen: list[str] = []
    real = tb_db.Tx.execute

    def spy(self: Any, sql: str, *a: Any, **kw: Any) -> Any:
        if "TEMP TABLE" in str(sql):
            seen.append(str(sql).split("(")[0].strip())
        return real(self, sql, *a, **kw)

    monkeypatch.setattr(tb_db.Tx, "execute", spy)
    _name, ok, detail = role_paths.check(tmp_path / "cluster")
    assert ok, detail
    assert "CREATE TEMP TABLE tb_asof_tmp" in seen  # the export's wind-back
    assert "CREATE TEMP TABLE tb_in_tmp" in seen  # the load
    assert "CREATE TEMP TABLE tb_drill_tmp" in seen  # the line of every store connection


def test_the_drill_runs_the_check() -> None:
    body = (ROOT / "tools" / "backup_drill.py").read_text(encoding="utf-8")
    assert 'checks.append(role_paths.check(base / "paths-cluster"))' in body
    assert backup_drill.ROLES_SCRIPT == role_paths.ROLES_SCRIPT


def test_the_one_line_names_every_path_and_counts_the_rest() -> None:
    bad = [f"a temporary table: tb_x on s{i}: E" for i in range(5)] + ["the OMOP load as tb_adapter: E"]
    assert role_paths.brief(bad) == [
        "a temporary table: tb_x on s0: E",
        "a temporary table: tb_x on s1: E",
        "a temporary table: tb_x on s2: E",
        "a temporary table: 2 more store connections the same",
        "the OMOP load as tb_adapter: E",
    ]

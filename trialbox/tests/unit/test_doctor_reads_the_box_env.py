"""E2E P-18: the installed ``sudo trialbox doctor`` gave 4 FAIL where the runbook's form (``--env-file deploy/.env``)
gave 1: ``chartno_rule`` and ``db_passwords`` said "give --env-file" although the box has its file, which the
launcher already reads as the box's settings. Without ``--env-file`` the doctor now reads the box's own
``deploy/.env``; a file named on the command line still wins, and a tree with none is judged as before."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import __main__ as tb_main
from tools.trialbox import doctor, launch

pytestmark = pytest.mark.nodb


@pytest.fixture
def seen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What the doctor was given; no check runs."""
    got: dict[str, Any] = {}

    def inputs_from(**kw: Any) -> Any:
        got.update(kw)
        return doctor.DoctorInputs(env={})

    monkeypatch.setattr(launch, "DEPLOY", tmp_path / "deploy")
    monkeypatch.setattr(doctor, "inputs_from", inputs_from)
    monkeypatch.setattr(doctor, "needs_image", lambda: False)
    monkeypatch.setattr(doctor, "run", lambda *a, **k: [])
    return got


def test_the_installed_doctor_reads_the_box_s_own_env_file(tmp_path: Path, seen: dict[str, Any]) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    assert tb_main.main(["doctor"]) == 0
    assert seen["env_file"] == tmp_path / "deploy" / ".env"


def test_a_named_env_file_wins(tmp_path: Path, seen: dict[str, Any]) -> None:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    other = tmp_path / "other.env"
    other.write_text("TB_ENV=TEST\n", encoding="utf-8")
    assert tb_main.main(["doctor", "--env-file", str(other)]) == 0
    assert seen["env_file"] == other


def test_a_tree_without_a_box_file_is_judged_as_before(seen: dict[str, Any]) -> None:
    assert tb_main.main(["doctor"]) == 0
    assert seen["env_file"] is None

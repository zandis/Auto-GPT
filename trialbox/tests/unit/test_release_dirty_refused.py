"""RELEASE-DIRTY (D-633, the owner's decision of 2026-11-13): a PRODUCTION or VALIDATION box refuses a bundle whose
release.json says it was built from a dirty checkout, at install and at update; DEV and TEST boxes take it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_update_safety import Recorder, _plan
from tools import update_status as us
from tools.trialbox import update as up

pytestmark = pytest.mark.nodb


class EnvBox(Recorder):
    def __init__(self, env: str) -> None:
        super().__init__()
        self._env = env

    def environment(self) -> str:
        return self._env


def _release(dirty: Any = True, **source: Any) -> dict[str, Any]:
    return {"release_id": "2026.11-1", "source": {"commit": "a" * 40, "tag": None, "dirty": dirty, **source}}


def _upd(box: Any, tmp: Path) -> up.Updater:
    return up.Updater(box, tmp / "updates", say=lambda _m: None)


def _with(tmp: Path, release: dict[str, Any] | None) -> up.Plan:
    plan = _plan(tmp)
    plan.release = release
    return plan


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_a_site_box_refuses_a_bundle_built_from_a_working_tree(tmp_path: Path, env: str) -> None:
    box = EnvBox(env)
    with pytest.raises(up.UpdateRefused) as exc:
        _upd(box, tmp_path).preflight(_with(tmp_path, _release(True)))
    said = str(exc.value)
    assert env in said and "working tree" in said and "commit" in said and "--allow-dirty" in said
    assert "DEV" in said and "TEST" in said  # where such a bundle may go
    assert box.calls == []  # nothing was touched


@pytest.mark.parametrize("env", ["DEV", "TEST"])
def test_a_dev_or_test_box_takes_it_and_records_it(tmp_path: Path, env: str) -> None:
    box = EnvBox(env)
    upd = _upd(box, tmp_path)
    assert upd.run(_with(tmp_path, _release(True)))["ok"]
    assert us.installed(tmp_path / "updates")["dirty"] is True


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION", "DEV", "TEST"])
def test_a_release_built_from_a_commit_goes_everywhere(tmp_path: Path, env: str) -> None:
    upd = _upd(EnvBox(env), tmp_path)
    assert upd.run(_with(tmp_path, _release(False)))["ok"]
    assert us.installed(tmp_path / "updates")["dirty"] is False


def test_the_refusal_comes_before_the_backup_at_an_update(tmp_path: Path) -> None:
    box = EnvBox("PRODUCTION")
    with pytest.raises(up.UpdateRefused, match="working tree"):
        _upd(box, tmp_path).run(_with(tmp_path, _release(True)))
    assert box.calls == []  # no backup, no rollback point, nothing stopped
    assert us.installed(tmp_path / "updates")["release_seq"] == 0


def test_a_bundle_with_no_release_record_is_taken_as_before_and_the_update_says_so(tmp_path: Path) -> None:
    """A bundle from before release.json, or a rulesets-only one: it cannot say, and other rules hold it."""
    notes = _upd(EnvBox("PRODUCTION"), tmp_path).preflight(_with(tmp_path, None))
    assert any("no release record" in n for n in notes)
    assert _upd(EnvBox("PRODUCTION"), tmp_path).run(_with(tmp_path, None))["ok"]
    assert us.installed(tmp_path / "updates").get("dirty") is None


@pytest.mark.parametrize(
    "release",
    [_release(None), _release("false"), _release(0), {"release_id": "x"}, {"release_id": "x", "source": "a commit"}],
)
def test_a_release_record_that_does_not_answer_is_refused_on_a_site_box(
    tmp_path: Path, release: dict[str, Any]
) -> None:
    with pytest.raises(up.UpdateRefused, match="does not say"):
        _upd(EnvBox("PRODUCTION"), tmp_path).preflight(_with(tmp_path, release))
    _upd(EnvBox("DEV"), tmp_path).preflight(_with(tmp_path, release))  # a DEV box is not held to it


def test_a_box_that_cannot_name_its_environment_counts_as_production(tmp_path: Path) -> None:
    with pytest.raises(up.UpdateRefused, match="PRODUCTION"):
        _upd(Recorder(), tmp_path).preflight(_with(tmp_path, _release(True)))
    with pytest.raises(up.UpdateRefused, match="PRODUCTION"):
        _upd(EnvBox("staging-ish"), tmp_path).preflight(_with(tmp_path, _release(True)))  # an unknown name too


def test_the_boxs_environment_is_what_its_env_file_says_never_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    monkeypatch.setenv("TB_ENV", "DEV")  # typed in front of the installer: it is not written to the box
    assert up.ComposeBox(deploy).environment() == "PRODUCTION"  # a fresh install: no deploy/.env yet
    (deploy / ".env").write_text("TB_SITE_ID=T\n", encoding="utf-8")
    assert up.ComposeBox(deploy).environment() == "PRODUCTION"
    (deploy / ".env").write_text("TB_ENV=dev\n", encoding="utf-8")
    assert up.ComposeBox(deploy).environment() == "DEV"
    (deploy / ".env").write_text("TB_ENV=DEV\nTB_ENV=PRODUCTION\n", encoding="utf-8")
    assert up.ComposeBox(deploy).environment() == "PRODUCTION"  # the last line counts, as install.sh reads it


def test_the_test_boxes_name_their_environment(tmp_path: Path) -> None:
    assert up.InProcessBox(tmp_path / "w", "postgresql://x/y", tmp_path / "b").environment() == "TEST"
    assert up.DemoBox(tmp_path).environment() == "DEV"

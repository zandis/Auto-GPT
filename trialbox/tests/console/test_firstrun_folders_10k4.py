"""10K-4 (D-1390; review 18, SO-4): the box's first-run page asks the backup, audit record and log folders, and the
box does not finish its set-up in PRODUCTION while the backups are only on its own disks or the audit record folder
cannot be mounted.

The page asks the folders and checks how they are written (``tb_common.box_answers.host_dir``); it cannot see the
host's disks, so whether the box may finish is asked by the box installer after the answers are applied
(``python3 -m tools.trialbox finish-check``; ``tests/unit/test_install_refuses_unsafe_folders_10k4.py``). Here the
whole path runs: the real ``deploy/box-install.sh`` and the console's real first-run page, as in
``test_box_install_rehearsal.py``."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console import firstrun as page
from console.app import create_app
from console.auth import UserStore
from console.i18n_firstrun import EN, JA, ZH
from fastapi.testclient import TestClient
from tb_common import firstrun
from tb_common.audit import AuditLog

from tests.console.test_box_install_rehearsal import _tree, _wait
from tests.console.test_console_app import PILOT_ENV, FakeBackend
from tests.console.test_firstrun import _answers, _box, _with_code

NEW_KEYS = (
    "firstrun.backup.dir", "firstrun.backup.dir.help", "firstrun.folders", "firstrun.folders.help",
    "firstrun.folders.production", "firstrun.anchor_dir", "firstrun.anchor_dir.help", "firstrun.log_dir",
    "firstrun.log_dir.help", "firstrun.err.host_dir",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _no_patients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page, "box_holds_patients", lambda: False)


def _written(b: dict[str, Any]) -> dict[str, Any]:
    got: dict[str, Any] = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    return got


@pytest.mark.parametrize(("lang", "cat"), [("en", EN), ("ja", JA), ("zh-TW", ZH)])
def test_the_page_asks_the_three_folders_in_each_language(tmp_path: Path, lang: str, cat: dict[str, str]) -> None:
    b = _box(tmp_path)
    shown = _with_code(b).get(f"/login/first-run/answers?lang={lang}").text
    for name in ("backup_dir", "anchor_dir", "log_dir"):
        assert f'name="{name}"' in shown
    for key in ("firstrun.backup.dir", "firstrun.anchor_dir", "firstrun.log_dir", "firstrun.folders.help"):
        assert cat[key] in shown.replace("&#39;", "'"), key


def test_a_production_box_says_it_does_not_finish_without_them(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_ENV="PRODUCTION")
    shown = _with_code(b).get("/login/first-run/answers").text
    assert 'data-testid="firstrun-folders-help"' in shown
    assert "its set-up does not finish until a backup place off the box is mounted" in shown
    assert EN["firstrun.folders.help"] not in shown


def test_the_chosen_folders_go_to_the_answers_file(tmp_path: Path) -> None:
    b = _box(tmp_path)
    r, _ = _answers(_with_code(b), backup_dir="/srv/disk2/", anchor_dir="/mnt/trialbox-audit", log_dir="/srv/logs")
    assert r.status_code == 200 and 'data-testid="firstrun-done"' in r.text, r.text[-600:]
    got = _written(b)
    assert (got["backup_dir"], got["anchor_dir"], got["log_dir"]) == ("/srv/disk2", "/mnt/trialbox-audit", "/srv/logs")


def test_folders_not_chosen_leave_the_answers_file_as_before(tmp_path: Path) -> None:
    b = _box(tmp_path)
    r, _ = _answers(_with_code(b))
    assert r.status_code == 200, r.text[-600:]
    assert not {"backup_dir", "anchor_dir", "log_dir"} & set(_written(b))


@pytest.mark.parametrize("field", ["backup_dir", "anchor_dir", "log_dir"])
@pytest.mark.parametrize("bad", ["relative/folder", "/srv/../etc", "/", "/a b", "/a$(id)", "/a TB_ENV=DEV"])
def test_a_folder_that_is_not_one_plain_full_path_is_refused_and_shown_again(tmp_path: Path, field: str,
                                                                             bad: str) -> None:  # fmt: skip
    b = _box(tmp_path)
    r, _ = _answers(_with_code(b), **{field: bad})
    assert r.status_code == 422 and f'data-testid="err-{field}"' in r.text
    assert EN["firstrun.err.host_dir"] in r.text.replace("&#39;", "'")
    assert b["users"].count() == 0 and not (b["folder"] / firstrun.ANSWERS).exists()
    assert f'id="{field}"' in r.text  # the field is there to be corrected


@pytest.mark.nodb
def test_the_new_texts_are_in_the_three_languages() -> None:
    for cat in (EN, JA, ZH):
        missing = [k for k in NEW_KEYS if not cat.get(k, "").strip()]
        assert not missing, missing
    # the preflight's words (tb_common.preflight, audit_share)
    assert "監査記録の保管先" in JA["firstrun.anchor_dir"] and "稽核紀錄" in ZH["firstrun.anchor_dir"]


# ------------------------------------------------------------------------------------------------ the whole path
def _owner_answers(t: dict[str, Any], tmp_path: Path, proc: subprocess.Popen[str], **over: str) -> None:
    screen = _wait(t["issue"], proc)
    code = re.search(r"One-time code:\s+(\S+)", screen)
    assert code
    app = create_app({**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "console"), "TB_FIRSTRUN_DIR": str(t["fr"]),
                      "TB_CONSOLE_MFA": "totp"}, backend=FakeBackend(), audit=AuditLog(tmp_path / "audit"),
                     users=UserStore())  # fmt: skip
    c = TestClient(app, base_url="https://testserver")
    assert c.post("/login/first-run", data={"code": code.group(1)}, follow_redirects=False).status_code == 303
    r, _ = _answers(c, **over)
    assert r.status_code == 200 and 'data-testid="firstrun-done"' in r.text, r.text[-500:]


def test_a_production_box_does_not_finish_its_set_up_until_its_folders_are_mounted(tmp_path: Path) -> None:
    """The owner chose a second disk at a folder that is not mounted and an audit record folder that is not there: the
    answers are applied, then the box stops before "ready" (nothing restarted on them). Once IT has mounted both
    (here: the folder is there, and the disk's folder carries the off-box mark), --firstrun finishes."""
    t: dict[str, Any] = _tree(tmp_path)
    disk, share = tmp_path / "disk2", tmp_path / "audit-share"
    proc = subprocess.Popen(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--yes"], cwd=tmp_path,
                            env=t["env"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # fmt: skip
    try:
        _owner_answers(t, tmp_path, proc, backup_dir=str(disk), anchor_dir=str(share))
        out, _ = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 1, out[-3000:]
    assert "TrialBox is ready" not in out and "the set-up is not finished" in out
    assert "every backup target is on the box's own disks" in out and f"{share} is not there" in out
    env = dict(ln.split("=", 1) for ln in (t["deploy"] / ".env").read_text(encoding="utf-8").splitlines() if "=" in ln)
    assert env["TB_ENV"] == "PRODUCTION" and env["TB_BACKUP_TARGETS"] == str(disk)  # the owner's answers applied
    assert env["TB_AUDIT_ANCHOR_TARGETS"] == str(share)
    assert "compose up" not in t["calls"].read_text(encoding="utf-8")  # not restarted on the refused settings
    disk.mkdir()
    (disk / ".trialbox-offbox").write_text("", encoding="utf-8")
    share.mkdir()
    again = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), "--firstrun"], cwd=tmp_path, env=t["env"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60, check=False)  # fmt: skip
    assert again.returncode == 0, again.stdout[-2000:]
    assert "TrialBox is ready: https://trialbox.local" in again.stdout and "One-time code:" not in again.stdout
    assert (t["deploy"] / "site" / "compose.anchors.yml").is_file()  # the console reads the signed heads there

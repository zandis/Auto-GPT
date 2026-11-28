"""H-139 (H139-10, the integrator's 7156055986): a box's deploy/.env without ``TB_ENV`` is still a PRODUCTION box.

The key tests now give the code a deploy folder of their own (``tests/own_deploy.py``), so the checkout's
``deploy/.env`` no longer reaches them. This keeps the rule itself under test. One case per group of the H139-10
failures: a box file that names no ``TB_ENV`` makes the key commands, the backup key ceremony and
``trialbox backup-keygen`` ask as a PRODUCTION box, though the caller says TEST (the stricter of the two). SAFE-1 A2
(the owner's decision of 2026-11-28): PRODUCTION allows the key ceremonies, so each now goes past rc1 and stops later
for its own reason on this bare folder, never with rc1's words.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tb_common import rc1_refusals

from tests.own_deploy import own_deploy

pytestmark = pytest.mark.nodb
PRODUCTION = "rc1 holds no backup key ceremony and makes no backup key on a PRODUCTION box"


@pytest.fixture
def box_without_tb_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    deploy = own_deploy(monkeypatch, tmp_path / "box" / "deploy", ceremony=True)
    (deploy / ".env").write_text("TB_SITE_ID=SYN\nCOMPOSE_FILE=docker-compose.yml\n", encoding="utf-8")  # no TB_ENV
    (deploy / ".env").chmod(0o600)
    monkeypatch.setenv("TB_ENV", "TEST")
    return deploy


def test_the_key_commands_read_a_box_file_without_tb_env_as_production(
    box_without_tb_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.keys import main as keys_main

    assert rc1_refusals.host_env(box_without_tb_env, {"TB_ENV": "TEST"}) == {"TB_ENV": "PRODUCTION"}
    sec = ["--secrets", str(tmp_path / "sec")]
    assert keys_main(["restic-key", *sec], env={"TB_ENV": "TEST"}) == 1  # no KEK in this bare folder
    err = capsys.readouterr().err
    assert PRODUCTION not in err and "rc1" not in err and "KEK" in err  # SAFE-1 A2: past rc1
    assert not (tmp_path / "sec").exists()


def test_the_ceremony_and_backup_keygen_read_a_box_file_without_tb_env_as_production(
    box_without_tb_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools import backup_key_ceremony as bkc
    from tools.trialbox.__main__ import main as trialbox_main

    monkeypatch.setattr(bkc, "is_root", lambda: True)
    assert rc1_refusals.host_env(box_without_tb_env, {"TB_ENV": "TEST"}) == {"TB_ENV": "PRODUCTION"}
    with pytest.raises(bkc.Stop) as got:
        bkc.run(tmp_path / "stick", "operator", "witness", {"TB_ENV": "TEST"})
    assert PRODUCTION not in got.value.say("en") and "rc1" not in got.value.say("en")  # SAFE-1 A2: past rc1
    priv, pub = tmp_path / "it" / "backup.key", tmp_path / "pub" / "backup.pub"
    trialbox_main(["backup-keygen", "--private", str(priv), "--public", str(pub)])
    err = capsys.readouterr().err
    assert PRODUCTION not in err and "rc1" not in err


def test_the_same_box_file_naming_test_is_not_refused(
    box_without_tb_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control: the same folder, its file naming TEST, lets the command past the refusal."""
    from tools.keys import main as keys_main

    (box_without_tb_env / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    keys_main(["restic-key", "--secrets", str(tmp_path / "sec")], env={"TB_ENV": "TEST"})
    assert PRODUCTION not in capsys.readouterr().err

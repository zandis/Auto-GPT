"""H-139, item 5 (the integrator's 7151749260): the fixtures now make their folders with explicit modes, whatever the
umask of the run. These tests show that each guard those fixtures met still refuses a folder or file that the group
can write, the case an ordinary user's umask 0002 makes. The group's write bit alone, without others', is enough.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tb_common import kek as K

from tests.unit.test_serving_engine_h112 import GPU_STACKS, ON, _box
from tools import keys
from tools import serving_profile as sp
from tools.trialbox import launch

GROUP_ONLY = (0o620, 0o660, 0o664)


@pytest.mark.parametrize("mode", GROUP_ONLY)
def test_the_box_file_the_group_can_write_is_refused(tmp_path: Path, mode: int) -> None:
    f = tmp_path / ".env"
    f.write_text("TB_DB_URL=postgresql://synthetic@db/x\n", encoding="utf-8")
    f.chmod(mode)
    with pytest.raises(launch.BoxFileError, match="can be written by group or others"):
        launch.box_file(tmp_path)
    f.chmod(0o600)
    assert launch.box_file(tmp_path) == {"TB_DB_URL": "postgresql://synthetic@db/x"}


@pytest.mark.parametrize("mode", [0o775, 0o770, 0o2775])
def test_the_settings_folder_the_group_can_write_is_refused(tmp_path: Path, mode: int) -> None:
    deploy = _box(tmp_path, GPU_STACKS[0], "TB_ENV=TEST\n", settings=ON)
    (deploy / "site").chmod(mode)
    assert any("alone (chmod go-w)" in p for p in sp.settings_problems(deploy)), sp.settings_problems(deploy)
    (deploy / "site").chmod(0o755)
    assert not any("alone (chmod go-w)" in p for p in sp.settings_problems(deploy))


@pytest.mark.parametrize("mode", [0o775, 0o770])
def test_the_passphrase_folder_the_group_can_write_is_refused(tmp_path: Path, mode: int) -> None:
    folder = tmp_path / "pp"
    folder.mkdir()
    f = folder / "init.pass"
    f.write_text("synthetic-h139-passphrase\n", encoding="utf-8")
    f.chmod(0o600)
    folder.chmod(mode)
    with pytest.raises(K.KekError, match=r"can be written by others \(mode 77"):
        keys.read_passphrase_file(str(f))
    folder.chmod(0o700)
    assert keys.read_passphrase_file(str(f)) == "synthetic-h139-passphrase"
    assert os.stat(folder).st_mode & 0o777 == 0o700

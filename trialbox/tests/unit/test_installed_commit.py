"""INSTALLED-COMMIT (D-994): the box records the commit of the release it runs, for the evidence gates (H-15 F1).

``release.json`` names the commit the release was built from (``source.commit``) and is signed with the bundle, but
it lives only in the bundle's ``meta/``: an installed box kept no commit, so a driver on the box had nothing to name
the code by but an image id, which the gates refuse (the integrator's ruling). ``Updater._record``, the one writer of
``deploy/updates/installed.json``, now writes ``commit`` beside ``dirty`` from the verified release, at install and at
every update: a 40-hex string, or ``null`` when the release names none (or anything else). A bundle with no release
record leaves the key out, as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_release_dirty_refused import EnvBox, _release, _upd, _with
from tools import update_status as us

pytestmark = pytest.mark.nodb
SHA = "0123456789abcdef0123456789abcdef01234567"


def _installed(tmp: Path) -> dict[str, object]:
    return us.installed(tmp / "updates")


def test_an_update_records_the_release_commit(tmp_path: Path) -> None:
    assert _upd(EnvBox("PRODUCTION"), tmp_path).run(_with(tmp_path, _release(False, commit=SHA)))["ok"]
    rec = _installed(tmp_path)
    assert rec["commit"] == SHA and rec["dirty"] is False


def test_a_first_install_records_it_too(tmp_path: Path) -> None:
    """install.sh's first record (``apply_update.sh`` on a box never installed) goes through the same writer."""
    _upd(EnvBox("PRODUCTION"), tmp_path)._record(_with(tmp_path, _release(False, commit=SHA)), live=False)
    assert _installed(tmp_path)["commit"] == SHA


def test_a_dirty_release_records_its_commit_and_says_dirty(tmp_path: Path) -> None:
    """The gates refuse it by ``dirty``; the record still says which commit the working tree was on."""
    assert _upd(EnvBox("TEST"), tmp_path).run(_with(tmp_path, _release(True, commit=SHA)))["ok"]
    rec = _installed(tmp_path)
    assert rec["commit"] == SHA and rec["dirty"] is True


@pytest.mark.parametrize("bad", [None, "", "ABCDEF" * 7, SHA[:39], SHA + "0", f"{SHA[:-1]} ", ["x"], 7])
def test_anything_but_a_40_hex_commit_is_recorded_as_null(tmp_path: Path, bad: object) -> None:
    assert _upd(EnvBox("TEST"), tmp_path).run(_with(tmp_path, _release(False, commit=bad)))["ok"]
    rec = _installed(tmp_path)
    assert "commit" in rec and rec["commit"] is None


def test_a_bundle_without_a_release_record_leaves_the_key_out(tmp_path: Path) -> None:
    assert _upd(EnvBox("TEST"), tmp_path).run(_with(tmp_path, None))["ok"]
    assert "commit" not in _installed(tmp_path)

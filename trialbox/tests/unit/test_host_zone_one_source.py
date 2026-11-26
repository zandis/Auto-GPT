"""The host's time zone has one reader (``tb_common.host_zone``): the install's questions (``tools.box.plan.detect``)
and ``deploy/check_host.sh`` take it from there, so the zone the install proposes is the zone the host check reports.
Before, the host check asked ``timedatectl`` first and the install read ``/etc/timezone`` first. Synthetic host folders
only."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_host_baseline import _box, _sh
from tools.box import plan as bp

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize(
    ("named", "linked", "want"),
    [
        ("Asia/Tokyo\n", "Asia/Taipei", "Asia/Tokyo"),  # both name one: the file first
        (None, "Asia/Taipei", "Asia/Taipei"),  # no file: the link
        ("\n", "Europe/Paris", "Europe/Paris"),  # an empty file names none: the link
    ],
)
def test_the_install_and_the_host_check_read_the_same_zone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, named: str | None, linked: str, want: str
) -> None:
    args, env = _box(tmp_path)  # its timedatectl says Asia/Taipei: a reader that asks it first disagrees
    host = tmp_path / "host"
    if named is not None:
        (host / "etc/timezone").write_text(named, encoding="utf-8")
    (host / "etc/localtime").symlink_to(f"/usr/share/zoneinfo/{linked}")
    monkeypatch.setattr(bp, "_run", lambda _cmd: "")  # no card, disk or network of this machine
    install = bp.detect(deploy=tmp_path, host_root=host).host_tz
    out = _sh(args, env).stdout
    assert install == want and f"PASS  host time zone {want}\n" in out, (install, out)

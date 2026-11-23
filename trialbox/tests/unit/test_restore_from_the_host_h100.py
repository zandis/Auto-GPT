"""H-100: the live restore starts from the host (the MVP walk's step 8 on the bench host).

Three gaps, each held here on the real entry point with the repo's stand-in for the container engine:

1. ``backup-nightly --deploy deploy`` (a relative folder) bound ``deploy/secrets/backup.pub`` and the dump folder by
   relative path, which the container engine reads as a volume name: every bind source is absolute now.
2. ``trialbox restore`` from the host ran in a plain one-off container with no hapi URL, no volume and no database
   client: it now runs in the backup image the way the nightly's job does, with the database URLs taken from the
   box's own ``deploy/.env`` (a caller's exported variable changes nothing; no password on a command line).
3. The backup image carries the database client tools (pinned, held, checked) and the superuser URL comes from the
   box, never from the caller.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.test_backup_schedule import FakeBox
from tools.trialbox import backup as bk
from tools.trialbox import update


def _mounts(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]


# ------------------------------------------------------------------------------------------------ gap 1
def test_nightly_with_a_relative_deploy_binds_only_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup_schedule as bs

    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    bk.keygen(tmp_path / "it.key", deploy / "secrets" / "backup.pub")
    nas = tmp_path / "nas"
    (deploy / ".env").write_text(
        "TB_DB_URL=postgresql://trialbox:zq~7!Kd~pw@db:5432/trialbox_wf\nTB_SITE_ID=CGMH\nTB_ENV=TEST\n"
        f"TB_BACKUP_TARGETS={nas}\nTB_BACKUP_RESTIC=off\nTB_BACKUP_JOB_WAIT_S=0\nTB_DOCKER_VOLUMES={tmp_path / 'volumes'}\n",
        encoding="utf-8",
    )
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k)
    fake = FakeBox()
    monkeypatch.setattr(update, "run_cmd", fake)  # the real ComposeOps and ComposeBox, the engine stood in for
    monkeypatch.chdir(tmp_path)
    bs.main_nightly(Path("deploy"))  # as typed from the install folder: `trialbox backup-nightly --deploy deploy`
    runs = [c for c in fake.calls if c[:2] == ["docker", "run"]]
    assert runs, fake.calls
    sources = [m.split(":", 1)[0] for m in _mounts(runs[0])]
    binds = [s for s in sources if not s.startswith("trialbox_")]  # named volumes are names
    assert binds and all(os.path.isabs(s) for s in binds), sources
    assert f"{deploy / 'secrets' / 'backup.pub'}:/in/backup.pub:ro" in _mounts(runs[0])
    assert any(s.startswith(str(deploy / ".backup-")) for s in binds), binds

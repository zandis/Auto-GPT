"""PERF-010 R4 (D-978): the box rehearsal backs up with restic and restores by the custodians' path.

The rehearsal box seals its keys under a passphrase KEK (the integrator's ruling (i)), which no custodians' shares
cover, so its own nightly keeps the single ``.tbbak`` (D-977) and restic never ran in the rehearsal. The step
``restic-restore`` (``tools/rehearse_box/box.sh``) therefore:

* checks that the box's own nightly choice reads "not covered" and names the passphrase KEK;
* makes a throwaway shamir KEK, its shares and a backup key pair in the rehearsal's work folder (never the box's);
* runs the nightly's own backup (``ComposeOps.make_backup``) with those folders against the box's real lake volume,
  in the bundle's backup image with ``--restic``;
* restores into a temporary folder by the custodians' path (``backup-verify --restic-share`` twice: the box's KEK is
  not used) and checks every lake file against the sealed manifest.

The live lake is never wiped. The product change: the restic job mounts the secrets folder the host decided on
(``TB_SECRETS_DIR``), by path, or the box's secrets volume when that is the folder (D-977 mounted the volume always).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tests.unit.test_backup_restic import _backup, site  # noqa: F401
from tests.unit.test_backup_schedule import FakeBox
from tests.unit.test_kek import box  # noqa: F401
from tests.unit.test_restic_password import stewards  # noqa: F401
from tools import keys as keys_cli
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bs

ROOT = Path(__file__).resolve().parents[2]
BOX_SH = ROOT / "tools" / "rehearse_box" / "box.sh"
REHEARSE_SH = ROOT / "tools" / "rehearse_box" / "rehearse.sh"


def _container(tmp_path: Path, secrets: Path | None) -> list[str]:
    deploy = tmp_path / "deploy"
    deploy.mkdir(exist_ok=True)
    (deploy / ".env").write_text("TB_SITE_ID=CGMH\n", encoding="utf-8")
    fake = FakeBox()
    compose = bs.ComposeOps(deploy, fake).box
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    pub = tmp_path / "box.pub"
    pub.write_text("pub")
    compose._backup_container(work, pub, [str(tmp_path / "nas")], restic=True, secrets=secrets)
    return next(c for c in fake.calls if c[:2] == ["docker", "run"])


def test_the_restic_job_mounts_the_secrets_folder_the_host_decided_on(tmp_path: Path) -> None:
    argv = _container(tmp_path, tmp_path / "scratch-secrets")
    assert f"{tmp_path / 'scratch-secrets'}:/run/secrets/trialbox:ro" in argv
    assert "trialbox_tb-secrets:/run/secrets/trialbox:ro" not in argv


def test_the_boxs_own_folder_is_its_volume(tmp_path: Path) -> None:
    for secrets in (None, Path(keys_cli.HOST_SECRETS)):
        argv = _container(tmp_path, secrets)
        assert "trialbox_tb-secrets:/run/secrets/trialbox:ro" in argv


def test_the_nightly_passes_the_folder_it_checked(tmp_path: Path) -> None:
    """The host checks TB_SECRETS_DIR's KEK and makes the key there; the job must open the same folder."""
    src = (ROOT / "tools" / "trialbox" / "backup_schedule.py").read_text(encoding="utf-8")
    call = src[src.index("self.box._backup_container(work, cfg.public_key") :]
    call = call[: call.index("# fmt: skip")]
    assert "secrets=self.secrets_dir()" in call


def test_verify_says_how_many_lake_files_came_from_restic(site: dict[str, Any]) -> None:  # noqa: F811
    """The rehearsal must see that the lake came back from restic, not an empty record: verify says so."""
    f = _backup(site)
    res = bk.verify(f, site["priv"], restic_pw=site["pw"])
    assert res["restic"]["files"] == 3 and res["restic"]["snapshot"]
    assert "pw" not in json_text(res) and site["pw"] not in json_text(res)


def json_text(d: dict[str, Any]) -> str:
    import json

    return json.dumps(d)


# ------------------------------------------------------------------------------------------------ the rehearsal step
def _step() -> str:
    text = BOX_SH.read_text(encoding="utf-8")
    m = re.search(r"\nrestic-restore\)\n(.*?)\n  ;;\n", text, re.S)
    assert m, "box.sh has no restic-restore phase"
    return m.group(1)


def test_the_rehearsal_runs_the_step_after_the_screens_built_the_lake() -> None:
    text = REHEARSE_SH.read_text(encoding="utf-8")
    steps = re.findall(r"^step ([a-z-]+) ", text, re.M)
    assert "restic-restore" in steps
    assert steps.index("restic-restore") > steps.index("screen-after-restart")


def test_the_step_uses_a_throwaway_shamir_kek_in_the_work_folder() -> None:
    s = _step()
    assert "--backend shamir" in s and '"$W/' in s.split("--backend shamir")[0].rsplit("\n", 3)[-1] + s
    assert "TB_KEK_FILE=" in s and "TB_KEK_HOST_DIR" in s
    assert "/run/trialbox/kek" not in s  # never the box's unsealed KEK
    assert "deploy/secrets/backup" not in s  # never the box's backup key


def test_the_step_checks_the_boxs_own_choice() -> None:
    s = _step()
    assert "incremental(" in s and "passphrase" in s


def test_the_step_restores_by_the_custodians_path_and_never_wipes_the_lake() -> None:
    s = _step()
    assert "backup-verify" in s and s.count("--restic-share") >= 2
    assert "--restic-from-box" not in s
    assert not re.search(r"\brm -rf\b[^\n]*(lake|/v/)", s)  # only its own work folder is removed
    assert '"restic"' in s and "is True" in s  # the run used restic, by the record

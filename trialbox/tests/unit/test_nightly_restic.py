"""PERF-010 R3c (D-977): the nightly backup sends the lake to restic when the custodians' shares cover the KEK.

``backup-nightly`` decides each night, before the backup container starts:

* ``TB_BACKUP_RESTIC=off``: the single ``.tbbak``, said so;
* the KEK not covered by shares (no KEK, a passphrase or KMS KEK, a TPM KEK without a current escrow set):
  the single ``.tbbak``, with the reason, never a failure, never a restic key the custodians could not open;
* covered: the host makes ``restic.key`` under the KEK when it is not there yet (``restic_repo.make_key``), and the
  backup runs in the ``trialbox-backup`` image (the release's job image, D-968's R1) with ``--restic``, the secrets
  volume and the unsealed KEK mounted read-only.

The choice and its reason go into ``backup-last.json`` and the audit, as ``incremental``. Every key and share is made
in the test's tmp folder.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

from tests.unit.test_backup_schedule import T0, FakeBox, _cfg, _offbox
from tests.unit.test_kek import _cli, box  # noqa: F401
from tests.unit.test_key_escrow import _escrow, tpm  # noqa: F401
from tests.unit.test_restic_password import stewards  # noqa: F401
from tools.trialbox import backup_schedule as bs
from tools.trialbox import restic_repo as rr


# ------------------------------------------------------------------------------------------------ do shares cover it
def test_a_shamir_kek_is_covered(stewards: dict[str, Path]) -> None:  # noqa: F811
    assert rr.shares_cover(stewards["sec"]) == ""


def test_a_tpm_kek_is_covered_only_with_its_current_escrow_set(
    tpm: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "not covered by escrow shares" in rr.shares_cover(tpm["sec"])
    assert _cli(capsys, *_escrow(tpm))[0] == 0
    assert rr.shares_cover(tpm["sec"]) == ""


def test_a_passphrase_kek_and_no_kek_are_not_covered(
    box: dict[str, Path],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert "no KEK" in rr.shares_cover(box["sec"])
    assert "no KEK" in rr.shares_cover(box["tmp"] / "no-such-folder")
    pp = box["tmp"] / "kek.pass"  # H-96 (ruling 7094934985): tools.keys takes it from a root-only file, not the env
    pp.write_text("a passphrase long enough for the rule here\n", encoding="utf-8")
    pp.chmod(0o600)
    assert (
        _cli(capsys, "init", "--secrets", str(box["sec"]), "--backend", "passphrase", "--passphrase-file", str(pp))[0]
        == 0
    )
    assert "not covered by escrow shares" in rr.shares_cover(box["sec"])


# ------------------------------------------------------------------------------------------------ the nightly's choice
def _ops(tmp_path: Path, sec: Path, extra: str = "") -> bs.ComposeOps:
    deploy = tmp_path / "deploy"
    deploy.mkdir(exist_ok=True)
    (deploy / ".env").write_text(f"TB_SITE_ID=CGMH\nTB_SECRETS_DIR={sec}\n{extra}", encoding="utf-8")
    return bs.ComposeOps(deploy, FakeBox())


def test_covered_makes_the_key_on_the_host_and_chooses_restic(tmp_path: Path, stewards: dict[str, Path]) -> None:  # noqa: F811
    sec = stewards["sec"]
    assert not K.wrapped_path(sec / rr.KEY).exists()
    ops = _ops(tmp_path, sec)
    use, why = ops.incremental(bs.config(ops.deploy, ops.env, process_env=False))
    assert use is True and "made" in why
    assert K.wrapped_path(sec / rr.KEY).exists() and not (sec / rr.KEY).exists()  # only ever wrapped
    use, why = ops.incremental(bs.config(ops.deploy, ops.env, process_env=False))
    assert use is True and "made" not in why  # the second night uses the key it has


def test_not_covered_keeps_the_single_backup_and_says_why(tmp_path: Path, tpm: dict[str, Path]) -> None:  # noqa: F811
    ops = _ops(tmp_path, tpm["sec"])
    use, why = ops.incremental(bs.config(ops.deploy, ops.env, process_env=False))
    assert use is False and "not covered by escrow shares" in why
    assert not K.wrapped_path(tpm["sec"] / rr.KEY).exists()  # no key the custodians could not open


def test_off_by_the_site(tmp_path: Path, stewards: dict[str, Path]) -> None:  # noqa: F811
    ops = _ops(tmp_path, stewards["sec"], "TB_BACKUP_RESTIC=off\n")
    cfg = bs.config(ops.deploy, ops.env, process_env=False)
    assert cfg.restic == "off"
    assert ops.incremental(cfg) == (False, "TB_BACKUP_RESTIC=off: the single encrypted backup")
    assert not K.wrapped_path(stewards["sec"] / rr.KEY).exists()


def test_a_bad_setting_is_a_setting_error(tmp_path: Path) -> None:
    cfg = bs.config(tmp_path, {"TB_BACKUP_RESTIC": "yes"}, process_env=False)
    assert any("TB_BACKUP_RESTIC" in e for e in cfg.setting_errors)


# ------------------------------------------------------------------------------------------------ the job container
def _run_argv(fake: FakeBox) -> list[str]:
    return next(c for c in fake.calls if c[:2] == ["docker", "run"])


def test_the_restic_backup_runs_in_the_backup_image_with_the_keys_read_only(tmp_path: Path) -> None:
    ops = _ops(tmp_path, tmp_path / "sec")
    work = tmp_path / "work"
    work.mkdir()
    pub = tmp_path / "box.pub"
    pub.write_text("pub")
    ops.box._backup_container(work, pub, [str(tmp_path / "nas")], restic=True)
    argv = _run_argv(ops.box.run)  # type: ignore[arg-type]
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert "trialbox-backup:1.0.0" in argv and "trialbox-py:1.0.0" not in argv
    assert "trialbox_tb-secrets:/run/secrets/trialbox:ro" in mounts
    assert "/run/trialbox:/run/trialbox:ro" in mounts
    assert argv[argv.index("backup") :].count("--restic") == 1


def test_the_single_backup_is_as_before(tmp_path: Path) -> None:
    ops = _ops(tmp_path, tmp_path / "sec")
    work = tmp_path / "work"
    work.mkdir()
    pub = tmp_path / "box.pub"
    pub.write_text("pub")
    ops.box._backup_container(work, pub, [str(tmp_path / "nas")])
    argv = _run_argv(ops.box.run)  # type: ignore[arg-type]
    assert "trialbox-py:1.0.0" in argv and "--restic" not in argv
    # the secrets volume is in every backup already (read-only at /v/secrets, encrypted to the hospital's key); only
    # the restic job gets it where tools.keys reads it, and the unsealed KEK
    assert not any(a.endswith(":/run/secrets/trialbox:ro") or ":/run/trialbox" in a for a in argv)


def test_the_images_and_the_kek_folder_follow_the_settings(tmp_path: Path) -> None:
    ops = _ops(tmp_path, tmp_path / "sec", "TB_BACKUP_IMAGE=reg.example/trialbox-backup:9\nTB_KEK_HOST_DIR=/run/kek\n")
    work = tmp_path / "work"
    work.mkdir()
    pub = tmp_path / "box.pub"
    pub.write_text("pub")
    ops.box._backup_container(work, pub, [str(tmp_path / "nas")], restic=True)
    argv = _run_argv(ops.box.run)  # type: ignore[arg-type]
    assert "reg.example/trialbox-backup:9" in argv and "/run/kek:/run/trialbox:ro" in argv


# ------------------------------------------------------------------------------------------------ the record
def test_the_night_records_its_choice(tmp_path: Path, tpm: dict[str, Path]) -> None:  # noqa: F811
    ops = _ops(tmp_path, tpm["sec"])
    cfg = _cfg(tmp_path, deploy=ops.deploy)
    audits: list[tuple[str, dict[str, Any]]] = []
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: audits.append((e, d)), now=T0,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"], res["errors"]
    inc = res["incremental"]
    assert inc["restic"] is False and "not covered by escrow shares" in inc["why"]
    assert audits[-1][1]["incremental"] == inc
    argv = _run_argv(ops.box.run)  # type: ignore[arg-type]
    assert "--restic" not in argv


def test_restic_is_never_started_without_the_host_key(
    tmp_path: Path,
    stewards: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A KEK that locks between the check and the key (the unseal gone): no restic, the reason said, the backup made."""
    ops = _ops(tmp_path, stewards["sec"])
    monkeypatch.setenv("TB_KEK_FILE", str(tmp_path / "no-kek-here"))
    for v in ("CREDENTIALS_DIRECTORY", "TB_KEK_PASSPHRASE"):
        monkeypatch.delenv(v, raising=False)
    use, why = ops.incremental(bs.config(ops.deploy, ops.env, process_env=False))
    assert use is False and "restic key" in why
    assert not K.wrapped_path(stewards["sec"] / rr.KEY).exists()
    _ = os  # keep the import for the environment fixture

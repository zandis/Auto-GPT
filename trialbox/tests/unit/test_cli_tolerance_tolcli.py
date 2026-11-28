"""TOL-CLI (TOL-1 §2.4; STOPS.csv T-U005, T-U007, T-U008, T-A002b; REAL2 M-6, M-7; E2E P-15).

The CLI verbs a clinic's IT person types on the host, each on a fake box (the engine and the restore step stood in):

* ``backup --to DIR`` on the host mounts the box's own public key into the one-off container (M-6);
* ``restore <backup folder> --key K`` is one command: the newest backup in the folder, the box's own defaults, no
  ``--yes`` (the box is kept as an encrypted copy first; the way back is printed), the pack beside the backup (M-7);
* ``restore-drill`` and ``mail status`` that cannot start say what they need, in en, ja and zh-TW (P-15);
* usage errors stay refusals at second 0 that change nothing, and name the fix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import __main__ as cli
from tools.trialbox import launch

NAME = "trialbox-CGMH-{}.tbbak"


def _backups(folder: Path, *stamps: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for s in stamps:
        f = folder / NAME.format(s)
        f.write_bytes(b"x")
        out.append(f)
    return out


def _deploy(tmp_path: Path) -> Path:
    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=TEST\n", encoding="utf-8")
    return deploy


# ------------------------------------------------------------------------------------------------ M-6
@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []

    def run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("tools.trialbox.launch.subprocess.run", run)
    return seen


def test_m6_backup_on_the_host_mounts_the_boxs_public_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: list[list[str]]
) -> None:
    deploy = _deploy(tmp_path)
    pub = deploy / "secrets" / "backup.pub"
    pub.write_text("pub", encoding="utf-8")
    monkeypatch.setattr(launch, "DEPLOY", deploy)
    nas = tmp_path / "nas"
    assert launch.run_in_image(["backup", "--to", str(nas)], launch.COMMANDS["backup"], {}) == 0
    argv = engine[0]
    assert f"{pub}:{pub}:ro" in argv, argv  # the file the image did not have
    assert argv[argv.index("--public") + 1] == str(pub)


def test_m6_a_public_key_that_is_given_or_set_in_the_box_file_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: list[list[str]]
) -> None:
    deploy = _deploy(tmp_path)
    monkeypatch.setattr(launch, "DEPLOY", deploy)
    mine, theirs = tmp_path / "mine.pub", tmp_path / "theirs.pub"
    mine.write_text("a", encoding="utf-8")
    theirs.write_text("b", encoding="utf-8")
    need = launch.COMMANDS["backup"]
    launch.run_in_image(["backup", "--to", str(tmp_path / "n"), "--public", str(mine)], need, {})
    assert engine[0].count("--public") == 1 and f"{mine}:{mine}:ro" in engine[0]
    launch.run_in_image(["backup", "--to", str(tmp_path / "n")], need, {"TB_BACKUP_PUBKEY": str(theirs)})
    assert f"{theirs}:{theirs}:ro" in engine[1]


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_m6_no_public_key_is_said_at_second_zero_in_the_language_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: list[list[str]],
    capsys: pytest.CaptureFixture[str], lang: str,
) -> None:  # fmt: skip
    monkeypatch.setattr(launch, "DEPLOY", _deploy(tmp_path))
    monkeypatch.setenv("TB_LANG", lang)
    assert launch.run_in_image(["backup", "--to", str(tmp_path / "n")], launch.COMMANDS["backup"], {}) == 2
    err = capsys.readouterr().err
    assert engine == [] and "backup-keygen" in err and "backup.pub" in err
    if lang != "en":
        assert not err.isascii(), err  # the words are the language's own


# ------------------------------------------------------------------------------------------------ M-7
class Step:
    """The host's restore step stood in: what it was given."""

    def __init__(self) -> None:
        self.got: Any = None

    def __call__(self, a: Any) -> int:
        self.got = a
        return 0


@pytest.fixture
def host_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Step]:
    from tools.trialbox import box_restore

    step = Step()
    monkeypatch.setattr(box_restore, "main", step)
    return _deploy(tmp_path), step


def test_m7_restore_from_a_backup_folder_needs_no_flag_but_the_folder_and_the_key(
    tmp_path: Path, host_box: tuple[Path, Step], capsys: pytest.CaptureFixture[str]
) -> None:
    deploy, step = host_box
    nas = tmp_path / "nas"
    newest = _backups(nas, "20261109T194500Z", "20261110T194500Z")[1]
    (nas / "snomed.tar").write_bytes(b"pack")  # the vendor pack kept beside the backups
    (deploy / ".env").write_text(f"TB_ENV=TEST\nTB_REFDATA_DIR={tmp_path / 'none'}\n", encoding="utf-8")
    code = cli.main(["restore", str(nas), "--key", str(tmp_path / "usb.key"), "--deploy", str(deploy)], installed=True)
    assert code == 0
    a = step.got
    assert Path(a.file) == newest  # the newest of the folder
    assert Path(a.public) == deploy / "secrets" / "backup.pub"  # the box's own
    assert Path(a.keep_to) == deploy / "pre-restore"
    assert Path(a.refdata) == nas  # the pack from beside the backup
    err = capsys.readouterr().err
    assert newest.name in err and str(deploy / "pre-restore") in err  # which backup, where the copy goes


def test_m7_the_kept_refdata_folder_still_wins_when_it_holds_the_packs(
    tmp_path: Path, host_box: tuple[Path, Step]
) -> None:
    deploy, step = host_box
    kept = deploy / "refdata" / "loaded"
    kept.mkdir(parents=True)
    (kept / "snomed.tar").write_bytes(b"pack")
    nas = tmp_path / "nas"
    (f,) = _backups(nas, "20261110T194500Z")
    (nas / "other.tar").write_bytes(b"pack")
    (deploy / ".env").write_text(f"TB_ENV=TEST\nTB_REFDATA_DIR={kept}\n", encoding="utf-8")
    assert cli.main(["restore", str(f), "--key", "k", "--deploy", str(deploy)], installed=True) == 0
    assert Path(step.got.refdata) == kept


def test_m7_a_file_named_is_restored_as_before_with_or_without_yes(tmp_path: Path, host_box: tuple[Path, Step]) -> None:
    deploy, step = host_box
    (f,) = _backups(tmp_path / "nas", "20261110T194500Z")
    for extra in ([], ["--yes"]):
        step.got = None
        assert cli.main(["restore", str(f), "--key", "k", "--deploy", str(deploy), *extra], installed=True) == 0
        assert Path(step.got.file) == f


def test_u007_without_yes_the_way_back_is_printed(
    tmp_path: Path, host_box: tuple[Path, Step], capsys: pytest.CaptureFixture[str]
) -> None:
    deploy, step = host_box
    (f,) = _backups(tmp_path / "nas", "20261110T194500Z")
    assert cli.main(["restore", str(f), "--key", "k", "--deploy", str(deploy)], installed=True) == 0
    err = capsys.readouterr().err
    assert step.got is not None and "trialbox restore <" in err and "--key" in err, err  # the undo command


def test_u008_no_copy_still_needs_yes_really(
    tmp_path: Path, host_box: tuple[Path, Step], capsys: pytest.CaptureFixture[str]
) -> None:
    """The kept class: a restore that keeps no copy of data it replaces stays a refusal (LOSS)."""
    deploy, step = host_box
    (f,) = _backups(tmp_path / "nas", "20261110T194500Z")
    argv = ["restore", str(f), "--key", "k", "--deploy", str(deploy), "--no-copy"]
    assert cli.main(argv, installed=True) == 2
    assert step.got is None and "--yes-really" in capsys.readouterr().err
    assert cli.main([*argv, "--yes-really"], installed=True) == 0 and step.got is not None
    assert "trialbox restore <" not in capsys.readouterr().err  # no copy kept: no way back is promised


def test_u008_no_copy_is_refused_in_process_too_and_neither_backend_starts(
    tmp_path: Path, host_box: tuple[Path, Step], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy, step = host_box
    ran: list[Any] = []

    def backup(a: Any) -> int:
        ran.append(a)
        return 0

    monkeypatch.setattr(cli, "_backup_cmd", backup)
    monkeypatch.setattr(launch, "has_libs", lambda *_a, **_k: True)  # a developer's interpreter: not the host
    (f,) = _backups(tmp_path / "nas", "20261110T194500Z")
    argv = ["restore", str(f), "--key", "k", "--deploy", str(deploy), "--no-copy"]
    assert cli.main(argv) == 2
    assert step.got is None and not ran and "--yes-really" in capsys.readouterr().err
    assert cli.main([*argv, "--yes"]) == 0 and len(ran) == 1  # the container the host started: --yes, as before
    assert cli.main([*argv, "--yes-really"]) == 0 and len(ran) == 2  # acknowledged: the in-process restore runs
    assert "trialbox restore <" not in capsys.readouterr().err  # it keeps no copy here: no way back is promised


def test_texts_fall_back_to_english_without_tb_common_or_with_an_unknown_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from tools.trialbox import cli_text

    real = builtins.__import__

    def blocked(name: str, *a: Any, **k: Any) -> Any:
        if name.startswith("tb_common"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.setenv("TB_LANG", "ja")
    assert cli_text.lang() == "en" and cli_text.say("restore_both") == cli_text.TEXTS["restore_both"]["en"]
    monkeypatch.setattr(builtins, "__import__", real)
    monkeypatch.setattr(cli_text, "lang", lambda: "xx")  # a code the texts do not carry
    assert cli_text.say("restore_both") == cli_text.TEXTS["restore_both"]["en"]


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_usage_errors_stay_second_zero_refusals_that_name_the_fix(
    tmp_path: Path, host_box: tuple[Path, Step], capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch, lang: str,
) -> None:  # fmt: skip
    deploy, step = host_box
    monkeypatch.setenv("TB_LANG", lang)
    empty = tmp_path / "empty"
    empty.mkdir()
    (f,) = _backups(tmp_path / "nas", "20261110T194500Z")
    both = ["restore", str(f), "--last", "--key", "k", "--deploy", str(deploy)]
    no_key = ["restore", str(f), "--deploy", str(deploy)]
    no_backup = ["restore", str(empty), "--key", "k", "--deploy", str(deploy)]
    no_source = ["restore", "--key", "k", "--deploy", str(deploy)]
    for argv, word in ((both, "--last"), (no_key, "--key"), (no_backup, ".tbbak"), (no_source, "--last")):
        assert cli.main(argv, installed=True) == 2, argv
        assert step.got is None  # nothing was started
        err = capsys.readouterr().err
        assert word in err, (argv, err)
        if lang != "en":
            assert not err.isascii(), err


# ------------------------------------------------------------------------------------------------ P-15
@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_p15_restore_drill_without_arguments_says_what_it_needs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, lang: str
) -> None:
    monkeypatch.setenv("TB_LANG", lang)
    assert cli.main(["restore-drill"], installed=True) == 2
    err = capsys.readouterr().err
    assert "--key" in err and "restore-drill" in err, err
    assert "Traceback" not in err
    if lang != "en":
        assert not err.isascii(), err


def test_p15_restore_drill_takes_a_folder_for_its_newest_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import restore_drill as rd

    seen: dict[str, Any] = {}

    def drill(file: Path, key: Path, env: Any, **_kw: Any) -> dict[str, Any]:
        seen["file"] = file
        return {"ok": True}

    monkeypatch.setattr(rd, "drill", drill)
    monkeypatch.setattr(rd, "record", lambda *a, **k: {})
    nas = tmp_path / "nas"
    newest = _backups(nas, "20261109T194500Z", "20261110T194500Z")[1]
    assert cli.main(["restore-drill", str(nas), "--key", "k", "--deploy", str(_deploy(tmp_path))]) == 0
    assert seen["file"] == newest


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_p15_mail_status_without_settings_or_docker_says_what_to_do(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lang: str
) -> None:
    from mail_gateway import admin
    from tb_common.config import ConfigError

    def no_settings(*_a: Any) -> int:
        raise ConfigError("no settings file")

    monkeypatch.setattr(admin, "main", no_settings)  # the host: no settings file
    monkeypatch.setenv("TB_LANG", lang)
    monkeypatch.setenv("TB_COMPOSE", str(tmp_path / "no-such-compose"))  # Docker cannot be started
    monkeypatch.delenv("TB_SERVICE_NAME", raising=False)
    monkeypatch.delenv("TB_ENV_FILE", raising=False)
    assert cli.main(["mail", "status"]) == 2
    err = capsys.readouterr().err
    assert "trialbox mail status" in err and "Traceback" not in err, err  # the command to run, on the box
    if lang != "en":
        assert not err.isascii(), err

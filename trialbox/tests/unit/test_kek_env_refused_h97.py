"""H-97 part C (the integrator's 7102655419; the review of H-96, L-2; H-94 (5)): no path takes the KEK passphrase from
a caller's environment.

H-96 refused ``TB_KEK_PASSPHRASE`` in the installers, the seal step and ``tools.keys``; three paths still honoured it:
``tb_common.kek.load_kek`` derived the KEK from the process environment, the nightly audit signer handed its container
``-e TB_KEK_PASSPHRASE`` (a caller's value lands in that container's configuration, ``docker inspect``), and the
nightly's restic key step forwarded it. Now ``load_kek`` refuses the process environment's value (the KEK file, the
start path of every box, is read first and unchanged; ``tools.keys`` still hands it the value it read from a root-only
file or stdin, in a mapping it builds), the signer is never given the name, and the restic step never forwards it.
The passphrases here are synthetic.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

from tests.unit.test_audit_heads_nightly import box as signer_box  # noqa: F401
from tests.unit.test_kek import box  # noqa: F401  (the stewards fixture stands on it)
from tests.unit.test_nightly_restic import _ops
from tests.unit.test_restic_password import stewards  # noqa: F401
from tools import keys
from tools.trialbox import audit_heads
from tools.trialbox import restic_repo as rr

pytestmark = pytest.mark.nodb
PHRASE = "synthetic-h97-" + "kek-passphrase-for-tests"  # synthetic


def _passphrase_box(tmp: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    sec = tmp / "sec"
    sec.mkdir(parents=True)
    for folder in (tmp, sec):  # H-139 (item 5, ruled b): explicit modes, never the run's umask
        folder.chmod(0o700)
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    pp = tmp / "init.pass"
    pp.write_text(PHRASE + "\n", encoding="utf-8")
    pp.chmod(0o600)
    assert keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                      "--passphrase-file", str(pp)], env={}) == 0  # fmt: skip
    capsys.readouterr()
    return sec


def test_load_kek_refuses_the_process_environment_and_keeps_the_start_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE RULE for the library: with TB_KEK_PASSPHRASE exported and no KEK file, load_kek refuses (never printing
    the value), whether it is handed the process environment or a copy of it. A box unsealed the usual way (the KEK
    file the unseal writes) still opens with the variable exported: the start path is unchanged. The mapping
    tools.keys builds from a root-only file or stdin still opens it."""
    sec = _passphrase_box(tmp_path, capsys)
    runtime = tmp_path / "run" / "kek"
    monkeypatch.setenv("TB_KEK_FILE", str(runtime))
    want = K.derive_from_passphrase(PHRASE, K.read_meta(sec) or {})
    # tools.keys' own path: the value in a mapping it built (the process environment holds none)
    monkeypatch.delenv("TB_KEK_PASSPHRASE", raising=False)
    assert K.load_kek(sec, {**os.environ, "TB_KEK_PASSPHRASE": PHRASE}) == want
    monkeypatch.setenv("TB_KEK_PASSPHRASE", PHRASE)
    for env in (None, os.environ, dict(os.environ), {**os.environ, "TB_KEK_PASSPHRASE": PHRASE}):
        with pytest.raises(K.KekError) as got:
            K.load_kek(sec, env)
        assert "TB_KEK_PASSPHRASE is set in the environment: refused" in str(got.value)
        assert PHRASE not in str(got.value)
    # the start path: tools.keys unseal writes the KEK file (from a root-only file here), and every load reads it
    pp = tmp_path / "unseal.pass"
    pp.write_text(PHRASE + "\n", encoding="utf-8")
    pp.chmod(0o600)
    monkeypatch.delenv("TB_KEK_PASSPHRASE")
    runtime.parent.mkdir()
    assert keys.main(["unseal", "--secrets", str(sec), "--out", str(runtime), "--passphrase-file", str(pp)]) == 0
    monkeypatch.setenv("TB_KEK_PASSPHRASE", PHRASE)
    assert K.load_kek(sec) == want and K.load_key_file(sec / "site_hmac.key")


def test_the_audit_signer_is_never_handed_the_passphrase(
    signer_box: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly signer's container: TB_KEK_PASSPHRASE exported by the caller is neither on its command line nor
    named there (no ``-e``), nor in the environment the docker command is run with."""
    monkeypatch.setenv("TB_KEK_PASSPHRASE", PHRASE)
    seen: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: list[str], env: dict[str, str] | None = None, **_: Any) -> str:
        seen.append((list(argv), dict(env or {})))
        if "run" in argv[:3]:
            return '{"ok": true, "problems": [], "signed": null, "detail": {}}'
        return ""

    env = {**os.environ, "TB_AUDIT_HOST_DIR": str(signer_box["audit"]),
           "TB_SECRETS_HOST_DIR": str(signer_box["secrets"]), "TB_AUDIT_ANCHOR_TARGETS": str(signer_box["share"])}  # fmt: skip
    audit_heads.sign_on_box(signer_box["deploy"], env, run=run)
    signer = next((a, e) for a, e in seen if "run" in a[:3])
    assert "TB_KEK_PASSPHRASE" not in signer[0] and PHRASE not in " ".join(signer[0])
    assert "TB_KEK_PASSPHRASE" not in signer[1] and PHRASE not in signer[1].values()
    assert "TB_KEK_PASSPHRASE" not in audit_heads.PASSED


def test_the_restic_key_step_never_forwards_the_passphrase(
    tmp_path: Path,
    stewards: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The nightly's restic key step: a passphrase in deploy/.env (refused there since H-96, written by hand here) is
    not forwarded to the key's load; one exported by the caller reaches load_kek only to be refused there."""
    from tools.trialbox import backup_schedule as bs

    got: list[dict[str, str]] = []

    def make_key(sec: Path, env: dict[str, str]) -> bool:
        got.append(dict(env))
        return True

    monkeypatch.setattr(rr, "make_key", make_key)
    monkeypatch.delenv("TB_KEK_PASSPHRASE", raising=False)
    ops = _ops(tmp_path, stewards["sec"], f"TB_KEK_PASSPHRASE={PHRASE}\n")
    use, _ = ops.incremental(bs.config(ops.deploy, ops.env, process_env=False))
    assert use is True and got and "TB_KEK_PASSPHRASE" not in got[-1]
    monkeypatch.setenv("TB_KEK_PASSPHRASE", PHRASE)
    monkeypatch.setenv("TB_KEK_FILE", str(tmp_path / "pp-not-unsealed"))  # a passphrase box not unsealed
    sec = _passphrase_box(tmp_path / "pp", capsys)
    with pytest.raises(K.KekError, match="refused"):
        K.load_kek(sec, dict(os.environ))  # what the step hands the key's load


@pytest.mark.parametrize("given", ["process", "mapping"])
def test_an_empty_variable_is_neither_a_refusal_nor_a_passphrase(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    """docker-compose.secrets.yml gives every other service TB_KEK_PASSPHRASE="" : an empty value is dropped. A box
    not unsealed is locked, as before (no refusal's words), and no KEK is derived from an empty passphrase."""
    sec = _passphrase_box(tmp_path, capsys)
    monkeypatch.setenv("TB_KEK_FILE", str(tmp_path / "not-unsealed"))
    if given == "process":
        monkeypatch.setenv("TB_KEK_PASSPHRASE", "")
        env: dict[str, str] | None = None
    else:
        monkeypatch.delenv("TB_KEK_PASSPHRASE", raising=False)
        env = {**os.environ, "TB_KEK_PASSPHRASE": ""}
    with pytest.raises(K.KekLockedError) as got:
        K.load_kek(sec, env)
    assert "refused" not in str(got.value) and "not unsealed" in str(got.value)


@pytest.mark.parametrize("value", [None, "", PHRASE, "synthetic-h97-some-other-value"])
def test_with_the_kek_file_the_start_path_is_byte_for_byte_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    """A box unsealed the usual way (tools.keys unseal writes the KEK file): load_kek returns exactly that file's bytes,
    and the site key opens, whatever the environment holds (unset, empty, the passphrase, another value)."""
    sec = _passphrase_box(tmp_path, capsys)
    runtime = tmp_path / "run" / "kek"
    runtime.parent.mkdir()
    pp = tmp_path / "unseal.pass"
    pp.write_text(PHRASE + "\n", encoding="utf-8")
    pp.chmod(0o600)
    monkeypatch.delenv("TB_KEK_PASSPHRASE", raising=False)
    assert (
        keys.main(["unseal", "--secrets", str(sec), "--out", str(runtime), "--passphrase-file", str(pp)], env={}) == 0
    )
    monkeypatch.setenv("TB_KEK_FILE", str(runtime))
    if value is not None:
        monkeypatch.setenv("TB_KEK_PASSPHRASE", value)
    for env in (None, dict(os.environ)):
        assert K.load_kek(sec, env) == runtime.read_bytes()
    assert K.load_key_file(sec / "site_hmac.key")


def test_tools_keys_builds_its_mapping_only_from_the_file_or_stdin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mapping tools.keys hands a command holds the passphrase only from --passphrase-file or --passphrase-stdin:
    a caller's value is refused before any command runs (exit 2, never printed), and an empty one adds nothing."""
    seen: list[dict[str, str]] = []

    def spy(a: object, env: dict[str, str]) -> int:
        seen.append(dict(env))
        return 0

    monkeypatch.setitem(keys.COMMANDS, "unseal", spy)
    pp = tmp_path / "unseal.pass"
    pp.write_text(PHRASE + "\n", encoding="utf-8")
    pp.chmod(0o600)
    argv = ["unseal", "--secrets", str(tmp_path / "sec"), "--passphrase-file", str(pp), "--keep-passphrase-files"]
    monkeypatch.setenv("TB_KEK_PASSPHRASE", "synthetic-h97-a-callers-value")
    assert keys.main(argv) == 2 and seen == []
    err = capsys.readouterr().err
    assert "refused" in err and "synthetic-h97-a-callers-value" not in err
    monkeypatch.setenv("TB_KEK_PASSPHRASE", "")
    assert keys.main(argv) == 0 and seen[-1]["TB_KEK_PASSPHRASE"] == PHRASE  # the file's value, nothing else
    monkeypatch.delenv("TB_KEK_PASSPHRASE")
    assert keys.main(["unseal", "--secrets", str(tmp_path / "sec")]) == 0 and "TB_KEK_PASSPHRASE" not in seen[-1]

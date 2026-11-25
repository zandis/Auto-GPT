"""H-96 (finding F-45, the integrator's ruling 7094934985): the KEK passphrase comes from a file only root can read or
from stdin, never from the environment.

The install test on a real host found it: the passphrase was given as ``sudo --preserve-env=TB_KEK_PASSPHRASE ...``
(the form the installers' help and RUNBOOK §16 showed), and sudo logged it as an ``ENV=`` line in the system
journal, which root and the adm group read. Now install.sh, box-install.sh, the bootstrap, seal_keys.sh and
tools.keys (its rotation too) refuse a passphrase in the environment, and take it from ``--kek-passphrase-file``
(a regular file, not a link, owned by the user that runs it, mode 0600; removed once the keys are sealed unless
``--keep-kek-passphrase-file``) or ``--kek-passphrase-stdin``. The signed re-run of install.sh gets a stdin
passphrase on a pipe at fd 8: never an argument, never an environment, never a file.

The invariant test runs the real install.sh under a stand-in sudo that logs its arguments and environment as sudo
does: the first run, the bundle load (a stand-in loader that does what the load does to the folder), the run from
the signed release, and the real seal step (the steps between the re-run and the site keys are cut from the signed
copy: settings, compose, TLS; the box rehearsal runs them whole). Every passphrase here is synthetic.
"""

from __future__ import annotations

import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

from tests.unit.test_rehearsal_real_servers_signed_rerun_h89 import rerun_bench
from tools import keys

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
PHRASE = "synthetic-h96-" + "passphrase-for-tests-only"  # synthetic; never a real passphrase
REFUSED = "TB_KEK_PASSPHRASE is set in the environment: refused"
BLOCK = re.compile(r"# ---- KEK-INPUT functions.*?# ---- end of KEK-INPUT functions\n", re.S)

# the stand-ins: sudo logs what sudo logs (its command line, and every variable it passes, with its value), then
# runs the command with the VAR=value words it was given; python3 logs its arguments and environment; docker logs its
# arguments and has every image
SUDO = """#!/bin/sh
{ printf 'COMMAND='; for a in "$@"; do printf ' %s' "$a"; done; printf '\\n'; env | sed 's/^/ENV=/'; } >> "$TB_SUDO_LOG"
exec env "$@"
"""
PY3 = f"""#!/bin/sh
{{ printf 'ARGV=%s\\n' "$*"; env | sed 's/^/ENV=/'; }} >> "$TB_ARGS_LOG"
[ ! -e /proc/self/fd/8 ] || echo "FD8=open" >> "$TB_ARGS_LOG"
exec {sys.executable} "$@"
"""
DOCKER = r"""#!/bin/sh
echo "$*" >> "$TB_TEST_LOG"
[ ! -e /proc/self/fd/8 ] || echo "FD8=open" >> "$TB_TEST_LOG"
case "$1 $2" in
  "volume ls") exit 0 ;;
  "version --format") echo 27.0; exit 0 ;;
  "image inspect") exit 0 ;;
esac
echo "Runtimes: nvidia runc"
"""
# the signed copy: the real installer with the steps between the run from the signed release and the site keys cut
# (the stand-in root of the seal step's own check: the tests run as any user)
CUT_START = "# Expose the signed host CLI on PATH."
CUT_END = "# T-612 (DATA-004): the site keys are made here"
CUT_IN = """id() { if [ "${1:-}" = -u ]; then echo 0; else command id "$@"; fi; }
HOST_PROFILE=site; TB_ENV_SITE=VALIDATION; COMPOSE=(echo compose)
echo "CUT: the steps between the run from the signed release and the site keys"
"""
SEALED = "SEALED BY THE RUN FROM THE SIGNED RELEASE"


def _write_pp(path: Path, text: str = PHRASE + "\n", mode: int = 0o600) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def _signed_copy(text: str) -> str:
    head, rest = text.split(CUT_START, 1)
    rest = rest[rest.index(CUT_END) :]
    after = '[ -z "$KP_FILE" ] || echo "    the KEK passphrase file $KP_FILE was not used'
    i = rest.index("\n", rest.index(after)) + 1
    return head + CUT_IN + rest[:i] + f'echo "{SEALED}"; exit 0\n'


def _box(tmp: Path) -> tuple[object, dict[str, str]]:
    b = rerun_bench(tmp)
    signed = _signed_copy((ROOT / "deploy" / "install.sh").read_text(encoding="utf-8"))
    (b.deploy / "install.sh.signed").write_text(signed, encoding="utf-8")
    (b.deploy / "hardening").mkdir()
    for name in ("seal_keys.sh", "lib.sh"):
        shutil.copy(ROOT / "deploy" / "hardening" / name, b.deploy / "hardening" / name)
    for name, text in (("sudo", SUDO), ("python3", PY3), ("docker", DOCKER)):
        (b.bin / name).write_text(text, encoding="utf-8")
        (b.bin / name).chmod(0o755)
    sec = tmp / "secrets"
    sec.mkdir()
    for name in ("site_hmac.key", "pid_map.key"):
        (sec / name).write_bytes(os.urandom(32))
    env = {**b.env(), "PYTHONPATH": f"{tmp / 'libs'}:{tmp}", "TB_SUDO_LOG": str(tmp / "sudo.log"),
           "TB_ARGS_LOG": str(tmp / "args.log"), "TB_SECRETS_HOST_DIR": str(sec), "TB_SYSTEMD": "0",
           "TB_KEK_FILE": str(tmp / "kek.runtime")}  # fmt: skip
    return b, env


def _install_under_sudo(
    b: object, env: dict[str, str], *more: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    args = ["--rehearsal", "--rehearsal-real-servers", "--gpu", "rtxpro6000", "--gpu-index", "1",
            "--engine-probe", str(b.probe), "--yes", *more]  # type: ignore[attr-defined]  # fmt: skip
    argv = [str(b.bin / "sudo"), "TB_KEK_BACKEND=passphrase", "bash", str(b.deploy / "install.sh"),  # type: ignore[attr-defined]
            str(b.tmp / "b.tar"), *args]  # type: ignore[attr-defined]  # fmt: skip
    return subprocess.run(argv, cwd=b.tmp, input=stdin if stdin is not None else "", capture_output=True, text=True,  # type: ignore[attr-defined]
                          env=env, timeout=300, check=False)  # fmt: skip


@pytest.mark.parametrize("given", ["file", "file-kept", "stdin"])
def test_no_passphrase_in_a_sudo_log_an_argument_or_an_environment_through_the_signed_rerun(
    tmp_path: Path, given: str
) -> None:
    """THE INVARIANT (H-96): under a stand-in sudo that logs its arguments and environment, the real installer's first
    run, the bundle load, the run from the signed release and the real seal step leave the passphrase in no sudo log
    line, no argument any process was given (sudo, docker, python3), no process environment the stand-ins saw, no
    output and no deploy/.env; and the keys are sealed under exactly that passphrase by the run from the signed
    release. The file is removed after sealing, or kept with --keep-kek-passphrase-file."""
    b, env = _box(tmp_path)
    pp = _write_pp(tmp_path / "kek.pass")
    more: tuple[str, ...] = {"file": ("--kek-passphrase-file", str(pp)),
                             "file-kept": ("--kek-passphrase-file", str(pp), "--keep-kek-passphrase-file"),
                             "stdin": ("--kek-passphrase-stdin",)}[given]  # fmt: skip
    r = _install_under_sudo(b, env, *more, stdin=PHRASE + "\n" if given == "stdin" else None)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "continuing from the signed release" in out and SEALED in out, out[-4000:]
    assert out.count("the passphrase file") == (1 if given.startswith("file") else 0), out[-2000:]
    logs = {name: (tmp_path / name).read_text(encoding="utf-8") for name in ("sudo.log", "args.log", "docker.log")}
    assert "ENV=TB_TEST_LOG=" in logs["sudo.log"] and "COMMAND=" in logs["sudo.log"]  # the stand-in logs what sudo does
    assert "ARGV=-m tools.keys init" in logs["args.log"]  # the keys commands ran on the logged python3
    for name, text in {**logs, "output": out}.items():
        assert PHRASE not in text, f"the passphrase is in {name}"
    assert "TB_KEK_PASSPHRASE=" not in logs["args.log"] + logs["sudo.log"]
    # the hand-on at fd 8 is read and closed by the run from the signed release: no child of it holds it open
    assert "FD8=open" not in logs["args.log"] + logs["docker.log"]
    env_file = b.deploy / ".env"  # type: ignore[attr-defined]
    assert not env_file.exists() or PHRASE not in env_file.read_text(encoding="utf-8")
    meta = K.read_meta(tmp_path / "secrets")
    assert meta is not None and meta["backend"] == "passphrase"
    kek = b.hostroot / "run" / "trialbox" / "kek"  # type: ignore[attr-defined]  # H-118: the box's own place
    assert K.derive_from_passphrase(PHRASE, meta) == kek.read_bytes()  # sealed under it
    assert pp.exists() is (given != "file")  # removed after sealing; kept when asked (stdin: never touched)


# ------------------------------------------------------------------------------------------------ the environment form
def _bootstrap(tmp: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    (tmp / "b.tar").write_bytes(b"")
    (tmp / "k.pub").write_text("stand-in\n", encoding="utf-8")
    return subprocess.run(["bash", str(ROOT / "deploy" / "bootstrap.sh"), str(tmp / "b.tar"), "--pub", str(tmp / "k.pub")],
                          cwd=tmp, env={**env, "TB_BOOTSTRAP_NO_ROOT": "1", "TB_BOOTSTRAP_ROOT": str(tmp / "opt")},
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


def _script(tmp: Path, script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    argv = {"install.sh": ["bash", str(ROOT / "deploy" / "install.sh"), str(tmp / "b.tar"), "--yes"],
            "box-install.sh": ["bash", str(ROOT / "deploy" / "box-install.sh"), str(tmp / "b.tar"), "--yes"],
            "seal_keys.sh": ["sh", str(SEAL), "--secrets", str(tmp), "--dry-run"]}[script]  # fmt: skip
    return subprocess.run(argv, cwd=tmp, env={**env, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}"},
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip


@pytest.mark.parametrize("var", ["TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE"])
@pytest.mark.parametrize("script", ["install.sh", "box-install.sh", "bootstrap.sh", "seal_keys.sh"])
def test_a_passphrase_in_the_environment_is_refused_before_anything(tmp_path: Path, script: str, var: str) -> None:
    """With or without sudo: exit 2, a plain message that names the file form and says the value is to be treated
    as exposed, the value never printed, and nothing run (the stand-in docker is never called)."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "docker").write_text(f'#!/bin/sh\necho "$*" >> {tmp_path}/docker.log\n', encoding="utf-8")
    (tmp_path / "bin" / "docker").chmod(0o755)
    (tmp_path / "b.tar").write_bytes(b"")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {var: PHRASE, "TB_BOX_NO_ROOT": "1"}
    r = _bootstrap(tmp_path, env) if script == "bootstrap.sh" else _script(tmp_path, script, env)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert f"{var} is set in the environment: refused, nothing was changed" in r.stderr
    assert "exposed" in r.stderr and "--kek-passphrase-file FILE" in r.stderr and "mode 0600" in r.stderr
    assert PHRASE not in r.stdout + r.stderr
    assert not (tmp_path / "docker.log").exists() and not (tmp_path / "opt").exists()


def test_an_empty_variable_is_no_passphrase_and_is_dropped(tmp_path: Path) -> None:
    """An empty TB_KEK_PASSPHRASE exposes nothing: not refused, and dropped so no child sees it (a dry run goes on)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_KEK_PASSPHRASE": ""}
    r = subprocess.run(["sh", "-c", '. /dev/stdin; kp_refuse_env; env | grep -c "^TB_KEK_PASSPHRASE" || :'],
                       input="KP_WHO=t\n" + BLOCK.search(SEAL.read_text(encoding="utf-8")).group(0),  # type: ignore[union-attr]
                       env=env, capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0 and r.stdout.strip() == "0", r


@pytest.mark.parametrize("command", [["init", "--backend", "passphrase"], ["unseal"],
                                     ["rotate-kek", "--backend", "passphrase"], ["status"]])  # fmt: skip
@pytest.mark.parametrize("var", ["TB_KEK_PASSPHRASE", "TB_KEK_NEW_PASSPHRASE"])
def test_tools_keys_refuses_the_environment_on_every_command_rotation_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str], var: str
) -> None:
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    rc = keys.main([*command, "--secrets", str(sec)], env={var: PHRASE})
    err = capsys.readouterr().err
    assert rc == 2 and f"{var} is set in the environment: refused" in err and "exposed" in err
    assert "--passphrase-file FILE" in err and PHRASE not in err
    assert sorted(p.name for p in sec.iterdir()) == ["site_hmac.key"]  # nothing made or wrapped


# ------------------------------------------------------------------------------------------------ the file's checks
def _bad_file(tmp: Path, case: str) -> tuple[Path, str]:
    good = _write_pp(tmp / "good.pass")
    if case == "link":
        (tmp / "link.pass").symlink_to(good)
        return tmp / "link.pass", "is a link"
    if case == "mode":
        return _write_pp(tmp / "mode.pass", mode=0o640), "has mode 640, not 0600"
    if case == "two-lines":  # the second line without its line break: wc -l says 1
        return _write_pp(tmp / "two.pass", PHRASE + "\nsecond line"), "line break"
    if case == "three-lines":
        return _write_pp(tmp / "three.pass", PHRASE + "\nsecond\nthird\n"), "line break"
    if case == "not-regular":
        (tmp / "dir.pass").mkdir()
        return tmp / "dir.pass", "not a regular file"
    # not the owner's: a file of root's when the tests run as another user, else one given away
    if os.geteuid() != 0:
        return Path("/etc/passwd"), "is owned by uid 0, not root (the user that runs this)"
    f = _write_pp(tmp / "theirs.pass")
    os.chown(f, 65534, 65534)
    return f, "is owned by uid 65534, not root (the user that runs this)"


CASES = ["link", "owner", "mode", "two-lines", "three-lines", "not-regular"]


@pytest.mark.parametrize("case", CASES)
def test_seal_keys_refuses_a_file_that_is_not_roots_alone(tmp_path: Path, case: str) -> None:
    f, said = _bad_file(tmp_path, case)
    sec = tmp_path / "sec"
    sec.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_KEK_BACKEND": "passphrase",
                                                                             "TB_HOST_ROOT": str(tmp_path)}  # fmt: skip
    r = subprocess.run(["sh", str(SEAL), "--secrets", str(sec), "--kek-passphrase-file", str(f), "--dry-run"],
                       env=env, capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 1 and said in r.stderr, r.stderr
    assert "would run" not in r.stdout and PHRASE not in r.stdout + r.stderr
    ok = subprocess.run(["sh", str(SEAL), "--secrets", str(sec), "--kek-passphrase-file", str(tmp_path / "good.pass"),
                         "--dry-run"], env=env, capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert ok.returncode == 0 and "would run: tools.keys init --backend passphrase" in ok.stdout, ok.stderr


@pytest.mark.parametrize("case", CASES)
def test_install_and_box_install_refuse_the_file_before_anything(tmp_path: Path, case: str) -> None:
    f, said = _bad_file(tmp_path, case)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "docker").write_text(f'#!/bin/sh\necho "$*" >> {tmp_path}/docker.log\n', encoding="utf-8")
    (tmp_path / "bin" / "docker").chmod(0o755)
    (tmp_path / "b.tar").write_bytes(b"")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_BOX_NO_ROOT": "1",
           "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}  # fmt: skip
    for argv in (["bash", str(ROOT / "deploy" / "install.sh"), str(tmp_path / "b.tar")],
                 ["bash", str(ROOT / "deploy" / "box-install.sh"), str(tmp_path / "b.tar"), "--answers",
                  str(tmp_path / "owner.json")]):  # fmt: skip
        r = subprocess.run([*argv, "--kek-passphrase-file", str(f), "--yes"], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
        assert r.returncode == 1 and said in r.stderr, (argv[1], r.stderr)
        assert not (tmp_path / "docker.log").exists() and PHRASE not in r.stdout + r.stderr


@pytest.mark.parametrize("case", CASES)
def test_tools_keys_refuses_the_file_too(tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str) -> None:
    f, said = _bad_file(tmp_path, case)
    sec = tmp_path / "sec"
    sec.mkdir()
    rc = keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--passphrase-file", str(f)], env={})
    err = capsys.readouterr().err
    words = {"link": "is a link", "mode": "has mode 640, not 0600", "two-lines": "more than one line",
             "three-lines": "more than one line", "not-regular": "not a regular file"}.get(case, said)  # fmt: skip
    assert rc == 1 and words in err, err
    assert not (sec / K.META_FILE).exists() and PHRASE not in err


def test_a_relative_file_path_is_refused_by_the_installers(tmp_path: Path) -> None:
    """install.sh and box-install.sh run from their folder: a relative path would name another file."""
    _write_pp(tmp_path / "rel.pass")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_BOX_NO_ROOT": "1"}
    for script in ("install.sh", "box-install.sh"):
        extra = ["--answers", "o.json"] if script == "box-install.sh" else []
        r = subprocess.run(["bash", str(ROOT / "deploy" / script), "b.tar", *extra, "--kek-passphrase-file",
                            "rel.pass"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
                           check=False)  # fmt: skip
        assert r.returncode == 1 and "give the file's full path" in r.stderr, (script, r.stderr)


# ------------------------------------------------------------------------------------------------ removed or kept
def _seal(tmp: Path, *more: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    for name in ("site_hmac.key", "pid_map.key"):
        if not K.wrapped_path(sec / name).exists():
            (sec / name).write_bytes(os.urandom(32))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    env |= {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "TB_HOST_ROOT": str(tmp / "host"),
            "TB_SYSTEMD": "0", "TB_KEK_FILE": str(tmp / "kek.runtime"), "TB_KEK_BACKEND": "passphrase"}  # fmt: skip
    return subprocess.run(["sh", str(SEAL), "--secrets", str(sec), "--conf", str(tmp / "none"), *more], input=stdin,
                          env=env, capture_output=True, text=True, timeout=300, check=False)  # fmt: skip


def test_the_file_is_removed_after_sealing_and_kept_when_asked(tmp_path: Path) -> None:
    f = _write_pp(tmp_path / "kek.pass")
    r = _seal(tmp_path, "--kek-passphrase-file", str(f), "--keep-kek-passphrase-file")
    assert r.returncode == 0 and f.exists() and "is kept (--keep-kek-passphrase-file)" in r.stdout, r.stderr
    meta = K.read_meta(tmp_path / "secrets")
    kek = tmp_path / "host" / "run" / "trialbox" / "kek"  # H-118: the box's own place, never the caller's
    assert meta is not None and K.derive_from_passphrase(PHRASE, meta) == kek.read_bytes()
    kek.unlink()  # a restart since: the box with a KEK is opened from the file, then wrapped
    (tmp_path / "secrets" / "extra.key").write_bytes(b"")  # not a protected key: nothing more to wrap
    r = _seal(tmp_path, "--kek-passphrase-file", str(f))
    assert r.returncode == 0 and not f.exists() and "is removed" in r.stdout, r.stderr
    assert kek.read_bytes() == K.derive_from_passphrase(PHRASE, meta)


def test_a_failed_seal_keeps_the_file_for_the_next_run(tmp_path: Path) -> None:
    f = _write_pp(tmp_path / "kek.pass", "short\n")  # tools.keys init refuses fewer than 12 characters
    r = _seal(tmp_path, "--kek-passphrase-file", str(f))
    assert r.returncode != 0 and "shorter than 12 characters" in r.stderr and f.exists()
    assert not (tmp_path / "secrets" / K.META_FILE).exists()


def test_seal_keys_on_a_terminal_asks_twice_not_shown(tmp_path: Path) -> None:
    """--kek-passphrase-stdin at a terminal: asked twice with the echo off; two that differ change nothing."""
    sec = tmp_path / "sec"
    sec.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_KEK_BACKEND": "passphrase",
                                                                             "TB_HOST_ROOT": str(tmp_path)}  # fmt: skip
    for second, want in ((PHRASE, "would run: tools.keys init --backend passphrase"), ("other", "differ")):
        pid, fd = pty.fork()
        if pid == 0:  # the child: the script on the terminal
            os.execvpe("sh", ["sh", str(SEAL), "--secrets", str(sec), "--kek-passphrase-stdin", "--dry-run"], env)
        seen = b""
        for line in (PHRASE, second):
            while b": " not in seen.rsplit(b"\n", 1)[-1]:
                select.select([fd], [], [], 10)
                seen += os.read(fd, 1024)
            os.write(fd, (line + "\n").encode())
            seen += b"\n"
            time.sleep(0.1)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], 1)[0]:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            seen += chunk
        os.waitpid(pid, 0)
        text = seen.decode(errors="replace")
        assert want in text and "the same again" in text, text
        assert PHRASE not in text  # the terminal's echo was off


# ------------------------------------------------------------------------------------------------ rotation
def _sealed_box(tmp: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    f = _write_pp(tmp / "old.pass")
    assert keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                      "--passphrase-file", str(f)], env={}) == 0  # fmt: skip
    capsys.readouterr()
    return sec


def test_rotation_takes_the_old_and_the_new_passphrase_from_files_or_stdin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sec = _sealed_box(tmp_path, capsys)
    site = K.unwrap(K.derive_from_passphrase(PHRASE, K.read_meta(sec) or {}), K.read_wrapped(sec / "site_hmac.key"),
                    "site_hmac.key")  # fmt: skip
    new = "synthetic-h96-the-new-one-for-tests"
    old_f, new_f = _write_pp(tmp_path / "old.pass"), _write_pp(tmp_path / "new.pass", new + "\n")
    runtime = tmp_path / "kek.runtime"  # not unsealed: the old passphrase opens it
    from tb_common.audit import AuditLog

    audit = tmp_path / "audit"  # the box's chain: every rotation is an audit event (ruling 7114085298, F3)
    AuditLog(audit).append("test.box_ready", actor="tester")
    rc = keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(old_f), "--new-passphrase-file", str(new_f)],
                   env={"TB_KEK_FILE": str(runtime), "TB_ENV": "DEV", "TB_AUDIT_DIR": str(audit)})  # fmt: skip
    out = capsys.readouterr()
    assert rc == 0, out.err
    meta = K.read_meta(sec) or {}
    assert K.unwrap(K.derive_from_passphrase(new, meta), K.read_wrapped(sec / "site_hmac.key"), "site_hmac.key") == site
    assert not old_f.exists() and not new_f.exists()  # both files removed once used
    assert PHRASE not in out.out + out.err and new not in out.out + out.err
    # stdin: two lines, the old first; a wrong old one changes nothing
    import io

    newer = "synthetic-h96-the-newer-one-for-tests"
    for old, rc_want in (("not-the-current-one-at-all", 1), (new, 0)):
        before = (sec / K.META_FILE).read_bytes()
        stdin = io.StringIO(f"{old}\n{newer}\n")
        sys_stdin, sys.stdin = sys.stdin, stdin
        try:
            rc = keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                            "--passphrase-stdin", "--new-passphrase-stdin"],
                           env={"TB_KEK_FILE": str(runtime), "TB_ENV": "DEV", "TB_AUDIT_DIR": str(audit)})  # fmt: skip
        finally:
            sys.stdin = sys_stdin
        capsys.readouterr()
        assert rc == rc_want
        assert ((sec / K.META_FILE).read_bytes() == before) is (rc_want == 1)
    meta = K.read_meta(sec) or {}
    assert (
        K.unwrap(K.derive_from_passphrase(newer, meta), K.read_wrapped(sec / "site_hmac.key"), "site_hmac.key") == site
    )


def test_keep_passphrase_files_keeps_them(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    f = _write_pp(tmp_path / "p.pass")
    assert keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                      "--passphrase-file", str(f), "--keep-passphrase-files"], env={}) == 0  # fmt: skip
    assert f.exists() and "is removed" not in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ held together
def test_the_three_copies_of_the_kek_input_functions_are_one() -> None:
    """install.sh and box-install.sh are copied alone into test folders and run from the stick's tree: each carries
    the functions itself; the three copies are the same lines."""
    blocks = {f: BLOCK.findall((ROOT / f).read_text(encoding="utf-8"))
              for f in ("deploy/install.sh", "deploy/box-install.sh", "deploy/hardening/seal_keys.sh")}  # fmt: skip
    assert all(len(b) == 1 for b in blocks.values()), {f: len(b) for f, b in blocks.items()}
    assert len({b[0] for b in blocks.values()}) == 1


def test_no_script_exports_the_passphrase_or_puts_it_on_a_command_line() -> None:
    """The value lives in KP_VALUE: never exported, never an argument (a pipe to stdin), never an -e of docker."""
    for f in ("deploy/install.sh", "deploy/box-install.sh", "deploy/hardening/seal_keys.sh", "deploy/bootstrap.sh",
              "tools/rehearse_box/box.sh", "tools/rehearse_box/rehearse.sh"):  # fmt: skip
        text = (ROOT / f).read_text(encoding="utf-8")
        assert not re.search(r"export\s+(TB_KEK_\w*PASSPHRASE|KP_VALUE)", text), f
        assert "--preserve-env=TB_KEK" not in text and "-e TB_KEK_PASSPHRASE" not in text, f
        for ln in text.splitlines():
            if "$KP_VALUE" in ln and not ln.lstrip().startswith("#"):
                piped = re.search(r"printf '%s\\n' \"\$KP_VALUE\"(\s*\||\))", ln)  # to a pipe: stdin or fd 8
                assert piped or "[" in ln or "KP_VALUE=" in ln, (f, ln)
    firstrun = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8").split("6. apply")[1]
    assert "--kek-passphrase-stdin" in firstrun.split("TZ_NEW=")[0]


def test_the_runbook_tool_writes_the_throwaway_passphrase_by_stdin_never_the_environment() -> None:
    """tools/runbook_install.py put it in docker exec's -e (its argument list) and the bootstrap's environment."""
    from tools import runbook_install as ri

    seen: list[tuple[str, dict[str, str] | None, str]] = []

    class Machine:
        def sh(self, command: str, *, cwd: str, env: dict[str, str] | None = None, stdin: str = "",
               timeout: int = 3600) -> ri.Result:  # fmt: skip
            seen.append((command, env, stdin))
            return ri.Result(0, "", "", 0.0)

    src = Path(ri.__file__).read_text(encoding="utf-8")
    assert '"TB_KEK_PASSPHRASE"' not in src and "KEK_PASS_FILE" in src
    cls = next(v for v in vars(ri).values() if isinstance(v, type) and hasattr(v, "_kek_file"))
    run: Any = object.__new__(cls)
    run.m = Machine()
    run.kek_pass = PHRASE
    assert run._kek_file()
    ((command, env, stdin),) = seen
    assert PHRASE not in command and not env and stdin == PHRASE + "\n" and "umask 077" in command

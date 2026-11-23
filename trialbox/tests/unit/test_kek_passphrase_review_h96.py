"""H-96, the review round of #1398 (the independent review 7102655010; the integrator's ruling 7102655419).

M-1: the passphrase file was checked by its name, one check at a time, and its folder never: another user who could
write the folder could swap the file between the checks and the read (the review won 23 of 400 in the shell and 259
of 3000 in tools.keys), and a link put in place once the keys were sealed made ``shred -u`` empty any root file. Now
the file's folders (real paths) must be root's (the user that runs this) and writable by no one else (a sticky shared
folder is allowed above the file's own folder); the file is opened once, checked on that descriptor (type, owner,
mode, one name) and read from it; the shell, which cannot open without following a link, also checks that the name
is still that very file and not a link; tools.keys opens with O_NOFOLLOW and checks with fstat; the file is removed
with rm (a link is taken away, never what it names). install.sh reads it once and hands it on by fd 8 and a pipe.

L-1: box-install.sh opens fd 8 only for a passphrase from stdin. The mutation survivors the review listed each get a
test here. Every passphrase here is synthetic.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from tb_common import kek as K

from tests.console.test_box_install_rehearsal import OWNER, _tree, _unattended
from tools import keys

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
SEAL = ROOT / "deploy" / "hardening" / "seal_keys.sh"
OPERATOR = "synthetic-h96-operator-passphrase-for-tests"  # synthetic
OTHER = "synthetic-h96-other-users-passphrase-for-tests"  # synthetic: what a swap would put in
BLOCK = re.compile(r"# ---- KEK-INPUT functions.*?# ---- end of KEK-INPUT functions\n", re.S)
RENAME_EXCHANGE = 2


def _pp(path: Path, text: str = OPERATOR + "\n", mode: int = 0o600) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def _folder(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)
    return path


# ------------------------------------------------------------------------------------------------ the shell's read
HARNESS = """KP_WHO=harness
{block}
kp_read_file "$1"
if [ "$KP_VALUE" = "$2" ]; then echo ACCEPTED-OPERATOR; else echo ACCEPTED-OTHER; fi
"""


def _harness(tmp: Path) -> Path:
    block = BLOCK.search(SEAL.read_text(encoding="utf-8"))
    assert block
    h = tmp / "read.sh"
    h.write_text(HARNESS.format(block=block.group(0)), encoding="utf-8")
    return h


def _shell_read(h: Path, f: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(h), str(f), OPERATOR], capture_output=True, text=True, timeout=30, check=False)


def test_the_shell_reads_a_file_in_a_safe_folder(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    f = _pp(_folder(tmp_path / "safe") / "kek.pass")
    r = _shell_read(h, f)
    assert r.returncode == 0 and r.stdout.strip() == "ACCEPTED-OPERATOR", r.stderr


@pytest.mark.parametrize(
    ("layout", "said"),
    [
        ("own-0777", "can be written by others (mode 777)"),
        ("own-0770", "can be written by others (mode 770)"),
        ("own-sticky-1777", "can be written by others (mode 1777)"),  # the file's own folder: never a shared one
        ("parent-0777", "can be written by others (mode 777)"),  # a folder above it, not sticky
        ("hard-link", "has 2 names (hard links), not one"),
    ],
)
def test_the_shell_refuses_a_folder_others_can_write_and_a_second_name(tmp_path: Path, layout: str, said: str) -> None:
    h = _harness(tmp_path)
    if layout.startswith("own-"):
        mode = int(layout.rsplit("-", 1)[1], 8)
        f = _pp(_folder(tmp_path / "d") / "kek.pass")
        (tmp_path / "d").chmod(mode)
    elif layout == "parent-0777":
        f = _pp(_folder(_folder(tmp_path / "open", 0o777) / "safe") / "kek.pass")
    else:
        f = _pp(_folder(tmp_path / "safe") / "kek.pass")
        os.link(f, tmp_path / "safe" / "second.name")
    r = _shell_read(h, f)
    assert r.returncode == 1 and said in r.stderr and "ACCEPTED" not in r.stdout, r.stderr
    assert OPERATOR not in r.stdout + r.stderr


def test_the_shell_refuses_a_folder_owned_by_another_user(tmp_path: Path) -> None:
    """The folders must be root's (the user that runs this). Run as root, the file's folder is given to uid 65534;
    run as a user (as CI does, who cannot chown), a stand-in `id` says the runner is uid 4242, so the test's own
    folders are another user's. Either way the folder's owner is what refuses it."""
    h = _harness(tmp_path)
    f = _pp(_folder(tmp_path / "safe") / "kek.pass")
    env = dict(os.environ)
    if os.geteuid() == 0:
        os.chown(tmp_path / "safe", 65534, 65534)
    else:
        b = _folder(tmp_path / "bin", 0o755)
        (b / "id").write_text(
            '#!/bin/sh\n[ "$*" = -u ] && { echo 4242; exit 0; }\nexec /usr/bin/id "$@"\n', encoding="utf-8"
        )
        (b / "id").chmod(0o755)
        env["PATH"] = f"{b}:{os.environ['PATH']}"
    r = subprocess.run(["sh", str(h), str(f), OPERATOR], env=env, capture_output=True, text=True, timeout=30,
                       check=False)  # fmt: skip
    assert r.returncode == 1 and "the folder" in r.stderr and "not root: refused" in r.stderr, r.stderr
    assert "ACCEPTED" not in r.stdout


def test_a_sticky_shared_folder_above_the_files_own_folder_is_allowed(tmp_path: Path) -> None:
    """/tmp is 1777: no one else can rename what is root's there, so a root-only folder under it is safe."""
    h = _harness(tmp_path)
    f = _pp(_folder(_folder(tmp_path / "shared", 0o1777) / "safe") / "kek.pass")
    r = _shell_read(h, f)
    assert r.returncode == 0 and r.stdout.strip() == "ACCEPTED-OPERATOR", r.stderr


SWAPPER = """
import ctypes, os, sys, time
libc = ctypes.CDLL(None, use_errno=True)
a, b, until = sys.argv[1].encode(), sys.argv[2].encode(), time.monotonic() + float(sys.argv[3])
while time.monotonic() < until:
    libc.renameat2(-100, a, -100, b, 2)
"""


def _swapper(a: Path, b: Path, seconds: float) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", SWAPPER, str(a), str(b), str(seconds)])


def _has_renameat2() -> bool:
    return hasattr(ctypes.CDLL(None), "renameat2")


@pytest.mark.parametrize("folder", ["0777", "0700"])
def test_the_swap_race_never_reads_another_value_in_the_shell(tmp_path: Path, folder: str) -> None:
    """THE RACE, as the review ran it: a loop exchanges the file's name with a link to a file holding another value
    (renameat2 RENAME_EXCHANGE) while the real kp_read_file reads it, 300 times. In a folder others can write (0777)
    every read is refused at the folder check. In a folder only the runner writes (0700; the swap stands for a write
    that is no longer possible) the descriptor checks see the link or the changed file: the other value is never
    accepted."""
    assert _has_renameat2(), "this libc has no renameat2: the race cannot be run here"
    h = _harness(tmp_path)
    d = _folder(tmp_path / "d", int(folder, 8))
    f = _pp(d / "kek.pass")
    _pp(tmp_path / "other.pass", OTHER + "\n")
    (d / "swap").symlink_to(tmp_path / "other.pass")
    seen = {"ACCEPTED-OPERATOR": 0, "ACCEPTED-OTHER": 0, "refused": 0}
    sw = _swapper(f, d / "swap", 120)
    try:
        for _ in range(300):
            r = _shell_read(h, f)
            seen[r.stdout.strip() if r.returncode == 0 else "refused"] += 1
    finally:
        sw.kill()
        sw.wait()
    print(f"shell, folder {folder}: {seen}")
    assert seen["ACCEPTED-OTHER"] == 0, seen
    if folder == "0777":
        assert seen["ACCEPTED-OPERATOR"] == 0, seen


def test_a_link_at_removal_is_taken_away_never_what_it_names(tmp_path: Path) -> None:
    """kp_remove_file (the seal step's, install.sh's) on a name that has become a link: the link goes, the file it
    names (a stand-in for any root file: deploy/.env, kek.json) keeps every byte."""
    block = BLOCK.search(SEAL.read_text(encoding="utf-8"))
    assert block
    victim = tmp_path / "a-root-file"
    victim.write_text("kept, every byte\n", encoding="utf-8")
    victim.chmod(0o600)
    name = _folder(tmp_path / "safe") / "kek.pass"
    name.symlink_to(victim)
    r = subprocess.run(["sh", "-c", f'KP_WHO=t\n{block.group(0)}\nkp_remove_file "$1"', "sh", str(name)],
                       capture_output=True, text=True, timeout=30, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert not name.is_symlink() and victim.read_text(encoding="utf-8") == "kept, every byte\n"
    assert "shred" not in block.group(0)


def test_seal_keys_refuses_a_file_in_a_folder_others_can_write_and_touches_nothing(tmp_path: Path) -> None:
    """The review's input 3: the seal step on a file in a folder another user can write is refused before anything,
    so nothing is sealed and nothing is removed afterwards."""
    d = _folder(tmp_path / "shared", 0o777)
    f = _pp(d / "kek.pass")
    sec = _folder(tmp_path / "sec")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_KEK_BACKEND": "passphrase",
                                                                             "TB_HOST_ROOT": str(tmp_path)}  # fmt: skip
    r = subprocess.run(["sh", str(SEAL), "--secrets", str(sec), "--kek-passphrase-file", str(f), "--dry-run"],
                       env=env, capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 1 and "can be written by others" in r.stderr, r.stderr
    assert f.read_text(encoding="utf-8") == OPERATOR + "\n" and "would run" not in r.stdout


# ------------------------------------------------------------------------------------------------ tools.keys
def _keys_read(f: Path) -> str:
    try:
        return "ACCEPTED-OPERATOR" if keys.read_passphrase_file(str(f)) == OPERATOR else "ACCEPTED-OTHER"
    except K.KekError:
        return "refused"


@pytest.mark.parametrize(
    ("layout", "said"),
    [
        ("own-0777", "can be written by others (mode 777)"),
        ("own-sticky-1777", "can be written by others (mode 1777)"),  # the file's own folder: never a shared one
        ("parent-0777", "can be written by others (mode 777)"),
        ("hard-link", "has 2 names (hard links), not one"),
        ("mode-0400", "has mode 400, not 0600"),
        ("mode-0700", "has mode 700, not 0600"),
        ("link-to-a-good-file", "is a link"),  # a link to a file that passes every other check
    ],
)
def test_tools_keys_refuses_an_unsafe_folder_a_second_name_a_mode_and_a_link(
    tmp_path: Path, layout: str, said: str
) -> None:
    safe = _folder(tmp_path / "safe")
    if layout == "own-0777":
        f = _pp(_folder(tmp_path / "d", 0o777) / "kek.pass")
    elif layout == "own-sticky-1777":
        f = _pp(_folder(tmp_path / "d", 0o1777) / "kek.pass")
    elif layout == "parent-0777":
        f = _pp(_folder(_folder(tmp_path / "open", 0o777) / "safe") / "kek.pass")
    elif layout == "hard-link":
        f = _pp(safe / "kek.pass")
        os.link(f, safe / "second.name")
    elif layout.startswith("mode-"):
        f = _pp(safe / "kek.pass", mode=int(layout[5:], 8))
    else:
        good = _pp(safe / "good.pass")
        f = safe / "kek.pass"
        f.symlink_to(good)
    with pytest.raises(K.KekError, match=re.escape(said)):
        keys.read_passphrase_file(str(f))


@pytest.mark.parametrize("folder", ["0777", "0700"])
def test_the_swap_race_never_reads_another_value_in_tools_keys(tmp_path: Path, folder: str) -> None:
    """THE RACE in tools.keys, as the review ran it: the name exchanged, 3000 times while it is read, with a regular
    file holding another value (in a 0700 folder: with a link to it, the one swap a writer of the folder could do and
    the runner's own checks would not see by owner or mode)."""
    assert _has_renameat2(), "this libc has no renameat2: the race cannot be run here"
    d = _folder(tmp_path / "d", int(folder, 8))
    f = _pp(d / "kek.pass")
    if folder == "0777":
        _pp(d / "swap", OTHER + "\n")
    else:
        _pp(tmp_path / "other.pass", OTHER + "\n")
        (d / "swap").symlink_to(tmp_path / "other.pass")
    seen = {"ACCEPTED-OPERATOR": 0, "ACCEPTED-OTHER": 0, "refused": 0}
    sw = _swapper(f, d / "swap", 120)
    try:
        time.sleep(0.2)
        for _ in range(3000):
            seen[_keys_read(f)] += 1
    finally:
        sw.kill()
        sw.wait()
    print(f"tools.keys, folder {folder}: {seen}")
    assert seen["ACCEPTED-OTHER"] == 0, seen
    if folder == "0777":
        assert seen["ACCEPTED-OPERATOR"] == 0, seen


@pytest.mark.parametrize("bad", ["synthetic\rh96-carriage-return", "synthetic\th96-tab-inside"])
def test_tools_keys_refuses_a_control_character_on_stdin_and_in_a_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    """The review's survivor: tools.keys run by hand checks the one line itself (the shell scripts check before
    their pipe)."""
    sec = _folder(tmp_path / "sec")
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    f = _pp(_folder(tmp_path / "safe") / "kek.pass", bad + "\n")
    assert keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--passphrase-file", str(f)],
                     env={}) == 1  # fmt: skip
    sys_stdin, sys.stdin = sys.stdin, io.StringIO(bad + "\n")
    try:
        rc = keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--passphrase-stdin"], env={})
    finally:
        sys.stdin = sys_stdin
    err = capsys.readouterr().err
    assert rc == 1 and err.count("control character") == 2, err
    assert not (sec / K.META_FILE).exists() and f.exists()


def test_a_failed_rotation_keeps_both_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The review's survivor: a wrong old passphrase changes nothing, and the operator's files stay for the next try."""
    sec = _folder(tmp_path / "sec")
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    safe = _folder(tmp_path / "safe")
    assert keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                      "--passphrase-file", str(_pp(safe / "first.pass"))], env={}) == 0  # fmt: skip
    before = (sec / K.META_FILE).read_bytes()
    old_f = _pp(safe / "old.pass", "synthetic-h96-not-the-current-one\n")
    new_f = _pp(safe / "new.pass", "synthetic-h96-the-new-one-for-tests\n")
    rc = keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(old_f), "--new-passphrase-file", str(new_f)],
                   env={"TB_KEK_FILE": str(tmp_path / "kek.runtime"), "TB_ENV": "DEV"})  # fmt: skip
    capsys.readouterr()
    assert rc == 1 and old_f.exists() and new_f.exists()
    assert (sec / K.META_FILE).read_bytes() == before


# ------------------------------------------------------------------------------------------------ the installers
def _env(tmp: Path) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("TB_")} | {"TB_BOX_NO_ROOT": "1"}


@pytest.mark.parametrize("fd", ["0", "1", "2"])
def test_install_refuses_a_hand_on_at_a_standard_fd(tmp_path: Path, fd: str) -> None:
    """The review's survivor: --kek-passphrase-fd takes 3 to 9 only (never stdin, stdout or stderr)."""
    r = subprocess.run(["bash", str(ROOT / "deploy" / "install.sh"), "b.tar", "--kek-passphrase-fd", fd, "--yes"],
                       cwd=tmp_path, env=_env(tmp_path), capture_output=True, text=True, timeout=60,
                       check=False)  # fmt: skip
    assert r.returncode == 1 and "--kek-passphrase-fd 3-9: give one" in r.stderr, r.stderr


def test_install_refuses_the_removal_option_without_its_own_hand_on(tmp_path: Path) -> None:
    victim = _pp(tmp_path / "a-file", "kept\n")
    r = subprocess.run(["bash", str(ROOT / "deploy" / "install.sh"), "b.tar", "--kek-passphrase-remove", str(victim),
                        "--yes"], cwd=tmp_path, env=_env(tmp_path), capture_output=True, text=True, timeout=60,
                       check=False)  # fmt: skip
    assert r.returncode == 1 and "--kek-passphrase-remove goes with --kek-passphrase-fd" in r.stderr, r.stderr
    assert victim.read_text(encoding="utf-8") == "kept\n"


@pytest.mark.parametrize("form", ["file", "stdin"])
def test_box_install_takes_a_passphrase_only_with_the_answers_file(tmp_path: Path, form: str) -> None:
    """The review's survivor: without --answers the owner sets the passphrase on the set-up page."""
    f = _pp(_folder(tmp_path / "safe") / "kek.pass")
    more = ["--kek-passphrase-file", str(f)] if form == "file" else ["--kek-passphrase-stdin"]
    r = subprocess.run(["bash", str(ROOT / "deploy" / "box-install.sh"), "b.tar", *more, "--yes"], cwd=tmp_path,
                       env=_env(tmp_path), input=OPERATOR + "\n", capture_output=True, text=True, timeout=60,
                       check=False)  # fmt: skip
    assert r.returncode == 1 and "go with --answers (the unattended install)" in r.stderr, r.stderr
    assert f.exists()


FD8_INSTALL = """#!/bin/sh
if [ -e /proc/self/fd/8 ]; then
  IFS= read -r got <&8 || :
  if [ "$got" = "$TB_TEST_PP" ]; then echo "FD8=the passphrase" >> {log}; else echo "FD8=open" >> {log}; fi
else echo "FD8=closed" >> {log}; fi
echo "ARGS=$*" >> {log}
echo "TrialBox is running."
"""


@pytest.mark.parametrize("form", ["file", "stdin"])
def test_box_install_opens_fd_8_only_for_a_passphrase_from_stdin(tmp_path: Path, form: str) -> None:
    """L-1: in the file form install.sh is given the file's name and nothing waits on fd 8 (no copy of the value);
    a passphrase from stdin goes on there, by a pipe."""
    t: dict[str, Any] = _tree(tmp_path)
    log = tmp_path / "fd8.log"
    stub = tmp_path / "install-fd8.sh"
    stub.write_text(FD8_INSTALL.format(log=log), encoding="utf-8")
    stub.chmod(0o755)
    f = _pp(_folder(tmp_path / "safe") / "kek.pass")
    more = ("--kek-passphrase-file", str(f)) if form == "file" else ("--kek-passphrase-stdin",)
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps(OWNER), encoding="utf-8")
    r = subprocess.run(["bash", str(t["deploy"] / "box-install.sh"), str(t["bundle"]), "--answers", str(owner), *more],
                       cwd=tmp_path, env={**t["env"], "TB_BOX_INSTALL": str(stub), "TB_TEST_PP": OPERATOR},
                       input=OPERATOR + "\n", capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    seen = log.read_text(encoding="utf-8")
    assert ("FD8=closed" if form == "file" else "FD8=the passphrase") in seen, seen + r.stderr[-2000:]
    if form == "file":
        assert f"--kek-passphrase-file {f.resolve()}" in seen
    assert OPERATOR not in r.stdout + r.stderr
    _ = _unattended  # the console bench's own runner is the one the other box tests use


def test_a_refused_rotation_keeps_both_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The review's survivor: a command that ends with rc 1 without an exception (rc1 refuses rotate-kek on a
    PRODUCTION box, R22-34) keeps the operator's files: they are removed only after the command did its work."""
    sec = _folder(tmp_path / "sec")
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    safe = _folder(tmp_path / "safe")
    assert keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                      "--passphrase-file", str(_pp(safe / "first.pass"))], env={}) == 0  # fmt: skip
    old_f = _pp(safe / "old.pass")
    new_f = _pp(safe / "new.pass", "synthetic-h96-the-new-one-for-tests\n")
    rc = keys.main(["rotate-kek", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(old_f), "--new-passphrase-file", str(new_f)],
                   env={"TB_KEK_FILE": str(tmp_path / "kek.runtime"), "TB_ENV": "PRODUCTION"})  # fmt: skip
    capsys.readouterr()
    assert rc == 1 and old_f.exists() and new_f.exists()

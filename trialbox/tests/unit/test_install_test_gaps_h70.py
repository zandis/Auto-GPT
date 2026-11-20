"""H-70: two gaps an install test on a real server found (2026-11-20).

H70-01 (F-5): `make images` needs Docker's buildx plugin (every Dockerfile uses RUN --mount); without it the build
stops first with a plain line naming buildx, not Docker's own error. A stand-in `docker` on PATH.
H70-02 (F-6): `deploy/hardening/apply.sh` with SSH=off, run from an SSH session, refuses and changes nothing unless
`--ssh-off-over-ssh` says to go ahead. The SSH session is a stand-in process tree under TB_HOST_ROOT/proc, or the
SSH_CONNECTION variable; stub nft and systemctl log what would have changed. install.sh asks the same rule
(`apply.sh check`) before it loads or writes anything."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYBIN = Path(sys.executable).parent
REFUSAL = "SSH=off would stop sshd and close port 22 under this SSH session, locking it out; nothing was changed."


def _bin(tmp: Path, scripts: dict[str, str]) -> Path:
    d = tmp / "bin"
    d.mkdir(exist_ok=True)
    for name, body in scripts.items():
        p = d / name
        p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        p.chmod(0o755)
    return d


# ----------------------------------------------------------------------------------------------- H70-01: buildx
@pytest.mark.parametrize(("has_buildx", "rc"), [(False, 2), (True, 0)])
def test_images_names_buildx_before_it_builds(tmp_path: Path, has_buildx: bool, rc: int) -> None:
    log = tmp_path / "docker.log"
    answer = (
        "echo 'github.com/docker/buildx v0.17.1'; exit 0"
        if has_buildx
        else "echo \"docker: 'buildx' is not a docker command.\" >&2; exit 1"
    )
    bin_dir = _bin(tmp_path, {"docker": f'echo "docker $*" >> {log}\ncase "$1" in buildx) {answer};; esac\nexit 1\n'})
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["make", "--no-print-directory", "buildx-check"], cwd=ROOT, env=env, capture_output=True,
                       text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == rc, r.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["docker buildx version"]
    missing = "images: Docker's buildx plugin is missing (docker buildx version failed)"
    assert (missing in r.stderr) is (not has_buildx)


def test_both_image_targets_check_buildx_first() -> None:
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\nimages: buildx-check jvm-deps $(FONTS)\n" in mk
    assert "\nimages-multiarch: buildx-check jvm-deps $(FONTS)\n" in mk


# ---------------------------------------------------------------------------------------- H70-02: SSH=off over SSH
def _host(tmp: Path, chain: list[str]) -> Path:
    """A stand-in /proc under the host root: self -> chain[0] -> chain[1] ... -> 1 (systemd)."""
    host = tmp / "host"
    pids = ["self", *[str(100 + i) for i in range(len(chain))]]
    names = ["sh", *chain]
    for i, pid in enumerate(pids):
        parent = pids[i + 1] if i + 1 < len(pids) else "1"
        (host / "proc" / pid).mkdir(parents=True)
        (host / "proc" / pid / "status").write_text(f"Name:\t{names[i]}\nPPid:\t{parent}\n", encoding="utf-8")
    (host / "proc" / "1").mkdir()
    (host / "proc" / "1" / "status").write_text("Name:\tsystemd\nPPid:\t0\n", encoding="utf-8")
    return host


def _apply(tmp: Path, chain: list[str], *args: str, ssh: str = "off",
           **env_extra: str) -> tuple[subprocess.CompletedProcess[str], str]:  # fmt: skip
    conf = tmp / "hardening.conf"
    conf.write_text(f'CLINIC_RANGES="192.0.2.0/24"\nSSH="{ssh}"\nIT_RANGES="203.0.113.0/28"\n', encoding="utf-8")
    log = tmp / "calls.log"
    log.touch()
    bin_dir = _bin(tmp, {n: f'echo "{n} $*" >> {log}\n' for n in ("nft", "systemctl", "sshd")})
    env = {"PATH": f"{bin_dir}:{PYBIN}:/usr/bin:/bin", "HOME": str(tmp), "TMPDIR": str(tmp),
           "TB_HOST_ROOT": str(_host(tmp, chain)), **env_extra}  # fmt: skip
    r = subprocess.run(["sh", "deploy/hardening/apply.sh", "--conf", str(conf), *args, "all"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    return r, log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("chain", "env_extra"),
    [
        (["bash", "sudo", "bash", "sshd"], {}),  # under sudo: the SSH variables are gone, sshd is in the parent chain
        (["bash", "sshd-session", "sshd"], {}),  # OpenSSH 9.8+ names the session process sshd-session
        (["bash", "login"], {"SSH_CONNECTION": "192.0.2.7 50000 192.0.2.1 22"}),
        (["bash", "login"], {"SSH_TTY": "/dev/pts/0"}),
    ],
)
def test_ssh_off_over_ssh_is_refused_and_nothing_changes(tmp_path: Path, chain: list[str],
                                                          env_extra: dict[str, str]) -> None:  # fmt: skip
    r, calls = _apply(tmp_path, chain, **env_extra)
    assert r.returncode == 1
    assert r.stderr.strip() == (
        f"hardening: {REFUSAL} Run it from the box's console, set SSH=it with your own address in IT_RANGES, "
        "or add --ssh-off-over-ssh (an option of install.sh too) to do it anyway"
    )
    assert calls == ""
    assert not (tmp_path / "host" / "etc").exists()


@pytest.mark.parametrize(("args", "env_extra"), [(["--ssh-off-over-ssh"], {}), ([], {"TB_SSH_OFF_OVER_SSH": "yes"})])
def test_the_override_keeps_todays_behaviour(tmp_path: Path, args: list[str], env_extra: dict[str, str]) -> None:
    r, calls = _apply(tmp_path, ["bash", "sudo", "bash", "sshd"], *args, **env_extra)
    assert r.returncode == 0, r.stderr
    assert "SSH off: the service is stopped and disabled" in r.stdout
    assert "systemctl disable --now ssh.service ssh.socket" in calls and "nft -f" in calls
    assert (tmp_path / "host" / "etc" / "trialbox" / "input.nft").exists()


@pytest.mark.parametrize("override", ["", "1", "true", "YES"])
def test_only_the_exact_word_overrides(tmp_path: Path, override: str) -> None:
    r, calls = _apply(tmp_path, ["bash", "sshd"], TB_SSH_OFF_OVER_SSH=override)
    assert r.returncode == 1 and REFUSAL in r.stderr and calls == ""


def test_not_on_ssh_nothing_changes_in_behaviour(tmp_path: Path) -> None:
    r, calls = _apply(tmp_path, ["bash", "login"])
    assert r.returncode == 0, r.stderr
    assert REFUSAL not in r.stderr
    assert "systemctl disable --now ssh.service ssh.socket" in calls and "nft -f" in calls


def test_ssh_it_over_ssh_is_not_refused(tmp_path: Path) -> None:
    r, calls = _apply(tmp_path, ["bash", "sshd"], ssh="it", SSH_CONNECTION="192.0.2.7 50000 192.0.2.1 22")
    assert r.returncode == 0, r.stderr
    assert "SSH from 203.0.113.0/28 only" in r.stdout and "nft -f" in calls


def test_render_over_ssh_still_prints(tmp_path: Path) -> None:
    conf = tmp_path / "hardening.conf"
    conf.write_text('CLINIC_RANGES="192.0.2.0/24"\nSSH="off"\n', encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TB_HOST_ROOT": str(_host(tmp_path, ["bash", "sshd"]))}
    r = subprocess.run(["sh", "deploy/hardening/apply.sh", "--conf", str(conf), "render"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert r.returncode == 0 and "table inet trialbox_input {" in r.stdout


@pytest.mark.parametrize(("on_ssh", "refused"), [(True, True), (False, False)])
def test_check_alone_refuses_or_passes_and_changes_nothing(tmp_path: Path, on_ssh: bool, refused: bool) -> None:
    r, calls = _apply_what(tmp_path, ["bash", "sshd" if on_ssh else "login"], "check")
    assert (r.returncode == 1) is refused and (REFUSAL in r.stderr) is refused, r.stderr
    assert r.stdout == "" and calls == "" and not (tmp_path / "host" / "etc").exists()


def _apply_what(tmp: Path, chain: list[str], what: str) -> tuple[subprocess.CompletedProcess[str], str]:
    conf = tmp / "hardening.conf"
    conf.write_text('CLINIC_RANGES="192.0.2.0/24"\nSSH="off"\n', encoding="utf-8")
    log = tmp / "calls.log"
    log.touch()
    bin_dir = _bin(tmp, {n: f'echo "{n} $*" >> {log}\n' for n in ("nft", "systemctl", "sshd")})
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp), "TB_HOST_ROOT": str(_host(tmp, chain))}
    r = subprocess.run(["sh", "deploy/hardening/apply.sh", "--conf", str(conf), what], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    return r, log.read_text(encoding="utf-8")


# ----------------------------------------------------------------------- H70-02 at the installer's start (install.sh)
def _tree(root: Path) -> dict[str, tuple[int, int, bytes]]:
    out: dict[str, tuple[int, int, bytes]] = {}
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        out[str(p.relative_to(root))] = (st.st_mode, st.st_mtime_ns, p.read_bytes() if p.is_file() else b"")
    return out


def _install(tmp: Path, args: list[str], **env_extra: str) -> tuple[subprocess.CompletedProcess[str], str, bool]:
    """install.sh on a site folder holding deploy/site/hardening.conf with the example's SSH=off, as root (a stand-in
    ``id``), with a stand-in ``docker`` that logs and reports the engine down, so an install that goes on stops at
    the host step. Returns the result, the docker log and whether the site folder is unchanged."""
    site = tmp / "site"
    (site / "deploy" / "hardening").mkdir(parents=True)
    shutil.copy(ROOT / "deploy" / "install.sh", site / "deploy" / "install.sh")
    for f in ("apply.sh", "lib.sh"):
        shutil.copy(ROOT / "deploy" / "hardening" / f, site / "deploy" / "hardening" / f)
    (site / "deploy" / "site").mkdir()
    shutil.copy(ROOT / "deploy" / "hardening" / "hardening.example.conf", site / "deploy" / "site" / "hardening.conf")
    bundle = tmp / "trialbox-1.0.0.tar"
    bundle.write_bytes(b"not a bundle")
    log = tmp / "docker.log"
    bin_dir = _bin(tmp, {"docker": f'echo "docker $*" >> {log}\nexit 1\n',
                         "id": 'if [ "$1" = -u ]; then echo 0; else exec /usr/bin/id "$@"; fi\n'})  # fmt: skip
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "SSH_"))}
    env.update({"PATH": f"{bin_dir}:{PYBIN}:/usr/bin:/bin", "TB_HOST_ROOT": str(tmp / "no-host"), **env_extra})
    before = _tree(site)
    r = subprocess.run(["bash", str(site / "deploy" / "install.sh"), str(bundle), "--mode", "stub", *args],
                       capture_output=True, text=True, cwd=tmp, env=env, check=False, stdin=subprocess.DEVNULL,
                       timeout=120)  # fmt: skip
    return r, log.read_text(encoding="utf-8") if log.exists() else "", _tree(site) == before


SSH_ENV = {"SSH_CONNECTION": "192.0.2.7 50000 192.0.2.1 22"}


def test_an_install_over_ssh_with_ssh_off_stops_before_anything_is_loaded_or_written(tmp_path: Path) -> None:
    r, docker, unchanged = _install(tmp_path, [], **SSH_ENV)
    assert r.returncode == 1
    assert REFUSAL in r.stderr
    assert "install: the host baseline would cut this SSH session (above): nothing was loaded or written" in r.stderr
    assert r.stdout == "" and docker == "" and unchanged  # not even the host step's heading, no docker call


@pytest.mark.parametrize(
    ("args", "env_extra"),
    [(["--ssh-off-over-ssh"], SSH_ENV), ([], {**SSH_ENV, "TB_SSH_OFF_OVER_SSH": "yes"}), ([], {})],
    ids=["over-ssh-option", "over-ssh-environment", "not-on-ssh"],
)
def test_an_install_goes_on_with_the_override_or_off_ssh(tmp_path: Path, args: list[str],
                                                         env_extra: dict[str, str]) -> None:  # fmt: skip
    r, docker, _ = _install(tmp_path, args, **env_extra)
    assert REFUSAL not in r.stderr
    assert "==> host" in r.stdout and "docker info" in docker  # past the check: the host step ran
    assert "Docker is not running" in r.stderr


def test_the_installer_hands_the_override_on_to_the_baseline_step() -> None:
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert 'sh deploy/hardening/apply.sh --conf "$HB_CONF" ${HB_OVER[@]+"${HB_OVER[@]}"} all' in install
    assert install.index('apply.sh" --conf') < install.index('say "host"')

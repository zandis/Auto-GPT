"""NEW-WIN-1 (D-600): the Windows installer's messages and its steps inside WSL2.

``deploy/windows/box-install.ps1`` cannot run on Linux: its logic is tested with Pester on PowerShell 7
(``tests/windows``, the CI job ``powershell``). Here: the messages it shows (three languages, the same values, the
product's wording rules) and ``deploy/windows/wsl-setup.sh``, the steps it runs as root inside WSL2, on stubs of
``dpkg``, ``docker``, ``systemctl``, ``nvidia-ctk`` and the Windows driver's ``nvidia-smi``. What only a Windows
machine can show is the P-0 rehearsal (``docs/handover/P-0-windows-rehearsal.md``)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

import pytest
from tb_common.wording import check

ROOT = Path(__file__).resolve().parents[2]
WIN = ROOT / "deploy/windows"
PS1 = WIN / "box-install.ps1"
SH = WIN / "wsl-setup.sh"
MESSAGES = json.loads((WIN / "box-install.messages.json").read_text(encoding="utf-8"))
LANGS = ("en", "ja", "zh-TW")
CARD = "NVIDIA RTX PRO 6000 Blackwell, 581.15, 97887 MiB"


# ------------------------------------------------------------------------------------------------ the messages
def test_every_message_is_in_three_languages_with_the_same_values() -> None:
    for key, entry in MESSAGES.items():
        assert set(entry) == set(LANGS), key
        holes = {lang: sorted(set(re.findall(r"\{(\d)\}", entry[lang]))) for lang in LANGS}
        assert holes["en"] == holes["ja"] == holes["zh-TW"], (key, holes)
        for lang in LANGS:
            assert entry[lang].strip(), (key, lang)
            assert check(entry[lang]) == [], (key, lang)


def test_the_installer_and_the_catalogue_name_the_same_messages() -> None:
    text = PS1.read_text(encoding="utf-8")
    used = set(re.findall(r'(?:Say|Stop-TbStep|Get-TbText) "([a-z0-9_]+)"', text))
    assert used == set(MESSAGES), (sorted(used - set(MESSAGES)), sorted(set(MESSAGES) - used))


def test_no_message_takes_more_values_than_the_installer_pads() -> None:
    # Get-TbText pads the values to three more than given, so a message may use {0} to {2} at most
    for key, entry in MESSAGES.items():
        assert all(int(n) <= 2 for n in re.findall(r"\{(\d)\}", entry["en"])), key


def test_the_launcher_has_windows_line_ends_and_the_scripts_are_ascii() -> None:
    cmd = (WIN / "Install-TrialBox.cmd").read_bytes()
    assert b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b"")
    assert PS1.read_bytes().isascii() and cmd.isascii()


def test_the_linux_installer_still_ends_with_the_line_the_done_mark_waits_for() -> None:
    sh = SH.read_text(encoding="utf-8")
    ready = re.search(r'^READY_LINE="([^"]+)"', sh, re.M)
    assert ready and ready.group(1) in (ROOT / "deploy/box-install.sh").read_text(encoding="utf-8")
    assert "TrialBox is running" in sh and "TrialBox is running" in (ROOT / "deploy/install.sh").read_text("utf-8")


# ------------------------------------------------------------------------------------------------ wsl-setup.sh
class Box:
    """A fake WSL2 system: /etc, /proc, /opt/trialbox and a bin/ of stubs that log their calls."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.etc, self.proc, self.root, self.bin = tmp / "etc", tmp / "proc", tmp / "opt", tmp / "bin"
        for d in (self.etc, self.proc / "1", self.bin):
            d.mkdir(parents=True)
        (self.proc / "1/comm").write_text("systemd\n")
        self.calls = tmp / "calls.log"
        self.smi = tmp / "wsl-lib" / "nvidia-smi"
        self.smi.parent.mkdir()
        self.stub(self.smi, f"echo '{CARD}'")
        self.stub("dpkg-query", 'cat "$TB_FAKE/dpkg-status" 2>/dev/null || true')
        self.stub("dpkg", "exit 0")
        self.stub("nvidia-ctk", "exit 0")
        self.stub("systemctl", "exit 0")
        self.stub("ldd", "printf '\\tlibc.so.6 => %s (0x1)\\n\\tlibnvidia-ml.so.1 => /usr/lib/wsl/lib/libnvidia-ml.so.1 (0x2)\\n\\t%s (0x3)\\n' \"$TB_FAKE/lib/libc.so.6\" \"$TB_FAKE/lib/ld.so\"")  # fmt: skip
        (tmp / "lib").mkdir()
        (tmp / "lib/libc.so.6").write_text("libc")
        (tmp / "lib/ld.so").write_text("loader")
        self.docker(image=False, runtimes="io.containerd.runc.v2 nvidia runc", run_rc=0)

    def stub(self, name: str | Path, body: str) -> None:
        p = name if isinstance(name, Path) else self.bin / name
        p.write_text(f'#!/bin/bash\necho "$(basename "$0") $*" >> "$TB_FAKE/calls.log"\n{body}\n')
        p.chmod(0o755)

    def docker(self, *, image: bool, runtimes: str, run_rc: int) -> None:
        self.stub(
            "docker",
            f"""case "$1 $2" in
  "image inspect") exit {0 if image else 1} ;;
  "import -") cat > "$TB_FAKE/probe.tar" ;;
  "info --format") echo '{runtimes}' ;;
  "version --format") echo 27.3.1 ;;
esac
case "$1" in run) if [ {run_rc} = 0 ]; then echo '{CARD}'; else echo 'could not select device driver "" with capabilities: [[gpu]]'; exit {run_rc}; fi ;; esac""",
        )

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "TB_FAKE": str(self.tmp),
            "TB_WSL_ETC": str(self.etc),
            "TB_WSL_PROC": str(self.proc),
            "TB_WSL_ROOT": str(self.root),
            "TB_WSL_SMI": str(self.smi),
            "TB_WSL_NO_ROOT": "1",
        }
        return subprocess.run(
            ["bash", str(SH), *args], capture_output=True, text=True, env=env, check=False, timeout=60
        )

    def log(self) -> str:
        return self.calls.read_text() if self.calls.exists() else ""


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def test_wslconf_turns_systemd_on_once_and_keeps_what_was_there(box: Box) -> None:
    (box.etc / "wsl.conf").write_text("[automount]\noptions=metadata\n[boot]\ncommand=echo hi\n")
    out = box.run("wslconf")
    assert out.returncode == 0 and out.stdout.strip() == "changed", out.stderr
    text = (box.etc / "wsl.conf").read_text()
    assert "systemd=true" in text and "options=metadata" in text and "command=echo hi" in text
    assert (box.etc / "wsl.conf.before-trialbox").read_text().startswith("[automount]")
    again = box.run("wslconf")
    assert again.stdout.strip() == "kept" and (box.etc / "wsl.conf").read_text() == text


def test_wslconf_writes_the_file_when_the_image_has_none(box: Box) -> None:
    assert box.run("wslconf").stdout.strip() == "changed"
    assert (box.etc / "wsl.conf").read_text().split() == ["[boot]", "systemd=true"]
    assert not (box.etc / "wsl.conf.before-trialbox").exists()


def test_pid1_names_the_first_process(box: Box) -> None:
    assert box.run("pid1").stdout.strip() == "systemd"


@pytest.mark.parametrize(
    ("status", "refused"),
    [
        ("ii  nvidia-container-toolkit\nii  libnvidia-container1\nii  docker-ce\n", ""),
        ("ii  nvidia-driver-570\nii  docker-ce\n", "nvidia-driver-570"),
        ("ii  libnvidia-compute-570\n", "libnvidia-compute-570"),
        ("rc  nvidia-driver-570\nun  nvidia-dkms-570\n", ""),  # removed packages are not a driver
    ],
)
def test_a_linux_nvidia_driver_is_refused_and_the_toolkit_is_not_one(box: Box, status: str, refused: str) -> None:
    (box.tmp / "dpkg-status").write_text(status)
    out = box.run("no-linux-driver")
    if refused:
        assert out.returncode == 1 and refused in out.stderr
    else:
        assert out.returncode == 0, out.stderr


def test_a_loaded_linux_kernel_driver_is_refused(box: Box) -> None:
    (box.proc / "driver/nvidia").mkdir(parents=True)
    (box.proc / "driver/nvidia/version").write_text("NVRM version: 570\n")
    out = box.run("no-linux-driver")
    assert out.returncode == 1 and "kernel driver" in out.stderr


def test_packages_install_from_the_media_only_and_docker_gets_the_nvidia_runtime(box: Box) -> None:
    debs = box.tmp / "debs"
    debs.mkdir()
    for n in ("docker-ce_27.3.1_amd64.deb", "nvidia-container-toolkit_1.17.0_amd64.deb"):
        (debs / n).write_text("deb")
    out = box.run("packages", str(debs))
    assert out.returncode == 0, out.stderr
    log = box.log()
    assert re.search(r"dpkg -i --skip-same-version \S+docker-ce_27\S+ \S+nvidia-container-toolkit", log)
    assert "nvidia-ctk runtime configure --runtime=docker" in log and "systemctl restart docker" in log
    assert "apt" not in log  # nothing is fetched: dpkg on the media's files


def test_a_driver_package_on_the_media_stops_the_step_before_dpkg(box: Box) -> None:
    debs = box.tmp / "debs"
    debs.mkdir()
    (debs / "docker-ce_27.3.1_amd64.deb").write_text("deb")
    (debs / "nvidia-driver-570_570.1_amd64.deb").write_text("deb")
    out = box.run("packages", str(debs))
    assert out.returncode == 1 and "nvidia-driver-570" in out.stderr
    assert "dpkg -i" not in box.log()


def test_packages_fail_when_docker_does_not_list_the_nvidia_runtime(box: Box) -> None:
    debs = box.tmp / "debs"
    debs.mkdir()
    (debs / "docker-ce_27.3.1_amd64.deb").write_text("deb")
    box.docker(image=False, runtimes="runc", run_rc=0)
    out = box.run("packages", str(debs))
    assert out.returncode == 1 and "nvidia runtime" in out.stderr


def test_gpu_builds_a_probe_without_the_drivers_libraries_and_prints_the_card(box: Box) -> None:
    out = box.run("gpu")
    assert out.returncode == 0 and out.stdout.strip() == CARD, out.stderr
    with tarfile.open(box.tmp / "probe.tar") as probe:
        names = probe.getnames()
    assert "probe/nvidia-smi" in names and any(n.endswith("lib/libc.so.6") for n in names)
    assert not any("libnvidia-ml" in n for n in names)  # only the container toolkit may bring the driver's library
    assert "docker run --rm --network none --gpus all trialbox-gpu-probe:local /probe/nvidia-smi" in box.log()


def test_gpu_fails_when_no_container_sees_the_card(box: Box) -> None:
    box.docker(image=True, runtimes="nvidia", run_rc=125)
    out = box.run("gpu")
    assert out.returncode == 1 and "no container sees the card" in out.stderr and "capabilities" in out.stderr


def test_gpu_fails_when_the_windows_driver_is_not_visible_in_wsl2(box: Box) -> None:
    box.smi.unlink()
    out = box.run("gpu")
    assert out.returncode == 1 and "Windows NVIDIA driver" in out.stderr
    assert "docker" not in box.log()


def _host_tar(tmp: Path) -> tuple[Path, Path]:
    src = tmp / "src/deploy"
    src.mkdir(parents=True)
    (src / "box-install.sh").write_text("#!/bin/bash\n")
    tar = tmp / "trialbox-host.tar"
    with tarfile.open(tar, "w") as t:
        t.add(src, arcname="deploy")
    pub = tmp / "vendor_ed25519.pub"
    pub.write_text("ed25519 public key\n")
    return tar, pub


def test_the_host_tree_is_unpacked_once_and_never_over_another_folder(box: Box) -> None:
    tar, pub = _host_tar(box.tmp)
    out = box.run("host-tree", str(tar), str(pub))
    assert out.returncode == 0 and "unpacked" in out.stdout and "vendor key sha256 " in out.stdout, out.stderr
    assert (box.root / "deploy/keys/vendor_ed25519.pub").read_text() == pub.read_text()
    (box.root / "deploy/settings.yaml").write_text("the site's own file\n")
    again = box.run("host-tree", str(tar), str(pub))
    assert again.returncode == 0 and "kept" in again.stdout
    assert (box.root / "deploy/settings.yaml").read_text() == "the site's own file\n"


def test_a_folder_that_is_not_a_host_tree_is_not_replaced(box: Box) -> None:
    tar, pub = _host_tar(box.tmp)
    box.root.mkdir()
    (box.root / "somebody.txt").write_text("not ours\n")
    out = box.run("host-tree", str(tar), str(pub))
    assert out.returncode == 1 and "not replaced" in out.stderr
    assert sorted(p.name for p in box.root.iterdir()) == ["somebody.txt"]


def test_a_different_vendor_key_is_refused(box: Box) -> None:
    tar, pub = _host_tar(box.tmp)
    assert box.run("host-tree", str(tar), str(pub)).returncode == 0
    pub.write_text("another key\n")
    out = box.run("host-tree", str(tar), str(pub))
    assert out.returncode == 1 and "differs" in out.stderr


def _installed_tree(box: Box, body: str) -> Path:
    d = box.root / "deploy"
    d.mkdir(parents=True)
    (d / "box-install.sh").write_text(f'#!/bin/bash\necho "box-install $*" >> "$TB_FAKE/calls.log"\n{body}\n')
    bundle = box.tmp / "trialbox-1.0.0.tar"
    bundle.write_text("bundle")
    return bundle


def test_install_runs_the_linux_installer_and_marks_the_box_done_only_when_it_said_ready(box: Box) -> None:
    bundle = _installed_tree(
        box, "echo '  One-time code:    ABCD-EFGH'; echo '  TrialBox is ready: https://box'; exit 1"
    )
    out = box.run("install", str(bundle), "--yes")
    assert out.returncode == 1  # the host check's FAIL lines: the exit code is the Linux installer's
    assert "ABCD-EFGH" in out.stdout  # the window shows the code
    assert f"box-install {bundle} --yes" in box.log()
    assert box.run("state").stdout.strip() == "installed=1"
    kept = "".join(
        p.read_text(errors="ignore") for p in box.tmp.rglob("*") if p.is_file() and p.name != "box-install.sh"
    )
    assert "ABCD-EFGH" not in kept  # and nothing on disk holds it
    n = box.log().count("box-install ")
    again = box.run("install", str(bundle))
    assert again.returncode == 0 and "already installed" in again.stdout and box.log().count("box-install ") == n


def test_install_that_stopped_is_not_marked_done(box: Box) -> None:
    bundle = _installed_tree(box, "echo 'box-install: the install stopped' >&2; exit 1")
    assert box.run("install", str(bundle)).returncode == 1
    assert box.run("state").stdout.strip() == "installed=0"


def test_install_goes_on_with_the_first_run_when_the_stack_was_already_installed(box: Box) -> None:
    bundle = _installed_tree(box, "echo '  TrialBox is ready: https://box'")
    site = box.root / "deploy/site/box"
    site.mkdir(parents=True)
    (site / "answers.json").write_text("{}")
    (site / "install.log").write_text("==> TrialBox is running\n")
    out = box.run("install", str(bundle))
    assert out.returncode == 0, out.stderr
    assert "box-install --firstrun" in box.log() and str(bundle) not in box.log()


def test_install_refuses_a_bundle_that_is_not_there(box: Box) -> None:
    _installed_tree(box, "exit 0")
    out = box.run("install", str(box.tmp / "missing.tar"))
    assert out.returncode == 1 and "no such bundle" in out.stderr
    assert "box-install" not in box.log()


def test_an_unknown_step_is_an_error(box: Box) -> None:
    assert box.run("format-disk").returncode == 1

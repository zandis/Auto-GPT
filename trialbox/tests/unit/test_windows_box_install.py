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
    # review M4: the media's path reaches PowerShell through a variable, never inside a quoted command text
    text = cmd.decode()
    assert 'set "TB_INSTALL_PS1=%~dp0windows\\box-install.ps1"' in text and "$env:TB_INSTALL_PS1" in text
    assert text.count("%~dp0") == 1 and "if errorlevel 1 pause" in text


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
        self.stub("nvidia-ctk", 'echo "runc nvidia" > "$TB_FAKE/runtimes"')  # configuring adds the runtime
        self.stub("systemctl", "exit 0")
        self.stub("ldd", "printf '\\tlibc.so.6 => %s (0x1)\\n\\tlibnvidia-ml.so.1 => /usr/lib/wsl/lib/libnvidia-ml.so.1 (0x2)\\n\\t%s (0x3)\\n' \"$TB_FAKE/lib/libc.so.6\" \"$TB_FAKE/lib/ld.so\"")  # fmt: skip
        (tmp / "lib").mkdir()
        (tmp / "lib/libc.so.6").write_text("libc")
        (tmp / "lib/ld.so").write_text("loader")
        (tmp / "runtimes").write_text("runc\n")
        self.docker(image=False, run_rc=0)

    def stub(self, name: str | Path, body: str) -> None:
        p = name if isinstance(name, Path) else self.bin / name
        p.write_text(f'#!/bin/bash\necho "$(basename "$0") $*" >> "$TB_FAKE/calls.log"\n{body}\n')
        p.chmod(0o755)

    def docker(self, *, image: bool, run_rc: int) -> None:
        self.stub(
            "docker",
            f"""case "$1 $2" in
  "image inspect") exit {0 if image else 1} ;;
  "import -") cat > "$TB_FAKE/probe.tar" ;;
  "info --format") cat "$TB_FAKE/runtimes" ;;
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
            "TB_WSL_LIBDIR": str(self.tmp / "libdir"),
            "TB_WSL_SYS": str(self.tmp / "sys"),
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
        # review M3: half-installed states and the driver's other package names
        ("iU  nvidia-driver-570\n", "nvidia-driver-570"),
        ("iF  nvidia-driver-570\n", "nvidia-driver-570"),
        ("ii  linux-modules-nvidia-570-6.8.0-48-generic\n", "linux-modules-nvidia-570"),
        ("ii  nvidia-open\n", "nvidia-open"),
        ("ii  libnvidia-decode-570\n", "libnvidia-decode-570"),
        ("ii  nvidia-modprobe\n", "nvidia-modprobe"),
        ("ii  nvidia-firmware-570-570.1\n", "nvidia-firmware-570"),
        ("ii  nvidia-container-toolkit-base\nii  libnvidia-container-tools\nii  nvidia-container-runtime\n", ""),
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


def test_a_driver_installed_without_packages_is_refused(box: Box) -> None:
    """Review M3: the .run installer leaves no package; its library and its kernel module are looked for."""
    lib = box.tmp / "libdir"
    lib.mkdir()
    (lib / "libnvidia-ml.so.1").write_text("driver")
    out = box.run("no-linux-driver")
    assert out.returncode == 1 and "libnvidia-ml.so.1" in out.stderr
    (lib / "libnvidia-ml.so.1").unlink()
    (box.tmp / "sys/module/nvidia").mkdir(parents=True)
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
    box.stub("nvidia-ctk", "exit 0")  # configured, and Docker still does not list it
    out = box.run("packages", str(debs))
    assert out.returncode == 1 and "nvidia runtime" in out.stderr


def test_a_second_run_of_packages_does_not_restart_docker_under_a_live_stack(box: Box) -> None:
    """Review M1: the step runs again on every start of the installer; the stack may be up by then."""
    debs = box.tmp / "debs"
    debs.mkdir()
    (debs / "docker-ce_27.3.1_amd64.deb").write_text("deb")
    assert box.run("packages", str(debs)).returncode == 0
    assert box.log().count("systemctl restart docker") == 1
    again = box.run("packages", str(debs))
    assert again.returncode == 0 and "not restarted" in again.stdout
    assert box.log().count("systemctl restart docker") == 1 and box.log().count("nvidia-ctk runtime configure") == 1


def test_gpu_builds_a_probe_without_the_drivers_libraries_and_prints_the_card(box: Box) -> None:
    out = box.run("gpu")
    assert out.returncode == 0 and out.stdout.strip() == CARD, out.stderr
    with tarfile.open(box.tmp / "probe.tar") as probe:
        names = probe.getnames()
    assert "probe/nvidia-smi" in names and any(n.endswith("lib/libc.so.6") for n in names)
    assert not any("libnvidia-ml" in n for n in names)  # only the container toolkit may bring the driver's library
    assert "docker run --rm --network none --gpus all trialbox-gpu-probe:local /probe/nvidia-smi" in box.log()


def test_gpu_fails_when_no_container_sees_the_card(box: Box) -> None:
    box.docker(image=True, run_rc=125)
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


def test_an_interrupted_unpack_is_taken_up_and_never_passes_for_a_host_tree(box: Box) -> None:
    """Review L2: the tree is unpacked beside the folder and moved into place whole."""
    tar, pub = _host_tar(box.tmp)
    part = Path(str(box.root) + ".unpacking")
    (part / "deploy").mkdir(parents=True)  # an earlier run died here: no box-install.sh yet
    assert not box.root.exists()
    out = box.run("host-tree", str(tar), str(pub))
    assert out.returncode == 0 and (box.root / "deploy/box-install.sh").is_file() and not part.exists(), out.stderr
    bad = box.tmp / "bad.tar"
    bad.write_text("not a tar")
    other = Box(box.tmp / "second")
    assert other.run("host-tree", str(bad), str(pub)).returncode == 1
    assert not other.root.exists()


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


def test_install_hands_the_rehearsal_on_to_the_linux_installer(box: Box) -> None:
    # NEW-WIN-11 (D-614): box-install.ps1 -Rehearsal -> wsl-setup.sh install BUNDLE [--yes] --rehearsal
    bundle = _installed_tree(box, "echo '  TrialBox is ready: https://box'")
    out = box.run("install", str(bundle), "--yes", "--rehearsal")
    assert out.returncode == 0, out.stderr
    assert f"box-install {bundle} --yes --rehearsal" in box.log()
    other = Box(box.tmp / "second")
    bundle2 = _installed_tree(other, "echo '  TrialBox is ready: https://box'")
    assert other.run("install", str(bundle2), "--rehearsal").returncode == 0
    assert f"box-install {bundle2} --rehearsal" in other.log()
    assert other.run("install", str(bundle2), "--bogus").returncode != 0


def test_the_first_run_of_a_rehearsal_box_is_not_handed_the_rehearsal_again(box: Box) -> None:
    # box-install.sh refuses --rehearsal with --firstrun: the first run finishes the box as it was installed
    bundle = _installed_tree(box, "echo '  TrialBox is ready: https://box'")
    site = box.root / "deploy/site/box"
    site.mkdir(parents=True)
    (site / "answers.json").write_text("{}")
    (site / "install.log").write_text("==> TrialBox is running\n")
    out = box.run("install", str(bundle), "--yes", "--rehearsal")
    assert out.returncode == 0, out.stderr
    assert "box-install --firstrun" in box.log() and "--rehearsal" not in box.log()


def test_install_refuses_a_bundle_that_is_not_there(box: Box) -> None:
    _installed_tree(box, "exit 0")
    out = box.run("install", str(box.tmp / "missing.tar"))
    assert out.returncode == 1 and "no such bundle" in out.stderr
    assert "box-install" not in box.log()


def test_boot_check_wants_docker_and_the_stack_enabled(box: Box) -> None:
    box.stub(
        "systemctl", 'case "$*" in "is-enabled trialbox.service") echo disabled; exit 1 ;; *) echo enabled ;; esac'
    )
    out = box.run("boot-check")
    assert out.returncode == 1 and "trialbox.service" in out.stderr and "docker.service" not in out.stderr
    box.stub("systemctl", "echo enabled")
    assert box.run("boot-check").returncode == 0


def test_the_console_forwarding_task_has_one_definition_with_the_boot_tasks_sign_in() -> None:
    """NEW-WIN-10 (D-613): on Windows 10 the forwarding script registers its own task; the installer only calls it."""
    ps1 = PS1.read_text(encoding="utf-8")
    proxy = (WIN / "console-proxy.ps1").read_text(encoding="utf-8")
    keep = (WIN / "register_keepalive.ps1").read_text(encoding="utf-8")
    name = re.search(r'\$script:TbProxyTask = "([^"]+)"', ps1)
    assert name and f'[string]$TaskName = "{name.group(1)}"' in proxy
    assert "New-ScheduledTaskTrigger -AtStartup" in proxy and "-LogonType S4U -RunLevel Highest" in proxy
    assert "-LogonType S4U -RunLevel Highest" in keep  # the same sign-in as the boot task: no stored password
    assert "& $Script -Register -User $Account" in ps1
    # it changes the console's port only, from every address of this PC, and nothing else
    assert "listenaddress=0.0.0.0" in proxy and "portproxy" in proxy
    assert (
        "portproxy delete" not in proxy
        and "portproxy reset" not in proxy
        and "interface portproxy add v4tov6" not in proxy
    )
    assert proxy.isascii()


def test_the_boot_task_has_one_definition_and_the_name_the_host_check_looks_for() -> None:
    ps1 = PS1.read_text(encoding="utf-8")
    keep = (WIN / "register_keepalive.ps1").read_text(encoding="utf-8")
    name = re.search(r'\$script:TbBootTask = "([^"]+)"', ps1)
    assert name and f'$TaskName = "{name.group(1)}"' in keep
    assert f'$TaskName = "{name.group(1)}"' in (WIN / "host_facts.ps1").read_text(encoding="utf-8")
    assert "New-ScheduledTaskTrigger -AtStartup" in keep and "-LogonType S4U" in keep  # no stored password
    assert "New-ScheduledTaskTrigger -AtStartup" not in ps1  # the installer calls the one definition


def test_the_task_script_and_the_judge_name_the_boxs_own_distribution() -> None:
    """Review of NEW-WIN-2, M3: run by hand as its header says, the script must not point the task at another system."""
    import importlib.util

    keep = (WIN / "register_keepalive.ps1").read_text(encoding="utf-8")
    assert '[string]$Distro = "TrialBox"' in keep and "Ubuntu-24.04" not in keep
    spec = importlib.util.spec_from_file_location("wsl2_policy_w2", WIN / "wsl2_policy.py")
    assert spec and spec.loader
    pol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pol)
    facts = {
        "keepalive_task_found": "1",
        "keepalive_task_triggers": "MSFT_TaskBootTrigger",
        "keepalive_task_logon_type": "S4U",
        "keepalive_task_state": "Running",
        "distro": "TrialBox",
    }
    for action, good in (
        ("wsl.exe -d TrialBox --exec /bin/sh -c 'exec sleep infinity'", True),
        ("wsl.exe -d Ubuntu-24.04 --exec /bin/sh -c 'exec sleep infinity'", False),
        ("wsl.exe -d TrialBox2 --exec /bin/sh", False),
    ):
        v = pol.Verdicts(strict=True)
        pol.check_keepalive({**facts, "keepalive_task_action": action}, v)
        assert ("another distribution" not in " ".join(v.lines)) is good, (action, v.lines)
        assert v.lines[0].startswith("PASS" if good else "FAIL"), v.lines


def _policy() -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location("wsl2_policy_w8", WIN / "wsl2_policy.py")
    assert spec and spec.loader
    pol = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pol)
    return pol


BITLOCKER_C = {
    "system_drive": "C:",
    "bitlocker_C_status": "FullyEncrypted",
    "bitlocker_C_protection": "On",
    "bitlocker_C_method": "XtsAes256",
}


@pytest.mark.parametrize(
    ("unlock", "protectors", "verdict", "says"),
    [
        # the box's setting tpm (D-494 point 6): the TPM alone opens the drive, and that is what was chosen
        ("tpm", "Tpm,RecoveryPassword", "PASS", "starts with nobody there"),
        ("tpm", "TpmNetworkKey,TpmPin,RecoveryPassword", "PASS", "starts with nobody there"),
        # review L1: a drive that asks for a PIN does not "start with nobody there", whatever the setting says
        ("tpm", "TpmPin,RecoveryPassword", "FAIL", "asks for a PIN or a key at start"),
        ("tpm", "Tpm,ExternalKey,RecoveryPassword", "PASS", "starts with nobody there"),
        ("tpm", "ExternalKey,RecoveryPassword", "FAIL", "the TPM does not open the drive"),
        ("tpm", "Password,RecoveryPassword", "FAIL", "the TPM does not open the drive"),
        ("tpm", "RecoveryPassword", "FAIL", "the TPM does not open the drive"),
        # tpm_pin, and no setting at all (not a box install): D-421's rule stands, the TPM alone is refused
        ("tpm_pin", "Tpm,RecoveryPassword", "FAIL", "the TPM alone opens it"),
        ("tpm_pin", "TpmPin,RecoveryPassword", "PASS", "unlock TpmPin"),
        ("", "Tpm,RecoveryPassword", "FAIL", "the TPM alone opens it"),
        ("TPM", "Tpm,RecoveryPassword", "PASS", "starts with nobody there"),  # the registry value's case
    ],
)
def test_the_disk_unlock_setting_decides_whether_the_tpm_alone_is_enough(
    unlock: str, protectors: str, verdict: str, says: str
) -> None:
    pol = _policy()
    v = pol.Verdicts(strict=True)  # type: ignore[attr-defined]
    facts = {**BITLOCKER_C, "bitlocker_C_protectors": protectors}
    if unlock:
        facts["bitlocker_unlock"] = unlock
    pol.check_bitlocker(facts, v)  # type: ignore[attr-defined]
    assert v.lines[0].startswith(verdict) and says in v.lines[0], v.lines


def test_an_unknown_unlock_setting_is_said_and_judged_as_the_strict_one() -> None:
    pol = _policy()
    v = pol.Verdicts(strict=True)  # type: ignore[attr-defined]
    facts = {**BITLOCKER_C, "bitlocker_C_protectors": "Tpm,RecoveryPassword", "bitlocker_unlock": "none"}
    pol.check_bitlocker(facts, v)  # type: ignore[attr-defined]
    text = " | ".join(v.lines)
    assert "unknown bitlocker_unlock 'none'" in text and "the TPM alone opens it" in text
    assert all(ln.startswith("FAIL") for ln in v.lines)


@pytest.mark.parametrize(
    ("auto", "verdict"),
    [("True", "PASS"), ("False", "FAIL"), ("", "PASS"), ("false", "FAIL"), ("0", "FAIL"), ("Unknown", "WARN")],
)
def test_the_data_drive_must_open_with_the_system_drive(auto: str, verdict: str) -> None:
    pol = _policy()
    v = pol.Verdicts(strict=True)  # type: ignore[attr-defined]
    facts = {
        **BITLOCKER_C,
        "bitlocker_C_protectors": "Tpm,RecoveryPassword",
        "bitlocker_unlock": "tpm",
        "vhdx_drive": "D:",
        "bitlocker_D_status": "FullyEncrypted",
        "bitlocker_D_protection": "On",
        "bitlocker_D_method": "XtsAes256",
    }
    if auto:
        facts["bitlocker_D_autounlock"] = auto
    pol.check_bitlocker(facts, v)  # type: ignore[attr-defined]
    line = next(ln for ln in v.lines if "BitLocker on D:" in ln)
    assert line.startswith(verdict), v.lines
    assert ("unlocks with the system drive" in line) is (auto == "True")


def test_the_owners_confirmation_at_the_install_answers_where_the_recovery_key_is_kept() -> None:
    """Review L3: a box set up by the installer must not fail "say where the recovery password is kept"."""
    facts = (WIN / "host_facts.ps1").read_text(encoding="utf-8")
    assert 'RegValue "HKLM:\\SOFTWARE\\TrialBox" "RecoveryKeyKeptBy"' in facts
    assert 'Set-TbMachineSetting "RecoveryKeyKeptBy"' in PS1.read_text(encoding="utf-8")
    pol = _policy()
    v = pol.Verdicts(strict=True)  # type: ignore[attr-defined]
    kept = "the box owner (each key shown and confirmed at the install)"
    facts_c = {**BITLOCKER_C, "bitlocker_C_protectors": "Tpm,RecoveryPassword", "recovery_escrow": kept}
    pol.check_recovery(facts_c, v)  # type: ignore[attr-defined]
    assert v.lines[0].startswith("PASS") and "the box owner" in v.lines[0]


def test_host_facts_prints_the_unlock_setting_and_the_installer_records_it_where_only_administrators_write() -> None:
    facts = (WIN / "host_facts.ps1").read_text(encoding="utf-8")
    ps1 = PS1.read_text(encoding="utf-8")
    assert 'Fact "bitlocker_unlock" (RegValue "HKLM:\\SOFTWARE\\TrialBox" "BitlockerUnlock")' in facts
    assert 'Fact "bitlocker_${tag}_autounlock"' in facts
    assert '$key = "HKLM:\\SOFTWARE\\TrialBox"' in ps1 and 'Set-TbMachineSetting "BitlockerUnlock" $unlock' in ps1


def test_the_installer_never_turns_bitlocker_off_and_never_logs_or_stores_a_recovery_key() -> None:
    ps1 = PS1.read_text(encoding="utf-8")
    assert not re.search(
        r"Disable-BitLocker|Suspend-BitLocker|Remove-BitLockerKeyProtector|Clear-BitLockerAutoUnlock|manage-bde", ps1
    )
    # the key's variable reaches the window and the printer only: no log line, no state field, no Say (Say logs)
    lines = [ln for ln in ps1.splitlines() if "$secret" in ln]
    assert len(lines) >= 4
    for line in lines:
        assert not re.search(r"Write-TbLog|Say |TbState\.|Set-Content|WriteAllText|Out-File|Invoke-TbNative", line), (
            line
        )
    # the same for the pair the seam returns (its Password field): handed to Confirm-TbRecoveryKey and nowhere else
    uses = [ln.strip() for ln in ps1.splitlines() if "$rp.Password" in ln]
    # (NEW-WIN-14: with the key's ID beside it, which is no secret)
    assert uses == ["Confirm-TbRecoveryKey $drv $rp.Password $rp.Id"], uses


def test_the_key_probe_handles_a_dummy_value_only_and_uses_the_boot_tasks_sign_in() -> None:
    """key-probe.ps1 runs in no test (Windows stores, the Task Scheduler): this holds what it must not do."""
    probe = (WIN / "key-probe.ps1").read_text(encoding="utf-8")
    assert probe.isascii()
    assert "RandomNumberGenerator" in probe and "$dummy" in probe
    # nothing of TrialBox's is read: no secrets folder, no key file, no .env, no site folder
    assert not re.search(r"secrets|\.env|site[/\\]|kek|vendor_ed25519|\.pem|RecoveryPassword", probe, re.I)
    # the same principal as the boot task
    keep = (WIN / "register_keepalive.ps1").read_text(encoding="utf-8")
    assert "-LogonType S4U -RunLevel Highest" in probe and "-LogonType S4U -RunLevel Highest" in keep
    # the value reaches WSL2 on standard input, never as an argument of wsl.exe; no tool beyond the base system
    hand = next(ln for ln in probe.splitlines() if "wsl.exe -d $Distro" in ln)
    assert hand.strip().startswith("$out = $hex | & wsl.exe") and "$hex" not in hand.split("wsl.exe", 1)[1]
    assert "xxd" not in probe


def test_the_key_probe_decides_at_startup_with_nobody_signed_in_and_leaves_no_task() -> None:
    """Review of NEW-WIN-8, H3 and L6: the run that decides is the one at startup, as the boot task runs."""
    probe = (WIN / "key-probe.ps1").read_text(encoding="utf-8")
    assert "New-ScheduledTaskTrigger -AtStartup" in probe and "[switch]$Collect" in probe
    assert "desktop_shells_running=" in probe and "ran_at=" in probe
    # the on-demand task is removed also when the run dies; the startup task is removed by -Collect
    assert re.search(r"\} finally \{[^}]*Unregister-ScheduledTask -TaskName \$TaskName", probe, re.S)
    collect = probe[probe.index("if ($Collect) {") : probe.index("$dummy = New-Object byte[] 32")]
    assert "Unregister-ScheduledTask -TaskName $TaskName" in collect
    # the task runs a copy in the installer's closed folder, not a path on the media, and the folder is not a parameter
    assert "$copy = Join-Path $ProbeDir" in probe and "$PSCommandPath, $mode" not in probe
    assert "[string]$ProbeDir" not in probe
    sheet = (ROOT / "docs/handover/P-0-windows-rehearsal.md").read_text(encoding="utf-8")
    assert "key-probe.ps1 -AtStartup" in sheet and "key-probe.ps1 -Collect" in sheet


def test_the_network_mode_is_asked_of_wsl_and_unknown_without_wslinfo(box: Box) -> None:
    assert box.run("network-mode").stdout.strip() == "unknown"  # no wslinfo on this machine: an old WSL
    box.stub("wslinfo", "printf 'mirrored\\r\\n'")
    assert box.run("network-mode").stdout.strip() == "mirrored"


def test_egress_check_wants_the_unit_active_and_the_table_loaded(box: Box) -> None:
    box.stub("systemctl", "echo inactive; exit 3")
    box.stub("nft", "exit 0")
    out = box.run("egress-check")
    assert out.returncode == 1 and "trialbox-egress.service is not active" in out.stderr
    box.stub("systemctl", "echo active")
    box.stub("nft", "exit 1")
    out = box.run("egress-check")
    assert out.returncode == 1 and "trialbox_egress is not loaded" in out.stderr
    box.stub("nft", "exit 0")
    assert box.run("egress-check").returncode == 0
    assert "nft list table inet trialbox_egress" in box.log()


def test_the_installer_opens_the_one_port_the_box_form_publishes_and_names_the_real_egress_table() -> None:
    ps1 = PS1.read_text(encoding="utf-8")
    port = re.search(r"\$script:TbConsolePort = (\d+)", ps1)
    assert port
    # every compose file the box form adds to the base (install.sh): one published port among them, and it is the
    # one the firewall admits; the base's own console port is reset by the identity file
    published: list[str] = []
    for name in ("identity", "box", "secrets", "rtxpro6000"):
        text = (ROOT / f"deploy/docker-compose.{name}.yml").read_text(encoding="utf-8")
        for entry in re.findall(r"^\s*ports:\s*(.+)$", text, re.M):
            if "!reset" not in entry:
                published += re.findall(r":(\d+):\d+", entry)
        assert not re.search(r"^\s*ports:\s*$", text, re.M), name  # no multi-line port list this test would not read
    assert published == [port.group(1)]
    assert "ports: !reset []" in (ROOT / "deploy/docker-compose.identity.yml").read_text(encoding="utf-8")
    # the rule admits the workstation's own subnet only, inbound, for WSL's virtual machines; nothing wider
    rule = ps1[ps1.index("function Write-TbConsoleFirewallRule") : ps1.index("function Set-TbConsoleFirewall")]
    assert (
        'RemoteAddresses = "LocalSubnet"' in rule and 'Direction = "Inbound"' in rule and "LocalPorts = $Port" in rule
    )
    assert "DefaultInboundAction Block" in ps1 and '"Any"' not in rule and "Disable-NetFirewall" not in ps1
    table = re.search(r'^TABLE = "([a-z_]+)"', (ROOT / "deploy/egress.py").read_text(encoding="utf-8"), re.M)
    assert table and f"nft list table inet {table.group(1)}" in SH.read_text(encoding="utf-8")


def _egress_box(box: Box, *, connects: bool, counts: bool) -> None:
    (box.tmp / "denied").write_text("5\n")
    box.stub(
        "docker",
        f"""case "$1 $2" in
  "network ls") echo trialbox_trialbox-net; echo trialbox_egress-net ;;
  "ps --filter") echo trialbox-gateway-1 ;;
esac
case "$1" in exec) {"echo 12 > $TB_FAKE/denied;" if counts else ""} exit {0 if connects else 1} ;; esac""",
    )
    box.stub(
        "nft",
        """n=$(cat "$TB_FAKE/denied")
echo '    ip saddr { 172.30.0.0/24 } counter packets 3 bytes 180 drop comment "trialbox no direct access"'
echo "    ip saddr { 172.30.0.0/24 } counter packets $n bytes 600 drop comment \"trialbox default deny\"" """,
    )


@pytest.mark.parametrize(
    ("connects", "counts", "verdict"),
    [
        (False, True, "verdict=held"),
        (True, False, "verdict=OUT"),
        (True, True, "verdict=OUT"),
        (False, False, "verdict=inconclusive"),
    ],
)
def test_the_egress_proof_reads_the_tables_own_counter(box: Box, connects: bool, counts: bool, verdict: str) -> None:
    """Review of NEW-WIN-4, H1: a failed connection alone proves nothing; the table's dropped-packet counter must
    rise, and a connection that succeeds is never a pass."""
    _egress_box(box, connects=connects, counts=counts)
    out = box.run("egress-proof")
    assert out.returncode == 0 and out.stdout.strip().splitlines()[-1].startswith(verdict), out.stdout + out.stderr
    log = box.log()
    assert "docker ps --filter network=trialbox_egress-net" in log  # a container that HAS a route out
    assert "docker exec trialbox-gateway-1 python3 -c" in log and "192.0.2.1" in log
    assert "denied_before=5" in out.stdout


def test_the_egress_proof_is_inconclusive_without_a_stack(box: Box) -> None:
    box.stub("docker", "exit 0")
    assert box.run("egress-proof").stdout.strip().startswith("verdict=inconclusive")


@pytest.mark.parametrize(
    ("ranges", "addr", "ok"),
    [
        ("192.0.2.0/24", "192.0.2.10/24", True),
        ("10.255.255.254/32", "192.0.2.10/24", False),  # review M2: the loopback's address was taken for the network
        ("198.51.100.0/24", "192.0.2.10/24", False),  # a VPN adapter's subnet
        ("192.0.2.10/32", "192.0.2.10/24", False),  # the PC itself only: no other computer is admitted
        ("192.0.2.0/24 2001:db8::/64", "192.0.2.10/24", True),
        ("", "192.0.2.10/24", False),
    ],
)
def test_the_lan_check_compares_the_boxs_firewall_with_this_pcs_real_network(
    box: Box, ranges: str, addr: str, ok: bool
) -> None:
    site = box.root / "deploy/site"
    site.mkdir(parents=True)
    (site / "hardening.conf").write_text(f'KEK_BACKEND=passphrase\nCLINIC_RANGES="{ranges}"\nSSH=off\n')
    box.stub(
        "ip",
        f"""case "$*" in
  *"route show default"*) echo 'default via 192.0.2.1 dev eth0 proto kernel' ;;
  *"addr show dev eth0"*) echo '2: eth0    inet {addr} brd 192.0.2.255 scope global eth0' ;;
esac""",
    )
    out = box.run("lan-check")
    assert (out.returncode == 0) is ok, out.stdout + out.stderr
    assert f"this PC's network address '{addr}'" in out.stdout


def test_an_unknown_step_is_an_error(box: Box) -> None:
    assert box.run("format-disk").returncode == 1

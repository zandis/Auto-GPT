"""NEW-WIN-9 (D-605): ``tools/windows_media.py`` builds the offline media the Windows installer reads, and checks one.

The media is built here from small stand-in inputs (no Windows package, image or driver is downloaded or committed).
The installer's own step 1 runs against a media of the same layout in the Pester tests (``tests/windows``); this
file holds the builder to what that step looks for."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import windows_media as wm

ROOT = Path(__file__).resolve().parents[2]
PS1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")


UBUNTU_2404 = 'PRETTY_NAME="Ubuntu 24.04.3 LTS"\nNAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n'


AMD64_STATUS = (
    "Package: base-files\nStatus: install ok installed\nArchitecture: amd64\nVersion: 13\n\n"
    "Package: adduser\nStatus: install ok installed\nArchitecture: all\nVersion: 3\n\n"
)


def _image(path: Path, os_release: str | None = UBUNTU_2404, extra: dict[str, bytes] | None = None) -> Path:
    """A tiny stand-in for a WSL root file system: a .tar.gz with its own etc/os-release."""
    import io
    import tarfile

    members = {"var/lib/dpkg/status": AMD64_STATUS.encode(), **(extra or {})}
    if os_release is not None:
        members["etc/os-release"] = os_release.encode()
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _inputs(tmp: Path) -> dict[str, Path]:
    src = tmp / "in"
    (src / "debs").mkdir(parents=True)
    files = {
        "bundle": src / "trialbox-1.0.0.tar",
        "wsl_msi": src / "wsl.2.4.13.0.x64.msi",
        "rootfs": src / "ubuntu-24.04-wsl-amd64.tar.gz",
        "vendor_pub": src / "vendor_ed25519.pub",
        "nvidia_driver": src / "581.15-desktop-win10-win11-64bit-international-dch-whql.exe",
    }
    for name, p in files.items():
        p.write_bytes(f"stand-in for {name}\n".encode())
    _image(files["rootfs"])
    for deb in (
        "docker-ce_27.3.1_amd64.deb",
        "nvidia-container-toolkit_1.17.0_amd64.deb",
        "libnvidia-container1_1.17.0_amd64.deb",
    ):
        (src / "debs" / deb).write_bytes(b"deb")
    return {**files, "debs": src / "debs"}


def _build(tmp: Path, **over: object) -> Path:
    args: dict[str, object] = {**_inputs(tmp), "out": tmp / "out", "version": "1.0.0"}
    args.update(over)
    return wm.build(**args)  # type: ignore[arg-type]


def test_a_media_is_laid_out_as_the_installer_reads_it_and_passes_its_own_check(tmp_path: Path) -> None:
    media = _build(tmp_path)
    assert media.name == "TRIALBOX-1.0.0"
    names = {p.relative_to(media).as_posix() for p in media.rglob("*") if p.is_file()}
    for want in (
        "Install-TrialBox.cmd", "README.txt", "SHA256SUMS",
        "windows/box-install.ps1", "windows/box-install.messages.json", "windows/wsl-setup.sh",
        "windows/register_keepalive.ps1", "windows/key-probe.ps1", "windows/preflight.ps1", "windows/host_facts.ps1",
        "windows/wsl/wsl.2.4.13.0.x64.msi", "windows/wsl/ubuntu-24.04-wsl-amd64.tar.gz",
        "windows/nvidia/581.15-desktop-win10-win11-64bit-international-dch-whql.exe",
        "linux/debs/docker-ce_27.3.1_amd64.deb", "linux/trialbox-host.tar", "linux/trialbox-1.0.0.tar",
        "linux/trialbox-1.0.0.tar.sha256", "linux/vendor_ed25519.pub", "docs/P-0-windows-rehearsal.md",
    ):  # fmt: skip
        assert want in names, want
    assert wm.check(media) == []
    # the launcher for cmd.exe, the script for bash: each with the line ends its reader needs
    assert b"\r\n" in (media / "Install-TrialBox.cmd").read_bytes()
    assert b"\r\n" not in (media / "windows/wsl-setup.sh").read_bytes()
    # every file but the list itself is listed, by a path with forward slashes
    listed = {ln.split("  ", 1)[1] for ln in (media / "SHA256SUMS").read_text().splitlines()}
    assert listed == names - {"SHA256SUMS"}


def test_the_host_tree_on_the_media_carries_the_linux_installer_and_the_windows_files(tmp_path: Path) -> None:
    import tarfile

    media = _build(tmp_path)
    with tarfile.open(media / "linux/trialbox-host.tar") as tar:
        members = set(tar.getnames())
    assert {
        "deploy/box-install.sh",
        "deploy/install.sh",
        "deploy/windows/wsl-setup.sh",
        "deploy/windows/host_facts.ps1",
    } <= members


def test_the_builder_looks_for_the_same_files_as_step_1_of_the_installer() -> None:
    """Find-TbOne in box-install.ps1 names each file the installer wants exactly once; the builder's table must
    hold every one of them, or a media could pass ``check`` and stop the installer."""
    found = re.findall(r'Find-TbOne (?:\(Join-Path \$win "wsl"\)|\$win|\$lin) "([^"]+)"', PS1)
    assert sorted(found) == sorted(
        ["wsl.*.msi", "ubuntu-24.04*.tar.gz", "wsl-setup.sh", "trialbox-host.tar", "trialbox-*.tar",
         "vendor_ed25519.pub", "register_keepalive.ps1"]
    )  # fmt: skip
    table = {pattern for patterns in wm.NEEDS_ONE.values() for pattern in patterns} | {wm.BUNDLE_PATTERN}
    assert set(found) == table
    # every call is one of the shapes read above: a new call of another shape turns this red, not silent
    assert len(re.findall(r"Find-TbOne [($]", PS1)) == len(found)
    # every file the installer reads from beside itself is one the builder places there
    beside = re.findall(r'Join-Path \$PSScriptRoot "([^"]+)"', PS1)
    assert beside and set(beside) <= set(wm.INSTALLER_FILES)
    # ... and it reaches no other folder of the media than these (a new one must be taught to the builder)
    assert set(re.findall(r'Join-Path \$(?:win|lin|m) "([^"]+)"', PS1)) <= {
        "wsl", "nvidia", "debs", "windows", "linux", "SHA256SUMS",
    }  # fmt: skip
    # the installer copies these beside itself for the run after the restart, and reads its messages from there
    for name in re.findall(r"foreach \(\$n in @\(([^)]*)\)\)", PS1)[0].replace('"', "").split(", "):
        assert name in wm.INSTALLER_FILES, name


def test_the_driver_rule_is_the_installers_own(tmp_path: Path) -> None:
    sh = (ROOT / "deploy/windows/wsl-setup.sh").read_text(encoding="utf-8")
    driver = re.search(r"^DRIVER_RE='([^']+)'", sh, re.M)
    toolkit = re.search(r"^TOOLKIT_RE='([^']+)'", sh, re.M)
    assert driver and toolkit
    assert wm.DRIVER_RE.pattern == driver.group(1) and wm.TOOLKIT_RE.pattern == toolkit.group(1)
    assert wm.is_linux_driver("nvidia-driver-570_570.1_amd64.deb") and wm.is_linux_driver(
        "libnvidia-compute-570_1_amd64.deb"
    )
    assert not wm.is_linux_driver("nvidia-container-toolkit_1.17.0_amd64.deb")
    assert not wm.is_linux_driver("libnvidia-container1_1.17.0_amd64.deb") and not wm.is_linux_driver(
        "docker-ce_27_amd64.deb"
    )


def test_a_linux_nvidia_driver_among_the_packages_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    (inputs["debs"] / "nvidia-driver-570_570.1_amd64.deb").write_bytes(b"deb")
    with pytest.raises(wm.MediaError, match="nvidia-driver-570_570.1_amd64.deb"):
        wm.build(**inputs, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"wsl_msi": "missing.msi"}, "--wsl-msi: no such file"),
        ({"rootfs": "rootfs.tar.gz"}, "cannot be read to its end as a .tar.gz archive"),
        ({"bundle": "trialbox-host.tar"}, "is not named trialbox-<version>.tar"),
        ({"version": "1.0 beta"}, "letters, digits"),
        ({"version": "../x"}, "letters, digits"),
        ({"debs": "empty"}, "no .deb package"),
    ],
)
def test_a_wrong_input_is_named_and_nothing_is_written(tmp_path: Path, change: dict[str, str], says: str) -> None:
    inputs: dict[str, object] = {**_inputs(tmp_path), "out": tmp_path / "out", "version": "1.0.0"}
    for key, value in change.items():
        if key == "version":
            inputs[key] = value
        else:
            p = tmp_path / "in" / value
            if value in ("rootfs.tar.gz", "trialbox-host.tar"):
                p.write_bytes(b"x")
            elif value == "empty":
                p.mkdir()
            inputs[key] = p
    with pytest.raises(wm.MediaError, match=re.escape(says)):
        wm.build(**inputs)  # type: ignore[arg-type]
    assert not (tmp_path / "out").exists()


def test_canonicals_own_file_name_is_taken_and_placed_under_a_name_the_installer_finds(tmp_path: Path) -> None:
    """Canonical publishes the image as ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz; the installer looks for
    ubuntu-24.04*.tar.gz. The image is known by its own etc/os-release, not by its name (D-609)."""
    inputs = _inputs(tmp_path)
    real = _image(tmp_path / "in/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz")
    media = wm.build(**{**inputs, "rootfs": real}, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    placed = [p.name for p in (media / "windows/wsl").glob("*.tar.gz")]
    assert placed == ["ubuntu-24.04.ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"]
    assert wm.check(media) == []
    import fnmatch

    assert fnmatch.fnmatch(placed[0], "ubuntu-24.04*.tar.gz")  # the installer's own pattern (Find-TbOne)
    assert (media / "windows/wsl" / placed[0]).read_bytes() == real.read_bytes()


@pytest.mark.parametrize(
    ("name", "os_release", "says"),
    [
        (
            "ubuntu-24.04-wsl-amd64.tar.gz",
            'ID=ubuntu\nVERSION_ID="22.04"\n',
            "is ubuntu 22.04; the installer imports Ubuntu 24.04",
        ),
        ("ubuntu-24.04-really.tar.gz", 'ID=debian\nVERSION_ID="12"\n', "is debian 12"),
        ("ubuntu-24.04-wsl-amd64.tar.gz", None, "holds no etc/os-release"),
        ("ubuntu-24.04-wsl-amd64.tar", UBUNTU_2404, "is not a .tar.gz archive"),
        ("ubuntu-24.04-wsl-arm64.tar.gz", "ARM64", "holds packages for arm64; the workstation needs the amd64 image"),
        ("ubuntu-24.04-wsl-none.tar.gz", "NOSTATUS", "holds packages for no architecture"),
    ],
)
def test_an_image_that_is_not_ubuntu_24_04_is_refused_whatever_its_name(
    tmp_path: Path, name: str, os_release: str | None, says: str
) -> None:
    inputs = _inputs(tmp_path)
    extra = {"bin/sh": b"#!"}
    if os_release == "ARM64":  # Canonical publishes the same release for arm64 under a like name
        os_release, extra = UBUNTU_2404, {"var/lib/dpkg/status": AMD64_STATUS.replace("amd64", "arm64").encode()}
    elif os_release == "NOSTATUS":
        os_release, extra = UBUNTU_2404, {"var/lib/dpkg/status": b""}
    image = _image(tmp_path / "in" / ("x-" + name), os_release, extra).rename(tmp_path / "in" / name)
    with pytest.raises(wm.MediaError, match=re.escape(says)):
        wm.build(**{**inputs, "rootfs": image}, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    assert not (tmp_path / "out").exists()


def test_an_image_cut_short_on_the_way_is_refused(tmp_path: Path) -> None:
    """The archive is read to its end: os-release sits early in it, so a cut copy would otherwise pass (review M3)."""
    import os

    inputs = _inputs(tmp_path)
    whole = _image(tmp_path / "in/ubuntu-24.04-big.tar.gz", extra={"usr/lib/big": os.urandom(300_000)})
    cut = tmp_path / "in/ubuntu-24.04-cut.tar.gz"
    cut.write_bytes(whole.read_bytes()[:150_000])
    with pytest.raises(wm.MediaError, match="cannot be read to its end"):
        wm.build(**{**inputs, "rootfs": cut}, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    assert wm.rootfs_name(whole) == "ubuntu-24.04-big.tar.gz"


def test_the_systems_own_os_release_file_is_the_one_believed(tmp_path: Path) -> None:
    """etc/os-release when it is a file; usr/lib/os-release only when etc holds a link (review L6)."""
    mixed = _image(
        tmp_path / "ubuntu-24.04-mixed.tar.gz",
        'ID=debian\nVERSION_ID="12"\n',
        {"usr/lib/os-release": UBUNTU_2404.encode()},
    )
    with pytest.raises(wm.MediaError, match="is debian 12"):
        wm.rootfs_name(mixed)
    release, archs = wm.image_facts(_image(tmp_path / "a.tar.gz", None, {"usr/lib/os-release": UBUNTU_2404.encode()}))
    assert release["VERSION_ID"] == "24.04" and archs == {"amd64"}


def test_an_output_folder_that_holds_files_is_never_written_over(tmp_path: Path) -> None:
    media = _build(tmp_path)
    before = (media / "SHA256SUMS").read_text()
    with pytest.raises(wm.MediaError, match="already holds files"):
        wm.build(**_inputs(tmp_path / "second"), out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    assert (media / "SHA256SUMS").read_text() == before


def test_check_names_every_reason_the_installer_would_stop(tmp_path: Path) -> None:
    media = _build(tmp_path)
    (media / "linux/trialbox-1.0.0.tar").write_bytes(b"changed on the way")
    (media / "windows/wsl/wsl.2.4.14.0.x64.msi").write_bytes(b"a second package")
    (media / "linux/debs/nvidia-driver-570_570.1_amd64.deb").write_bytes(b"deb")
    (media / "linux/vendor_ed25519.pub").unlink()
    problems = "\n".join(wm.check(media))
    assert "linux/trialbox-1.0.0.tar: does not match SHA256SUMS" in problems
    assert "windows/wsl/wsl.*.msi: the installer wants exactly one, found 2" in problems
    assert "windows/wsl/wsl.2.4.14.0.x64.msi: not listed in SHA256SUMS" in problems
    assert "linux/debs/nvidia-driver-570_570.1_amd64.deb: a Linux NVIDIA driver package" in problems
    assert "linux/vendor_ed25519.pub: the installer wants exactly one, found 0" in problems
    assert "linux/vendor_ed25519.pub: listed in SHA256SUMS but not on the media" in problems


def test_check_fails_a_script_whose_line_ends_were_changed_on_the_way(tmp_path: Path) -> None:
    media = _build(tmp_path)
    setup = media / "windows/wsl-setup.sh"
    setup.write_bytes(setup.read_bytes().replace(b"\n", b"\r\n"))
    wm.write_sums(media)  # even with matching sums: bash would not run it
    assert any("wsl-setup.sh has Windows line ends" in p for p in wm.check(media))


def test_the_command_line_builds_and_checks(tmp_path: Path) -> None:
    i = _inputs(tmp_path)
    cmd = [sys.executable, "-m", "tools.windows_media"]
    env = {"PYTHONPATH": f"{ROOT / 'libs'}:{ROOT}", "PATH": "/usr/bin:/bin"}
    built = subprocess.run(
        [*cmd, "build", "--out", str(tmp_path / "out"), "--version", "1.0.0", "--bundle", str(i["bundle"]),
         "--wsl-msi", str(i["wsl_msi"]), "--rootfs", str(i["rootfs"]), "--debs", str(i["debs"]),
         "--vendor-pub", str(i["vendor_pub"]), "--link"],
        capture_output=True, text=True, cwd=ROOT, env=env, check=False, timeout=120,
    )  # fmt: skip
    assert built.returncode == 0 and "SHA256SUMS written, not signed" in built.stdout, built.stderr
    media = tmp_path / "out/TRIALBOX-1.0.0"
    assert "none (install it first)" in (media / "README.txt").read_text()
    ok = subprocess.run(
        [*cmd, "check", str(media)], capture_output=True, text=True, cwd=ROOT, env=env, check=False, timeout=120
    )
    assert ok.returncode == 0 and "nothing here would stop" in ok.stdout
    (media / "windows/box-install.ps1").write_text("changed")
    bad = subprocess.run(
        [*cmd, "check", str(media)], capture_output=True, text=True, cwd=ROOT, env=env, check=False, timeout=120
    )
    assert bad.returncode == 1 and "FAIL  windows/box-install.ps1: does not match SHA256SUMS" in bad.stdout


def test_a_file_added_later_fails_the_check_until_the_list_is_written_again(tmp_path: Path) -> None:
    media = _build(tmp_path)
    (media / "docs/network-sheet.en.html").write_text("<html></html>")
    assert wm.check(media) == ["docs/network-sheet.en.html: not listed in SHA256SUMS"]
    assert wm.main(["sums", str(media)]) == 0
    assert wm.check(media) == []
    assert wm.main(["sums", str(tmp_path / "in")]) == 1  # not a media folder: nothing is written there
    assert not (tmp_path / "in/SHA256SUMS").exists()


def test_packages_without_docker_or_the_container_toolkit_are_refused(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    (inputs["debs"] / "docker-ce_27.3.1_amd64.deb").unlink()
    with pytest.raises(wm.MediaError, match=r"lacks Docker Engine \(docker-ce_\*\.deb\)"):
        wm.build(**inputs, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    assert not (tmp_path / "out").exists()
    media = _build(tmp_path / "second")
    (media / "linux/debs/nvidia-container-toolkit_1.17.0_amd64.deb").unlink()
    wm.write_sums(media)
    assert wm.check(media) == ["linux/debs: lacks the NVIDIA Container Toolkit (nvidia-container-toolkit_*.deb)"]


def test_a_build_that_fails_midway_leaves_no_media_and_can_be_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import host_tree

    def broken(*_a: object, **_k: object) -> None:
        raise host_tree.HostTreeError("the tree cannot be packed")

    inputs = _inputs(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(host_tree, "pack", broken)
        with pytest.raises(host_tree.HostTreeError):
            wm.build(**inputs, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
        assert list((tmp_path / "out").iterdir()) == []  # no TRIALBOX-1.0.0, no .part
        args = ["build", "--out", str(tmp_path / "out"), "--version", "1.0.0", "--bundle", str(inputs["bundle"]),
                "--wsl-msi", str(inputs["wsl_msi"]), "--rootfs", str(inputs["rootfs"]), "--debs", str(inputs["debs"]),
                "--vendor-pub", str(inputs["vendor_pub"])]  # fmt: skip
        assert wm.main(args) == 1  # a message, not a traceback
    media = wm.build(**inputs, out=tmp_path / "out", version="1.0.0")  # type: ignore[arg-type]
    assert wm.check(media) == [] and not (tmp_path / "out/TRIALBOX-1.0.0.part").exists()


def test_file_names_are_matched_as_windows_matches_them(tmp_path: Path) -> None:
    media = _build(tmp_path)
    (media / "windows/wsl/WSL.2.5.0.0.X64.MSI").write_bytes(b"a second package, in capitals")
    wm.write_sums(media)
    assert wm.check(media) == ["windows/wsl/wsl.*.msi: the installer wants exactly one, found 2"]
    (media / "windows/wsl/wsl.2.4.13.0.x64.msi").unlink()
    wm.write_sums(media)
    assert wm.check(media) == []  # only the one in capitals: the installer takes it


def test_a_link_never_reaches_the_media(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    real = inputs["rootfs"].rename(tmp_path / "in/real-image")
    inputs["rootfs"].symlink_to(real)
    media = wm.build(**inputs, out=tmp_path / "out", version="1.0.0", link=True)
    image = media / "windows/wsl/ubuntu-24.04-wsl-amd64.tar.gz"
    assert not image.is_symlink() and image.read_bytes() == real.read_bytes()
    (media / "docs/extra.txt").symlink_to(real)
    wm.write_sums(media)
    assert "docs/extra.txt: a link, not a file" in wm.check(media)


def test_the_list_is_never_written_through_a_link(tmp_path: Path) -> None:
    media = _build(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("not the media's")
    (media / "SHA256SUMS").unlink()
    (media / "SHA256SUMS").symlink_to(outside)
    wm.write_sums(media)
    assert outside.read_text() == "not the media's" and not (media / "SHA256SUMS").is_symlink()


def test_a_list_saved_by_a_windows_editor_is_read_and_an_unreadable_one_is_named(tmp_path: Path) -> None:
    media = _build(tmp_path)
    sums = media / "SHA256SUMS"
    sums.write_bytes(b"\xef\xbb\xbf" + sums.read_bytes().replace(b"\n", b"\r\n"))
    assert wm.check(media) == []
    sums.write_bytes(sums.read_text(encoding="utf-8-sig").encode("utf-16"))
    assert wm.check(media) == ["SHA256SUMS cannot be read as UTF-8 text (UnicodeDecodeError)"]
    assert wm.main(["check", str(media)]) == 1


def test_a_launcher_with_one_unix_line_end_fails_the_check(tmp_path: Path) -> None:
    media = _build(tmp_path)
    launcher = media / "Install-TrialBox.cmd"
    launcher.write_bytes(launcher.read_bytes() + b"rem added on Linux\n")
    wm.write_sums(media)
    assert wm.check(media) == ["Install-TrialBox.cmd has a line without a Windows line end"]


def test_nothing_is_downloaded_and_no_windows_payload_is_in_the_repository() -> None:
    source = (ROOT / "tools/windows_media.py").read_text(encoding="utf-8")
    assert not re.search(r"urllib|requests|http://|https://|curl|wget", source)
    payload = [
        p for p in (ROOT / "deploy/windows").rglob("*") if p.suffix.lower() in (".msi", ".exe", ".gz", ".deb", ".vhdx")
    ]
    assert payload == []

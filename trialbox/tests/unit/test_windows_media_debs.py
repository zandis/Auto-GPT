"""NEW-WIN-9 (D-609): ``tools/windows_media_debs.py`` works out the Ubuntu packages of the Windows offline media.

Here: everything but the network and apt itself (they are replaced): which files it reads from the image, that an
image that is not Ubuntu 24.04 is refused, the repository keys' fingerprints, the sources and the options apt
gets, and what is done with what apt fetched. The real run (Canonical's image, Ubuntu's, Docker's and NVIDIA's
repositories) was made once by hand on 2026-11-13 and is recorded in D-609; it is not a test, because a test must
not go online."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tools import windows_media_debs as wd

UBUNTU = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n'
STATUS = "Package: base-files\nStatus: install ok installed\nVersion: 13ubuntu10\nArchitecture: amd64\n\n"
# gpg --show-keys --with-colons of a key file: the primary key's fingerprint, then a subkey's
DOCKER_COLONS = (
    "pub:-:4096:1:8D81803C0EBFCD88:1487788586:::-:::scSC::::::23::0:\n"
    "fpr:::::::::9DC858229FC7DD38854AE2D88D81803C0EBFCD88:\n"
    "uid:-::::1487792064::A4B6F1A2::Docker Release (CE deb) <docker@docker.com>::::::::::0:\n"
    "sub:-:4096:1:7EA0A9C3F273FCD8:1487788586::::::s::::::23:\n"
    "fpr:::::::::D3306A018370199E527AE7997EA0A9C3F273FCD8:\n"
)


def _image(path: Path, os_release: str = UBUNTU, drop: str = "") -> Path:
    members = {"./etc/os-release": os_release, "./usr/share/keyrings/ubuntu-archive-keyring.gpg": "KEYRING",
               "./var/lib/dpkg/status": STATUS, "./bin/sh": "#!"}  # fmt: skip
    with tarfile.open(path, "w:gz") as tar:
        for name, text in members.items():
            if drop and name.endswith(drop):
                continue
            info = tarfile.TarInfo(name)
            info.size = len(text.encode())
            tar.addfile(info, io.BytesIO(text.encode()))
    return path


class Apt:
    """In place of apt-get: records its calls; ``install --download-only`` leaves packages in apt's own cache."""

    def __init__(self, debs: tuple[str, ...]) -> None:
        self.calls: list[list[str]] = []
        self.debs = debs

    def __call__(self, args: list[str], what: str) -> str:
        self.calls.append(args)
        if "install" in args:
            cache = Path(next(a.split("=", 1)[1] for a in args if a.startswith("Dir::Cache=")))
            for name in self.debs:
                (cache / "archives" / name).write_bytes(b"deb " + name.encode())
        return ""


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_key(name: str, into: Path) -> Path:
        (into / f"{name}.asc").write_text("KEY")
        return into / f"{name}.asc"

    monkeypatch.setattr(wd, "fetch_key", fake_key)
    monkeypatch.setattr("shutil.which", lambda tool: f"/usr/bin/{tool}")


GOOD = ("docker-ce_5%3a29.9.3-1~ubuntu.24.04~noble_amd64.deb", "nvidia-container-toolkit_1.20.2-1_amd64.deb",
        "libnvidia-container1_1.20.2-1_amd64.deb", "nftables_1.0.9-1ubuntu0.1_amd64.deb")  # fmt: skip


def test_the_set_is_worked_out_against_the_images_own_packages_and_placed_in_the_folder(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    apt = Apt(GOOD)
    monkeypatch.setattr(wd, "_apt", apt)
    out, work = tmp_path / "debs", tmp_path / "work"
    placed = wd.collect(_image(tmp_path / "ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"), out, work)
    assert sorted(p.name for p in placed) == sorted(GOOD) and sorted(p.name for p in out.iterdir()) == sorted(GOOD)
    update, install = apt.calls
    assert update[-1] == "update"
    assert install[install.index("install") :] == [
        "install",
        "--download-only",
        "-y",
        "--no-install-recommends",
        *wd.PACKAGES,
    ]
    # apt reads the IMAGE's package state, and nothing of this machine's: every folder it uses is under --work
    opts = dict(a.split("=", 1) for a in install if "=" in a and "::" in a)
    assert opts["Dir::State::status"] == str(work / "image/var/lib/dpkg/status")
    assert (work / "image/var/lib/dpkg/status").read_text() == STATUS
    for key in ("Dir::State", "Dir::Cache", "Dir::Etc", "Dir::Etc::sourcelist", "Dir::Etc::sourceparts",
                "Dir::Etc::trustedparts", "Dir::Etc::parts", "Dir::Etc::preferencesparts"):  # fmt: skip
        assert opts[key].startswith(str(work) + "/"), key
    assert opts["APT::Architecture"] == "amd64"
    text = (work / "etc/sources.list").read_text()
    assert (
        f"signed-by={work}/image/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://archive.ubuntu.com/ubuntu noble "
        in text
    )
    assert f"signed-by={work}/keys/docker.asc] https://download.docker.com/linux/ubuntu noble stable" in text
    assert f"signed-by={work}/keys/nvidia.asc] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /" in text
    assert "trusted=yes" not in text and "allow-unauthenticated" not in " ".join(install).lower()


def test_what_it_asks_for_is_what_the_installers_package_step_needs() -> None:
    from tools import windows_media as wm

    assert set(wm.NEEDED_PACKAGES) <= set(wd.PACKAGES)  # Docker Engine and the NVIDIA Container Toolkit
    assert not any(wm.is_linux_driver(f"{p}_1_amd64.deb") for p in wd.PACKAGES)


@pytest.mark.parametrize(
    ("os_release", "drop", "says"),
    [
        ('ID=ubuntu\nVERSION_ID="22.04"\n', "", "is ubuntu 22.04; the installer imports Ubuntu 24.04"),
        ('ID=debian\nVERSION_ID="12"\n', "", "is debian 12"),
        (UBUNTU, "dpkg/status", "holds no var/lib/dpkg/status"),
        (UBUNTU, "ubuntu-archive-keyring.gpg", "holds no usr/share/keyrings/ubuntu-archive-keyring.gpg"),
    ],
)
def test_an_image_that_is_not_an_ubuntu_24_04_system_is_refused_before_anything_is_fetched(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch, os_release: str, drop: str, says: str
) -> None:
    apt = Apt(GOOD)
    monkeypatch.setattr(wd, "_apt", apt)
    with pytest.raises(wd.DebsError, match=says.replace(".", r"\.").replace(";", ";")):
        wd.collect(_image(tmp_path / "image.tar.gz", os_release, drop), tmp_path / "debs", tmp_path / "work")
    assert apt.calls == [] and not (tmp_path / "debs").exists()


def test_canonicals_image_keeps_os_release_under_usr_lib_with_a_link_in_etc(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seen on the real image (2026-11-13): etc/os-release is a link, the file is usr/lib/os-release."""
    path = tmp_path / "ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        link = tarfile.TarInfo("etc/os-release")
        link.type, link.linkname = tarfile.SYMTYPE, "../usr/lib/os-release"
        tar.addfile(link)
        for name, text in (("usr/lib/os-release", UBUNTU), ("usr/share/keyrings/ubuntu-archive-keyring.gpg", "K"),
                           ("var/lib/dpkg/status", STATUS)):  # fmt: skip
            info = tarfile.TarInfo(name)
            info.size = len(text.encode())
            tar.addfile(info, io.BytesIO(text.encode()))
    monkeypatch.setattr(wd, "_apt", Apt(GOOD))
    assert len(wd.collect(path, tmp_path / "debs", tmp_path / "work")) == len(GOOD)
    from tools import windows_media as wm

    assert wm.rootfs_name(path) == "ubuntu-24.04." + path.name


def test_a_file_that_is_not_an_archive_is_named(tmp_path: Path, offline: None) -> None:
    bad = tmp_path / "image.tar.gz"
    bad.write_bytes(b"not an archive")
    with pytest.raises(wd.DebsError, match="cannot be read as a tar archive"):
        wd.collect(bad, tmp_path / "debs", tmp_path / "work")


def test_a_linux_nvidia_driver_in_the_set_stops_it_and_nothing_is_placed(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wd, "_apt", Apt((*GOOD, "nvidia-driver-570_570.1_amd64.deb")))
    with pytest.raises(wd.DebsError, match="nvidia-driver-570_570.1_amd64.deb"):
        wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path / "work")
    assert not (tmp_path / "debs").exists()


def test_nothing_fetched_is_an_error_and_a_folder_that_holds_files_is_not_written_over(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wd, "_apt", Apt(()))
    with pytest.raises(wd.DebsError, match="fetched no package"):
        wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path / "work")
    full = tmp_path / "full"
    full.mkdir()
    (full / "old.deb").write_bytes(b"x")
    with pytest.raises(wd.DebsError, match="already holds files"):
        wd.collect(_image(tmp_path / "image2.tar.gz"), full, tmp_path / "work2")
    assert [p.name for p in full.iterdir()] == ["old.deb"]


def test_only_the_primary_keys_fingerprint_is_read_from_gpg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Done:
        stdout, returncode = DOCKER_COLONS, 0

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())
    assert wd.fingerprints(tmp_path / "docker.asc") == [wd.KEYS["docker"][1]]


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


@pytest.mark.parametrize(
    "got", [["0000000000000000000000000000000000000000"], [], ["9DC858229FC7DD38854AE2D88D81803C0EBFCD88", "AAAA"]]
)
def test_a_repository_key_with_another_fingerprint_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, got: list[str]
) -> None:
    asked: list[str] = []

    def fake_open(url: str, timeout: float) -> _Resp:
        asked.append(url)
        return _Resp(b"-----BEGIN PGP PUBLIC KEY BLOCK-----")

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr(wd, "fingerprints", lambda _p: got)
    with pytest.raises(wd.DebsError, match="is not the one this tool knows"):
        wd.fetch_key("docker", tmp_path)
    assert asked == ["https://download.docker.com/linux/ubuntu/gpg"]
    monkeypatch.setattr(wd, "fingerprints", lambda _p: [wd.KEYS["docker"][1]])
    assert wd.fetch_key("docker", tmp_path).name == "docker.asc"


def test_every_address_is_https_or_ubuntus_signed_archive_and_the_fingerprints_are_whole() -> None:
    for name, (url, fingerprint) in wd.KEYS.items():
        assert url.startswith("https://"), name
        assert len(fingerprint) == 40 and set(fingerprint) <= set("0123456789ABCDEF"), name
    text = wd.sources(Path("/k/ubuntu.gpg"), Path("/k/docker.asc"), Path("/k/nvidia.asc"))
    for line in text.splitlines():
        assert "signed-by=/k/" in line, line  # no source without a key of its own
        assert line.split("] ", 1)[1].startswith(
            ("https://", "http://archive.ubuntu.com/", "http://security.ubuntu.com/")
        ), line


def test_the_command_line_names_a_missing_image(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert wd.main(["--rootfs", str(tmp_path / "none.tar.gz"), "--out", str(tmp_path / "debs")]) == 1
    assert "no such file" in capsys.readouterr().err

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

from tools import fetch_pinned
from tools import windows_media_debs as wd

UBUNTU = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n'
STATUS = "Package: base-files\nStatus: install ok installed\nVersion: 13ubuntu10\nArchitecture: amd64\n\n"
OTHER_STATUS = STATUS.replace("amd64", "arm64")
# gpg --show-keys --with-colons of a key file: the primary key's fingerprint, then a subkey's
DOCKER_COLONS = (
    "pub:-:4096:1:8D81803C0EBFCD88:1487788586:::-:::scSC::::::23::0:\n"
    "fpr:::::::::9DC858229FC7DD38854AE2D88D81803C0EBFCD88:\n"
    "uid:-::::1487792064::A4B6F1A2::Docker Release (CE deb) <docker@docker.com>::::::::::0:\n"
    "sub:-:4096:1:7EA0A9C3F273FCD8:1487788586::::::s::::::23:\n"
    "fpr:::::::::D3306A018370199E527AE7997EA0A9C3F273FCD8:\n"
)


def _image(path: Path, os_release: str = UBUNTU, drop: str = "") -> Path:
    status = STATUS
    if os_release == "ARM64":
        os_release, status = UBUNTU, OTHER_STATUS
    members = {"./etc/os-release": os_release, "./usr/share/keyrings/ubuntu-archive-keyring.gpg": "KEYRING",
               "./var/lib/dpkg/status": status, "./bin/sh": "#!"}  # fmt: skip
    with tarfile.open(path, "w:gz") as tar:
        for name, text in members.items():
            if drop and name.endswith(drop):
                continue
            info = tarfile.TarInfo(name)
            info.size = len(text.encode())
            tar.addfile(info, io.BytesIO(text.encode()))
    return path


class Apt:
    """In place of apt-get: records its calls. ``--print-uris`` names ``debs``; ``--download-only`` leaves them in
    the cache apt's configuration file names, and with them ``strays`` that apt never named."""

    def __init__(self, debs: tuple[str, ...], strays: tuple[str, ...] = (), skip: tuple[str, ...] = ()) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.debs, self.strays, self.skip = debs, strays, skip

    def __call__(self, args: list[str], what: str, env: dict[str, str]) -> str:
        self.calls.append(args)
        self.envs.append(env)
        if "--print-uris" in args:
            return "".join(f"'https://example.invalid/pool/{n}' {n} 1234 SHA256:{'0' * 64}\n" for n in self.debs)
        if "--download-only" in args:
            conf = Path(env["APT_CONFIG"]).read_text()
            cache = Path(next(ln.split('"')[1] for ln in conf.splitlines() if ln.startswith("Dir::Cache ")))
            for name in (*self.debs, *self.strays):
                if name not in self.skip:
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
    seen: dict[str, str] = {}

    def spy(args: list[str], what: str, env: dict[str, str]) -> str:
        if "update" in args:  # the run's own folder, while it still exists
            work = Path(env["APT_CONFIG"]).parents[1]
            seen["work"] = str(work)
            seen["conf"] = Path(env["APT_CONFIG"]).read_text()
            seen["sources"] = (work / "etc/sources.list").read_text()
            seen["status"] = (work / "image/var/lib/dpkg/status").read_text()
        return apt(args, what, env)

    monkeypatch.setattr(wd, "_apt", spy)
    out, parent = tmp_path / "debs", tmp_path / "work"
    parent.mkdir()
    placed = wd.collect(_image(tmp_path / "ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"), out, parent)
    assert sorted(p.name for p in placed) == sorted(GOOD) and sorted(p.name for p in out.iterdir()) == sorted(GOOD)
    update, uris, download = apt.calls
    assert update == ["update"]
    assert uris == ["install", "-y", "--no-install-recommends", *wd.PACKAGES, "--print-uris"]
    assert download == ["install", "-y", "--no-install-recommends", *wd.PACKAGES, "--download-only"]
    # apt reads the IMAGE's package state, and nothing of this machine's: every folder it uses is in this run's own
    work = seen["work"]
    assert Path(work).parent == parent and not Path(work).exists()  # made new for the run, removed after it
    conf = dict(ln.rstrip(";").split(" ", 1) for ln in seen["conf"].splitlines())
    assert conf["Dir::State::status"] == f'"{work}/image/var/lib/dpkg/status"' and seen["status"] == STATUS
    for key in ("Dir::State", "Dir::Cache", "Dir::Etc", "Dir::Etc::parts", "Dir::Etc::sourcelist", "Dir::Etc::sourceparts",
                "Dir::Etc::trusted", "Dir::Etc::trustedparts", "Dir::Etc::preferences", "Dir::Etc::preferencesparts",
                "Dir::Etc::netrc", "Dir::Etc::netrcparts"):  # fmt: skip
        assert conf[key].startswith(f'"{work}/'), key
    assert conf["APT::Architecture"] == '"amd64"'
    assert (
        conf["APT::Get::AllowUnauthenticated"] == '"false"' and conf["Acquire::AllowInsecureRepositories"] == '"false"'
    )
    text = seen["sources"]
    assert (
        f"signed-by={work}/image/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://archive.ubuntu.com/ubuntu noble "
        in text
    )
    assert f"signed-by={work}/keys/docker.asc] https://download.docker.com/linux/ubuntu noble stable" in text
    assert f"signed-by={work}/keys/nvidia.asc] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /" in text
    assert "trusted=yes" not in text


def test_apt_gets_its_configuration_by_file_and_none_of_the_callers_environment(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Options on apt's command line come after it has read the machine's /etc/apt/apt.conf.d (review H2)."""
    monkeypatch.setenv("APT_CONFIG", "/somewhere/hostile.conf")
    monkeypatch.setenv("DEBIAN_FRONTEND", "x")
    monkeypatch.setenv("https_proxy", "http://proxy.example:3128")
    apt = Apt(GOOD)
    monkeypatch.setattr(wd, "_apt", apt)
    (tmp_path / "w").mkdir()
    wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path / "w")
    for args, env in zip(apt.calls, apt.envs, strict=True):
        assert not any(a == "-o" or a.startswith("Dir::") for a in args), args
        assert env["APT_CONFIG"].endswith("/etc/apt.conf") and env["APT_CONFIG"].startswith(str(tmp_path / "w"))
        assert set(env) - set(wd.PROXY_VARS) == {
            "APT_CONFIG",
            "PATH",
            "LC_ALL",
            "HOME",
        }  # the proxy is all that is kept
        assert env["https_proxy"] == "http://proxy.example:3128"


def test_the_machines_own_apt_settings_do_not_reach_the_run(tmp_path: Path) -> None:
    """With the real apt-config, where there is one: what apt would use under the tool's configuration."""
    import shutil
    import subprocess

    if shutil.which("apt-config") is None:
        pytest.skip("no apt on this machine")
    conf = tmp_path / "etc/apt.conf"
    conf.parent.mkdir()
    conf.write_text(wd.apt_config(tmp_path, tmp_path / "status"))
    dump = subprocess.run(
        ["apt-config", "dump"], env=wd.apt_env(conf), capture_output=True, text=True, check=True
    ).stdout
    assert f'Dir::Etc "{tmp_path}/etc";' in dump and f'Dir::Etc::parts "{tmp_path}/etc/apt.conf.d";' in dump
    assert 'Acquire::AllowInsecureRepositories "false";' in dump and 'APT::Get::AllowUnauthenticated "false";' in dump
    # hooks come only from configuration files: with none of the machine's read, there is none
    assert "Post-Invoke" not in dump and "Pre-Invoke" not in dump, dump


def test_only_what_apt_named_for_this_run_reaches_the_output(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A package apt did not name (an older version left in a cache, a file someone placed) is never copied: the
    installer runs dpkg -i on every .deb of the media as root (review H1)."""
    strays = ("evil-planted_1.0_amd64.deb", "docker-ce_5%3a28.0.0-1~ubuntu.24.04~noble_amd64.deb")
    monkeypatch.setattr(wd, "_apt", Apt(GOOD, strays=strays))
    (tmp_path / "w").mkdir()
    placed = wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path / "w")
    assert sorted(p.name for p in placed) == sorted(GOOD)
    assert sorted(p.name for p in (tmp_path / "debs").iterdir()) == sorted(GOOD)
    assert list((tmp_path / "w").iterdir()) == []  # and nothing of the run is left for the next one


def test_a_work_folder_left_by_an_earlier_run_cannot_reach_this_one(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "w"
    for d in ("cache/archives", "etc/sources.list.d", "etc/apt.conf.d"):
        (parent / d).mkdir(parents=True)
    (parent / "cache/archives/evil-planted_1.0_amd64.deb").write_bytes(b"x")
    (parent / "etc/sources.list.d/extra.list").write_text("deb [trusted=yes] file:/tmp/x ./\n")
    apt = Apt(GOOD)
    monkeypatch.setattr(wd, "_apt", apt)
    placed = wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", parent)
    assert sorted(p.name for p in placed) == sorted(GOOD)
    assert all(Path(env["APT_CONFIG"]).parents[1] != parent for env in apt.envs)  # a new folder inside, not this one


def test_a_package_apt_named_and_did_not_fetch_stops_the_run(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wd, "_apt", Apt(GOOD, skip=(GOOD[1],)))
    (tmp_path / "w").mkdir()
    with pytest.raises(wd.DebsError, match="did not fetch: " + GOOD[1].replace(".", r"\.")):
        wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path / "w")
    assert not (tmp_path / "debs").exists()


def test_the_names_are_read_from_what_apt_prints() -> None:
    text = (
        "Reading package lists...\n"
        "'https://download.docker.com/linux/ubuntu/dists/noble/pool/stable/amd64/docker-ce_29.9.3-1_amd64.deb' "
        "docker-ce_5%3a29.9.3-1~ubuntu.24.04~noble_amd64.deb 21012345 SHA512:abc\n"
        "'http://archive.ubuntu.com/ubuntu/pool/main/n/nftables/nftables_1.0.9-1ubuntu0.1_amd64.deb' nftables_1.0.9-1ubuntu0.1_amd64.deb 69000 SHA256:def\n"
        "'http://x/y' ../escape.deb 1 SHA256:0\n'http://x/y' notadeb.txt 1 SHA256:0\n"
    )
    assert wd.wanted_files(text) == [
        "docker-ce_5%3a29.9.3-1~ubuntu.24.04~noble_amd64.deb",
        "nftables_1.0.9-1ubuntu0.1_amd64.deb",
    ]


def test_what_it_asks_for_is_what_the_installers_package_step_needs() -> None:
    from tools import windows_media as wm

    assert set(wm.NEEDED_PACKAGES) <= set(wd.PACKAGES)  # Docker Engine and the NVIDIA Container Toolkit
    assert not any(wm.is_linux_driver(f"{p}_1_amd64.deb") for p in wd.PACKAGES)


@pytest.mark.parametrize(
    ("os_release", "drop", "says"),
    [
        ('ID=ubuntu\nVERSION_ID="22.04"\n', "", "is ubuntu 22.04; the installer imports Ubuntu 24.04"),
        ('ID=debian\nVERSION_ID="12"\n', "", "is debian 12"),
        (UBUNTU, "dpkg/status", "holds packages for no architecture"),
        ("ARM64", "", "holds packages for arm64; the workstation needs the amd64 image"),
        (UBUNTU, "ubuntu-archive-keyring.gpg", "holds no usr/share/keyrings/ubuntu-archive-keyring.gpg"),
    ],
)
def test_an_image_that_is_not_an_ubuntu_24_04_system_is_refused_before_anything_is_fetched(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch, os_release: str, drop: str, says: str
) -> None:
    apt = Apt(GOOD)
    monkeypatch.setattr(wd, "_apt", apt)
    with pytest.raises(wd.DebsError, match=says.replace(".", r"\.").replace(";", ";")):
        wd.collect(_image(tmp_path / "image.tar.gz", os_release, drop), tmp_path / "debs", tmp_path)
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
    assert len(wd.collect(path, tmp_path / "debs", tmp_path)) == len(GOOD)
    from tools import windows_media as wm

    assert wm.rootfs_name(path) == "ubuntu-24.04." + path.name


def test_a_file_that_is_not_an_archive_is_named(tmp_path: Path, offline: None) -> None:
    bad = tmp_path / "image.tar.gz"
    bad.write_bytes(b"not an archive")
    with pytest.raises(wd.DebsError, match="cannot be read to its end as a .tar.gz archive"):
        wd.collect(bad, tmp_path / "debs", tmp_path)


def test_a_linux_nvidia_driver_in_the_set_stops_it_and_nothing_is_placed(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wd, "_apt", Apt((*GOOD, "nvidia-driver-570_570.1_amd64.deb")))
    with pytest.raises(wd.DebsError, match="nvidia-driver-570_570.1_amd64.deb"):
        wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path)
    assert not (tmp_path / "debs").exists()


def test_nothing_fetched_is_an_error_and_a_folder_that_holds_files_is_not_written_over(
    tmp_path: Path, offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wd, "_apt", Apt(()))
    with pytest.raises(wd.DebsError, match="would fetch no package"):
        wd.collect(_image(tmp_path / "image.tar.gz"), tmp_path / "debs", tmp_path)
    full = tmp_path / "full"
    full.mkdir()
    (full / "old.deb").write_bytes(b"x")
    with pytest.raises(wd.DebsError, match="already holds files"):
        wd.collect(_image(tmp_path / "image2.tar.gz"), full, tmp_path)
    assert [p.name for p in full.iterdir()] == ["old.deb"]


def test_only_the_primary_keys_fingerprint_is_read_from_gpg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Done:
        stdout, returncode = DOCKER_COLONS, 0

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())
    assert wd.fingerprints(tmp_path / "docker.asc") == [wd.KEYS["docker"][1]]


@pytest.mark.parametrize(
    "got", [["0000000000000000000000000000000000000000"], [], ["9DC858229FC7DD38854AE2D88D81803C0EBFCD88", "AAAA"]]
)
def test_a_repository_key_with_another_fingerprint_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, got: list[str]
) -> None:
    asked: list[tuple[str, str]] = []

    def fake_fetch(url: str, out: Path, sha256: str) -> None:
        asked.append((url, sha256))
        out.write_bytes(b"-----BEGIN PGP PUBLIC KEY BLOCK-----")

    monkeypatch.setattr(fetch_pinned, "fetch", fake_fetch)
    monkeypatch.setattr(wd, "fingerprints", lambda _p: got)
    with pytest.raises(wd.DebsError, match="is not the one this tool knows"):
        wd.fetch_key("docker", tmp_path)
    # asked the house way: the https address with the pinned sha256 of the key file
    assert asked == [("https://download.docker.com/linux/ubuntu/gpg", wd.KEYS["docker"][2])]
    monkeypatch.setattr(wd, "fingerprints", lambda _p: [wd.KEYS["docker"][1]])
    assert wd.fetch_key("docker", tmp_path).name == "docker.asc"


def test_a_key_file_that_is_not_the_pinned_one_or_cannot_be_fetched_is_refused_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def other_file(url: str, out: Path, sha256: str) -> None:
        raise fetch_pinned.PinError("sha256 abc, pinned " + sha256)

    monkeypatch.setattr(fetch_pinned, "fetch", other_file)
    with pytest.raises(wd.DebsError, match="is not the file this tool knows"):
        wd.fetch_key("nvidia", tmp_path)

    def no_network(url: str, out: Path, sha256: str) -> None:
        raise fetch_pinned.FetchError("no answer after three tries")

    monkeypatch.setattr(fetch_pinned, "fetch", no_network)
    with pytest.raises(
        wd.DebsError, match="could not be fetched from https://nvidia.github.io/libnvidia-container/gpgkey"
    ):
        wd.fetch_key("nvidia", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_real_fetch_refuses_a_file_with_another_sha256_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through tools/fetch_pinned.py itself, with only its transfer replaced: a changed key file never lands."""
    real = fetch_pinned.fetch
    monkeypatch.setattr(
        fetch_pinned,
        "fetch",
        lambda url, out, sha256: real(url, out, sha256, get=lambda _u: b"not the published key file"),
    )
    with pytest.raises(wd.DebsError, match="is not the file this tool knows"):
        wd.fetch_key("docker", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_every_address_is_https_or_ubuntus_signed_archive_and_the_fingerprints_are_whole() -> None:
    for name, (url, fingerprint, sha256) in wd.KEYS.items():
        assert url.startswith("https://"), name
        assert len(fingerprint) == 40 and set(fingerprint) <= set("0123456789ABCDEF"), name
        assert len(sha256) == 64 and set(sha256) <= set("0123456789abcdef"), name
    text = wd.sources(Path("/k/ubuntu.gpg"), Path("/k/docker.asc"), Path("/k/nvidia.asc"))
    for line in text.splitlines():
        assert "signed-by=/k/" in line, line  # no source without a key of its own
        assert line.split("] ", 1)[1].startswith(
            ("https://", "http://archive.ubuntu.com/", "http://security.ubuntu.com/")
        ), line


def test_an_image_this_user_may_not_read_is_a_message_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    image = _image(tmp_path / "image.tar.gz")

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(wd, "collect", refuse)
    assert wd.main(["--rootfs", str(image), "--out", str(tmp_path / "debs")]) == 1
    assert "Permission denied" in capsys.readouterr().err


def test_the_command_line_names_a_missing_image(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert wd.main(["--rootfs", str(tmp_path / "none.tar.gz"), "--out", str(tmp_path / "debs")]) == 1
    assert "no such file" in capsys.readouterr().err

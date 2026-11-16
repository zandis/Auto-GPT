"""OPS-006 (D-966): the offline media for a bare Ubuntu box, built by ``tools/linux_media.py`` (the Windows media's
builder reused: ``tools/windows_media.py``, ``tools/windows_media_debs.py``) and checked by ``deploy/box-prepare.sh``
before it installs anything. No network and no Docker here: the packages are made-up files and the vendor key is
made in the test's folder."""

from __future__ import annotations

import inspect
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import linux_media, sign_bundle, windows_media_debs

ROOT = Path(__file__).resolve().parents[2]
DEBS = ("docker-ce_5%3a28.5.1-1~ubuntu.24.04~noble_amd64.deb", "docker-compose-plugin_2.40.0-1~ubuntu.24.04~noble_amd64.deb",
        "nvidia-container-toolkit_1.17.8-1_amd64.deb", "nvidia-driver-580-server-open_580.95.05-0ubuntu0.24.04.2_amd64.deb",
        "nftables_1.0.9-1build1_amd64.deb", "cron_3.0pl1-184ubuntu2_amd64.deb")  # fmt: skip


def _inputs(tmp_path: Path) -> dict[str, Path]:
    debs = tmp_path / "debs"
    debs.mkdir(parents=True)
    for name in DEBS:
        (debs / name).write_bytes(name.encode())
    bundle = tmp_path / "trialbox-2026.11-1.tar"
    bundle.write_bytes(b"signed bundle stand-in")
    priv, pub = sign_bundle.keygen(tmp_path / "keys")
    return {"debs": debs, "bundle": bundle, "priv": priv, "pub": pub}


def _build(tmp_path: Path, *, sign: bool = True) -> Path:
    i = _inputs(tmp_path)
    media = linux_media.build(out=tmp_path / "media", version="2026.11-1", bundle=i["bundle"], debs=i["debs"],
                              vendor_pub=i["pub"])  # fmt: skip
    if sign:
        linux_media.sign(media, i["priv"])
    return media


def test_the_package_set_is_the_windows_one_plus_the_hosts_own() -> None:
    """The bare box needs what WSL2 needs, and what WSL2 gets from Windows or the image: the Linux driver (open
    modules, which the Blackwell cards need), the host tools' python3 libraries, and the mDNS responder (D-965)."""
    assert set(windows_media_debs.PACKAGES) < set(linux_media.PACKAGES)
    for need in ("python3-yaml", "python3-cryptography", "avahi-daemon", linux_media.DRIVER):
        assert need in linux_media.PACKAGES, need
    assert linux_media.DRIVER.startswith("nvidia-driver-580") and linux_media.DRIVER.endswith("-open")
    assert "restricted" in linux_media.COMPONENTS.split()  # where Ubuntu keeps the driver


def test_collect_asks_apt_for_the_linux_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The packages come from the Windows media's collector, with the Linux set, the restricted component, and the
    driver allowed in."""
    seen: dict[str, object] = {}

    def fake_collect(rootfs: Path, out: Path, parent: Path, **kw: object) -> list[Path]:
        seen.update(kw, rootfs=rootfs)
        return []

    monkeypatch.setattr(windows_media_debs, "collect", fake_collect)
    linux_media.collect_debs(tmp_path / "rootfs.tar.gz", tmp_path / "out", tmp_path)
    assert seen["packages"] == linux_media.PACKAGES
    assert seen["components"] == linux_media.COMPONENTS
    assert seen["allow_driver"] is True


def test_the_windows_collector_is_unchanged_by_default() -> None:
    """The keywords that let the Linux set carry its driver are off unless asked for: the Windows media is unchanged."""
    sig = inspect.signature(windows_media_debs.collect)
    assert sig.parameters["allow_driver"].default is False
    assert sig.parameters["packages"].default == windows_media_debs.PACKAGES
    keys = (Path("u"), Path("d"), Path("n"))
    assert "restricted" not in windows_media_debs.sources(*keys)
    assert " main universe restricted\n" in windows_media_debs.sources(*keys, components="main universe restricted")


def test_layout_and_sums(tmp_path: Path) -> None:
    media = _build(tmp_path)
    assert media.name == "TRIALBOX-2026.11-1"
    for rel in ("README.txt", "SHA256SUMS", "SHA256SUMS.sig", "linux/box-prepare.sh", "linux/trialbox-host.tar",
                "linux/trialbox-2026.11-1.tar", "linux/trialbox-2026.11-1.tar.sha256", "linux/vendor_ed25519.pub",
                *(f"linux/debs/{d}" for d in DEBS)):  # fmt: skip
        assert (media / rel).is_file(), rel
    assert os.access(media / "linux/box-prepare.sh", os.X_OK)
    assert b"\r\n" not in (media / "linux/box-prepare.sh").read_bytes()
    assert not (media / "windows").exists()
    assert (
        subprocess.run(["sha256sum", "--quiet", "--strict", "-c", "SHA256SUMS"], cwd=media, check=False).returncode == 0
    )
    assert linux_media.check(media) == []
    assert "box-prepare.sh" in (media / "README.txt").read_text(encoding="utf-8")


def test_the_signature_is_one_openssl_checks(tmp_path: Path) -> None:
    """The bare box has openssl and not yet python3-cryptography: the box checks the signature with openssl."""
    media = _build(tmp_path)
    r = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", "linux/vendor_ed25519.pub", "-rawin",
                        "-in", "SHA256SUMS", "-sigfile", "SHA256SUMS.sig"], cwd=media, capture_output=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize(
    ("missing", "says"),
    [
        ("docker-ce", "Docker Engine"),
        ("nvidia-container-toolkit", "Container Toolkit"),
        ("nvidia-driver-580-server-open", "NVIDIA driver"),
    ],
)
def test_a_set_without_a_needed_package_is_refused(tmp_path: Path, missing: str, says: str) -> None:
    i = _inputs(tmp_path)
    for p in i["debs"].glob(f"{missing}_*.deb"):
        p.unlink()
    with pytest.raises(linux_media.MediaError, match=says):
        linux_media.build(out=tmp_path / "media", version="2026.11-1", bundle=i["bundle"], debs=i["debs"],
                          vendor_pub=i["pub"])  # fmt: skip
    assert not (tmp_path / "media/TRIALBOX-2026.11-1").exists()
    assert not (tmp_path / "media/TRIALBOX-2026.11-1.part").exists()


def test_a_full_folder_is_not_overwritten(tmp_path: Path) -> None:
    media = _build(tmp_path)
    i = _inputs(tmp_path / "again")
    with pytest.raises(linux_media.MediaError, match="already holds files"):
        linux_media.build(out=media.parent, version="2026.11-1", bundle=i["bundle"], debs=i["debs"],
                          vendor_pub=i["pub"])  # fmt: skip


def test_check_names_a_changed_byte_and_a_missing_signature(tmp_path: Path) -> None:
    media = _build(tmp_path, sign=False)
    assert any("SHA256SUMS.sig" in p for p in linux_media.check(media))
    (media / "linux/debs" / DEBS[4]).write_bytes(b"changed")
    assert any("nftables" in p for p in linux_media.check(media))


def test_sign_refuses_a_media_that_fails_its_check(tmp_path: Path) -> None:
    i = _inputs(tmp_path)
    media = linux_media.build(out=tmp_path / "media", version="2026.11-1", bundle=i["bundle"], debs=i["debs"],
                              vendor_pub=i["pub"])  # fmt: skip
    (media / "linux/debs" / DEBS[0]).write_bytes(b"changed")
    with pytest.raises(linux_media.MediaError, match="docker-ce"):
        linux_media.sign(media, i["priv"])
    assert not (media / "SHA256SUMS.sig").exists()


def test_sign_refuses_a_key_that_is_not_the_medias(tmp_path: Path) -> None:
    media = _build(tmp_path, sign=False)
    other = sign_bundle.keygen(tmp_path / "other")[0]
    with pytest.raises(linux_media.MediaError, match="vendor_ed25519.pub"):
        linux_media.sign(media, other)
    assert not (media / "SHA256SUMS.sig").exists()


def test_cli_build_check_sign(tmp_path: Path) -> None:
    i = _inputs(tmp_path)
    out = tmp_path / "media"
    assert linux_media.main(["build", "--out", str(out), "--version", "2026.11-1", "--bundle", str(i["bundle"]),
                             "--debs", str(i["debs"]), "--vendor-pub", str(i["pub"])]) == 0  # fmt: skip
    media = out / "TRIALBOX-2026.11-1"
    assert linux_media.main(["check", str(media)]) == 1  # not signed yet
    assert linux_media.main(["sign", str(media), "--key", str(i["priv"])]) == 0
    assert linux_media.main(["check", str(media)]) == 0


def test_make_target() -> None:
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\nmedia-linux:" in mk and "tools.linux_media build" in mk


# -------------------------------------------------------------------------------------------- box-prepare.sh


def _prepare_env(tmp_path: Path, *, os_id: str = "ubuntu", ver: str = "24.04", gpu: bool = True,
                 smi_ok: bool = False) -> tuple[dict[str, str], Path]:  # fmt: skip
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls.log"
    for name in ("dpkg", "systemctl", "nvidia-ctk"):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {calls}\n', encoding="utf-8")
    (stubs / "nvidia-smi").write_text(f"#!/bin/sh\nexit {0 if smi_ok else 9}\n", encoding="utf-8")
    (stubs / "docker").write_text(
        f'#!/bin/sh\necho "docker $*" >> {calls}\ncase "$1" in info) grep -q nvidia-ctk {calls} && echo "runc nvidia" || echo runc ;;'
        " version) echo 26.1.3 ;; esac\n",
        encoding="utf-8",
    )
    for f in stubs.iterdir():
        f.chmod(0o755)
    osr = tmp_path / "os-release"
    osr.write_text(f'ID={os_id}\nVERSION_ID="{ver}"\n', encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "TB_PREPARE_NO_ROOT": "1",
        "TB_PREPARE_OS_RELEASE": str(osr),
        "TB_PREPARE_GPU": "1" if gpu else "0",
        "TB_PREPARE_ROOT": str(tmp_path / "opt-trialbox"),
    }
    return env, calls


def _prepare(media: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(media / "linux/box-prepare.sh"), str(media), *args], env=env, check=False,
                          capture_output=True, text=True, timeout=120)  # fmt: skip


def _pub(media: Path) -> tuple[str, str]:
    return ("--pub", str(media / "linux/vendor_ed25519.pub"))


def test_prepare_installs_from_the_media(tmp_path: Path) -> None:
    media = _build(tmp_path)
    env, calls = _prepare_env(tmp_path)
    r = _prepare(media, env, *_pub(media))
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls.read_text(encoding="utf-8")
    assert "dpkg -i --skip-same-version" in log
    for deb in DEBS:
        assert deb in log, deb
    assert "systemctl enable docker" in log
    assert "nvidia-ctk runtime configure --runtime=docker" in log
    root = tmp_path / "opt-trialbox"
    assert (root / "deploy/box-install.sh").is_file()
    assert (root / "deploy/keys/vendor_ed25519.pub").read_bytes() == (media / "linux/vendor_ed25519.pub").read_bytes()
    assert "reboot" in r.stdout  # the driver loads after a restart
    assert f"{root}/deploy/box-install.sh {media}/linux/trialbox-2026.11-1.tar" in r.stdout


def test_prepare_again_keeps_the_host_tree(tmp_path: Path) -> None:
    media = _build(tmp_path)
    env, _ = _prepare_env(tmp_path, smi_ok=True)
    assert _prepare(media, env, *_pub(media)).returncode == 0
    marker = tmp_path / "opt-trialbox/deploy/site-file"
    marker.write_text("kept", encoding="utf-8")
    r = _prepare(media, env, *_pub(media))
    assert r.returncode == 0, r.stderr
    assert "kept:" in r.stdout and marker.read_text(encoding="utf-8") == "kept"
    assert "reboot" not in r.stdout  # the driver answers


def test_prepare_without_a_gpu_skips_the_toolkit(tmp_path: Path) -> None:
    media = _build(tmp_path)
    env, calls = _prepare_env(tmp_path, gpu=False)
    r = _prepare(media, env, *_pub(media))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nvidia-ctk" not in calls.read_text(encoding="utf-8")


@pytest.mark.parametrize(("os_id", "ver"), [("ubuntu", "22.04"), ("debian", "12")])
def test_prepare_refuses_another_system(tmp_path: Path, os_id: str, ver: str) -> None:
    media = _build(tmp_path)
    env, calls = _prepare_env(tmp_path, os_id=os_id, ver=ver)
    r = _prepare(media, env, *_pub(media))
    assert r.returncode != 0 and "Ubuntu 24.04" in r.stderr
    assert not calls.exists()


def test_prepare_refuses_a_changed_byte(tmp_path: Path) -> None:
    media = _build(tmp_path)
    (media / "linux/debs" / DEBS[5]).write_bytes(b"changed")
    env, calls = _prepare_env(tmp_path)
    r = _prepare(media, env, *_pub(media))
    assert r.returncode != 0 and DEBS[5] in r.stdout + r.stderr
    assert not calls.exists()


def test_prepare_refuses_an_unlisted_package(tmp_path: Path) -> None:
    """A package added to the disk after it was signed would be installed by the glob: refused."""
    media = _build(tmp_path)
    (media / "linux/debs/extra_1_amd64.deb").write_bytes(b"extra")
    env, calls = _prepare_env(tmp_path)
    r = _prepare(media, env, *_pub(media))
    assert r.returncode != 0 and "extra_1_amd64.deb" in r.stderr
    assert not calls.exists()


def test_prepare_refuses_a_key_other_than_the_one_given_out_of_band(tmp_path: Path) -> None:
    media = _build(tmp_path)
    other = sign_bundle.keygen(tmp_path / "other")[1]
    env, calls = _prepare_env(tmp_path)
    r = _prepare(media, env, "--pub", str(other))
    assert r.returncode != 0 and "vendor key" in r.stderr
    assert not calls.exists()


def test_prepare_refuses_a_bad_signature(tmp_path: Path) -> None:
    media = _build(tmp_path)
    sums = media / "SHA256SUMS"
    sums.write_text(sums.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    env, calls = _prepare_env(tmp_path)
    r = _prepare(media, env, *_pub(media))
    assert r.returncode != 0 and "signature" in r.stderr
    assert not calls.exists()


def test_prepare_needs_the_key_given_out_of_band(tmp_path: Path) -> None:
    media = _build(tmp_path)
    env, calls = _prepare_env(tmp_path)
    r = _prepare(media, env)
    assert r.returncode == 2 and "--pub" in r.stderr
    assert not calls.exists()


def test_prepare_never_unpacks_over_a_folder_that_is_not_a_host_tree(tmp_path: Path) -> None:
    media = _build(tmp_path)
    env, _ = _prepare_env(tmp_path)
    (tmp_path / "opt-trialbox").mkdir()
    (tmp_path / "opt-trialbox/other").write_text("x", encoding="utf-8")
    r = _prepare(media, env, *_pub(media))
    assert r.returncode != 0 and "not a TrialBox host tree" in r.stderr


def test_box_install_says_where_docker_comes_from(tmp_path: Path) -> None:
    """Without Docker, box-install.sh points at the media's prepare step instead of failing on `docker run`."""
    bare = tmp_path / "bin"  # a PATH with the shell's basic tools and no docker
    bare.mkdir()
    for tool in ("python3", "dirname", "mkdir", "chmod", "chown", "id", "sed", "cat", "printf"):
        found = shutil.which(tool)
        assert found, tool
        (bare / tool).symlink_to(found)
    r = subprocess.run([shutil.which("bash") or "/bin/bash", str(ROOT / "deploy/box-install.sh"), "x.tar"], check=False, capture_output=True, text=True,
                       env={"PATH": str(bare), "TB_BOX_NO_ROOT": "1", "TB_FIRSTRUN_HOST_DIR": str(tmp_path / "fr"),
                            "HOME": str(tmp_path)}, timeout=30)  # fmt: skip
    assert r.returncode != 0 and "box-prepare.sh" in r.stderr

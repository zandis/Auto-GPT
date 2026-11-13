"""Collect the Ubuntu packages of the Windows offline media (NEW-WIN-9, D-609; ``docs/handover/OFFLINE-MEDIA.md``).

    python3 -m tools.windows_media_debs --rootfs ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz --out debs/

The Windows installer installs Docker Engine and the NVIDIA Container Toolkit inside WSL2 from the media's
``linux/debs`` with ``dpkg -i``: every package they need that the Ubuntu WSL image does not already hold must be
there, and nothing may be missing, because the workstation is never online. This tool works that set out against
the image itself: it reads the image's own list of installed packages (``var/lib/dpkg/status`` inside the tarball)
and asks ``apt-get`` what installing ``PACKAGES`` on exactly that system would fetch. apt works in a folder of its
own (``--work``, else a temporary one): this machine's packages are neither read nor changed, no container is
needed, and it does not need root.

This is the one media tool that goes online, and only when the vendor runs it, on a machine that may: it fetches
the package lists and the packages from Ubuntu's archive, Docker's repository and NVIDIA's, into the folder the
vendor names (never into the repository). The two repository keys are fetched too and are accepted only when their
fingerprints are the ones written here (``KEYS``); Ubuntu's archive key is the image's own.

Needs ``apt-get`` and ``gpg`` on this machine (any Debian or Ubuntu). ``tools.windows_media build --debs`` then
refuses the set if a Linux NVIDIA driver slipped in or Docker or the toolkit is missing.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from tools import windows_media

# what the Windows installer's package step needs (deploy/windows/wsl-setup.sh: docker, nvidia-ctk) and what the
# box's host side uses (deploy/egress.py: nft; the backup schedule: cron)
PACKAGES = ("docker-ce", "docker-ce-cli", "containerd.io", "docker-compose-plugin", "nvidia-container-toolkit",
            "nftables", "cron")  # fmt: skip
SUITE = "noble"  # Ubuntu 24.04, the release the installer imports
UBUNTU_KEYRING = "usr/share/keyrings/ubuntu-archive-keyring.gpg"
STATUS = "var/lib/dpkg/status"
OS_RELEASE = "etc/os-release"
# repository, the key's address, the fingerprint of its primary key (published by Docker and by NVIDIA)
KEYS = {
    "docker": ("https://download.docker.com/linux/ubuntu/gpg", "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"),
    "nvidia": ("https://nvidia.github.io/libnvidia-container/gpgkey", "C95B321B61E88C1809C4F759DDCAE044F796ECB0"),
}
TIMEOUT_S = 60


class DebsError(Exception):
    """The set of packages could not be worked out or fetched."""


def read_image(rootfs: Path, into: Path) -> dict[str, Path]:
    """The three files of the image apt needs, copied under ``into``. Refuses an image that is not Ubuntu 24.04."""
    wanted = {STATUS, UBUNTU_KEYRING, OS_RELEASE}
    found: dict[str, Path] = {}
    # in Canonical's image etc/os-release is a link to usr/lib/os-release: the file is read where it is
    names = {
        STATUS: STATUS,
        UBUNTU_KEYRING: UBUNTU_KEYRING,
        **dict.fromkeys(windows_media.OS_RELEASE_FILES, OS_RELEASE),
    }
    try:
        with tarfile.open(rootfs, "r:*") as tar:
            for member in tar:
                name = names.get(member.name.removeprefix("./"), "")
                if name and name not in found and member.isfile():
                    data = tar.extractfile(member)
                    if data is None:
                        continue
                    dst = into / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(data.read())
                    found[name] = dst
                    if len(found) == len(wanted):
                        break
    except (OSError, tarfile.TarError) as exc:
        raise DebsError(f"--rootfs: {rootfs} cannot be read as a tar archive ({exc})") from exc
    missing = sorted(wanted - set(found))
    if missing:
        raise DebsError(f"--rootfs: {rootfs.name} holds no {', '.join(missing)}: not an Ubuntu root file system")
    release = windows_media.os_release(found[OS_RELEASE].read_text(encoding="utf-8", errors="replace"))
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise DebsError(f"--rootfs: {rootfs.name} is {release.get('ID', '?')} {release.get('VERSION_ID', '?')}; "
                        "the installer imports Ubuntu 24.04")  # fmt: skip
    return found


def fingerprints(key_file: Path) -> list[str]:
    """The fingerprints of the primary keys in a key file, as gpg reads them (nothing is imported anywhere)."""
    try:
        out = subprocess.run(
            ["gpg", "--show-keys", "--with-colons", str(key_file)],
            capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError) as exc:
        raise DebsError(f"gpg could not read {key_file.name}: {exc}") from exc
    prints, after_pub = [], False
    for line in out.stdout.splitlines():
        fields = line.split(":")
        if fields[0] in ("pub", "sub"):
            after_pub = fields[0] == "pub"
        elif fields[0] == "fpr" and after_pub and len(fields) > 9:
            prints.append(fields[9])
            after_pub = False
    return prints


def fetch_key(name: str, into: Path) -> Path:
    url, want = KEYS[name]
    dst = into / f"{name}.asc"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:  # a fixed https address, above
            dst.write_bytes(resp.read())
    except OSError as exc:
        raise DebsError(f"the {name} repository key could not be fetched from {url}: {exc}") from exc
    got = fingerprints(dst)
    if got != [want]:
        raise DebsError(f"the {name} repository key at {url} is not the one this tool knows: fingerprint "
                        f"{', '.join(got) or 'none'}, expected {want}. Nothing was fetched with it")  # fmt: skip
    return dst


def sources(ubuntu_key: Path, docker_key: Path, nvidia_key: Path) -> str:
    lines = [
        f"deb [arch=amd64 signed-by={ubuntu_key}] http://archive.ubuntu.com/ubuntu {SUITE} main universe",
        f"deb [arch=amd64 signed-by={ubuntu_key}] http://archive.ubuntu.com/ubuntu {SUITE}-updates main universe",
        f"deb [arch=amd64 signed-by={ubuntu_key}] http://security.ubuntu.com/ubuntu {SUITE}-security main universe",
        f"deb [arch=amd64 signed-by={docker_key}] https://download.docker.com/linux/ubuntu {SUITE} stable",
        f"deb [signed-by={nvidia_key}] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /",
    ]
    return "\n".join(lines) + "\n"


def apt_options(work: Path, status: Path) -> list[str]:
    """apt in a world of its own: the image's package state, its own lists and cache, none of this machine's."""
    etc = work / "etc"
    pairs = {
        "Dir::State": work / "state",
        "Dir::State::status": status,
        "Dir::Cache": work / "cache",
        "Dir::Etc": etc,
        "Dir::Etc::sourcelist": etc / "sources.list",
        "Dir::Etc::sourceparts": etc / "sources.list.d",
        "Dir::Etc::preferencesparts": etc / "preferences.d",
        "Dir::Etc::trustedparts": etc / "trusted.gpg.d",
        "Dir::Etc::parts": etc / "apt.conf.d",
        "APT::Architecture": "amd64",
        "APT::Architectures": "amd64",
        "APT::Sandbox::User": "root",  # apt's own download user cannot read a folder of ours
        "Debug::NoLocking": "1",
        "APT::Get::List-Cleanup": "0",
    }
    out: list[str] = []
    for key, value in pairs.items():
        out += ["-o", f"{key}={value}"]
    return out


def _apt(args: list[str], what: str) -> str:
    try:
        run = subprocess.run(["apt-get", *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        raise DebsError(f"apt-get is not on this machine ({exc}): run this on Debian or Ubuntu") from exc
    if run.returncode != 0:
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-12:])
        raise DebsError(f"apt-get {what} failed:\n{tail}")
    return run.stdout


def collect(rootfs: Path, out: Path, work: Path) -> list[Path]:
    if out.exists() and any(out.iterdir()):
        raise DebsError(f"{out} already holds files: name an empty folder (nothing is overwritten)")
    for tool in ("apt-get", "gpg"):
        if shutil.which(tool) is None:
            raise DebsError(f"{tool} is not on this machine: run this on Debian or Ubuntu")
    image = read_image(rootfs, work / "image")
    for d in ("state/lists/partial", "cache/archives/partial", "etc/sources.list.d", "etc/preferences.d",
              "etc/trusted.gpg.d", "etc/apt.conf.d", "keys"):  # fmt: skip
        (work / d).mkdir(parents=True, exist_ok=True)
    keys = {name: fetch_key(name, work / "keys") for name in KEYS}
    (work / "etc/sources.list").write_text(
        sources(image[UBUNTU_KEYRING], keys["docker"], keys["nvidia"]), encoding="utf-8"
    )
    opts = apt_options(work, image[STATUS])
    _apt([*opts, "update"], "update")
    _apt([*opts, "install", "--download-only", "-y", "--no-install-recommends", *PACKAGES], "install --download-only")
    fetched = sorted((work / "cache/archives").glob("*.deb"))
    if not fetched:
        raise DebsError("apt-get fetched no package: the image already holds every one of them, or the lists are empty")
    drivers = [p.name for p in fetched if windows_media.is_linux_driver(p.name)]
    if drivers:
        raise DebsError(
            "the set holds a Linux NVIDIA driver package, which is never installed in WSL2: " + ", ".join(drivers)
        )
    out.mkdir(parents=True, exist_ok=True)
    placed = []
    for p in fetched:
        shutil.copy2(p, out / p.name)
        placed.append(out / p.name)
    return placed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.windows_media_debs", description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--rootfs", type=Path, required=True, help="the Ubuntu 24.04 WSL image the media will carry")
    ap.add_argument(
        "--out", type=Path, required=True, help="an empty folder for the .deb packages (the media's --debs)"
    )
    ap.add_argument("--work", type=Path, help="apt's own folder (lists, cache); default: a temporary one, removed")
    args = ap.parse_args(argv)
    try:
        if not args.rootfs.is_file():
            raise DebsError(f"--rootfs: no such file: {args.rootfs}")
        if args.work is not None:
            args.work.mkdir(parents=True, exist_ok=True)
            placed = collect(args.rootfs, args.out, args.work.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="tb-media-debs-") as tmp:
                placed = collect(args.rootfs, args.out, Path(tmp))
    except DebsError as exc:
        print(f"windows_media_debs: {exc}", file=sys.stderr)
        return 1
    size = sum(p.stat().st_size for p in placed)
    for p in placed:
        print(p.name)
    print(f"{len(placed)} packages, {size / 1e6:.0f} MB, in {args.out}: give it to tools.windows_media build --debs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

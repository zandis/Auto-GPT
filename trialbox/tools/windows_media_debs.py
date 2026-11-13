"""Collect the Ubuntu packages of the Windows offline media (NEW-WIN-9, D-609; ``docs/handover/OFFLINE-MEDIA.md``).

    python3 -m tools.windows_media_debs --rootfs ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz --out debs/

The Windows installer installs Docker Engine and the NVIDIA Container Toolkit inside WSL2 from the media's
``linux/debs`` with ``dpkg -i``: every package they need that the Ubuntu WSL image does not already hold must be
there, and nothing may be missing, because the workstation is never online. This tool works that set out against
the image itself: it reads the image's own list of installed packages (``var/lib/dpkg/status`` inside the tarball)
and asks ``apt-get`` what installing ``PACKAGES`` on exactly that system would fetch. apt works in a folder made
new for each run, with a configuration of its own (``APT_CONFIG``): this machine's packages and apt settings are
neither read nor changed, no container is needed, and it does not need root (run it as an ordinary user). Only
the files apt named for this run go to the output.

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
# repository, the key's address, the fingerprint of its primary key (published by Docker and by NVIDIA)
KEYS = {
    "docker": ("https://download.docker.com/linux/ubuntu/gpg", "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"),
    "nvidia": ("https://nvidia.github.io/libnvidia-container/gpgkey", "C95B321B61E88C1809C4F759DDCAE044F796ECB0"),
}
TIMEOUT_S = 60


class DebsError(Exception):
    """The set of packages could not be worked out or fetched."""


def read_image(rootfs: Path, into: Path) -> dict[str, Path]:
    """The two files of the image apt needs, copied under ``into`` (fixed names; a member's own name is never used
    as a path). Refuses an image that is not a whole Ubuntu 24.04 system for amd64 (``windows_media.rootfs_name``)."""
    try:
        windows_media.rootfs_name(rootfs)
    except windows_media.MediaError as exc:
        raise DebsError(str(exc)) from exc
    wanted = {STATUS, UBUNTU_KEYRING}
    found: dict[str, Path] = {}
    try:
        with tarfile.open(rootfs, "r:gz") as tar:
            for member in tar:
                name = member.name.removeprefix("./")
                if name in wanted and name not in found and member.isfile():
                    data = tar.extractfile(member)
                    if data is None:
                        continue
                    dst = into / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(data.read())
                    found[name] = dst
                    if len(found) == len(wanted):
                        break
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise DebsError(f"--rootfs: {rootfs} cannot be read as a tar archive ({exc})") from exc
    missing = sorted(wanted - set(found))
    if missing:
        raise DebsError(f"--rootfs: {rootfs.name} holds no {', '.join(missing)}: not an Ubuntu root file system")
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


def apt_config(work: Path, status: Path) -> str:
    """apt's whole configuration for this run, as the text of the file ``APT_CONFIG`` names.

    It must come by that file and not by ``-o`` options: apt reads the machine's ``/etc/apt/apt.conf.d`` before it
    looks at its command line, so options given there come too late to keep the machine's own settings (a hook,
    "allow unauthenticated", a default release) out. With ``Dir::Etc`` set here, apt reads nothing of the
    machine's: its state, lists, cache, sources, preferences and trusted keys are all under ``work``, which
    ``collect`` makes new for each run."""
    etc = work / "etc"
    pairs = {
        "Dir::State": work / "state",
        "Dir::State::status": status,
        "Dir::Cache": work / "cache",
        "Dir::Etc": etc,
        "Dir::Etc::main": "apt.conf",
        "Dir::Etc::parts": etc / "apt.conf.d",
        "Dir::Etc::sourcelist": etc / "sources.list",
        "Dir::Etc::sourceparts": etc / "sources.list.d",
        "Dir::Etc::preferences": etc / "preferences",
        "Dir::Etc::preferencesparts": etc / "preferences.d",
        "Dir::Etc::trusted": etc / "trusted.gpg",
        "Dir::Etc::trustedparts": etc / "trusted.gpg.d",
        "Dir::Etc::netrc": etc / "auth.conf",
        "Dir::Etc::netrcparts": etc / "auth.conf.d",
        "APT::Architecture": "amd64",
        "APT::Architectures": "amd64",
        "APT::Get::AllowUnauthenticated": "false",
        "Acquire::AllowInsecureRepositories": "false",
        "Acquire::AllowDowngradeToInsecureRepositories": "false",
        "APT::Sandbox::User": "root",  # as root, apt's download user could not read a folder of ours
        "Debug::NoLocking": "1",
        "APT::Get::List-Cleanup": "0",
    }
    return "".join(f'{key} "{value}";\n' for key, value in pairs.items())


PROXY_VARS = ("http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")


def apt_env(config_file: Path) -> dict[str, str]:
    """The environment apt runs in: its configuration file, a plain PATH, and the machine's proxy if it has one
    (a vendor's network may need it; the packages are checked by signature whatever carries them)."""
    import os

    env = {
        "APT_CONFIG": str(config_file),
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LC_ALL": "C",
        "HOME": str(config_file.parent),
    }
    env.update({k: v for k, v in os.environ.items() if k in PROXY_VARS})
    return env


def _apt(args: list[str], what: str, env: dict[str, str]) -> str:
    try:
        run = subprocess.run(["apt-get", *args], capture_output=True, text=True, check=False, env=env)
    except OSError as exc:
        raise DebsError(f"apt-get is not on this machine ({exc}): run this on Debian or Ubuntu") from exc
    if run.returncode != 0:
        tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-12:])
        raise DebsError(f"apt-get {what} failed:\n{tail}")
    return run.stdout


def wanted_files(print_uris: str) -> list[str]:
    """The file names apt says it would fetch (``apt-get install --print-uris``: ``'<uri>' <file> <size> <hash>``)."""
    names = []
    for line in print_uris.splitlines():
        if line.startswith("'"):
            fields = line.split()
            if len(fields) >= 2 and fields[1].endswith(".deb") and "/" not in fields[1]:
                names.append(fields[1])
    return names


def collect(rootfs: Path, out: Path, parent: Path) -> list[Path]:
    """``parent``: where this run's working folder is made. The folder is always new: nothing an earlier run, or
    anyone else, left behind (a list, a source, a key, a package) can reach apt or the output."""
    if out.exists() and any(out.iterdir()):
        raise DebsError(f"{out} already holds files: name an empty folder (nothing is overwritten)")
    for tool in ("apt-get", "gpg"):
        if shutil.which(tool) is None:
            raise DebsError(f"{tool} is not on this machine: run this on Debian or Ubuntu")
    work = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    try:
        image = read_image(rootfs, work / "image")
        for d in ("state/lists/partial", "cache/archives/partial", "etc/sources.list.d", "etc/preferences.d",
                  "etc/trusted.gpg.d", "etc/apt.conf.d", "etc/auth.conf.d", "keys"):  # fmt: skip
            (work / d).mkdir(parents=True, exist_ok=True)
        keys = {name: fetch_key(name, work / "keys") for name in KEYS}
        (work / "etc/sources.list").write_text(
            sources(image[UBUNTU_KEYRING], keys["docker"], keys["nvidia"]), encoding="utf-8"
        )
        (work / "etc/apt.conf").write_text(apt_config(work, image[STATUS]), encoding="utf-8")
        env = apt_env(work / "etc/apt.conf")
        install = ["install", "-y", "--no-install-recommends", *PACKAGES]
        _apt(["update"], "update", env)
        wanted = wanted_files(_apt([*install, "--print-uris"], "install --print-uris", env))
        if not wanted:
            raise DebsError("apt-get would fetch no package: the image already holds every one of them")
        _apt([*install, "--download-only"], "install --download-only", env)
        # only what apt said it would fetch, each one fetched (and so checked against the signed lists) in this run
        fetched = [work / "cache/archives" / name for name in sorted(wanted)]
        lacking = [p.name for p in fetched if not p.is_file()]
        if lacking:
            raise DebsError("apt-get did not fetch: " + ", ".join(lacking))
        drivers = [p.name for p in fetched if windows_media.is_linux_driver(p.name)]
        if drivers:
            raise DebsError("the set holds a Linux NVIDIA driver package, which is never installed in WSL2: "
                            + ", ".join(drivers))  # fmt: skip
        out.mkdir(parents=True, exist_ok=True)
        placed = []
        for p in fetched:
            shutil.copy2(p, out / p.name)
            placed.append(out / p.name)
        return placed
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.windows_media_debs", description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--rootfs", type=Path, required=True, help="the Ubuntu 24.04 WSL image the media will carry")
    ap.add_argument(
        "--out", type=Path, required=True, help="an empty folder for the .deb packages (the media's --debs)"
    )
    ap.add_argument("--work", type=Path, help="where this run's working folder is made (new each run, removed after)")
    args = ap.parse_args(argv)
    try:
        if not args.rootfs.is_file():
            raise DebsError(f"--rootfs: no such file: {args.rootfs}")
        parent = args.work.resolve() if args.work is not None else Path(tempfile.gettempdir())
        parent.mkdir(parents=True, exist_ok=True)
        placed = collect(args.rootfs, args.out, parent)
    except (DebsError, OSError) as exc:
        print(f"windows_media_debs: {exc}", file=sys.stderr)
        return 1
    size = sum(p.stat().st_size for p in placed)
    for p in placed:
        print(p.name)
    print(f"{len(placed)} packages, {size / 1e6:.0f} MB, in {args.out}: give it to tools.windows_media build --debs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

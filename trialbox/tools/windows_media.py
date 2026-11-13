"""The offline media for a Windows workstation (NEW-WIN-9, D-605; ``docs/handover/OFFLINE-MEDIA.md``).

    python3 -m tools.windows_media build --out DIR --version 1.0.0 --bundle trialbox-1.0.0.tar \\
        --wsl-msi wsl.2.x.y.0.x64.msi --rootfs ubuntu-24.04-wsl-amd64.tar.gz --debs DEBS_DIR \\
        --vendor-pub vendor_ed25519.pub [--nvidia-driver DRIVER.exe] [--measured DIR] [--link]
    python3 -m tools.windows_media check DIR/TRIALBOX-1.0.0
    python3 -m tools.windows_media sums DIR/TRIALBOX-1.0.0      # after a file was added: list again, then check

``build`` lays out ``DIR/TRIALBOX-<version>/`` as ``deploy/windows/box-install.ps1`` reads it: the launcher and the
installer's own files from this source tree, the release's host tree (``tools.host_tree.pack``), and the files the
vendor brings (the signed bundle, the WSL package, the Ubuntu image, the packages for Ubuntu, the vendor's public
key, the Windows NVIDIA driver). It writes ``SHA256SUMS`` over every file. Nothing is downloaded: each input is a
path the caller names. ``check`` reads a media back the way step 1 of the installer does (the files it needs are
there, each exactly once where it wants one, each listed and matching), so a media is checked before it leaves.
``build`` works in ``TRIALBOX-<version>.part`` and moves it into place only when ``check`` passes.

What it refuses: a missing input; a package of a Linux NVIDIA driver among the packages (WSL2 uses the Windows
driver; the installer would refuse the media); an output folder that already holds something. What it does not do:
it does not sign ``SHA256SUMS`` (the vendor key is not on a build machine; ``SHA256SUMS.sig`` is added by the
release's signing step), and it does not check the bundle's own signature (``deploy/install.sh`` does, on the box).
Standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "deploy" / "windows"
# the installer's own files: the launcher at the media's root, the rest under windows/
LAUNCHER = "Install-TrialBox.cmd"
INSTALLER_FILES = (
    "box-install.ps1",
    "box-install.messages.json",
    "wsl-setup.sh",
    "register_keepalive.ps1",
    "key-probe.ps1",
    "preflight.ps1",
    "host_facts.ps1",
)
# what step 1 of box-install.ps1 looks for (Find-TbOne: exactly one match each); a test holds the two together
NEEDS_ONE = {
    "windows/wsl": ("wsl.*.msi", "ubuntu-24.04*.tar.gz"),
    "windows": ("wsl-setup.sh", "register_keepalive.ps1"),
    "linux": ("trialbox-host.tar", "vendor_ed25519.pub"),
}
BUNDLE_PATTERN, HOST_TAR = "trialbox-*.tar", "trialbox-host.tar"
# a package of a Linux NVIDIA driver: every NVIDIA package unless it is the container toolkit's own
# (the same two expressions as deploy/windows/wsl-setup.sh; a test holds them together)
DRIVER_RE = re.compile(
    r"^(nvidia-|libnvidia-|linux-modules-nvidia-|linux-objects-nvidia-|linux-signatures-nvidia-"
    r"|xserver-xorg-video-nvidia|cuda-drivers)"
)
TOOLKIT_RE = re.compile(
    r"^(nvidia-container-toolkit|nvidia-container-toolkit-base|nvidia-container-runtime|nvidia-docker2"
    r"|libnvidia-container1|libnvidia-container-tools)$"
)
# the package step of wsl-setup.sh stops without these two commands (docker, nvidia-ctk)
NEEDED_PACKAGES = {"docker-ce": "Docker Engine", "nvidia-container-toolkit": "the NVIDIA Container Toolkit"}
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
SUMS = "SHA256SUMS"
OK_LINE = (
    "ok: nothing here would stop the installer's step 1 (Microsoft's signature on the WSL package is not checked here)"
)
CHUNK = 1 << 20


class MediaError(Exception):
    """The media cannot be built, or is not one the installer would take."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def is_linux_driver(deb_name: str) -> bool:
    package = deb_name.split("_", 1)[0]
    return bool(DRIVER_RE.match(package)) and not TOOLKIT_RE.match(package)


def _put(src: Path, dst: Path, link: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if link:
        try:
            os.link(os.path.realpath(src), dst)
            return
        except OSError:
            pass  # another file system: copy
    shutil.copy2(src, dst)


def _text(src: Path, dst: Path, newline: str) -> None:
    """A script with the line ends its reader needs, whatever the checkout has (cmd.exe: CRLF; bash: LF)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    dst.write_bytes(text.replace("\n", newline).encode("utf-8"))


def _match(folder: Path, pattern: str) -> list[Path]:
    """Files of a folder by a pattern, upper and lower case alike: as ``Get-ChildItem -Filter`` on Windows."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and fnmatch.fnmatchcase(p.name.lower(), pattern.lower()))


def _missing_packages(names: list[str]) -> list[str]:
    have = {n.split("_", 1)[0].lower() for n in names}
    return [f"{what} ({package}_*.deb)" for package, what in NEEDED_PACKAGES.items() if package not in have]


def _files(media: Path) -> list[Path]:
    return sorted(p for p in media.rglob("*") if p.is_file() and p.name not in (SUMS, SUMS + ".sig", SUMS + ".part"))


def write_sums(media: Path) -> int:
    lines = [f"{sha256(p)}  {p.relative_to(media).as_posix()}" for p in _files(media)]
    part = media / (SUMS + ".part")  # never through a link named SHA256SUMS
    if part.is_symlink() or part.exists():
        part.unlink()
    part.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(part, media / SUMS)
    return len(lines)


def build(
    *,
    out: Path,
    version: str,
    bundle: Path,
    wsl_msi: Path,
    rootfs: Path,
    debs: Path,
    vendor_pub: Path,
    nvidia_driver: Path | None = None,
    measured: Path | None = None,
    link: bool = False,
    source: Path = ROOT,
) -> Path:
    if not VERSION_RE.match(version):
        raise MediaError(f"version '{version}': letters, digits, dot, dash and underscore only")
    inputs = {"--bundle": bundle, "--wsl-msi": wsl_msi, "--rootfs": rootfs, "--vendor-pub": vendor_pub}
    if nvidia_driver is not None:
        inputs["--nvidia-driver"] = nvidia_driver
    for flag, path in inputs.items():
        if not path.is_file():
            raise MediaError(f"{flag}: no such file: {path}")
    if not fnmatch.fnmatch(wsl_msi.name, "wsl.*.msi"):
        raise MediaError(
            f"--wsl-msi: '{wsl_msi.name}' is not named wsl.<version>.x64.msi (the installer looks for wsl.*.msi)"
        )
    if not fnmatch.fnmatch(rootfs.name, "ubuntu-24.04*.tar.gz"):
        raise MediaError(f"--rootfs: '{rootfs.name}' is not named ubuntu-24.04*.tar.gz (the installer imports that)")
    if not fnmatch.fnmatch(bundle.name, BUNDLE_PATTERN) or bundle.name == HOST_TAR:
        raise MediaError(f"--bundle: '{bundle.name}' is not named trialbox-<version>.tar")
    packages = sorted(p for p in debs.glob("*.deb") if p.is_file()) if debs.is_dir() else []
    if not packages:
        raise MediaError(f"--debs: no .deb package in {debs}")
    drivers = [p.name for p in packages if is_linux_driver(p.name)]
    if drivers:
        raise MediaError(
            "--debs holds a Linux NVIDIA driver package (WSL2 uses the Windows driver; the installer refuses such "
            f"a media): {', '.join(drivers)}"
        )
    lacking = _missing_packages([p.name for p in packages])
    if lacking:
        raise MediaError(f"--debs lacks {' and '.join(lacking)}: the installer's package step would stop")
    for name in (LAUNCHER, *INSTALLER_FILES):
        if not (source / "deploy/windows" / name).is_file():
            raise MediaError(f"the source tree has no deploy/windows/{name}")
    final = out / f"TRIALBOX-{version}"
    if final.is_symlink() or (final.exists() and (not final.is_dir() or any(final.iterdir()))):
        raise MediaError(f"{final} already holds files: name an empty folder (nothing is overwritten)")
    # built beside its final place and moved there only when it passes its own check: a build that fails
    # midway leaves nothing that looks like a media, and can be run again
    media = out / f"TRIALBOX-{version}.part"
    if media.is_symlink():
        raise MediaError(f"{media} is a link: remove it")
    if media.exists():
        shutil.rmtree(media)  # what a failed build left
    try:
        _lay_out(media, version, bundle, wsl_msi, rootfs, packages, vendor_pub, nvidia_driver, measured, link, source)
        problems = check(media)
        if problems:  # never hand over a media the installer would stop on
            raise MediaError("the media just built does not pass its own check: " + "; ".join(problems))
        if final.exists():
            final.rmdir()  # empty, checked above
        os.replace(media, final)
    except BaseException:
        shutil.rmtree(media, ignore_errors=True)
        raise
    return final


def _lay_out(
    media: Path,
    version: str,
    bundle: Path,
    wsl_msi: Path,
    rootfs: Path,
    packages: list[Path],
    vendor_pub: Path,
    nvidia_driver: Path | None,
    measured: Path | None,
    link: bool,
    source: Path,
) -> None:
    from tools import host_tree

    media.mkdir(parents=True)
    _text(source / "deploy/windows" / LAUNCHER, media / LAUNCHER, "\r\n")
    for name in INSTALLER_FILES:
        src = source / "deploy/windows" / name
        if name.endswith(".sh"):
            _text(src, media / "windows" / name, "\n")
        else:
            _put(src, media / "windows" / name, False)
    _put(wsl_msi, media / "windows/wsl" / wsl_msi.name, link)
    _put(rootfs, media / "windows/wsl" / rootfs.name, link)
    if nvidia_driver is not None:
        _put(nvidia_driver, media / "windows/nvidia" / nvidia_driver.name, link)
    for p in packages:
        _put(p, media / "linux/debs" / p.name, link)
    (media / "linux").mkdir(parents=True, exist_ok=True)
    host_tree.pack(source, media / "linux" / HOST_TAR)
    _put(bundle, media / "linux" / bundle.name, link)
    (media / "linux" / (bundle.name + ".sha256")).write_text(f"{sha256(bundle)}  {bundle.name}\n", encoding="utf-8")
    _put(vendor_pub, media / "linux/vendor_ed25519.pub", False)
    if measured is not None and measured.is_dir():
        for p in sorted(measured.glob("serving_config.*.json")):
            _put(p, media / "measured" / p.name, False)
    sheet = source / "docs/handover/P-0-windows-rehearsal.md"
    if sheet.is_file():
        _put(sheet, media / "docs" / sheet.name, False)
    readme = [
        f"TrialBox {version}: offline media for a Windows workstation.",
        f"Built {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} by tools/windows_media.py.",
        "",
        "To install: sign in as the Windows administrator account that will own the box and",
        "double-click Install-TrialBox.cmd in this folder.",
        "",
        "SHA256SUMS lists the sha256 of every file here. The installer checks the files it uses",
        "against it before it changes anything.",
        "",
        "Windows NVIDIA driver on this media: " + (nvidia_driver.name if nvidia_driver else "none (install it first)"),
    ]
    (media / "README.txt").write_bytes("\r\n".join([*readme, ""]).encode("ascii"))
    write_sums(media)


def check(media: Path) -> list[str]:
    """Reasons the installer would stop on this media, as far as they can be read without Windows; empty when none.

    Not looked at: Microsoft's signature on the WSL package (step 1 of the installer checks it with Windows' own
    means), the bundle's signature, and whether the packages install. Stricter than the installer: every file must
    be listed (the installer checks only those it uses), a listed path must match in case, ``wsl-setup.sh`` must
    have Unix line ends (the installer converts them itself), nothing may be a link."""
    problems: list[str] = []
    sums_file = media / SUMS
    if not sums_file.is_file():
        return [f"no {SUMS} in {media}"]
    listed: dict[str, str] = {}
    try:
        sums_text = sums_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [f"{SUMS} cannot be read as UTF-8 text ({type(exc).__name__})"]
    for line in sums_text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if m:
            listed[m.group(2).strip().replace("\\", "/")] = m.group(1).lower()
    if not (media / LAUNCHER).is_file():
        problems.append(f"no {LAUNCHER}")
    elif re.search(rb"(?<!\r)\n", (media / LAUNCHER).read_bytes()) or b"\r\n" not in (media / LAUNCHER).read_bytes():
        problems.append(f"{LAUNCHER} has a line without a Windows line end")
    for name in ("box-install.ps1", "box-install.messages.json"):
        if not (media / "windows" / name).is_file():
            problems.append(f"no windows/{name}")
    for folder, patterns in NEEDS_ONE.items():
        for pattern in patterns:
            found = _match(media / folder, pattern)
            if len(found) != 1:
                problems.append(f"{folder}/{pattern}: the installer wants exactly one, found {len(found)}")
    linux = media / "linux"
    bundles = [p for p in _match(linux, BUNDLE_PATTERN) if p.name.lower() != HOST_TAR]
    if len(bundles) != 1:
        problems.append(f"linux/{BUNDLE_PATTERN}: the installer wants exactly one bundle, found {len(bundles)}")
    packages = _match(linux / "debs", "*.deb")
    if not packages:
        problems.append("linux/debs: no .deb package")
    else:
        problems += [f"linux/debs: lacks {what}" for what in _missing_packages([p.name for p in packages])]
    problems += [f"linux/debs/{p.name}: a Linux NVIDIA driver package" for p in packages if is_linux_driver(p.name)]
    setup = media / "windows/wsl-setup.sh"
    if setup.is_file() and b"\r\n" in setup.read_bytes():
        problems.append("windows/wsl-setup.sh has Windows line ends (the builder writes Unix ones)")
    problems += [
        f"{p.relative_to(media).as_posix()}: a link, not a file" for p in sorted(media.rglob("*")) if p.is_symlink()
    ]
    for p in _files(media):
        rel = p.relative_to(media).as_posix()
        if rel not in listed:
            problems.append(f"{rel}: not listed in {SUMS}")
        elif sha256(p) != listed[rel]:
            problems.append(f"{rel}: does not match {SUMS} (damaged or changed)")
    on_disk = {p.relative_to(media).as_posix() for p in _files(media)}
    problems += [f"{rel}: listed in {SUMS} but not on the media" for rel in sorted(set(listed) - on_disk)]
    return problems


def host_tree_error() -> type[Exception]:
    from tools import host_tree

    return host_tree.HostTreeError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.windows_media", description=(__doc__ or "").split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="lay out TRIALBOX-<version>/ and write SHA256SUMS")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--version", required=True)
    b.add_argument("--bundle", type=Path, required=True, help="the signed bundle of tools/make_bundle.sh")
    b.add_argument("--wsl-msi", type=Path, required=True, help="wsl.<version>.x64.msi from Microsoft")
    b.add_argument("--rootfs", type=Path, required=True, help="ubuntu-24.04-wsl-amd64.tar.gz")
    b.add_argument("--debs", type=Path, required=True, help="folder of .deb packages for Ubuntu 24.04")
    b.add_argument("--vendor-pub", type=Path, required=True)
    b.add_argument("--nvidia-driver", type=Path, help="the NVIDIA driver for Windows (the installer does not run it)")
    b.add_argument("--measured", type=Path, help="folder of serving_config.<gpu>.json")
    b.add_argument("--link", action="store_true", help="hard-link the large inputs when on the same file system")
    c = sub.add_parser("check", help="would the installer take this media?")
    c.add_argument("media", type=Path)
    w = sub.add_parser("sums", help="write SHA256SUMS again, after a file was added to the media")
    w.add_argument("media", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            media = build(
                out=args.out, version=args.version, bundle=args.bundle, wsl_msi=args.wsl_msi, rootfs=args.rootfs,
                debs=args.debs, vendor_pub=args.vendor_pub, nvidia_driver=args.nvidia_driver, measured=args.measured,
                link=args.link,
            )  # fmt: skip
            print(f"media: {media} ({len(_files(media))} files; {SUMS} written, not signed)")
            return 0
        if args.cmd == "sums":
            if not (args.media / LAUNCHER).is_file():
                raise MediaError(f"{args.media} is not a media folder (no {LAUNCHER})")
            print(f"{SUMS}: {write_sums(args.media)} files listed (not signed)")
        problems = check(args.media)
    except (MediaError, OSError, UnicodeError, host_tree_error()) as exc:
        print(f"windows_media: {exc}", file=sys.stderr)
        return 1
    for line in problems:
        print(f"FAIL  {line}")
    print("the installer would stop on this media" if problems else OK_LINE)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

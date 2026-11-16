"""The offline media for a bare Ubuntu 24.04 box (OPS-006, D-966; ``docs/handover/OFFLINE-MEDIA.md``).

    python3 -m tools.linux_media debs --rootfs ubuntu-24.04-server-cloudimg-amd64-root.tar.xz --out debs/
    python3 -m tools.linux_media build --out DIR --version 1.0.0 --bundle trialbox-1.0.0.tar --debs debs/ \\
        --vendor-pub vendor_ed25519.pub [--measured deploy/measured] [--link]
    python3 -m tools.linux_media sign DIR/TRIALBOX-1.0.0 --key vendor_ed25519.key     # on the signing machine
    python3 -m tools.linux_media check DIR/TRIALBOX-1.0.0

The Windows media's tools, reused (``tools/windows_media.py``, ``tools/windows_media_debs.py``): the same
``TRIALBOX-<version>/`` folder with its ``linux/`` half, the same ``SHA256SUMS`` and the same rules (built in a
``.part`` folder, moved into place only when it passes its own check; a folder that holds files is never written).

``debs`` asks apt, against the image of the system the box starts from, what installing ``PACKAGES`` would fetch:
Docker Engine, the compose plugin and the NVIDIA Container Toolkit as on Windows, and what a bare box has not got
that WSL2 gets from Windows or its image: the Linux NVIDIA driver (``DRIVER``; open kernel modules, which the
Blackwell cards need), the host tools' python3 libraries, and the mDNS responder of the ``.local`` name (D-965).
It is the one step that goes online (Ubuntu's archive with ``restricted``, Docker's and NVIDIA's repositories).

``sign`` writes ``SHA256SUMS.sig``: the vendor key's raw Ed25519 signature over ``SHA256SUMS``, which the box checks
with ``openssl`` before anything is installed (a bare Ubuntu has openssl and not yet python3-cryptography). It
refuses a media that fails ``check`` and a key whose public half is not the media's ``linux/vendor_ed25519.pub``.
``deploy/box-prepare.sh`` (copied to ``linux/``) is what runs on the box. The disk's unlock rule (HW-010) is not
here: it waits on the owner's decision.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from tools import windows_media as wm
from tools import windows_media_debs

ROOT = Path(__file__).resolve().parents[1]
DRIVER = "nvidia-driver-580-server-open"  # install.sh wants 580.65.06 or later; Blackwell needs the open modules
# Docker Engine from Docker's repository as on Windows (Ubuntu's docker.io conflicts with it: not both)
PACKAGES = (*windows_media_debs.PACKAGES, DRIVER, "python3-yaml", "python3-cryptography", "avahi-daemon", "openssl")
COMPONENTS = "main universe restricted"
PREPARE = "box-prepare.sh"
SIG = wm.SUMS + ".sig"
# what box-prepare.sh needs among the packages: one of each (name prefix of the .deb file -> what it is)
NEEDED = {
    ("docker.io", "docker-ce"): "Docker Engine",
    ("docker-compose-v2", "docker-compose-plugin"): "the compose plugin",
    ("nvidia-container-toolkit",): "the NVIDIA Container Toolkit",
    ("nvidia-driver-",): "the Linux NVIDIA driver",
}
DOCS = ("network-sheet.en.html", "network-sheet.ja.html", "network-sheet.zh-TW.html")


class MediaError(Exception):
    """The media cannot be built, signed or used as it is."""


def collect_debs(rootfs: Path, out: Path, parent: Path) -> list[Path]:
    return windows_media_debs.collect(rootfs, out, parent, packages=PACKAGES, components=COMPONENTS, allow_driver=True)


def _lacking(names: list[str]) -> list[str]:
    have = [n.split("_", 1)[0] for n in names]
    return [what for prefixes, what in NEEDED.items() if not any(h.startswith(prefixes) for h in have)]


def build(
    *,
    out: Path,
    version: str,
    bundle: Path,
    debs: Path,
    vendor_pub: Path,
    measured: Path | None = None,
    link: bool = False,
    source: Path = ROOT,
) -> Path:
    if not wm.VERSION_RE.match(version):
        raise MediaError(f"version '{version}': letters, digits, dot, dash and underscore only")
    for flag, path in {"--bundle": bundle, "--vendor-pub": vendor_pub}.items():
        if not path.is_file():
            raise MediaError(f"{flag}: no such file: {path}")
    if not fnmatch.fnmatch(bundle.name, wm.BUNDLE_PATTERN) or bundle.name == wm.HOST_TAR:
        raise MediaError(f"--bundle: '{bundle.name}' is not named trialbox-<version>.tar")
    packages = sorted(p for p in debs.glob("*.deb") if p.is_file()) if debs.is_dir() else []
    if not packages:
        raise MediaError(f"--debs: no .deb package in {debs}")
    lacking = _lacking([p.name for p in packages])
    if lacking:
        raise MediaError(f"--debs lacks {' and '.join(lacking)}: box-prepare.sh would stop")
    final = out / f"TRIALBOX-{version}"
    if final.is_symlink() or (final.exists() and (not final.is_dir() or any(final.iterdir()))):
        raise MediaError(f"{final} already holds files: name an empty folder (nothing is overwritten)")
    media = out / f"TRIALBOX-{version}.part"
    if media.is_symlink():
        raise MediaError(f"{media} is a link: remove it")
    if media.exists():
        shutil.rmtree(media)  # what a failed build left
    try:
        _lay_out(media, version, bundle, packages, vendor_pub, measured, link, source)
        problems = check(media, signed=False)
        if problems:
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
    packages: list[Path],
    vendor_pub: Path,
    measured: Path | None,
    link: bool,
    source: Path,
) -> None:
    from tools import host_tree

    linux = media / "linux"
    linux.mkdir(parents=True)
    wm._text(source / "deploy" / PREPARE, linux / PREPARE, "\n")
    (linux / PREPARE).chmod(0o755)
    for p in packages:
        wm._put(p, linux / "debs" / p.name, link)
    host_tree.pack(source, linux / wm.HOST_TAR)
    wm._put(bundle, linux / bundle.name, link)
    (linux / (bundle.name + ".sha256")).write_text(f"{wm.sha256(bundle)}  {bundle.name}\n", encoding="utf-8")
    wm._put(vendor_pub, linux / "vendor_ed25519.pub", False)
    if measured is not None and measured.is_dir():
        for p in sorted(measured.glob("serving_config.*.json")):
            wm._put(p, media / "measured" / p.name, False)
    for doc in DOCS:
        page = source / "docs/handover" / doc
        if page.is_file():
            wm._put(page, media / "docs" / doc, False)
    driver = next((p.name for p in packages if p.name.startswith("nvidia-driver-")), "none")
    readme = [
        f"TrialBox {version}: offline media for a bare Ubuntu 24.04 box.",
        f"Built {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} by tools/linux_media.py.",
        "",
        "To prepare the box (as root, with the vendor key you were given apart from this disk):",
        f"  sudo bash <this folder>/linux/{PREPARE} <this folder> --pub <the vendor key>",
        "then follow what it prints (a restart for the driver, then deploy/box-install.sh with the bundle).",
        "",
        f"{wm.SUMS} lists the sha256 of every file here; {SIG} is the vendor's signature over it.",
        f"Linux NVIDIA driver on this media: {driver}",
    ]
    (media / "README.txt").write_text("\n".join([*readme, ""]), encoding="ascii")
    wm.write_sums(media)


def check(media: Path, *, signed: bool = True) -> list[str]:
    """Reasons box-prepare.sh would stop on this media, as far as they can be read here; empty when none. The
    signature itself is checked by ``sign`` and on the box; here only that there is one."""
    sums = media / wm.SUMS
    if not sums.is_file():
        return [f"no {wm.SUMS} in {media}"]
    listed: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, _, rel = line.partition("  ")
        listed[rel] = digest
    problems: list[str] = []
    linux = media / "linux"
    for name in (PREPARE, wm.HOST_TAR, "vendor_ed25519.pub"):
        if not (linux / name).is_file():
            problems.append(f"no linux/{name}")
    bundles = [p for p in wm._match(linux, wm.BUNDLE_PATTERN) if p.name != wm.HOST_TAR]
    if len(bundles) != 1:
        problems.append(f"linux/{wm.BUNDLE_PATTERN}: box-prepare.sh wants exactly one bundle, found {len(bundles)}")
    packages = wm._match(linux / "debs", "*.deb")
    problems += [f"linux/debs: lacks {what}" for what in _lacking([p.name for p in packages])]
    problems += [f"{p.relative_to(media).as_posix()}: a link, not a file" for p in media.rglob("*") if p.is_symlink()]
    files = wm._files(media)
    for p in files:
        rel = p.relative_to(media).as_posix()
        if rel not in listed:
            problems.append(f"{rel}: not listed in {wm.SUMS}")
        elif wm.sha256(p) != listed[rel]:
            problems.append(f"{rel}: does not match {wm.SUMS} (damaged or changed)")
    on_disk = {p.relative_to(media).as_posix() for p in files}
    problems += [f"{rel}: listed in {wm.SUMS} but not on the media" for rel in sorted(set(listed) - on_disk)]
    if signed and not (media / SIG).is_file():
        problems.append(f"no {SIG}: sign the media (tools.linux_media sign) before it leaves")
    return problems


def sign(media: Path, key: Path) -> Path:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

    problems = check(media, signed=False)
    if problems:
        raise MediaError("not signed, the media fails its check: " + "; ".join(problems))
    private = serialization.load_pem_private_key(key.read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise MediaError(f"{key} is not an Ed25519 key")
    public = serialization.load_pem_public_key((media / "linux/vendor_ed25519.pub").read_bytes())
    raw = serialization.Encoding.Raw, serialization.PublicFormat.Raw
    if not isinstance(public, Ed25519PublicKey) or public.public_bytes(*raw) != private.public_key().public_bytes(*raw):
        raise MediaError("the key is not the one of the media's linux/vendor_ed25519.pub: not signed")
    out = media / SIG
    out.write_bytes(private.sign((media / wm.SUMS).read_bytes()))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.linux_media", description=(__doc__ or "").split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("debs", help="the packages, from Ubuntu's, Docker's and NVIDIA's archives (online)")
    d.add_argument("--rootfs", type=Path, required=True, help="the Ubuntu 24.04 image the box starts from")
    d.add_argument("--out", type=Path, required=True, help="an empty folder for the .deb packages")
    d.add_argument("--work", type=Path, help="where this run's working folder is made (new each run, removed after)")
    b = sub.add_parser("build", help="lay out TRIALBOX-<version>/ (no network)")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--version", required=True)
    b.add_argument("--bundle", type=Path, required=True)
    b.add_argument("--debs", type=Path, required=True)
    b.add_argument("--vendor-pub", type=Path, required=True)
    b.add_argument("--measured", type=Path)
    b.add_argument("--link", action="store_true", help="hard links instead of copies where the file system allows")
    s = sub.add_parser("sign", help="SHA256SUMS.sig with the vendor key")
    s.add_argument("media", type=Path)
    s.add_argument("--key", type=Path, required=True)
    c = sub.add_parser("check", help="read a media back as box-prepare.sh will")
    c.add_argument("media", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "debs":
            if not args.rootfs.is_file():
                raise MediaError(f"--rootfs: no such file: {args.rootfs}")
            parent = args.work.resolve() if args.work is not None else Path(tempfile.gettempdir())
            parent.mkdir(parents=True, exist_ok=True)
            placed = collect_debs(args.rootfs, args.out, parent)
            print(f"{len(placed)} packages in {args.out}: give it to tools.linux_media build --debs")
        elif args.cmd == "build":
            media = build(out=args.out, version=args.version, bundle=args.bundle, debs=args.debs,
                          vendor_pub=args.vendor_pub, measured=args.measured, link=args.link)  # fmt: skip
            print(f"built {media}: sign it (tools.linux_media sign) before it leaves")
        elif args.cmd == "sign":
            print(f"signed: {sign(args.media, args.key)}")
        else:
            problems = check(args.media)
            for p in problems:
                print(f"linux_media: {p}", file=sys.stderr)
            if problems:
                return 1
            print(f"{args.media}: complete, listed and signed")
    except (MediaError, windows_media_debs.DebsError, wm.MediaError, OSError, ValueError) as exc:
        print(f"linux_media: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

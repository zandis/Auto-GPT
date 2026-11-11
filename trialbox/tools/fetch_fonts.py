"""Fetch the report fonts (SPEC §9: Noto Sans CJK TC/JP embedded) into ``.cache/fonts`` (copied into the images).

Downloads the OFL variable fonts from the google/fonts repository and instantiates static Regular (400) and Bold (700)
TrueType files, which reportlab embeds as subsets. Idempotent; sha256 of every output is printed for the build log.

Every download is pinned (ENG-013, T-110b): the URL names one commit of google/fonts, and the downloaded bytes must have
the sha256 below, or nothing is written. To move the fonts, change the commit and the three sums in one pull request.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# google/fonts main on 2026-11-10
COMMIT = "5bb28733cec313b63fbd415b574b5ae35c8aa8b8"
BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl"
FONTS = {
    "NotoSansTC": f"{BASE}/notosanstc/NotoSansTC%5Bwght%5D.ttf",
    "NotoSansJP": f"{BASE}/notosansjp/NotoSansJP%5Bwght%5D.ttf",
}
LICENSE = f"{BASE}/notosanstc/OFL.txt"
SHA256 = {
    FONTS["NotoSansTC"]: "864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f",
    FONTS["NotoSansJP"]: "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f",
    LICENSE: "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9",
}


class PinError(RuntimeError):
    """A download whose sha256 is not the pinned one."""


def checked(url: str, data: bytes) -> bytes:
    """``data`` when its sha256 is the one pinned for ``url``; else :class:`PinError` (an unpinned URL too)."""
    want = SHA256.get(url)
    got = hashlib.sha256(data).hexdigest()
    if want is None or got != want:
        raise PinError(f"{url}: sha256 {got} is not the pinned {want or '(none)'}; refusing it")
    return data


def _get(url: str) -> bytes:
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    with urllib.request.urlopen(url, timeout=120, context=ctx) as resp:
        data: bytes = resp.read()
    return checked(url, data)


def main(argv: list[str] | None = None) -> int:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "fonts")
    args = ap.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    try:
        return _fetch(out, TTFont, instantiateVariableFont)
    except PinError as exc:
        print(f"fetch_fonts: {exc}", file=sys.stderr)
        return 1


def _fetch(out: Path, TTFont: Any, instantiateVariableFont: Any) -> int:  # noqa: N803 (fontTools names)
    if not (out / "OFL.txt").exists():
        (out / "OFL.txt").write_bytes(_get(LICENSE))
    for family, url in FONTS.items():
        targets = {w: out / f"{family}-{name}.ttf" for w, name in ((400, "Regular"), (700, "Bold"))}
        if all(p.exists() for p in targets.values()):
            continue
        vf = out / f"{family}-VF.ttf"
        if not vf.exists():
            print(f"downloading {family} ...", file=sys.stderr)
            vf.write_bytes(_get(url))
        else:  # a download left by an interrupted run is checked like a fresh one
            checked(url, vf.read_bytes())
        for weight, path in targets.items():
            font = TTFont(str(vf))
            instantiateVariableFont(font, {"wght": weight}, inplace=True)
            font.save(str(path))
        vf.unlink()
    for p in sorted(out.glob("*.ttf")):
        print(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

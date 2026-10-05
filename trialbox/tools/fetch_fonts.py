"""Fetch the report fonts (SPEC §9: Noto Sans CJK TC/JP embedded) into ``.cache/fonts`` (copied into the images).

Downloads the OFL variable fonts from the google/fonts repository and instantiates static Regular (400) and Bold (700)
TrueType files, which reportlab embeds as subsets. Idempotent; sha256 of every output is printed for the build log.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl"
FONTS = {
    "NotoSansTC": f"{BASE}/notosanstc/NotoSansTC%5Bwght%5D.ttf",
    "NotoSansJP": f"{BASE}/notosansjp/NotoSansJP%5Bwght%5D.ttf",
}
LICENSE = f"{BASE}/notosanstc/OFL.txt"


def _get(url: str) -> bytes:
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    with urllib.request.urlopen(url, timeout=120, context=ctx) as resp:
        data: bytes = resp.read()
    return data


def main(argv: list[str] | None = None) -> int:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "fonts")
    args = ap.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
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

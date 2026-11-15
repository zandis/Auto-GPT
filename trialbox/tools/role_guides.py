"""T-317 (D-774): write the role guides from the console's help catalogue.

``PYTHONPATH=libs:services:. python -m tools.role_guides --out docs/guides`` (from ``trialbox/``) writes ``<role>.<lang>.md`` for every console role in en, ja and
zh-TW (``console.guides``). The files are generated: never edit them by hand; change the help text and run this
again (``tests/console/test_role_guides_from_the_help.py`` fails when they differ)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LANGS = ("en", "ja", "zh-TW")


def write(out: Path) -> list[Path]:
    from console import guides

    out.mkdir(parents=True, exist_ok=True)
    made = []
    for role in guides.ROLES:
        for lang in LANGS:
            path = out / f"{role}.{lang}.md"
            path.write_text(guides.markdown(role, lang), encoding="utf-8")
            made.append(path)
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("docs/guides"))
    args = ap.parse_args(argv)
    for p in write(args.out):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())

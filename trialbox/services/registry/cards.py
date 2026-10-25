"""Write or check model cards from the registry: ``python -m registry.cards [--write]`` (S1-07, MOD-8)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from registry.registry import CARDS_DIR, DEFAULT_PATH, Registry, card_markdown


def expected(reg: Registry) -> dict[str, str]:
    return {f"{b.build_id}.md": card_markdown(b) for b in reg.builds}


def stale(reg: Registry, cards_dir: Path = CARDS_DIR) -> list[str]:
    """Card files that are missing or differ from the generated text."""
    out: list[str] = []
    for name, text in expected(reg).items():
        p = cards_dir / name
        if not p.exists() or p.read_text(encoding="utf-8") != text:
            out.append(name)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--cards", type=Path, default=CARDS_DIR)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    reg = Registry.load(args.registry)
    if args.write:
        args.cards.mkdir(parents=True, exist_ok=True)
        for name, text in expected(reg).items():
            (args.cards / name).write_text(text, encoding="utf-8")
        return 0
    bad = stale(reg, args.cards)
    for name in bad:
        print(f"stale or missing card: {name}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

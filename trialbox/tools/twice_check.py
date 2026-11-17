"""V-11: the generated blocks of the "twice has one effect" page, made from its ``twice.json`` and ``findings.json``.

``python tools/twice_check.py --check`` compares each marked block of the page whole with what the two files give
(exit 1 on any difference); ``--write`` rewrites the blocks. A block is the text between
``<!-- twice:NAME:begin -->`` and ``<!-- twice:NAME:end -->``."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/plan/measurements/twice-one-effect-2026-11-17.md"
NAMES = ("verdict", "cases", "findings", "not-driven")


def _routes(row: dict[str, Any]) -> list[str]:
    """The inventory form ("POST /path") of the routes a case drove."""
    raw = row.get("routes") or ([row["route"]] if "route" in row else [])
    out = []
    for r in raw:
        m = re.match(r"(POST|PUT|PATCH|DELETE) (\S+)", str(r))
        if m:
            out.append(f"{m.group(1)} {m.group(2).rstrip(',')}")
    return out


def blocks(twice: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, str]:
    cases = {k: v for k, v in sorted(twice.items()) if k != "inventory"}
    by_case: dict[str, list[str]] = {}
    for f in findings:
        for c in f.get("cases", []):
            by_case.setdefault(c, []).append(f["id"])
    sev = {s: sum(1 for f in findings if f["severity"] == s) for s in ("High", "Medium", "Low")}
    held = [k for k in cases if k not in by_case]
    inventory = list((twice.get("inventory") or {}).get("routes") or [])
    driven = sorted({r for row in cases.values() for r in _routes(row) if r in inventory})
    verdict = (
        f"{len(cases)} cases measured; {len(held)} held one effect; {len(cases) - len(held)} did not. "
        f"{len(findings)} findings: {sev['High']} High, {sev['Medium']} Medium, {sev['Low']} Low. "
        f"Changing console routes: {len(inventory)} in the live app; {len(driven)} driven twice; "
        f"{len(inventory) - len(driven)} not driven."
    )
    lines = ["| case | place | one effect | finding | counts |", "|---|---|---|---|---|"]
    for k, row in cases.items():
        place = row.get("place") or ", ".join(row.get("routes") or [row.get("route", "")])
        counts = {a: b for a, b in row.items() if a not in ("place", "route", "routes")}
        ids = ", ".join(by_case.get(k, []))
        shown = json.dumps(counts, sort_keys=True)
        lines.append(f"| {k} | `{place}` | {'no' if ids else 'yes'} | {ids or '-'} | `{shown}` |")
    flines = ["| id | severity | lane | basis | place | claim |", "|---|---|---|---|---|---|"]
    for f in findings:
        flines.append(f"| {f['id']} | {f['severity']} | {f['lane']} | {f['basis']} | `{f['place']}` | {f['claim']} |")
    nd = [r for r in inventory if r not in driven]
    return {
        "verdict": verdict,
        "cases": "\n".join(lines),
        "findings": "\n".join(flines),
        "not-driven": "\n".join(f"- `{r}`" for r in nd) or "- none",
    }


def _load(folder: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    twice = json.loads((folder / "twice.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())["findings"]
    return twice, findings


def render(page: str, want: dict[str, str]) -> str:
    for name, body in want.items():
        pat = re.compile(rf"(<!-- twice:{name}:begin -->)\n(?:.*?\n)?(<!-- twice:{name}:end -->)", re.S)
        if not pat.search(page):
            raise ValueError(f"the page has no block {name}")
        m = pat.search(page)
        assert m is not None
        page = page[: m.start()] + f"{m.group(1)}\n{body}\n{m.group(2)}" + page[m.end() :]
    return page


def check(page: str, want: dict[str, str]) -> list[str]:
    """The names of the blocks that differ from what the files give."""
    bad = []
    for name, body in want.items():
        m = re.search(rf"<!-- twice:{name}:begin -->\n(.*?)\n<!-- twice:{name}:end -->", page, re.S)
        if m is None or m.group(1) != body:
            bad.append(name)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="twice_check")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--page", default=str(PAGE))
    args = ap.parse_args(argv)
    page_path = Path(args.page)
    want = blocks(*_load(page_path.with_suffix("")))
    text = page_path.read_text()
    if args.write:
        page_path.write_text(render(text, want))
        return 0
    bad = check(text, want)
    if bad:
        print(f"twice_check: blocks differ from the json: {', '.join(bad)}")
        return 1
    print(f"twice_check: {len(want)} blocks match the json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

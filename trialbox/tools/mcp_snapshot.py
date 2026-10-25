"""Snapshot and lint the front-door ``tools/list`` (spec v4 HER-8; OWASP MCP Top 10 MCP03/MCP04; S1-09).

    python -m tools.mcp_snapshot --check   # exit 1 if tools/list differs from the reviewed snapshot or fails lint
    python -m tools.mcp_snapshot --write   # rewrite the snapshot after review of the diff

The snapshot is ``services/frontdoor_mcp/tools_list.snapshot.json`` (canonical JSON). Lint covers every description
string in the list (tool descriptions and schema field descriptions): no imperative instructions aimed at the model,
no URLs, no invisible or bidirectional-control Unicode. It also checks that the tool set is exactly the §9.3 list and
that no tool is above tier T1.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "services" / "frontdoor_mcp" / "tools_list.snapshot.json"
EXPECTED = (
    "tb.submit_request",
    "tb.status",
    "tb.ask_protocol",
    "tb.registry_search",
    "tb.atlas_describe",
    "tb.aggregate_query",
    "tb.resend_released_file",
    "tb.ops_read",
)
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|ai)\b", re.I)
_IMPERATIVE = re.compile(
    r"\b(?:ignore|disregard|always|never tell|you must|you should|do not tell|call this|use this tool|"
    r"before (?:using|calling)|instead of|override|forget|pretend|system prompt)\b",
    re.I,
)
_LEADING_VERB = re.compile(r"^(?:call|use|send|run|execute|ignore|always|tell|ask|invoke|forward|delete)\b", re.I)
_INVISIBLE = {"Cf", "Co", "Cn"}


def current() -> list[dict[str, Any]]:
    from frontdoor_mcp.server import tools_list

    return tools_list()


def canonical(tools: list[dict[str, Any]]) -> str:
    return json.dumps(tools, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def _descriptions(obj: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("description", "title") and isinstance(v, str):
                yield f"{path}.{k}", v
            else:
                yield from _descriptions(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _descriptions(v, f"{path}[{i}]")


def lint(tools: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    names = tuple(str(t.get("name")) for t in tools)
    if sorted(names) != sorted(EXPECTED) or len(names) != len(set(names)):
        problems.append(f"tool set {sorted(names)} is not exactly the §9.3 list")
    for t in tools:
        tier = (t.get("annotations") or {}).get("tb/tier")
        if tier not in ("T0", "T1"):
            problems.append(f"{t.get('name')}: tier {tier!r} is not allowed on the front door (T2/T3 never listed)")
        for where, text in _descriptions(t, str(t.get("name"))):
            if _URL.search(text):
                problems.append(f"{where}: contains a URL")
            if _IMPERATIVE.search(text) or _LEADING_VERB.search(text.strip()):
                problems.append(f"{where}: reads as an instruction to the model")
            bad = sorted({f"U+{ord(c):04X}" for c in text if unicodedata.category(c) in _INVISIBLE})
            if bad:
                problems.append(f"{where}: invisible or control Unicode {', '.join(bad)}")
    return problems


def check(snapshot: Path = SNAPSHOT) -> tuple[bool, list[str]]:
    tools = current()
    problems = lint(tools)
    now = canonical(tools)
    if not snapshot.exists():
        problems.append(f"{snapshot} missing (run --write after review)")
    elif snapshot.read_text(encoding="utf-8") != now:
        diff = difflib.unified_diff(
            snapshot.read_text(encoding="utf-8").splitlines(), now.splitlines(), "snapshot", "current", lineterm=""
        )
        problems.append("tools/list differs from the reviewed snapshot:\n" + "\n".join(list(diff)[:80]))
    return not problems, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mcp_snapshot", description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    a = ap.parse_args(argv)
    if a.write:
        problems = lint(current())
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        a.snapshot.write_text(canonical(current()), encoding="utf-8")
        print(f"wrote {a.snapshot}")
        return 0
    ok, problems = check(a.snapshot)
    print("tools/list snapshot OK" if ok else "\n".join(problems))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

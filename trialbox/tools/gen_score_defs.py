"""Generate ``libs/tb_common/score_defs.json`` from the catalogue's ``catalogue/scores/*.yaml`` (WS-04.3, D-189).

The catalogue is the source of every derived-score definition; the box reads only the generated file. Each definition
keeps the YAML's content (inputs, formula, coefficients, windows, edge cases, worked examples, sources) and adds:

* ``def_version``: ``<score_id>@<version>`` (the YAML's ``version``), the name a stored derived row carries;
* ``sha256``: a hash of the YAML's content (keys sorted), so a stored row also names the exact text it came from.

A definition's content never changes under the same version: when a YAML changed but kept its ``version``, the
generator refuses (bump ``version`` in the catalogue), so a stored row's ``def_version`` always means one formula.

Usage::

    python tools/gen_score_defs.py          # regenerate
    python tools/gen_score_defs.py --check  # exit 1 if the committed file is stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "catalogue" / "scores"
OUT = ROOT / "libs" / "tb_common" / "score_defs.json"


class StaleVersion(ValueError):
    """A catalogue definition changed but kept its version."""


def _plain(x: Any) -> Any:
    """Mapping keys as text (YAML band tables use numbers as keys), dates and the like as text."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x if x is None or isinstance(x, (str, int, float, bool)) else str(x)


def _canon(doc: Any) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def load(src: Path = SRC) -> dict[str, dict[str, Any]]:
    """``{score_id: definition}`` from every YAML in ``src``."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(src.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "score_id" not in doc or "version" not in doc:
            raise ValueError(f"{path.name}: not a score definition (score_id and version are required)")
        doc = _plain(doc)
        sid = str(doc["score_id"])
        if sid in out:
            raise ValueError(f"{path.name}: score_id {sid} is defined twice")
        out[sid] = {
            **doc,
            "file": f"catalogue/scores/{path.name}",
            "def_version": f"{sid}@{doc['version']}",
            "sha256": hashlib.sha256(_canon(doc).encode("utf-8")).hexdigest(),
        }
    return out


def render(defs: dict[str, dict[str, Any]], previous: dict[str, Any] | None = None) -> str:
    """The generated file's text. ``previous`` (the committed file) is checked: same version means same content."""
    old = (previous or {}).get("definitions", {})
    for sid, d in defs.items():
        o = old.get(sid)
        if o is not None and o.get("version") == d["version"] and o.get("sha256") != d["sha256"]:
            raise StaleVersion(f"{d['file']} changed but kept version {d['version']}: bump its version")
    doc = {
        "generated_by": "tools/gen_score_defs.py",
        "source": "catalogue/scores/*.yaml",
        "definitions": {sid: defs[sid] for sid in sorted(defs)},
    }
    return json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/gen_score_defs.py")
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = ap.parse_args(argv)
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    try:
        text = render(load(), previous)
    except StaleVersion as e:
        print(f"score definitions: {e}", file=sys.stderr)
        return 1
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("score definitions are stale: run python tools/gen_score_defs.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(json.loads(text)['definitions'])} definitions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

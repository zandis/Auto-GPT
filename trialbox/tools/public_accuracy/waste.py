"""Wasted model calls in a stored run: cut at the answer cap, looping, outside the schema (card H-40). Offline: no GPU,
no model, no network.

    python -m tools.public_accuracy.waste RUN [RUN ...] [--json OUT] [--scratch DIR]

``RUN`` is read as :mod:`.replay` reads it (a driver's ``.tgz``, unpacked by its safe extractor into a new empty folder
outside the repository; an extracted folder; or a folder of them). Only ``work/raw-traces.json`` is read: one record
per model call (``span`` ``chat``) or per refused call (``span`` ``refusal``), with the model alias, the prompt
``id@version``, the messages sent and the text the model returned. Nothing in a run is executed or changed.

What a trace does **not** record, and so this tool does not read: the model's finish reason, the call's tokens and the
call's duration (the gateway's ledger has tokens and latency; the stored sets do not hold the ledger). Each count below
is therefore a rule on the returned text, stated here and on the card's page:

* **cut** (ended at the token limit): the text is not JSON and the parser ran off its end (the error's position is at
  or past the last non-blank character, or a string is never closed): the answer stopped before its JSON closed.
  ``at_cap`` is the looser bound:
  :func:`tb_llm.budget.estimate_tokens` of the text (an over-estimate, D-645) is at least 90 % of the prompt's
  ``max_tokens``.
* **loop** (the output repeats): some block of ``p`` characters (1 <= p <= :data:`MAX_PERIOD`) follows itself back to
  back so that the repeated stretch covers at least ``span`` characters and holds at least ``reps`` copies. The default
  is ``span`` 64, ``reps`` 4; :data:`GRID` gives the counts under looser and stricter rules.
* **outside the schema**: the text is not JSON, or it is JSON that fails the prompt's registered output schema
  (``jsonschema`` with null read as absent, as the gateway's ``_schema_ok`` checks it).
* **timeout**: a refused call whose upstream kinds hold ``timeout``: it returned no text at all.
* **repair**: a call whose messages hold an earlier assistant answer (the caller asked again after a bad answer).

The share of model time is not recorded either. The tool gives a proxy: each call's estimated output tokens (decode
dominates a long answer), and the share of them in flagged calls. Timeouts carry no text and are counted apart.

Exit 0 when the tool ran, whatever it found; 2 on an input it will not read.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.public_accuracy.replay import Refused, collect, commit

SCHEMA_VERSION = 1
MAX_PERIOD = 256
#: (span, reps) rules for the sensitivity grid; DEFAULT_RULE is the page's
GRID: tuple[tuple[int, int], ...] = ((16, 2), (32, 3), (64, 4), (128, 8), (256, 16))
DEFAULT_RULE = (64, 4)
AT_CAP_SHARE = 0.9


def estimate_tokens(text: str) -> int:
    from tb_llm.budget import estimate_tokens as est

    return est(text)


def longest_repeat(text: str, max_period: int = MAX_PERIOD) -> tuple[int, int]:
    """(chars, copies) of the longest stretch in which one block follows itself back to back (0, 0 when none).

    For each period p, a run of r positions where text[i] == text[i + p] is a stretch of r + p characters made of
    (r + p) / p copies of one block. The longest stretch over all p wins; ties keep the shorter period."""
    n = len(text)
    if n < 2:
        return 0, 0
    import numpy as np

    a = np.frombuffer(text.encode("utf-32-le"), dtype=np.uint32)
    best = (0, 0)
    for p in range(1, min(max_period, n // 2) + 1):
        eq = a[:-p] == a[p:]
        if not eq.any():
            continue
        d = np.diff(np.concatenate(([0], eq.view(np.int8), [0])))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        run = int((ends - starts).max())
        chars = run + p
        if chars > best[0]:
            best = (chars, chars // p)
    return best


def is_loop(rep: tuple[int, int], rule: tuple[int, int] = DEFAULT_RULE) -> bool:
    span, reps = rule
    return rep[0] >= span and rep[1] >= reps


def cut(text: str) -> bool:
    """The text is not JSON and the parser ran off its end (or a string never closes)."""
    try:
        json.loads(text)
        return False
    except json.JSONDecodeError as e:
        return e.msg.startswith("Unterminated string") or e.pos >= len(text.rstrip())
    except ValueError:
        return False


_SCHEMAS: dict[str, Any] = {}


def schema_of(prompt: str) -> tuple[dict[str, Any] | None, int | None]:
    """(the registered output schema, max_tokens) of ``id@version``; (None, None) for a prompt the registry lacks."""
    if prompt in _SCHEMAS:
        known: tuple[dict[str, Any] | None, int | None] = _SCHEMAS[prompt]
        return known
    got: tuple[dict[str, Any] | None, int | None] = (None, None)
    try:
        from tb_contracts.schema import inline_schema
        from tb_llm.prompt_registry import default_registry

        pid, ver = prompt.split("@", 1)
        p = default_registry().get(pid, int(ver), environment="sandbox")  # read only: qualification is not asked
        cap = next((int(ln.split(":", 1)[1]) for ln in p.text.splitlines() if ln.startswith("max_tokens:")), None)
        got = (inline_schema(p.entry.schema) if p.entry.schema else None, cap)
    except Exception:  # an unknown prompt is reported as such (schema_unknown), not a crash
        got = (None, None)
    _SCHEMAS[prompt] = got
    return got


def in_schema(text: str, schema: dict[str, Any] | None) -> bool | None:
    """True/False by the schema; False when the text is not JSON; None when no schema is known."""
    try:
        obj = json.loads(text)
    except ValueError:
        return False
    if schema is None:
        return None
    import jsonschema
    from tb_contracts import null_absent

    try:
        jsonschema.validate(null_absent(schema, obj), schema)
        return True
    except jsonschema.ValidationError:
        return False


def classify(trace: dict[str, Any]) -> dict[str, Any]:
    """One trace's flags."""
    a = trace.get("attributes") or {}
    prompt = str(a.get("tb.prompt") or "")
    schema, cap = schema_of(prompt)
    text = trace.get("output")
    refused = trace.get("span") == "refusal"
    row: dict[str, Any] = {
        "model": a.get("tb.model_alias"), "prompt": prompt, "refused": refused,
        "timeout": refused and "timeout" in (a.get("tb.upstream_kinds") or []),
        "cache_hit": a.get("tb.cache") == "hit",
        "repair": any(isinstance(m, dict) and m.get("role") == "assistant" for m in trace.get("prompt") or []),
    }  # fmt: skip
    if refused or not isinstance(text, str):
        return row | {"tokens": 0, "cut": False, "at_cap": False, "repeat": (0, 0), "outside_schema": None}
    tok = estimate_tokens(text)
    ok = in_schema(text, schema)
    return row | {
        "tokens": tok, "cut": cut(text), "at_cap": cap is not None and tok >= AT_CAP_SHARE * cap,
        "repeat": longest_repeat(text), "outside_schema": None if ok is None else not ok,
    }  # fmt: skip


def count(traces: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Counts per model alias (and per model and prompt), with the token-share proxy."""
    acc: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    for t in traces:
        r = classify(t)
        for key in (str(r["model"]), f"{r['model']} {r['prompt']}"):
            c = acc[key]
            c["calls"] += 1
            c["timeout"] += r["timeout"]
            c["refused"] += r["refused"]
            c["repair"] += r["repair"]
            c["cache_hit"] += r["cache_hit"]
            if r["refused"]:
                continue
            c["answered"] += 1
            c["cut"] += r["cut"]
            c["at_cap"] += r["at_cap"]
            c["outside_schema"] += bool(r["outside_schema"])
            c["schema_unknown"] += r["outside_schema"] is None
            for span, reps in GRID:
                c[f"loop_{span}x{reps}"] += is_loop(r["repeat"], (span, reps))
            loop = is_loop(r["repeat"])
            c["loop"] += loop
            flagged = r["cut"] or loop or bool(r["outside_schema"])
            c["flagged"] += flagged
            c["tokens"] += r["tokens"]
            c["tokens_flagged"] += r["tokens"] if flagged else 0
    out = {}
    for k, c in sorted(acc.items()):
        d = dict(c)
        d["token_share_flagged"] = round(d.get("tokens_flagged", 0) / d["tokens"], 4) if d.get("tokens") else 0.0
        out[k] = d
    return out


def waste(paths: list[Path], scratch: Path) -> dict[str, Any]:
    found = collect(paths, scratch)
    sets = {}
    for name, d in sorted(found.items()):
        raw = json.loads((d / "work" / "raw-traces.json").read_text(encoding="utf-8"))
        rows = raw.get("traces") if isinstance(raw, dict) else raw
        sets[name] = {"since": raw.get("since") if isinstance(raw, dict) else None, "by_model": count(rows or [])}
    return {"schema_version": SCHEMA_VERSION, "tool": "python -m tools.public_accuracy.waste", **commit(),
            "rule": {"loop": {"span": DEFAULT_RULE[0], "reps": DEFAULT_RULE[1], "max_period": MAX_PERIOD},
                     "at_cap_share": AT_CAP_SHARE, "grid": [list(g) for g in GRID]}, "sets": sets}  # fmt: skip


def render(r: dict[str, Any]) -> str:
    cols = ("calls", "timeout", "cut", "at_cap", "loop", "outside_schema", "repair", "flagged")
    out = [f"Wasted calls (schema {r['schema_version']}) on commit {str(r['commit'])[:12]}; loop rule "
           f"span>={r['rule']['loop']['span']} reps>={r['rule']['loop']['reps']}"]  # fmt: skip
    for name, s in r["sets"].items():
        out.append(f"set {name}:")
        out.append("  " + f"{'model [prompt]':34s}" + "".join(f"{c:>15s}" for c in cols) + f"{'token share':>13s}")
        for k, c in s["by_model"].items():
            out.append("  " + f"{k:34s}" + "".join(f"{c.get(x, 0):>15d}" for x in cols)
                       + f"{c['token_share_flagged']:>13.1%}")  # fmt: skip
        grid = {k: [c.get(f"loop_{a}x{b}", 0) for a, b in r["rule"]["grid"]] for k, c in s["by_model"].items()}
        out.append("  loops under the grid " + ", ".join(f"{a}x{b}" for a, b in r["rule"]["grid"]) + ": "
                   + "; ".join(f"{k} {v}" for k, v in grid.items() if " " not in k))  # fmt: skip
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.waste", description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("runs", nargs="+", type=Path, help="stored sets: .tgz, extracted folders, or a folder of them")
    ap.add_argument("--json", type=Path, help="write the report here (JSON)")
    ap.add_argument("--scratch", type=Path, help="an empty folder outside the repository (default: a temporary one)")
    a = ap.parse_args(argv)
    try:
        if a.scratch:
            if a.scratch.exists() and any(a.scratch.iterdir()):
                raise Refused(f"--scratch {a.scratch}: not empty")
            res = waste(a.runs, a.scratch)
        else:
            with tempfile.TemporaryDirectory(prefix="tb-waste-") as t:
                res = waste(a.runs, Path(t))
    except (Refused, tarfile.TarError, OSError) as exc:
        print(f"waste: {exc}", file=sys.stderr)
        return 2
    if a.json:
        a.json.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

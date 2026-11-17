"""Card V-8: the audit-trail findings page and its numbers, held together.

    python -m tools.audit_trail_check --check          # the page's generated blocks match the json beside it
    python -m tools.audit_trail_check --write          # rewrite the page's generated blocks from the json
    python -m tools.audit_trail_check --sweep OUT.json # every audit write in services/, read from the code

``--sweep`` reads the code (basis: hypothesis): each call of an audit ``append`` in ``services/``, its file and
line, the keyword arguments it passes, which of them may carry typed free text or a person (by name), and whether
the call wraps its arguments in a masking function (``mask_detail``, ``mask_ids``, ``clean_note``).

``changing_routes(app)`` lists the non-GET routes of a live app object, included routers flattened, each with the
handler's file and line and the first audit write in the handler's own body (or none)."""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-11-17"
PAGE = ROOT / "docs" / "plan" / "measurements" / f"audit-trail-{DAY}.md"
DIR = ROOT / "docs" / "plan" / "measurements" / f"audit-trail-{DAY}"

#: keyword names whose value is typed by a person or may name one
FREE = re.compile(r"(?i)^(note|notes|reason|why|text|comment|comments|message|subject|body|free_text|label|title|"
                  r"query|q|name|display_name|email|mail|phone|description|answer|remark|summary|request)$")  # fmt: skip
MASKS = ("mask_detail", "mask_ids", "clean_note", "mask_text", "masked", "redact")
APPEND = re.compile(r"\b(?:au|audit|_audit|self\.audit|h\.au|self\._audit|log)\.append\(")


# ---------------------------------------------------------------------------------------------- routes
def changing_routes(app: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def visit(routes: list[Any], prefix: str) -> None:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                ctx = getattr(r, "include_context", None)
                visit(list(inner.routes), prefix + str(getattr(ctx, "prefix", "") or ""))
                continue
            path, methods, ep = getattr(r, "path", None), getattr(r, "methods", None), getattr(r, "endpoint", None)
            if not isinstance(path, str) or ep is None:
                continue
            for m in sorted(set(methods or ()) - {"GET", "HEAD", "OPTIONS"}):
                out.append({"method": m, "path": prefix + path, **handler_audit(ep)})

    visit(list(app.routes), "")
    return sorted(out, key=lambda x: (x["path"], x["method"]))


def handler_audit(ep: Any) -> dict[str, Any]:
    fn = inspect.unwrap(ep)
    try:
        src, start = inspect.getsourcelines(fn)
        file = str(Path(inspect.getsourcefile(fn) or "").resolve().relative_to(ROOT))
    except (OSError, TypeError, ValueError):
        return {"handler": getattr(fn, "__qualname__", "?"), "place": "?", "audit_call": None}
    call = next((f"{file}:{start + i}" for i, ln in enumerate(src) if APPEND.search(ln)), None)
    return {"handler": fn.__qualname__, "place": f"{file}:{start}", "audit_call": call}


# ---------------------------------------------------------------------------------------------- the sweep
def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}  # fmt: skip


def sweep(root: Path = ROOT / "services") -> list[dict[str, Any]]:
    rows = []
    for f in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text("utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"):
                continue
            target = ast.unparse(node.func.value)
            if not re.search(r"(?:^|\.)(au|audit|_audit)$", target):
                continue
            keys: list[str] = []
            for kw in node.keywords:
                if kw.arg:
                    keys.append(kw.arg)
                if kw.arg == "detail" and isinstance(kw.value, ast.Dict):
                    keys += [f"detail.{k.value}" for k in kw.value.keys if isinstance(k, ast.Constant)]
            free = sorted({k for k in keys if FREE.match(k.split(".")[-1])})
            masked = bool(_names(node) & set(MASKS))
            rows.append({"place": f"{_rel(f)}:{node.lineno}", "event": _event(node), "fields": keys,
                         "free": free, "masked": masked})  # fmt: skip
    return rows


def _rel(f: Path) -> str:
    try:
        return str(f.resolve().relative_to(ROOT))
    except ValueError:
        return f.name


def _event(node: ast.Call) -> str:
    if node.args and isinstance(node.args[0], ast.Constant):
        return str(node.args[0].value)
    return ast.unparse(node.args[0]) if node.args else "?"


# ---------------------------------------------------------------------------------------------- the page
BLOCK = re.compile(r"<!-- generated:(\w+) -->\n(.*?)<!-- /generated:\1 -->", re.S)


def _load(d: Path) -> dict[str, Any]:
    return {n: json.loads((d / f"{n}.json").read_text("utf-8")) for n in ("tamper", "routes", "findings")}


def render(data: dict[str, Any]) -> dict[str, str]:
    """The page's generated blocks, from the json."""
    t = data["tamper"]["cases"]
    tamper = ["| case | `audit_verify --heads` | console Verify | without `--heads` | first error |", "|---|---|---|---|---|"]
    for c in t:
        tamper.append(f"| {c['case']} | {_ok(c['cli_heads_ok'])} | {_ok(c['console_ok'])} | "
                      f"{_ok(c['cli_no_heads_ok'])} | {_cell(c['first_error'])} |")  # fmt: skip
    caught = sum(1 for c in t if c["cli_heads_ok"] is False and c["console_ok"] is False)
    tamper.append("")
    tamper.append(f"Cases: {len(t)}. Caught by both entries: {caught}. Passed by both: "
                  f"{sum(1 for c in t if c['cli_heads_ok'] and c['console_ok'])}.")  # fmt: skip
    r = data["routes"]
    driven = ["| route | column | status | events | who | what | when | which | planted values in clear "
              "| change and event |", "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for row in r["driven"]:
        driven.append(f"| `{row['route']}` | {row['column']} | {row['status']} | {', '.join(row['events']) or 'none'} "
                      f"| {_yn(row['who'])} | {_yn(row['what'])} | {_yn(row['when'])} | {_yn(row['which'])} | "
                      f"{', '.join(row.get('leaks') or []) or '-'} | {row.get('order', '-')} |")  # fmt: skip
    ok = [x for x in r["driven"] if x["success"]]
    done = sum(1 for x in r["inventory"] if x.get("driven"))
    driven.append("")
    driven.append(f"Changing routes in the live apps: {len(r['inventory'])}. Brought to success: {done} "
                  f"({len(ok)} calls). Calls with no event: {sum(1 for x in ok if not x['what'])}. "
                  f"Not shown: {len(r['inventory']) - done}, of which no audit call in the handler's own body: "
                  f"{sum(1 for x in r['inventory'] if not x['audit_call'] and not x.get('driven'))}.")  # fmt: skip
    f = data["findings"]["findings"]
    findings = ["| id | severity | lane | basis | place | claim | ruling |", "|---|---|---|---|---|---|---|"]
    for x in f:
        findings.append(f"| {x['id']} | {x['severity']} | {x['lane']} | {x['basis']} | `{x['place']}` | "
                        f"{_cell(x['claim'])} | {x.get('ruling') or '-'} |")  # fmt: skip
    findings.append("")
    findings.append(f"Findings: {len(f)}. High: {sum(1 for x in f if x['severity'] == 'High')}. "
                    f"Medium: {sum(1 for x in f if x['severity'] == 'Medium')}. "
                    f"Low: {sum(1 for x in f if x['severity'] == 'Low')}.")  # fmt: skip
    return {"tamper": "\n".join(tamper) + "\n", "driven": "\n".join(driven) + "\n",
            "findings": "\n".join(findings) + "\n"}  # fmt: skip


def _ok(v: Any) -> str:
    return {True: "PASS", False: "FAIL", None: "-"}[v]


def _yn(v: bool) -> str:
    return "yes" if v else "missing"


def _cell(s: str) -> str:
    return str(s).replace("|", "/").replace("\n", " ")[:140]


def problems(page: str, data: dict[str, Any]) -> list[str]:
    want = render(data)
    got = {m.group(1): m.group(2) for m in BLOCK.finditer(page)}
    out = [f"block {k}: missing from the page" for k in want if k not in got]
    out += [f"block {k}: differs from the json (run --write)" for k in want if k in got and got[k] != want[k]]
    out += [f"block {k}: on the page, not made from the json" for k in got if k not in want]
    return out


def write(page: str, data: dict[str, Any]) -> str:
    want = render(data)
    return BLOCK.sub(lambda m: f"<!-- generated:{m.group(1)} -->\n{want.get(m.group(1), m.group(2))}"
                               f"<!-- /generated:{m.group(1)} -->", page)  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sweep", type=Path)
    ap.add_argument("--page", type=Path, default=PAGE)
    ap.add_argument("--dir", type=Path, default=DIR)
    a = ap.parse_args(argv)
    if a.sweep:
        a.sweep.write_text(json.dumps(sweep(), indent=1) + "\n", "utf-8")
        return 0
    data = _load(a.dir)
    page = a.page.read_text("utf-8")
    if a.write:
        a.page.write_text(write(page, data), "utf-8")
        return 0
    bad = problems(page, data)
    for p in bad:
        print(p, file=sys.stderr)
    print("audit-trail page: " + ("FAIL" if bad else "PASS"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

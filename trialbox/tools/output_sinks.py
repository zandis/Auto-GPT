"""Inventory model, log, mail, file download and archive output sites.

Review search: chat/complete/judge/embed/encode and HTTP endpoints (including the model proxy),
getLogger and logger methods, SMTP/send/deliver/transport, FastAPI route paths, file/stream
responses, attachment headers and base64 file envelopes, publish, zip/tar members and support-bundle.
Scan every Python module in libs and services, plus the support writer under tools. Dynamic log
arguments and exception tracebacks count unless the expression demonstrably contains only counts,
types or constants. Keep one entry per call, including multiple calls in one function.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tools/output_sinks.json"
DEF = (ast.FunctionDef, ast.AsyncFunctionDef)
APPROVED = ast.Constant(value=None)  # internal provenance marker, never a node from parsed source
LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
MODEL_PATH = re.compile(r"/(?:(?:chat/)?completions|responses|embeddings?|embed|tokenize)(?:/|$)")
FILE_ROUTE = re.compile(r"/(?:export|download|files|view)(?:[/._{]|$)|\.(?:csv|pdf|zip|xlsx|xml|docx|tar\.gz)$")


@dataclass(frozen=True, order=True)
class Site:
    file: str
    function: str
    area: str
    sink: str
    expression: str


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _name(node.func) + "()"
    return ""


def _strings(node: ast.AST) -> Iterator[str]:
    return (n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def _kw(node: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in node.keywords if k.arg == name), None)


def _fixed(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Call):
        return _name(node.func) == "len"
    if isinstance(node, ast.Attribute) and node.attr == "__name__":
        return True
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple)):
        return all(_fixed(n) for n in ast.iter_child_nodes(node) if not isinstance(n, ast.Load))
    return False


class Scan(ast.NodeVisitor):
    def __init__(self, file: str, tree: ast.Module) -> None:
        self.file = file
        self.scope: list[str] = []
        self.sites: list[Site] = []
        self.defs: dict[str, ast.expr] = {}
        self.file_responses = 0
        self.alias: dict[str, str] = {}
        self.loggers = {"log", "_log", "logger", "logging"}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                self.alias.update({a.asname or a.name: f"{n.module}.{a.name}" for a in n.names})
            elif isinstance(n, ast.Import):
                self.alias.update({a.asname: a.name for a in n.names if a.asname})
            elif (
                isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Call)
                and _name(n.value.func).endswith(("getLogger", "get_logger"))
            ):
                self.loggers.update(_name(t).lower() for t in n.targets)

    def name(self, node: ast.AST) -> str:
        first, dot, rest = _name(node).partition(".")
        return self.alias.get(first, first) + dot + rest

    def gated(self, node: ast.AST | None) -> bool:
        """Follow the payload operand, not incidental gate calls elsewhere in the function."""
        if node is None:
            return False
        if isinstance(node, ast.Name):
            return self.defs.get(node.id) is APPROVED
        if isinstance(node, ast.Subscript):
            return self.gated(node.value)
        if isinstance(node, ast.ListComp):
            return self.gated(node.elt)
        if isinstance(node, ast.BoolOp):
            return all(self.gated(v) or (isinstance(v, ast.Constant) and v.value in (None, b"")) for v in node.values)
        if isinstance(node, ast.Dict):
            return (
                bool(node.values)
                and all(k is None or isinstance(k, ast.Constant) for k in node.keys)
                and all(self.gated(v) for v in node.values)
            )
        if isinstance(node, ast.Call):
            name = self.name(node.func)
            if name in {"tok", "tokenizer"}:
                return (
                    len(node.args) == 1
                    and self.gated(node.args[0])
                    and all(
                        k.arg in {"truncation", "padding", "return_tensors", "max_length"} and _fixed(k.value)
                        for k in node.keywords
                    )
                )
            if isinstance(node.func, ast.Attribute) and node.func.attr == "to":
                return (
                    self.gated(node.func.value)
                    and len(node.args) == 1
                    and _name(node.args[0]) == "settings().device"
                    and not node.keywords
                )
            if name in {"json.dumps", "io.BytesIO", "bytes"} and node.args:
                return self.gated(node.args[0])
            if isinstance(node.func, ast.Attribute) and node.func.attr == "encode":
                return self.gated(node.func.value)
            if name == "chart_parts" and node.args and self.file == "services/sitesetup/charts.py":
                return self.gated(node.args[0])
            if name == "tb_common.output_gate.prepare_output":
                return True
            if name.rsplit(".", 1)[-1] == "render" and len(node.args) == 2:
                return self.gated(node.args[1])
        return False

    def token_batch(self, node: ast.expr) -> bool:
        """A tokenizer's output unpacked into a callable, including after a device transfer."""
        operand = self.defs.get(node.id) if isinstance(node, ast.Name) else node
        if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Attribute) and operand.func.attr == "to":
            operand = operand.func.value
        return isinstance(operand, ast.Call) and self.name(operand.func).rsplit(".", 1)[-1] in {"tok", "tokenizer"}

    def add(self, area: str, sink: str, node: ast.AST) -> None:
        # Stable across line moves and formatting, distinct for different operands in the same function.
        digest = hashlib.sha256(ast.dump(node).encode()).hexdigest()[:12]
        self.sites.append(Site(self.file, ".".join(self.scope) or "<module>", area, sink, digest))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        outer = self.defs
        self.defs = {}
        before = self.file_responses
        for stmt in node.body:
            self.visit(stmt)
        # Also file routes that return a dict, delegate to a helper, or display an artifact inline.
        if self.file_responses == before:
            for d in node.decorator_list:
                if (
                    isinstance(d, ast.Call)
                    and self.name(d.func).endswith((".get", ".post"))
                    and d.args
                    and any(FILE_ROUTE.search(path) for path in _strings(d.args[0]))
                ):
                    self.add("download", "file route", d.args[0])
        self.defs = outer
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def invalidate(self, target: ast.expr) -> None:
        seen: set[str] = set()
        while True:
            if isinstance(target, (ast.Attribute, ast.Subscript)):
                target = target.value
            elif isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute):
                target = target.func.value
            elif isinstance(target, ast.Name) and target.id not in seen and (source := self.defs.get(target.id)):
                seen.add(target.id)
                target = source
            else:
                break
        if target is APPROVED:
            # Names bound to projections can share any nested dict or list. Without
            # proof of independence the enclosing value and aliases need reapproval.
            self.defs = {k: v for k, v in self.defs.items() if v is not APPROVED}

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.generic_visit(node)
        self.invalidate(node.target)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.defs[target.id] = APPROVED if self.gated(node.value) else node.value
            elif isinstance(target, (ast.Subscript, ast.Attribute)):
                self.invalidate(target)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        original = self.defs.copy()
        ends = []
        for branch in (node.body, node.orelse):
            self.defs = original.copy()
            for stmt in branch:
                self.visit(stmt)
            if not branch or not isinstance(branch[-1], (ast.Return, ast.Raise)):
                ends.append(self.defs)
        self.merge(ends)

    def merge(self, ends: list[dict[str, ast.expr]]) -> None:
        """A name is approved after a branch only if every path reaching it was safe."""
        self.defs = {}
        for key, value in ends[0].items() if ends else ():
            choices = [end.get(key) for end in ends]
            if all(v is value for v in choices):
                self.defs[key] = value
            elif APPROVED in choices and all(
                v is APPROVED or (isinstance(v, ast.Constant) and v.value in (None, b"")) for v in choices
            ):
                self.defs[key] = APPROVED

    def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
        original = self.defs.copy()
        for stmt in node.body:
            self.visit(stmt)
        normal = self.defs.copy()
        for stmt in node.orelse:
            self.visit(stmt)
        ends = [self.defs.copy()]
        for handler in node.handlers:
            self.merge([original, normal])
            self.visit(handler)
            if not isinstance(handler.body[-1], (ast.Return, ast.Raise)):
                ends.append(self.defs.copy())
        self.merge(ends)
        for stmt in node.finalbody:
            self.visit(stmt)

    visit_TryStar = visit_Try

    def visit_For(self, node: ast.For) -> None:
        original = self.defs.copy()
        self.visit(node.iter)
        if isinstance(node.target, ast.Name):
            self.defs[node.target.id] = APPROVED if self.gated(node.iter) else node.iter
        for stmt in node.body:
            self.visit(stmt)
        self.merge([original, self.defs])
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_While(self, node: ast.While) -> None:
        original = self.defs.copy()
        self.visit(node.test)
        for stmt in node.body:
            self.visit(stmt)
        self.merge([original, self.defs])
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value:
            self.visit(node.value)
            if isinstance(node.target, ast.Name):
                self.defs[node.target.id] = APPROVED if self.gated(node.value) else node.value
            elif isinstance(node.target, (ast.Attribute, ast.Subscript)):
                self.invalidate(node.target)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if isinstance(item.optional_vars, ast.Name):
                self.defs[item.optional_vars.id] = item.context_expr
        for stmt in node.body:
            self.visit(stmt)

    def archive_handle(self, node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
            return False
        source = self.defs.get(node.func.value.id)
        return isinstance(source, ast.Call) and self.name(source.func) in ("zipfile.ZipFile", "tarfile.open")

    def visit_Return(self, node: ast.Return) -> None:
        if isinstance(node.value, ast.Dict):
            keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
            if keys & {"name", "filename"} and keys & {"text", "b64", "data"} and keys & {"media_type", "b64"}:
                self.file_responses += 1
                if not self.gated(node.value):
                    self.add("download", "file envelope", node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self.name(node.func)
        method = name.rsplit(".", 1)[-1]
        args = node.args
        if method in ("run", "_call") and args and self.name(args[0]).endswith((".chat_json", ".chat", ".embed")):
            self.add("model", self.name(args[0]).rsplit(".", 1)[-1], node)
        if method == "partial" and args:
            name = self.name(args[0])
            method = name.rsplit(".", 1)[-1]
            args = args[1:]
        owner = name.rpartition(".")[0].lower()
        values = [*args, *(k.value for k in node.keywords)]
        first = args[0] if args else None
        if method in ("post", "request", "post_json", "urlopen", "Request"):
            urls = list(args[:2] if method == "request" else args[:1])
            urls += [k.value for k in node.keywords if k.arg == "url"]
            strings = [s for u in urls for s in _strings(self.defs.get(u.id, u) if isinstance(u, ast.Name) else u)]
            if owner in ("app", "r", "router"):
                pass  # route registration
            elif any(MODEL_PATH.search(s) for s in strings) or (
                self.file.startswith("services/model_guard/") and method == "request"
            ):
                if not self.gated(_kw(node, "json") or _kw(node, "body") or _kw(node, "data")):
                    self.add("model", method, node)
            elif any(s.endswith("/send") for s in strings) and not self.gated(_kw(node, "json")):
                self.add("mail", method, node)
        elif method in (
            "chat",
            "chat_json",
            "complete",
            "judge",
            "embed",
            "call_model",
            "generate_content",
            "invoke_model",
        ) or name.endswith(("completions.create", "responses.create", "embeddings.create", "_st.encode")):
            payload = first
            if (method == "chat_json" and len(args) >= 2) or (method == "call_model" and len(args) >= 2):
                payload = args[1]
            elif method == "judge":
                payload = _kw(node, "excerpts")
                if payload is None:
                    payload = next((k.value for k in node.keywords if k.arg is None and self.gated(k.value)), None)
            raw_judge_text = method == "judge" and any(
                k.arg in ("criterion_text", "note_question") and not self.gated(k.value) for k in node.keywords
            )
            if raw_judge_text or not self.gated(payload or _kw(node, "messages")):
                self.add("model", method, node)
        elif method == "model" or any(
            k.arg is None and (method in ("encoder", "llm") or self.token_batch(k.value)) for k in node.keywords
        ):
            if not values or not all(self.gated(v) for v in values):
                self.add("model", method, node)
        elif method in ("ie_locator", "generate_content_async") or (
            method in ("generate", "predict", "invoke", "encode")
            and owner.rsplit(".", 1)[-1] in ("model", "llm", "embedder")
        ):
            if not self.gated(first):
                self.add("model", method, node)
        elif method == "client" and _kw(node, "json_mode") is not None:
            if not self.gated(first):
                self.add("model", "injected client", node)
        elif method in LOG and (
            owner.rsplit(".", 1)[-1] in self.loggers
            or "getlogger()" in owner
            or "get_logger()" in owner
            or name.startswith("logging.")
        ):
            if method == "exception" or any(not (_fixed(v) or self.gated(v)) for v in values) or _kw(node, "exc_info"):
                self.add("log", method, node)
        elif method == "write" and (
            owner.endswith("traces") or (owner == "ts" and self.file.startswith("services/tracestore/"))
        ):
            if not self.gated(first):
                self.add("log", "trace write", node)
        elif (name in ("sys.stderr.write", "sys.stdout.write") and any(not _fixed(v) for v in values)) or method in (
            "log_failure",
            "getMessage",
            "formatException",
        ):
            self.add("log", method, node)
        elif method in ("sendmail", "send_message", "deliver", "transport", "send") and owner:
            content = next((k.value for k in node.keywords if k.arg in ("body", "data", "msg")), None)
            if method in ("transport", "sendmail") and len(args) > 2:
                content = args[2]
            if not self.gated(content or first):
                self.add("mail", method, node)
        elif method in ("FileResponse", "StreamingResponse") or (
            method == "Response"
            and any(
                "content-disposition" in s.lower()
                or "attachment;" in s.lower()
                or s in {"application/zip", "application/pdf", "application/octet-stream", "text/csv"}
                for s in _strings(node)
            )
        ):
            self.file_responses += 1
            headers = _kw(node, "headers")
            if not self.gated(first or _kw(node, "content") or _kw(node, "path")) or (
                headers is not None and not (_fixed(headers) or self.gated(headers))
            ):
                self.add("download", method, node)
        elif (
            method == "publish"
            and owner in ("ctx", "self")
            and (owner == "ctx" or self.file == "services/orchestrator/core.py")
        ):
            if not self.gated(args[1] if len(args) > 1 else _kw(node, "data")):
                self.add("job file", method, node)
        elif self.file == "tools/support_bundle.py" and (name == "b.add" or name == "part.replace"):
            if not self.gated(args[1] if len(args) > 1 else first):
                self.add("support", name, node)
        elif method == "put" and any(s == "application/zip" for s in _strings(node)):
            if not self.gated(args[1] if len(args) > 1 else _kw(node, "data")):
                self.add("package", "store zip", node)
        elif method in ("write_bytes", "write_text") and self.file.startswith("services/deliverables/"):
            if not self.gated(first):
                self.add("package", method, node)
        elif self.archive_handle(node) and (method in ("write", "add") or (method == "open" and "w" in _strings(node))):
            self.add("package", method, node)
        elif method in ("writestr", "addfile", "make_archive", "draft_zip", "build_sponsor_pack", "_write_tar") or (
            method in ("write", "add") and owner in ("tar", "tf", "z", "zf", "zipf", "archive")
        ):
            content = args[1] if method in ("addfile", "writestr") and len(args) > 1 else first
            raw_member = method == "writestr" and first is not None and not (_fixed(first) or self.gated(first))
            if raw_member or not self.gated(content):
                self.add("support" if "support_bundle" in self.file else "package", method, node)
        elif method in {
            "update",
            "extend",
            "append",
            "setdefault",
            "insert",
            "__setitem__",
            "__iadd__",
            "__ior__",
        } and isinstance(node.func, ast.Attribute):
            self.invalidate(node.func.value)
        self.generic_visit(node)


def inspect_source(file: str, source: str) -> list[Site]:
    tree = ast.parse(source, filename=file)
    scan = Scan(file, tree)
    scan.visit(tree)
    return scan.sites


def inventory(root: Path = ROOT) -> Counter[Site]:
    paths = [p for folder in ("libs", "services") for p in (root / folder).rglob("*.py")]
    paths.append(root / "tools/support_bundle.py")
    return Counter(s for p in sorted(paths) for s in inspect_source(p.relative_to(root).as_posix(), p.read_text()))


def inventory_ceiling() -> Counter[Site]:
    """The destination revision's inventory, including multiplicities. Missing history fails the check."""
    path = "trialbox/tools/output_sinks.json"

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=ROOT.parent)

    def sites(content: bytes) -> Counter[Site]:
        return Counter(Site(**{k: v for k, v in row.items() if k != "why"}) for row in json.loads(content))

    def at(revision: str) -> Counter[Site]:
        return sites(git("show", f"{revision}:{path}"))

    base = os.environ.get("TB_OUTPUT_SINK_BASE")
    if not base and git("rev-parse", "--is-shallow-repository").strip() == b"true":
        raise ValueError("a shallow checkout needs an independent TB_OUTPUT_SINK_BASE")
    if not git("ls-tree", "--full-tree", base or "HEAD", "--", path):
        # The first slice may arrive as separate commits or as one squashed review.
        # Authenticate its seed even in a worktree where the table has never been committed.
        initial = git("log", "--diff-filter=A", "-1", "--format=%H", "HEAD", "--", path).decode().strip()
        content = git("show", f"{initial}:{path}") if initial else TABLE.read_bytes()
        if hashlib.sha256(content).hexdigest() not in {
            "b6d8e3a4cddea3ba9296d1be000f796e0d514e8785ec22e722666b974a3ba084",
            "052f3497cf8763795b2e85ab83b8ef05b5e20f26856b942ff48ee871a5d0b935",
        }:
            raise ValueError("unrecognised initial output sink inventory")
        return sites(content)
    if base:
        return at(base)

    # Local checkouts compare the current table with the preceding table change.
    ceiling = at("HEAD")
    revisions = git("log", "-2", "--format=%H", "--first-parent", "--", path).decode().splitlines()
    return ceiling & at(revisions[1]) if len(revisions) == 2 else ceiling

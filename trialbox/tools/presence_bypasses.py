"""Inventory Python sites which can create, enable, or publish executable presence IR.

Count sites, not just functions. A second write in an inventoried function consumes a second row.
The first revision bootstraps its ceiling by scanning the Git base's Python files with the same rules.
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import tarfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "tools/presence_bypasses.json"
AREAS = ("libs", "services")
OFFLINE_BUILDER = "tools/build_rulesets.py"
GATE_FILE = "services/criteria_compiler/ir_extract/postprocess.py"
GATE = "criteria_compiler.ir_extract.postprocess.admit_presence"
IR = {"CriterionIR", "CriterionIRv3"}
NON_EXEC = {"human", "note"}
LOGIC = {"logic", "atoms"}
MUTATORS = {"update", "setdefault", "__setitem__", "append", "extend", "insert", "clear", "pop", "remove"}


@dataclass(frozen=True, order=True)
class Site:
    file: str
    function: str
    operation: str
    statement: str


class Scan(ast.NodeVisitor):
    def __init__(self, file: str, tree: ast.Module):
        self.file = file
        self.scope: list[str] = []
        self.bindings: dict[str, ast.expr] = {}
        self.parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        self.sites: list[Site] = []
        self.guarded: set[str] = set()
        self.inputs: set[str] = set()
        self.prepared: set[str] = set()
        self.stripped: set[str] = set()
        self.visit(tree)

    def resolve(self, node: ast.expr) -> ast.expr:
        seen: set[str] = set()
        while isinstance(node, ast.Name) and node.id in self.bindings and node.id not in seen:
            seen.add(node.id)
            node = self.bindings[node.id]
        return node

    def path(self, node: ast.expr) -> str:
        # Bind aliases at assignment time so rebinding a name cannot introduce a cycle.
        if isinstance(node, ast.Name) and node.id in self.stripped:
            return node.id
        node = self.resolve(node)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return self.path(node.value) + "." + node.attr
        if isinstance(node, ast.Subscript):
            return self.path(node.value) + "." + (self.literal(node.slice) or "[]")
        if isinstance(node, ast.Call) and node.args:
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "setdefault"}:
                return self.path(node.func.value) + "." + (self.literal(node.args[0]) or "[]")
            if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
                return self.path(node.args[0]) + "." + (self.literal(node.args[1]) or "[]")
        return ""

    def literal(self, node: ast.expr | None) -> str | None:
        if node is None:
            return None
        node = self.resolve(node)
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def fields(self, node: ast.expr | None, seen: frozenset[int] = frozenset()) -> dict[str, ast.expr]:
        if node is None:
            return {}
        node = self.resolve(node)
        if id(node) in seen:
            return {}
        seen = seen | {id(node)}
        if isinstance(node, ast.IfExp) and isinstance(node.body, ast.Dict) and isinstance(node.orelse, ast.Dict):
            keys = self.fields(node.body, seen).keys() | self.fields(node.orelse, seen).keys()
            return dict.fromkeys(keys, node)
        if isinstance(node, ast.Dict):
            pairs = [(self.literal(k), v) for k, v in zip(node.keys, node.values, strict=True)]
        elif isinstance(node, ast.List | ast.Tuple):
            pairs = [
                (self.literal(pair.elts[0]), pair.elts[1])
                for pair in node.elts
                if isinstance(pair, ast.List | ast.Tuple) and len(pair.elts) == 2
            ]
        elif isinstance(node, ast.Call) and self.path(node.func) in {"dict", "builtins.dict"}:
            pairs = [(None, a) for a in node.args] + [(k.arg, k.value) for k in node.keywords]
        else:
            return {}
        result: dict[str, ast.expr] = {}
        for key, value in pairs:
            if key is None:
                spread = self.fields(value, seen)
                if not spread or "" in spread:
                    result.clear()  # an unknown expansion could overwrite the class or predicate
                result.update(spread or {"": value})
            else:
                result[key] = value
        return result

    def gate(self, call: ast.Call) -> bool:
        name = self.path(call.func)
        return name == GATE or (self.file == GATE_FILE and name == "admit_presence")

    def guarded_locals(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        # A draft may be inspected and reassigned before admission. A bare use that hands it to
        # anything else (including return, an alias, or a second append) disqualifies that proof.
        names: set[str] = set()
        escaped: set[str] = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                p = self.parents[n]
                if isinstance(p, ast.Call) and self.gate(p) and p.args and n is p.args[0]:
                    names.add(n.id)
                elif isinstance(p, ast.Attribute):
                    call = self.parents.get(p)
                    if isinstance(call, ast.Call) and call.func is p:
                        assign = self.parents.get(call)
                        if not (
                            p.attr == "model_copy"
                            and isinstance(assign, ast.Assign)
                            and all(isinstance(t, ast.Name) and t.id == n.id for t in assign.targets)
                        ):
                            escaped.add(n.id)
                else:
                    escaped.add(n.id)
        return names - escaped

    def prepared_locals(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
        """Fresh dictionaries used only to build a typed model or its update. Count the consuming call."""
        local: set[str] = set()
        consumed: set[str] = set()
        escaped: set[str] = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.AnnAssign | ast.Assign) and isinstance(n.value, ast.Dict | ast.DictComp):
                targets = [n.target] if isinstance(n, ast.AnnAssign) else n.targets
                local.update(t.id for t in targets if isinstance(t, ast.Name))
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                p = self.parents[n]
                if isinstance(p, ast.Subscript) and p.value is n and isinstance(p.ctx, ast.Store):
                    continue
                if isinstance(p, ast.keyword) and p.arg == "update":
                    p = self.parents[p]
                if isinstance(p, ast.Call) and (
                    set(self.path(p.func).split(".")) & IR or self.path(p.func).endswith(".model_copy")
                ):
                    consumed.add(n.id)
                else:
                    escaped.add(n.id)
        return local & consumed - escaped

    def visit_Return(self, node: ast.Return) -> None:
        values = node.value.elts if isinstance(node.value, ast.Tuple | ast.List) else [node.value]
        if any(isinstance(v, ast.Name) and self.path(v) in self.inputs for v in values):
            self.report(node, "release input criterion")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        # A detached model_dump stripped of the mandatory IR envelope (e.g. canonical hashing)
        # cannot be executed. Recognize the key-removal loop, not the name of a hash helper.
        keys = self.resolve(node.iter)
        if isinstance(keys, ast.Tuple | ast.List) and isinstance(node.target, ast.Name):
            removed = {self.literal(k) for k in keys.elts}
            for stmt in node.body:
                if not (
                    {"id", "ruleset", "text"} <= removed
                    and isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Attribute)
                ):
                    continue
                call = stmt.value
                func = stmt.value.func
                if (
                    func.attr == "pop"
                    and isinstance(func.value, ast.Name)
                    and call.args
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == node.target.id
                ):
                    initial = self.resolve(func.value)
                    if isinstance(initial, ast.Call) and self.path(initial.func).endswith(".model_dump"):
                        self.stripped.add(func.value.id)
        iterator = self.path(node.iter).split(".")
        if isinstance(node.target, ast.Name) and set(iterator) & LOGIC and iterator[0] not in self.stripped:
            self.bindings[node.target.id] = ast.Name(id=".".join([*iterator, "[]"]))
        self.generic_visit(node)

    def report(self, node: ast.AST, operation: str) -> None:
        if self.file == GATE_FILE and self.scope == ["admit_presence"]:
            return
        parent = self.parents.get(node)
        if isinstance(parent, ast.Call) and self.gate(parent) and parent.args and parent.args[0] is node:
            return
        if isinstance(parent, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id in self.guarded for t in parent.targets
        ):
            return
        # The owning statement distinguishes the same spelling on two release paths.
        statement = node
        while not isinstance(statement, ast.stmt) and statement in self.parents:
            statement = self.parents[statement]
        self.sites.append(Site(self.file, ".".join(self.scope) or "<module>", operation, ast.unparse(statement)))

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        old, guarded = self.bindings, self.guarded
        self.bindings = dict(old)
        old_inputs, old_prepared, old_stripped = self.inputs, self.prepared, self.stripped
        self.inputs, self.prepared, self.stripped = set(), set(), set()
        if isinstance(node, ast.ClassDef):
            self.guarded = set()
        else:
            self.guarded = self.guarded_locals(node)
            self.prepared = self.prepared_locals(node)
            self.inputs = {
                arg.arg
                for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                if arg.annotation and self.path(arg.annotation).split(".")[-1] in IR
            }
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()
        self.bindings, self.guarded = old, guarded
        self.inputs, self.prepared, self.stripped = old_inputs, old_prepared, old_stripped

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for item in node.names:
            self.bindings[item.asname or item.name] = ast.Name(id=f"{node.module}.{item.name}")

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            if item.asname:
                self.bindings[item.asname] = ast.Name(id=item.name)

    def assigned_value(self, value: ast.expr) -> ast.expr:
        resolved = self.resolve(value)
        if isinstance(resolved, ast.Attribute | ast.Subscript) or (
            isinstance(resolved, ast.Call) and self.path(resolved)
        ):
            return ast.Name(id=self.path(resolved))
        return resolved

    def assignment(self, node: ast.AST, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Tuple | ast.List):
            rhs = self.resolve(value)
            if (
                isinstance(rhs, ast.Tuple | ast.List)
                and len(rhs.elts) == len(target.elts)
                and not any(isinstance(e, ast.Starred) for e in (*target.elts, *rhs.elts))
            ):
                values = [self.assigned_value(item) for item in rhs.elts]
            else:
                values = [ast.Name(id="<unpacked>")] * len(target.elts)
            for dest, item in zip(target.elts, values, strict=True):
                self.assignment(node, dest, item)
            return
        if isinstance(target, ast.Starred):
            self.assignment(node, target.value, value)
            return
        if isinstance(target, ast.Name):
            self.stripped.discard(target.id)
            resolved = self.assigned_value(value)
            if isinstance(resolved, ast.Name | ast.Constant | ast.Dict | ast.Call | ast.Tuple):
                self.bindings[target.id] = resolved
            else:
                self.bindings.pop(target.id, None)
        elif isinstance(target, ast.Subscript | ast.Attribute):
            parts = self.path(target).split(".")
            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.JoinedStr):
                path_parts = [v.value for v in target.slice.values if isinstance(v, ast.Constant)]
                if path_parts and path_parts[0] == "ir/" and path_parts[-1] == ".json":
                    self.report(node, "serialize executable IR")
            if parts[-1] in {"class", "class_"} and self.literal(value) not in NON_EXEC:
                self.report(node, "write executable class")
            elif set(parts[1:]) & LOGIC:
                if not (isinstance(target.value, ast.Name) and target.value.id in self.prepared | self.stripped):
                    self.report(node, "mutate criterion logic")
            elif parts[-1] in {"id", "ruleset", "text"} and isinstance(target.value, ast.Name):
                self.stripped.discard(target.value.id)
            elif parts[-2:] == ["review", "status"] and self.literal(value) != "rejected":
                self.report(node, "activate review")
            elif parts[-1] == "review":
                supplied = self.resolve(value)
                status = self.fields(value).get("status")
                if (
                    (isinstance(supplied, ast.Constant) and supplied.value is None)
                    or (status is not None and self.literal(status) != "rejected")
                    or (isinstance(supplied, ast.Call) and self.path(supplied.func).endswith("CriterionReview"))
                    or (set(parts[:-1]) & (self.inputs | {"criterion", "criteria", "edited_ir"}))
                ):
                    self.report(node, "replace criterion review")

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        for target in node.targets:
            self.assignment(node, target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)
        if node.value is not None:
            self.assignment(node, node.target, node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            parts = self.path(target).split(".")
            if set(parts[1:]) & (LOGIC | {"review"}):
                self.report(node, "delete criterion restriction")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.generic_visit(node)
        if set(self.path(node.target).split(".")) & LOGIC:
            self.report(node, "mutate criterion logic")

    def non_presence(self, fields: dict[str, ast.expr]) -> bool:
        cls = self.literal(fields.get("class", fields.get("class_")))
        atom = self.fields(fields.get("logic"))
        return (
            cls in NON_EXEC
            or self.literal(atom.get("domain")) == "demographic"
            or bool(self.fields(atom.get("value")).keys() - {""})
            or bool(self.fields(atom.get("duration")).keys() - {""})
            or bool(self.literal(atom.get("derived")))
        )

    def construction(self, node: ast.expr, fields: dict[str, ast.expr]) -> None:
        parent = self.parents.get(node)
        if isinstance(parent, ast.keyword):
            parent = self.parents[parent]
        if isinstance(parent, ast.Call):
            parts = self.path(parent.func).split(".")
            if set(parts) & IR or parts[-1] in {"update", "copy", "model_copy"}:
                return  # the enclosing construction or mutation owns this site
        if self.non_presence(fields):
            return
        if (
            isinstance(parent, ast.AnnAssign)
            and isinstance(parent.target, ast.Name)
            and parent.target.id in self.prepared
        ):
            return
        if isinstance(parent, ast.Assign) and all(
            isinstance(t, ast.Name) and t.id in self.prepared for t in parent.targets
        ):
            return
        key = fields.get("class_", fields.get("class"))
        if key and self.path(key).endswith(".data_class") and not ({"logic", "kind", "ruleset"} & fields.keys()):
            return  # gateway data classification
        if key is not None and (
            self.literal(key) in {"structured", "mixed"}
            or (self.literal(key) is None and {"logic", "", "class_"} & fields.keys())
        ):
            self.report(node, "construct executable class")
        elif "logic" in fields and (
            "" in fields
            or (isinstance(node, ast.Call) and node.args)
            or (isinstance(parent, ast.BinOp | ast.AugAssign) and isinstance(parent.op, ast.BitOr))
        ):
            self.report(node, "copy executable logic")

    def visit_DictComp(self, node: ast.DictComp) -> None:
        if (
            any(self.path(g.iter).endswith(".criteria") for g in node.generators)
            and any(isinstance(n, ast.Attribute) and n.attr == "text" for n in ast.walk(node.key))
            and isinstance(node.value, ast.Name)
        ):
            self.report(node, "index criteria for reuse by text")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        self.construction(node, self.fields(node))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = self.path(node.func)
        parts = name.split(".")
        method = parts[-1]
        kw: dict[str, ast.expr] = {}
        for k in node.keywords:
            if k.arg:
                kw[k.arg] = k.value
            else:
                kw.update(self.fields(k.value))
        arg = node.args[0] if node.args else None
        if method in IR or (
            set(parts[:-1]) & IR
            and method
            in {
                "model_validate",
                "model_validate_json",
                "model_construct",
                "parse_obj",
                "parse_raw",
                "construct",
            }
        ):
            if not self.non_presence(self.fields(arg) | kw):
                self.report(node, "construct " + next(x for x in parts if x in IR))
        elif name in {"dict", "builtins.dict"}:
            self.construction(node, self.fields(node))
        elif method in {"model_copy", "copy", "update", "setdefault", "__setitem__", "setattr"}:
            fields = self.fields(kw.get("update", arg)) | kw
            if method in {"setdefault", "__setitem__", "setattr"} and len(node.args) >= 2:
                fields = {self.literal(node.args[-2]) or "": node.args[-1]}
            if not self.non_presence(fields):
                if "class_" in fields or "class" in fields:
                    self.report(node, "set executable class")
                elif "logic" in fields:
                    self.report(node, "replace criterion logic")
                elif "status" in fields and "review" in parts[:-1] and self.literal(fields["status"]) != "rejected":
                    self.report(node, "activate review")
                elif (
                    method in {"copy", "model_copy"}
                    and "update" in kw
                    and not self.fields(kw["update"])
                    and parts[0] in self.inputs
                ):
                    self.report(node, "apply unknown criterion update")
                elif "review" in fields:
                    review = fields["review"]
                    if isinstance(review, ast.Constant) and review.value is None and "equivalence" in fields:
                        pass  # the ruleset manifest's review and equivalence reports
                    elif isinstance(review, ast.Call) and any(
                        k.arg == "status" and self.literal(k.value) == "rejected" for k in review.keywords
                    ):
                        pass
                    else:
                        self.report(node, "replace criterion review")
        if method == "setattr" and arg and set(self.path(arg).split(".")[1:]) & LOGIC:
            self.report(node, "mutate criterion logic")
        if method in MUTATORS and set(parts[1:-1]) & LOGIC:
            self.report(node, "mutate criterion logic")
        if parts[-2:-1] == ["review"] and (
            method == "clear" or (method in {"pop", "__delitem__"} and self.literal(arg) == "status")
        ):
            self.report(node, "delete criterion restriction")
        if method == "update" and arg and self.path(arg).endswith(".valuesets"):
            self.report(node, "merge remapped ValueSets")
        if method == "build_artifacts" and self.file == OFFLINE_BUILDER:
            self.report(node, "compile stored IR with remapped codes")
        if method == "_map" and self.file.endswith("/terminology/mapper.py"):
            self.report(node, "resolve concept code set")
        if method == "_presence":
            self.report(node, "emit presence predicate")
        if method in {"tag", "retag", "promote"} and (
            "repo" in parts or self.file.endswith("criteria_compiler/repo.py")
        ):
            self.report(node, "publish ruleset " + method)
        if (
            method in {"CriterionLibraryRecord", "model_validate", "model_validate_json"}
            and "CriterionLibraryRecord" in parts
        ):
            data = self.fields(arg)
            if self.literal((data | kw).get("status")) != "draft":
                self.report(
                    node, "restore library record" if method == "model_validate_json" else "persist library record"
                )
        if method == "LibraryApproval":
            self.report(node, "approve library criterion")
        self.generic_visit(node)


def scan(file: str, data: bytes | str) -> list[Site]:
    return Scan(file, ast.parse(data, filename=file)).sites


def inventory(data: bytes | str) -> Counter[Site]:
    rows = json.loads(data)
    assert isinstance(rows, list)
    for row in rows:
        assert row["why"].strip(), row
    return Counter(Site(r["file"], r["function"], r["operation"], r["statement"]) for r in rows)


def working_sites() -> Counter[Site]:
    return Counter(
        site
        for file in [*(f for area in AREAS for f in (ROOT / area).rglob("*.py")), ROOT / OFFLINE_BUILDER]
        for site in scan(file.relative_to(ROOT).as_posix(), file.read_bytes())
    )


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def base_sources(revision: str, prefix: str) -> Iterator[tuple[str, bytes]]:
    paths = [f":(top,glob){prefix}{area}/**/*.py" for area in AREAS]
    paths.append(":(top)" + prefix + OFFLINE_BUILDER)
    with tarfile.open(fileobj=io.BytesIO(git("archive", revision, *paths))) as archive:
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                yield member.name.removeprefix(prefix), stream.read()


def base_ceiling() -> Counter[Site]:
    base = os.environ.get("GATE_BASE_REF", "origin/master")
    revision = git("rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
    prefix = git("rev-parse", "--show-prefix").decode().strip()
    scanner = Path(__file__).relative_to(ROOT).as_posix()
    if git("ls-tree", "--name-only", revision, "--", INVENTORY).strip() and (
        git("show", f"{revision}:{prefix}{scanner}") == (ROOT / scanner).read_bytes()
    ):
        return inventory(git("show", f"{revision}:{prefix}{INVENTORY}"))
    # A new detector can reveal old sites. Its ceiling comes from running that same
    # detector on base source, including the offline builder, never from proposed rows.
    return Counter(site for path, data in base_sources(revision, prefix) for site in scan(path, data))

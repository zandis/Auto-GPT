"""Find screening-input boundaries in libs/, services/ and tools/, including local and HTTP entry points.

Search vocabulary was built by tracing CURRENT, generation holds, lake_generation, the NDJSON
and OMOP builders, build/rebuild/ingest/backfill, publish/decide, and ruleset tag/materialize
from their service routes, CLI and worker entry points. Entries identify functions, including
nested workers. A forwarding call to an unchecked boundary is itself an entry point.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import tarfile
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RATCHET = "tools/screening_inputs_ratchet.json"
BASE_ENV = "TB_GATE_BASE_REV"
type Location = tuple[str, str]

# Distinctive entry points also match a bound callback with the same name. Common names
# (build, decide, current, install, etc.) are matched by receiver/module below.
CALLS = {
    "hold_screening": "restore",
    "release_own_hold": "restore",
    "restore_db": "restore",
    "start_rebuild": "rebuild",
    "rebuild": "rebuild",
    "_rebuild": "rebuild",
    "run_rebuild_job": "rebuild",
    "http_rebuild": "rebuild",
    "BuildLock": "rebuild",
    "RebuildRequest": "rebuild",
    "rebuild_lake": "rebuild",
    "run_ingest": "ingest",
    "run_local": "ingest",
    "ingest_site": "ingest",
    "_run_ingest": "ingest",
    "_run_in_process": "ingest",
    "IngestRequest": "ingest",
    "run_followed": "ingest",
    "publish_night": "ingest",
    "open_night": "ingest",
    "_write_merged": "backfill",
    "backfill": "backfill",
    "backfill_cmd": "backfill",
    "BackfillReport": "backfill",
    "publish_held": "steward",
    "held_folder": "steward",
    "lake_rows": "builders",
    "omop_rows": "builders",
    "load_night": "builders",
    "load_batch": "builders",
    "merge_patients": "builders",
    "_merge_person": "builders",
    "export_spool": "builders",
    "run_batch": "builders",
    "begin_batch": "builders",
    "index_snapshot": "builders",
    "index_notes": "builders",
    "sync_snapshot": "builders",
    "write_snapshot": "builders",
    "promote_built": "pointer",
    "_point_alias": "pointer",
    "_write_generation": "pointer",
    "_newest_generation": "generation",
    "generation_of": "generation",
    "night_of": "generation",
    "require_approved": "jobs",
    "run_screen": "jobs",
}
KEYS = {"generation", "lake_generation", "serving_generation", "current_generation"}
GATE = "tb_common.screening_inputs.admit_screening_inputs"
PIN = "orchestrator.jobs.PinnedLake.admit_screen"
START = "orchestrator.scenarios.screen.start_screen"

# Operations with common method names, matched by resolved module/class as well as the
# distinctive contracts above. Includes the adapter's merge and the two lake builders.
QUALIFIED = {
    "adapter.ndjson.list_snapshots": "generation",
    "adapter.pipeline._current": "generation",
    "adapter.publish._current": "generation",
    "omop.export._export": "builders",
    "omop.export.export_rows": "builders",
    "omop.load.resolve_conflict": "steward",
    "omop.load.set_status": "steward",
    "omop.conflicts.resolve": "steward",
    "sitesetup.service.SiteSetup.decide": "steward",
    "sitesetup.service.SiteSetup.resolve": "steward",
    "sitesetup.store.SetupStore.decide": "steward",
    "tb_contracts.landing.ServingPointer": "pointer",
    "orchestrator.derive.after_ingest": "builders",
    "patient_profile.twin.after_ingest": "builders",
    "criteria_compiler.repo.RulesetRepo.tag": "importer",
    "criteria_compiler.repo.RulesetRepo._tag": "importer",
    "criteria_compiler.repo.RulesetRepo._tag_seeded": "importer",
    "criteria_compiler.service.Compiler._approve": "importer",
    "adapter.ndjson._write_type": "builders",
    "adapter.dual_write._load": "builders",
    "adapter.backfill._merged": "backfill",
    "adapter.backfill._publish": "backfill",
    "omop.load._load": "builders",
    "omop.load._stage": "builders",
    "omop.load._Builder.build": "builders",
    "datacore.generations.guarded": "builders",
    "patient_profile.twin.build": "builders",
    "criteria_compiler.import_ruleset.install": "importer",
    "lake.app._launch": "rebuild",
    "lake.app._command": "rebuild",
    "adapter.app._run_command": "ingest",
    "lake.app._named": "generation",
    "lake.store.Lake._build": "builders",
    "lake.store.Lake._point_alias": "pointer",
    "lake.source.rebuild_source": "builders",
    "omop.export._emit_all": "builders",
    "adapter.backfill._spool": "backfill",
    "lake.client.LakeHttp._named": "generation",
    "criteria_compiler.repo.RulesetRepo.materialize_all": "importer",
    "datacore.dataops.DataOps.decide": "steward",
    "sitesetup.service.SiteSetup.publish": "rebuild",
    "omop.load._Builder": "builders",
    "vec.index.embed_missing": "builders",
    "tb_common.derived_store.DerivedStore.recompute": "builders",
}
HTTP = {
    "/rebuild": "rebuild",
    "/promote": "pointer",
    "/publish": "steward",
    "/run": "ingest",
    "/ops/ingest": "ingest",
    "/backfill": "backfill",
    "/holds": "generation",
    "/query": "generation",
    "/chunks/search": "generation",
    "/vec/s2b": "generation",
}
POINTER = re.compile(r"(?:^|[/\.])CURRENT(?:$|\.)")


def _qualified(path: str) -> str:
    return path.split("/", 1)[-1].removesuffix(".py").replace("/", ".")


class Scanner(ast.NodeVisitor):
    def __init__(self, file: str) -> None:
        self.file = file
        self.module = _qualified(file)
        self.names: dict[str, str] = {}
        self.scope: list[str] = []
        self.hits: dict[Location, Counter[str]] = {}
        self.tokens: set[str] = set()
        self.permitted_name: str | None = None
        self.probes: Counter[str] = Counter()
        self.started = False

    def probe(self, area: str) -> None:
        self.probes[area] += 1

    def hit(self, area: str, count: int = 1) -> None:
        self.hits.setdefault((self.file, ".".join(self.scope) or "<module>"), Counter())[area] += count

    def uses_permit(self, n: ast.AST | None) -> bool:
        if isinstance(n, ast.Name):
            return n.id in self.tokens
        # The date stored with a pin is derived from the admitted generation.
        if isinstance(n, ast.Call) and self.symbol(n.func) == "datetime.date.fromisoformat" and len(n.args) == 1:
            snap = n.args[0]
            return (
                isinstance(snap, ast.Attribute)
                and snap.attr == "snapshot"
                and isinstance(snap.value, ast.Call)
                and self.symbol(snap.value.func) == "tb_common.generation.Generation.parse"
                and len(snap.value.args) == 1
                and self.uses_permit(snap.value.args[0])
            )
        return False

    def symbol(self, n: ast.AST | None) -> str:
        if isinstance(n, ast.Name):
            return self.names.get(n.id, n.id)
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.Attribute):
            return f"{self.symbol(n.value)}.{n.attr}"
        if isinstance(n, ast.Call):
            name = self.symbol(n.func)
            if name == "functools.partial" and n.args:
                return self.symbol(n.args[0])
            if name == "getattr" and len(n.args) >= 2:
                return f"{self.symbol(n.args[0])}.{self.symbol(n.args[1])}"
            if name.endswith(("Path", ".with_name", ".joinpath")) and n.args:
                return "/".join(self.symbol(a) for a in n.args)
            if name.endswith((".setdefault", ".get")) and n.args:
                return f"{name.rsplit('.', 1)[0]}.{self.symbol(n.args[0])}"
            return name
        if isinstance(n, ast.Subscript):
            return f"{self.symbol(n.value)}.{self.symbol(n.slice)}"
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div | ast.Add):
            return self.symbol(n.left) + ("/" if isinstance(n.op, ast.Div) else "") + self.symbol(n.right)
        if isinstance(n, ast.JoinedStr):
            return "".join(self.symbol(v) for v in n.values)
        if isinstance(n, ast.FormattedValue):
            return self.symbol(n.value)
        if isinstance(n, ast.BoolOp):
            return self.symbol(n.values[0])
        return "*"

    def declarations(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                self.names[stmt.name] = ".".join((self.module, *self.scope, stmt.name))

    def visit_Module(self, n: ast.Module) -> None:
        self.declarations(n.body)
        self.generic_visit(n)

    def visit_Import(self, n: ast.Import) -> None:
        for a in n.names:
            self.names[a.asname or a.name] = a.name

    def visit_ImportFrom(self, n: ast.ImportFrom) -> None:
        module = n.module or ""
        if n.level:
            package = self.module.split(".")[: -n.level]
            module = ".".join([*package, *([module] if module else [])])
        for a in n.names:
            self.names[a.asname or a.name] = f"{module}.{a.name}"

    def bind(self, target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.tokens.discard(target.id)
            if target.id == self.permitted_name:
                self.permitted_name = None
            symbol = self.symbol(value)
            if symbol != "*":
                self.names[target.id] = symbol
        elif isinstance(target, ast.Tuple | ast.List) and isinstance(value, ast.Tuple | ast.List):
            for dest, src in zip(target.elts, value.elts, strict=False):
                self.bind(dest, src)

    def assignment(self, target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Tuple | ast.List) and isinstance(value, ast.Tuple | ast.List):
            for dest, src in zip(target.elts, value.elts, strict=False):
                self.assignment(dest, src)
        elif isinstance(target, ast.Attribute) and target.attr in KEYS:
            if not self.uses_permit(value):
                self.hit("generation")
        else:
            self.visit(target)

    def visit_Assign(self, n: ast.Assign) -> None:
        self.visit(n.value)
        for target in n.targets:
            self.assignment(target, n.value)
            self.bind(target, n.value)
            if isinstance(target, ast.Subscript):
                self.job(self.symbol(target.slice), self.symbol(n.value))
            if isinstance(target, ast.Tuple) and isinstance(n.value, ast.Call):
                called = self.symbol(n.value.func)
                if called in (GATE, PIN, START) and len(target.elts) == 2:
                    self.tokens.update(elt.id for elt in target.elts if isinstance(elt, ast.Name))
                    self.started = called == START
                    if (
                        called == PIN
                        and self.module == "orchestrator.scenarios.screen"
                        and self.scope == ["start_screen"]
                    ):
                        # The candidate generation and approved rule are inputs to this pin.
                        self.probes.clear()
                    first = target.elts[0]
                    self.permitted_name = first.id if called != START and isinstance(first, ast.Name) else None

    def visit_AnnAssign(self, n: ast.AnnAssign) -> None:
        if n.value is not None:
            self.visit(n.value)
            self.assignment(n.target, n.value)
            self.bind(n.target, n.value)

    def visit_ClassDef(self, n: ast.ClassDef) -> None:
        self.names[n.name] = f"{self.module}.{n.name}"
        self.scope.append(n.name)
        self.declarations(n.body)
        for stmt in n.body:
            self.visit(stmt)
        self.scope.pop()

    def visit_FunctionDef(self, n: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names[n.name] = ".".join((self.module, *self.scope, n.name))
        outer_names = self.names.copy()
        outer_state = self.tokens, self.probes, self.started, self.permitted_name
        for param in n.args.args:
            typ = self.symbol(param.annotation)
            self.names[param.arg] = typ if typ not in {"*", "Any", "typing.Any"} else param.arg
        if self.scope and n.args.args and n.args.args[0].arg == "self":
            self.names["self"] = ".".join((self.module, *self.scope))
        self.scope.append(n.name)
        self.tokens, self.probes, self.started, self.permitted_name = set(), Counter(), False, None
        self.declarations(n.body)
        for dec in n.decorator_list:
            if isinstance(dec, ast.Call) and self.symbol(dec.func).endswith(".post"):
                self.endpoint([self.symbol(arg) for arg in dec.args])
        for stmt in n.body:
            self.visit(stmt)
        for area, count in self.probes.items():
            self.hit(area, count)
        self.scope.pop()
        self.names = outer_names
        self.tokens, self.probes, self.started, self.permitted_name = outer_state

    def visit_AsyncFunctionDef(self, n: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(n)

    def key(self, key: str) -> None:
        if key.rsplit(".", 1)[-1] in KEYS | {"GENERATION_OPTION", "GENERATION_HEADER", "X-TB-Lake-Generation"}:
            self.hit("generation")

    def visit_BoolOp(self, n: ast.BoolOp) -> None:
        if isinstance(n.op, ast.Or) and any(self.symbol(v).endswith(".pinned") for v in n.values):
            self.probe("generation")
        self.generic_visit(n)

    def visit_JoinedStr(self, n: ast.JoinedStr) -> None:
        if self.module != "tb_common.generation" and any(
            isinstance(v, ast.Constant) and v.value == ".g" for v in n.values
        ):
            self.hit("generation")
        self.generic_visit(n)

    def visit_Subscript(self, n: ast.Subscript) -> None:
        self.key(self.symbol(n.slice))
        self.generic_visit(n)

    def visit_Dict(self, n: ast.Dict) -> None:
        for key, value in zip(n.keys, n.values, strict=True):
            if not self.uses_permit(value):
                self.key(self.symbol(key))
            self.job(self.symbol(key), self.symbol(value))
        self.generic_visit(n)

    def job(self, key: str, value: str) -> None:
        if key == "type" and value == "INGEST":
            self.hit("ingest")

    def visit_Call(self, n: ast.Call) -> None:
        name = self.symbol(n.func)
        method = name.rsplit(".", 1)[-1]
        args = [self.symbol(a) for a in n.args]
        for kw in n.keywords:
            if kw.arg:
                if method == "update" and kw.arg == "snapshot_date" and not self.uses_permit(kw.value):
                    self.hit("jobs")
                if method in {"dict", "update", "model_copy", "PinnedLake", "RebuildResult"} and not self.uses_permit(
                    kw.value
                ):
                    forwards_build = (
                        name == "tb_contracts.RebuildResult"
                        and kw.arg == "generation"
                        and self.symbol(kw.value) == "lake.store.Lake.rebuild.generation"
                        and any(
                            k.arg == "snapshot" and self.symbol(k.value) == "lake.store.Lake.rebuild.snapshot"
                            for k in n.keywords
                        )
                    )
                    if not forwards_build:
                        self.key(kw.arg)
                self.job(kw.arg, self.symbol(kw.value))
        if (
            self.module == "tb_common.screening_inputs"
            and self.scope == ["admit_screening_inputs"]
            and name.endswith(".options.get")
            and args == ["lake_generation"]
        ):
            self.generic_visit(n)
            return
        if method in {"get", "setdefault", "pop", "__setitem__", "setattr", "__getitem__"} and args:
            self.key(args[1] if method == "setattr" and len(args) > 1 else args[0])
        if method == "set" and args[:1] == ["screening.after_restore"]:
            self.hit("restore")
        if name == "operator.setitem" and len(args) == 3:
            self.key(args[1])
        if method in {"dict", "update"} and n.args and isinstance(n.args[0], ast.List | ast.Tuple):
            for pair in n.args[0].elts:
                if isinstance(pair, ast.Tuple | ast.List) and len(pair.elts) == 2:
                    self.key(self.symbol(pair.elts[0]))
        if name == "heapq.merge" and self.module in {"adapter.ndjson", "adapter.backfill"}:
            self.hit("backfill" if self.module == "adapter.backfill" else "builders")
        if (
            method == "isinstance"
            and args[1:] == ["orchestrator.jobs.PinnedLake"]
            and (self.module == "orchestrator.scenarios.screen" and self.scope == ["start_screen"])
        ):
            self.probe("jobs")
        if method in {"query", "chunks_search", "vec_s2b", "search"} and "lake" in name.lower():
            receiver = name.rsplit(".", 1)[0]
            metadata = (
                self.module == "tb_common.screening_inputs"
                and self.scope == ["admit_screening_inputs"]
                and args == ["SELECT lake_inventory, omop_inventory FROM lake_meta"]
                and method == "query"
                and receiver.endswith(".orch.services.lake")
                and len(n.keywords) == 1
                and n.keywords[0].arg == "snapshot"
                and self.symbol(n.keywords[0].value) == "orchestrator.scenarios.screen.screening_use.generation"
            )
            if receiver != "orchestrator.core.Ctx.services.lake" and not metadata:
                self.hit("generation")
        if name in QUALIFIED:
            self.hit(QUALIFIED[name])
        if method == "require_approved":
            self.probes["jobs"] += 1
        elif method in CALLS and name != "tb_common.provenance_index.rebuild" and not self.permitted_call(n, method):
            self.hit(CALLS[method])
        if method == "promote" and "registry" not in name.lower():
            self.hit("importer" if "repo" in name else "pointer")
        if method == "PinnedLake" and not self.tokens:
            self.probe("generation")
        if method == "generation" and not (
            self.module == "tb_common.screening_inputs"
            and self.scope == ["admit_screening_inputs"]
            and name
            in {
                "orchestrator.core.screening_worker.orch.services.lake.generation",
                "orchestrator.core.screening_worker.orch.services.lake.lake.generation",
            }
            and any(
                k.arg == "recover" and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords
            )
        ):
            self.probe("generation")
        if (
            method == "hold"
            and ("lake" in name.lower() or any(k.arg == "pin" for k in n.keywords))
            and not self.permitted_call(n, method)
        ):
            self.hit("generation")
        if (
            method in {"snapshot", "current", "pin"}
            and ("lake" in name.lower() or self.file.startswith("services/lake/"))
            and not self.started
        ):
            self.probe("generation")
        if method in {"flatten", "stream"} and "Flattener" in name:
            self.hit("builders")
        if method in {"materialize", "retag"} or (method == "write_dir" and args[:1] == ["main"]):
            self.hit("importer")
        if method == "decide" and (
            "dataops" in self.module or "dataops" in name.lower() or "promote" in {k.arg for k in n.keywords}
        ):
            self.hit("steward")
        if method in {"publish", "run", "build", "begin"}:
            self.callback(name, method)
        if method in {"ingest", "run_ingest"} or (method == "add_job" and "INGEST" in ast.unparse(n)):
            self.hit("ingest")
        if method == "execute" and args and re.search(r"(?:INSERT INTO|UPDATE) (?:built|built_kept) ", args[0], re.I):
            self.hit("builders")
        if (
            method == "execute"
            and args
            and re.match(
                r"UPDATE (?:tb_conflict SET state = 'resolved'|tb_record SET status|fact SET status = \?)",
                args[0],
                re.I,
            )
        ):
            self.hit("steward")
        if method == "replace" and args and args[0].endswith(".duckdb") and ("/db/" in args[0] or "lake" in name):
            self.hit("pointer")
        if method == "rename" and name.startswith("criteria_compiler.repo.RulesetRepo.path"):
            self.hit("importer")
        if method == "approve" and "compiler" in name.lower():
            self.hit("importer")
        if method == "begin" and args[:1] in (["fhir"], ["derived"], ["vec"], ["twin"]):
            self.hit("builders")
        if method in {"read_text", "read_bytes"} and POINTER.search(name):
            self.probe("generation")
        if method in {"post", "post_json", "post_raw", "_call", "_ask", "request"}:
            self.endpoint(args)
        if method in {
            "write_text",
            "write_bytes",
            "replace",
            "rename",
            "symlink_to",
            "symlink",
            "link",
            "copy",
            "copy2",
            "copyfile",
            "open",
        }:
            targets = (
                [name, *args]
                if method == "open"
                else [name]
                if method.startswith("write") or method == "symlink_to"
                else args[-1:]
            )
            modes = [*args, *(self.symbol(k.value) for k in n.keywords if k.arg == "mode")]
            writes = method != "open" or any(re.fullmatch(r"[wax][bt+]?", a) for a in modes)
            if writes and any(POINTER.search(t) for t in targets):
                self.hit("pointer")
        self.generic_visit(n)

    def permitted_call(self, n: ast.Call, method: str) -> bool:
        if method == "run_screen":
            return (
                self.started
                and len(n.args) > 1
                and self.uses_permit(n.args[1])
                and any(k.arg == "admitted_scope" and self.uses_permit(k.value) for k in n.keywords)
            )
        generation = next((k.value for k in n.keywords if k.arg == "generation"), n.args[0] if n.args else None)
        return (
            isinstance(generation, ast.Name) and generation.id == self.permitted_name and generation.id in self.tokens
        )

    def callback(self, name: str, method: str) -> None:
        if method == "begin" and ("Built" in name or "book." in name or "ledger." in name):
            self.hit("builders")
        if method == "build" and ("cfg." in name or "twin" in name):
            self.hit("builders")
        if method == "publish" and (
            "adapter" in name or "SiteSetup" in name or "sitesetup" in name or self.module == "orchestrator.setup_api"
        ):
            self.hit("steward")
        if method == "run" and "adapter" in name:
            self.hit("ingest")

    def endpoint(self, args: list[str]) -> None:
        if args and args[0].lower() == "get":
            return
        for arg in args:
            path = urlsplit(arg).path if "://" in arg else arg
            # HTTP clients often use f"{self.base}/rebuild" or base + "/promote".
            if not path.startswith("/"):
                _, slash, suffix = path.partition("/")
                path = slash + suffix
            if path in HTTP:
                self.hit(HTTP[path])
            if path.endswith("/decide") and ("/dataops/" in path or "/data-ops/" in path):
                self.hit("steward")
            if path.endswith("/resolve") and ("/omop/conflicts/" in path or "/data/conflicts/" in path):
                self.hit("steward")

    def branch(self, statements: list[ast.stmt]) -> None:
        # A gate inside one branch cannot authorize a sibling or the code after the branch.
        tokens, probes, started, generation = self.tokens.copy(), self.probes.copy(), self.started, self.permitted_name
        self.probes = Counter()
        for stmt in statements:
            self.visit(stmt)
        for area, count in self.probes.items():
            self.hit(area, count)
        self.tokens, self.probes, self.started = tokens & self.tokens, probes, started
        self.permitted_name = generation if generation in self.tokens else None

    def visit_If(self, n: ast.If) -> None:
        self.visit(n.test)
        self.branch(n.body)
        self.branch(n.orelse)
        if isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not) and isinstance(n.test.operand, ast.Call):
            test = n.test.operand
            if (
                self.symbol(test.func) == "isinstance"
                and len(test.args) == 2
                and isinstance(test.args[0], ast.Name)
                and isinstance(n.body[-1], ast.Raise)
            ):
                self.names[test.args[0].id] = self.symbol(test.args[1])

    def visit_AsyncFor(self, n: ast.AsyncFor) -> None:
        self.visit_For(n)

    def visit_For(self, n: ast.For | ast.AsyncFor) -> None:
        self.visit(n.iter)
        self.branch(n.body)
        self.branch(n.orelse)

    def visit_While(self, n: ast.While) -> None:
        self.visit(n.test)
        self.branch(n.body)
        self.branch(n.orelse)

    def visit_Match(self, n: ast.Match) -> None:
        self.visit(n.subject)
        for case in n.cases:
            self.branch(case.body)

    def visit_Try(self, n: ast.Try) -> None:
        self.branch(n.body)
        for handler in n.handlers:
            self.branch(handler.body)
        self.branch(n.orelse)
        self.branch(n.finalbody)


def scan_source(file: str, source: str) -> dict[Location, Counter[str]]:
    scanner = Scanner(file)
    scanner.visit(ast.parse(source, filename=file))
    for area, count in scanner.probes.items():
        scanner.hit(area, count)
    return scanner.hits


def scan(files: Iterable[tuple[str, str]]) -> dict[Location, Counter[str]]:
    hits: dict[Location, Counter[str]] = {}
    for name, source in files:
        hits.update(scan_source(name, source))
    return hits


def working_tree() -> dict[Location, Counter[str]]:
    return scan(
        (p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
        for folder in ("libs", "services", "tools")
        for p in sorted((ROOT / folder).rglob("*.py"))
    )


def inventory(data: bytes) -> set[Location]:
    entries = json.loads(data)
    result: set[Location] = set()
    for row in entries:
        if not row["why"].strip() or (row["file"], row["function"]) in result:
            raise ValueError("empty rationale or duplicate screening-input ratchet entry")
        result.add((row["file"], row["function"]))
    return result


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def base_revision() -> str:
    return (
        git("rev-parse", "--verify", "--end-of-options", os.environ.get(BASE_ENV, "origin/master") + "^{commit}")
        .decode()
        .strip()
    )


def base_files(base: str) -> Iterator[tuple[str, str]]:
    # git archive runs under trialbox/ and gives the committed files relative to it.
    archive = git("archive", "--format=tar", base, "libs", "services", "tools")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for member in tree:
            if member.isfile() and member.name.endswith(".py"):
                blob = tree.extractfile(member)
                assert blob is not None
                yield member.name, blob.read().decode()


def check_ratchet() -> None:
    found = working_tree()
    listed = inventory((ROOT / RATCHET).read_bytes())
    if listed != found.keys():
        raise AssertionError(f"unlisted: {sorted(found.keys() - listed)}; obsolete: {sorted(listed - found.keys())}")
    base = base_revision()
    original = scan(base_files(base))
    # On the first slice the base has no inventory. Later slices must also respect rows
    # removed from the committed ratchet. Neither a changed JSON file nor a second sink
    # in an existing function buys permission to grow.
    if git("ls-tree", base, "--", RATCHET).strip():
        prefix = git("rev-parse", "--show-prefix").decode().strip()
        allowed = inventory(git("show", f"{base}:{prefix}{RATCHET}"))
    else:
        allowed = set(original)
    growth = {loc: counts - original.get(loc, Counter()) for loc, counts in found.items()}
    new = {loc for loc, added in growth.items() if added} | (listed - allowed)
    if new:
        raise AssertionError(f"new screening-input bypasses since {base}: {sorted(new)}")


if __name__ == "__main__":
    check_ratchet()

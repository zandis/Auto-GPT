"""NEW-ARCH-18 (ARCH-021, D-543): every store's schema is on the role list of the service that opens it.

A service signs in to the trial database as its own role and reaches only the schemas on its list
(``deploy/docker/db-init/30-service-roles.sh``, D-378). A store opened by a service whose role is not on the
schema's list works in every test (one role there) and fails on a box. This test reads the code: every
``Database.connect(url, <schema>)`` in ``services/`` and ``libs/``, and for each service with a role every module
its process can import.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from tests.unit.test_db_roles import ACCESS, SCHEMAS, _as, roles_cluster  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
#: the folder of each service that has a database role of its own (D-378)
ROLE_OF = {"console": "tb_console", "orchestrator": "tb_orchestrator", "mail_gateway": "tb_mail_gateway",
           "gateway": "tb_gateway", "lake": "tb_lake", "adapter": "tb_adapter",
           "criteria_compiler": "tb_criteria_compiler"}  # fmt: skip
#: a helper that opens the schema its caller names: (module, parameter) -> what the scan reads instead
DYNAMIC = {
    ("console.storedb", "schema"): "open_db(url, <schema>, ...): every call of it is read (a literal second argument)",
    ("omop.schema", "name"): "connect(url, name=SCHEMA): the default is read; another name is a rerun's scratch schema",
    ("orchestrator.db", "name"): "JobLease (D-532): a second connection to the store its JobDB opened; no other schema",
    ("orchestrator.db", "schema"): "JobDB(url, schema=SCHEMA_NAME): the default is read",
    ("orchestrator.db_pg", "schema"): "the workflow backend: the default (wf) is read; the recall ledger names its own",
    ("sitesetup.service", "name"): "Reset (D-714): a practice space's own OMOP store, omop_<hash> of its lake folder "
    "(omop.schema.schema_for), opened only to drop it and only when it exists",
}
#: opened through the workflow backend by a name held in another constant (orchestrator.recall.ledger.LEDGER_SCHEMA)
BACKEND_SCHEMAS = {"recall"}


#: a store's module that a service loads and never opens: (service, schema) -> why. Read once, by a person.
_LAKE_CASCADE = (
    "lake.client loads vec.s2b for two names, and vec.s2b loads the matching cascade for its S2b types; the cascade's "
    "engine imports {what}. The lake never runs the cascade: the orchestrator does, and passes it the rows."
)
LOADED_NOT_OPENED = {
    ("lake", "derived"): _LAKE_CASCADE.format(what="tb_common.derived_store for three type names"),
    ("lake", "optout"): _LAKE_CASCADE.format(what="tb_common.optout (the opt-out filter of a screening run)"),
    ("lake", "pidmap"): _LAKE_CASCADE.format(what="tb_common.optout, which reads the pid map's aliases"),
}
#: on a list and opened by no code: why it is still listed
LISTED_ONLY = {
    "mpi": "retired with the second ingest stack (D-381); still listed so that a volume that has the schema keeps "
    "its group and owner, and nothing opens it",
}


def _modules() -> dict[str, Path]:
    out = {}
    for base in ("services", "libs"):
        for f in (ROOT / base).rglob("*.py"):
            rel = f.relative_to(ROOT / base).with_suffix("")
            out[".".join(rel.parts[:-1] if rel.name == "__init__" else rel.parts)] = f
    return out


MODS = _modules()


def _opened(f: Path) -> set[str]:
    """The schemas one module opens. A literal or a module constant in ``Database.connect(url, <schema>)``; for a
    helper that takes the schema as a parameter, that parameter's default and ``?<parameter>``; and the second
    argument of every call of ``open_db`` (the console's helper). Read wherever the call stands (a function, an
    ``async`` one, the module's own body) and however the schema is passed (second argument, ``name=`` or
    ``schema=``); a schema the scan cannot read is a ``?`` entry, never dropped (the review's M3)."""
    tree = ast.parse(f.read_text(encoding="utf-8"))
    consts = {t.id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}  # fmt: skip
    for n in tree.body:  # an annotated constant: SCHEMA: str = "x"
        if (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)):  # fmt: skip
            consts[n.target.id] = n.value.value

    def text_of(a: ast.AST | None) -> str | None:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        return consts.get(a.id) if isinstance(a, ast.Name) else None

    def is_connect(func: ast.AST) -> bool:
        if not (isinstance(func, ast.Attribute) and func.attr == "connect"):
            return False
        v = func.value  # Database.connect or <module>.Database.connect
        return (isinstance(v, ast.Name) and v.id == "Database") or (
            isinstance(v, ast.Attribute) and v.attr == "Database"
        )

    def is_open_db(func: ast.AST) -> bool:
        return (isinstance(func, ast.Name) and func.id == "open_db") or (
            isinstance(func, ast.Attribute) and func.attr == "open_db"
        )

    def schema_arg(n: ast.Call, names: tuple[str, ...]) -> ast.AST | None:
        if len(n.args) >= 2:
            return n.args[1]
        return next((k.value for k in n.keywords if k.arg in names), None)

    out: set[str] = set()

    def read(scope: ast.AST, defaults: dict[str, ast.AST | None]) -> None:
        for n in ast.iter_child_nodes(scope):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [*n.args.posonlyargs, *n.args.args]
                own: dict[str, ast.AST | None] = dict.fromkeys((a.arg for a in args), None)
                own.update(zip([a.arg for a in args][len(args) - len(n.args.defaults) :], n.args.defaults, strict=True))
                own.update({a.arg: d for a, d in zip(n.args.kwonlyargs, n.args.kw_defaults, strict=True)})
                read(n, {**defaults, **own})
                continue
            if isinstance(n, ast.Call) and (is_connect(n.func) or is_open_db(n.func)):
                a = schema_arg(n, ("name", "schema"))
                if a is None:
                    out.add("?" + ast.unparse(n)[:60])  # no schema the scan can see
                elif got := text_of(a):
                    out.add(got)
                elif isinstance(a, ast.Name) and a.id in defaults:
                    out.add("?" + a.id)
                    if got := text_of(defaults[a.id]):
                        out.add(got)
                else:
                    out.add("?" + ast.unparse(a))
            read(n, defaults)

    read(tree, {})
    return out


OPENED = {m: _opened(f) for m, f in MODS.items()}


def _module_level(tree: ast.Module) -> list[ast.stmt]:
    """The statements that run at import: the module's body, and what sits in its ``if`` / ``try`` / ``with``."""
    out: list[ast.stmt] = []
    todo = list(tree.body)
    while todo:
        n = todo.pop()
        out.append(n)
        if isinstance(n, (ast.If, ast.Try, ast.With)):
            todo += [*n.body, *getattr(n, "orelse", []), *getattr(n, "finalbody", []),
                     *(s for h in getattr(n, "handlers", []) for s in h.body)]  # fmt: skip
    return out


def _imports(f: Path, nested: bool = True) -> set[str]:
    tree = ast.parse(f.read_text(encoding="utf-8"))
    named: set[str] = set()
    for n in ast.walk(tree) if nested else _module_level(tree):
        if isinstance(n, ast.Import):
            named |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            named |= {n.module, *(f"{n.module}.{a.name}" for a in n.names)}
    return {".".join(m.split(".")[:i]) for m in named for i in range(1, m.count(".") + 2)} & set(MODS)


def _closure(service: str) -> set[str]:
    """Every module the service's process can run: its own package's imports wherever they stand, and in another
    package only the imports at module level (those run when the module is loaded; an import inside a function of
    another package runs only if the service calls that function, which a reading of the text cannot know). The
    same rule as the table test of who writes which audit family (``test_audit_roles``): the console imports
    ``orchestrator.candidates`` for two constants and would otherwise be held to everything the orchestrator's
    own functions import."""
    seen: set[str] = set()
    todo = {m for m in MODS if m == service or m.startswith(service + ".")}
    while todo:
        m = todo.pop()
        seen.add(m)
        own = m == service or m.startswith(service + ".")
        todo |= _imports(MODS[m], nested=own) - seen
    return seen


def test_every_schema_the_code_opens_is_on_a_role_list() -> None:
    literal = {s for v in OPENED.values() for s in v if not s.startswith("?")}
    assert literal, "the scan found no Database.connect call: it reads nothing"
    assert literal <= set(SCHEMAS), f"opened by the code and on no role's list: {sorted(literal - set(SCHEMAS))}"
    assert set(SCHEMAS) >= BACKEND_SCHEMAS
    # and the other way: a schema on a list that no code opens is a left-over (or the scan lost a store)
    unread = set(SCHEMAS) - literal - BACKEND_SCHEMAS
    assert unread == set(LISTED_ONLY), f"on a role's list and opened by no code the scan reads: {sorted(unread)}"
    from orchestrator.recall.ledger import LEDGER_SCHEMA

    assert {LEDGER_SCHEMA} == BACKEND_SCHEMAS
    dynamic = {(m, s[1:]) for m, v in OPENED.items() for s in v if s.startswith("?")}
    assert dynamic == set(DYNAMIC), (
        f"a schema named at run time: say why in DYNAMIC, or name it: {sorted(dynamic ^ set(DYNAMIC))}"
    )
    assert all(why.strip() for why in DYNAMIC.values())


@pytest.mark.parametrize("service", sorted(ROLE_OF))
def test_a_service_opens_only_schemas_on_its_own_list(service: str) -> None:
    """Everything the service's process can import, for every service (the review's M1: the lake opens ``vec`` and
    ``omop`` through the shared packages, not in its own folder), and the workflow backend's ledger for the role
    that runs it (LOW-1)."""
    from orchestrator.recall.ledger import LEDGER_SCHEMA

    role = ROLE_OF[service]
    mods = _closure(service)
    missing = {s: sorted(m for m in mods if s in OPENED[m])
               for m in mods for s in OPENED[m] if not s.startswith("?") and s not in ACCESS[role]}  # fmt: skip
    if "orchestrator.recall.ledger" in mods and LEDGER_SCHEMA not in ACCESS[role]:
        missing[LEDGER_SCHEMA] = ["orchestrator.recall.ledger"]
    excused = {sch for (svc, sch) in LOADED_NOT_OPENED if svc == service}
    assert excused <= set(missing), f"no longer needed in LOADED_NOT_OPENED: {sorted(excused - set(missing))}"
    missing = {k: v for k, v in missing.items() if k not in excused}
    assert missing == {}, f"{role} opens a store its role cannot reach on a box: {missing}"


def test_the_scan_reads_every_way_a_store_is_opened(tmp_path: Path) -> None:
    """The review's M3: each of these was missed and passed. A schema the scan cannot read is a ``?`` entry."""
    cases = {
        'from tb_common.db import Database\nDB = Database.connect(URL, "edc")\n': {"edc"},
        'async def f():\n    return Database.connect(url, "edc")\n': {"edc"},
        'def f():\n    return Database.connect(url=u, name="edc")\n': {"edc"},
        'def f():\n    return Database.connect(u, name="edc")\n': {"edc"},
        'import tb_common.db\ndef f():\n    return tb_common.db.Database.connect(u, "edc")\n': {"edc"},
        'def f():\n    return storedb.open_db(u, "edc", [])\n': {"edc"},
        'import os\ndef f():\n    return open_db(u, os.environ["X"], [])\n': {"?os.environ['X']"},
        'S: str = "edc"\ndef f():\n    return Database.connect(u, S)\n': {"edc"},
        'def f(u, schema="edc"):\n    return open_db(u, schema, [])\n': {"edc", "?schema"},
        "def f():\n    return Database.connect(u)\n": {"?Database.connect(u)"},
    }
    for i, (text, want) in enumerate(cases.items()):
        f = tmp_path / f"m{i}.py"
        f.write_text(text, encoding="utf-8")
        assert _opened(f) == want, text


def test_arch021_the_console_opens_the_twin_store_and_both_hosts_the_not_matched_store(
    roles_cluster: tuple[Path, str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finding as it was run: on a cluster with the real role script, `ProfileStore()` as the console's role
    failed with "no schema has been selected to create in"; `tuned` was on no list."""
    from patient_profile.twin import ProfileStore
    from tb_common.notmatched import NotMatchedStore

    url = roles_cluster[1]
    for key in [k for k in os.environ if k.startswith("PG")]:
        monkeypatch.delenv(key)
    ProfileStore(_as(url, "tb_orchestrator")).close()  # the orchestrator builds the twin
    ProfileStore(_as(url, "tb_console")).close()  # the console reads it (GET .../patients/{pid}/twin)
    for role in ("tb_console", "tb_orchestrator"):
        NotMatchedStore(_as(url, role)).close()

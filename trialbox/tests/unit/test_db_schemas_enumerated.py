"""NEW-ARCH-18 (ARCH-021, D-543): every store's schema is on the role list of the service that opens it.

A service signs in to the trial database as its own role and reaches only the schemas on its list
(``deploy/docker/db-init/30-service-roles.sh``, D-378). A store opened by a service whose role is not on the
schema's list works in every test (one role there) and fails on a box. This test reads the code: every
``Database.connect(url, <schema>)`` in ``services/`` and ``libs/``, and for the console and the orchestrator
(which host the shared stores) every module their process can import.
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
HOSTS = ("console", "orchestrator")  # their processes import the shared stores: everything they can run is checked
#: a helper that opens the schema its caller names: (module, parameter) -> what the scan reads instead
DYNAMIC = {
    ("console.storedb", "schema"): "open_db(url, <schema>, ...): every call of it is read (a literal second argument)",
    ("omop.schema", "name"): "connect(url, name=SCHEMA): the default is read; another name is a rerun's scratch schema",
    ("orchestrator.db", "schema"): "JobDB(url, schema=SCHEMA_NAME): the default is read",
    ("orchestrator.db_pg", "schema"): "the workflow backend: the default (wf) is read; the recall ledger names its own",
}
#: opened through the workflow backend by a name held in another constant (orchestrator.recall.ledger.LEDGER_SCHEMA)
BACKEND_SCHEMAS = {"recall"}


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
    helper that takes the schema as a parameter, that parameter's default and ``?<parameter>``; and the literal
    second argument of every call of ``open_db`` (the console's helper)."""
    tree = ast.parse(f.read_text(encoding="utf-8"))
    consts = {t.id: n.value.value for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}  # fmt: skip

    def text_of(a: ast.AST | None) -> str | None:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
        return consts.get(a.id) if isinstance(a, ast.Name) else None

    out: set[str] = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        args = [*fn.args.posonlyargs, *fn.args.args]
        defaults: dict[str, ast.AST | None] = dict.fromkeys((a.arg for a in args), None)
        defaults.update(zip([a.arg for a in args][len(args) - len(fn.args.defaults) :], fn.args.defaults, strict=True))
        defaults.update({a.arg: d for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True)})
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and len(n.args) >= 2):
                continue
            func = n.func
            if isinstance(func, ast.Name) and func.id == "open_db" and (got := text_of(n.args[1])):
                out.add(got)
            if not (isinstance(func, ast.Attribute) and func.attr == "connect"
                    and isinstance(func.value, ast.Name) and func.value.id == "Database"):  # fmt: skip
                continue
            a = n.args[1]
            if got := text_of(a):
                out.add(got)
            elif isinstance(a, ast.Name) and a.id in defaults:
                out.add("?" + a.id)
                if got := text_of(defaults[a.id]):
                    out.add(got)
            else:
                out.add("?" + ast.unparse(a))
    return out


OPENED = {m: _opened(f) for m, f in MODS.items()}


def _imports(f: Path) -> set[str]:
    named: set[str] = set()
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            named |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            named |= {n.module, *(f"{n.module}.{a.name}" for a in n.names)}
    return {".".join(m.split(".")[:i]) for m in named for i in range(1, m.count(".") + 2)} & set(MODS)


def _closure(service: str) -> set[str]:
    seen: set[str] = set()
    todo = {m for m in MODS if m == service or m.startswith(service + ".")}
    while todo:
        m = todo.pop()
        seen.add(m)
        todo |= _imports(MODS[m]) - seen
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
    role = ROLE_OF[service]
    mods = _closure(service) if service in HOSTS else {m for m in MODS if m == service or m.startswith(service + ".")}
    missing = {s: sorted(m for m in mods if s in OPENED[m])
               for m in mods for s in OPENED[m] if not s.startswith("?") and s not in ACCESS[role]}  # fmt: skip
    assert missing == {}, f"{role} opens a store its role cannot reach on a box: {missing}"


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

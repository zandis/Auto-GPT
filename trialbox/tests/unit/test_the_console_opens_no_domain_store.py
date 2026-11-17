"""NEW-ARCH-3 (D-761): the console reaches the domain stores only through the orchestrator's routes.

The deep review's ARCH-005: a process boundary that is no data boundary. The console imported the orchestrator's
stores and opened them itself, so a compromised or broken console owned the tables, and T-718 (owner is not
writer) and T-715 (the person verified at the callee) could not be finished. This test reads every module of the
console for the classes and functions that open a domain store. Each one left is listed with the slice of
NEW-ARCH-3 that removes it; the list only shrinks: a name gone from the code must leave the list.

A pure helper of another service (a rule, a constant, a dataclass) may be imported: it opens nothing."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"

#: (module, name) that opens a store of another service's schema
OPENERS: set[tuple[str, str]] = {
    ("datacore.dataops", "DataOps"),  # dataops: the night's batches (slice 1, D-761: over /dataops/...)
    ("datacore.dataops", "newest_night"),
    ("datacore", "dataops"),
    ("datacore.generations", "*"),  # it opens DataOps
    ("omop.schema", "connect"),  # omop: the clinical store and its conflicts
    ("omop", "schema"),
    ("omop.conflicts", "*"),
    ("omop", "conflicts"),
    ("sitesetup.store", "SetupStore"),  # sitesetup: the box's switches
    ("orchestrator.db", "JobDB"),  # orch: the jobs
    ("orchestrator.candidates", "CandidateRegistry"),  # the screening registry
}
#: what is left, by file, with the slice that takes it out (only shrinks)
OWED: dict[tuple[str, str, str], str] = {}  # NEW-ARCH-3 slices 2 and 3 (D-865, D-864): none left


def _found() -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for path in sorted(CONSOLE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):  # ``import datacore.dataops as d`` (the review)
                for alias in node.names:
                    parent, _, last = alias.name.rpartition(".")
                    if (parent, last) in OPENERS or (alias.name, "*") in OPENERS or alias.name in ("importlib",):
                        out.add((path.name, alias.name, ""))
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    key = (node.module, alias.name)
                    wild = (node.module, "*")
                    if key in OPENERS or wild in OPENERS or (node.module.startswith("omop") and node.module != "omop"):
                        out.add((path.name, node.module, alias.name))
    return out


def test_no_console_module_opens_a_domain_store_but_the_listed_ones() -> None:
    found = _found()
    new = sorted(found - set(OWED))
    assert not new, f"a console module opens another service's store; use the orchestrator's routes: {new}"
    gone = sorted(set(OWED) - found)
    assert not gone, f"no longer in the code: take them off OWED (the list only shrinks): {gone}"


def test_the_data_operations_page_opens_no_store() -> None:
    text = (CONSOLE / "dataops_page.py").read_text(encoding="utf-8")
    assert not re.search(r"\bDataOps\(|import DataOps\b", text)

"""The role walk (card V-2, plan 8 activity V8): every route of the box, as every role, against the matrix.

    python -m tools.role_walk inproc      # run the walk's tests on the in-process apps, then write the report
    python -m tools.role_walk report      # write the report again from the fragments the last run left
    python -m tools.role_walk live --base-url https://box.example   # walk a running box (accounts from the env)

What it does, in-process (``tests/console/test_matrix_role_walk*.py`` and
``tests/unit/test_matrix_role_walk_orchestrator.py`` call the functions here and leave their results in
``ROLE_WALK_OUT``):

1. **The declared table.** Every route of the console's app object has one row in :data:`DECLARED`: the matrix
   action(s) it must ask, or ``public`` / ``signed_in`` / ``scope``, with the decision that says so. The tests read
   it and never infer it; a route with no row fails. (:func:`infer` and :func:`draft_table`, over a walk traced by
   :class:`Tracer`, made the first draft once; they are not used by the tests.) The orchestrator declares its action
   on the route (``require_actor``), read from the app (``orchestrator.actor.walk``).
2. **The walk.** Each route is called by each column of :data:`COLUMNS` (the seven roles, signed out, and in- and
   out-of-scope accounts); :func:`decide` reads the answer (allowed only on success) and :func:`expected_of` gives
   ``permit`` for the column's role and its standing in the study (:func:`standing`).
3. **The report.** ``walk.json`` (every cell) and the page ``docs/plan/measurements/role-walk-<day>.md``.

``live`` mode walks a running box by base URL with the gates of the committed ``walk.json``: it signs in each column
whose ``ROLE_WALK_<COLUMN>_USER`` and ``ROLE_WALK_<COLUMN>_PASSWORD`` are set (never printed) and writes
``live-<host>.json`` beside the report. A box whose sign-in asks a second factor needs a bearer token instead:
``ROLE_WALK_<COLUMN>_TOKEN`` (the ``/api/v1`` routes only).
"""

from __future__ import annotations

import argparse
import functools
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-11-17"
MEASURE = ROOT / "docs" / "plan" / "measurements"
OUT = MEASURE / f"role-walk-{DAY}"
PAGE = MEASURE / f"role-walk-{DAY}.md"
FRAGMENTS_ENV = "ROLE_WALK_OUT"
STUDY = "GZQO"  # the synthetic study of the console's test box
OTHER = "ZZQX"  # a study no column's data is in (the out-of-scope accounts are scoped to it)
PID = "a" * 32
#: the pseudonyms of the seeded SCREEN job (``_done_screen``): a page that shows one names a patient
PSEUDONYMS = ("a" * 8, "b" * 8)
SUB_TICKS = ("screen", "refer")  # the sub-investigator's ticks: some tasks, not all, so the column differs from the PI


# ---------------------------------------------------------------------------------------------- the columns
@dataclass(frozen=True)
class Column:
    name: str
    role: str | None  # None: signed out
    affiliation: str = "hospital"
    studies: str = ""  # an SMO or CRO account's studies (D-104, D-380)
    log: str = ""  # its entry in GZQO's delegation log: "pi", "sub" (SUB_TICKS) or "monitor" (a CRO grant)
    what: str = ""


COLUMNS: tuple[Column, ...] = (
    Column("anon", None, what="not signed in"),
    Column("admin", "admin", what="the administrator (IT operator)"),
    Column("crc", "coordinator", what="a hospital coordinator (every study)"),
    Column("smo_in", "coordinator", "smo", STUDY, what="an SMO coordinator scoped to GZQO"),
    Column("smo_out", "coordinator", "smo", OTHER, what="an SMO coordinator scoped to another study"),
    Column("inv", "investigator", what="an investigator on no log of GZQO"),
    Column("pi", "investigator", log="pi", what="the investigator GZQO's log names PI"),
    Column("sub", "investigator", log="sub", what="a sub-investigator of GZQO ticked screen and refer"),
    Column("viewer", "viewer", what="a viewer"),
    Column("cro_in", "cro", "cro", STUDY, what="a CRO account scoped to GZQO, no monitor grant"),
    Column("cro_out", "cro", "cro", OTHER, what="a CRO account scoped to another study"),
    Column("cro_mon", "cro", "cro", STUDY, log="monitor", what="a CRO account with a monitor grant in GZQO"),
    Column("steward", "steward", what="the data steward"),
    Column("privacy", "privacy", what="the privacy office"),
)
BY_NAME = {c.name: c for c in COLUMNS}


def sees(col: Column, study: str = STUDY) -> bool:
    """The account sees the study (D-104: an empty study list is every study; D-380: an SMO or CRO account lists its
    own)."""
    return col.role is not None and (not col.studies or study in col.studies.split(","))


@functools.cache
def standing(col: Column) -> Any:
    """The column's standing in GZQO, as the matrix's header defines it: the log names a PI (``pi``); the account is
    that PI, or holds the tasks its role row gives with the log's ticks, or a monitor grant. Read from the matrix,
    not from the console's code, so the walk compares the console with the matrix and not with itself."""
    from tb_common.authz import STUDY_TASKS, Standing, permit

    if col.role is None or not sees(col):
        return Standing(False, frozenset(), False)
    is_pi = col.log == "pi"
    held = Standing(is_pi, frozenset(SUB_TICKS if col.log == "sub" else ()), True)
    tasks = frozenset(t for t in STUDY_TASKS if permit(col.role, f"task.{t}", held))
    return Standing(is_pi, tasks, True, col.log == "monitor")


# ---------------------------------------------------------------------------------------------- the routes
#: not walked as roles: signing in and out and the session's own routes (the forged-session tests take them), the
#: static files and the health answer (public by design)
SKIP = re.compile(r"^/(login|logout|lang|role|static|healthz|favicon|api/v1/session|enrol)(/|$|\.)")
CHANGING = ("POST", "PUT", "DELETE", "PATCH")
#: a path names GZQO's data: a study, a patient of it, a job of it or its registry
STUDY_PATH = re.compile(r"\{(rs|ruleset|job_id|record)(:\w+)?\}|/(patients|candidates)/\{pid\}")
#: path parameters other than ``1``: a file format, and an operations action that stops at its first check
#: (``update_check`` with no bundle named answers 400 after the role check; nothing runs)
PARAMS = {"fmt": "xlsx", "action": "update_check"}
#: routes that answer without a sign-in, each with the rule that says so
PUBLIC: dict[str, str] = {
    "/about": "T-617a (console.about): the licence notices are for anyone the box is shown to; no study content",
    "/about/NOTICE.txt": "T-617a: the same notices as plain text",
    "/api/edc/health": "the EDC door's health (console.edc_door): a version number only",
}
#: the form fields a changing call sends beyond the CSRF token: the study, where the right depends on it
FORM_FIELDS: dict[str, dict[str, str]] = {"/pilot/request": {"ruleset": STUDY}, "/pilot/case": {"ruleset": STUDY}}
#: D-104: the lists across every study, which an account scoped to some studies (SMO, CRO) never opens
CROSS_STUDY = re.compile(r"^/(jobs|audit|pilot/mailbox|pilot/cascade)(/|$)")


def console_routes(app: Any) -> list[dict[str, Any]]:
    """Every route of the console's app object: method, path and handler (``module.function``)."""
    from fastapi.routing import APIRoute

    out = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        handler = f"{r.endpoint.__module__}.{r.endpoint.__qualname__}"
        for m in sorted(r.methods or ()):
            if m in ("GET", *CHANGING):
                out.append({"method": m, "path": r.path, "handler": handler, "walked": not SKIP.match(r.path)})
    return sorted(out, key=lambda x: (x["method"] != "GET", x["path"], x["method"]))


def fill(path: str, job_id: str) -> str:
    """The route's parameters: GZQO, a seeded patient and the seeded SCREEN job; every other one ``1``."""

    def one(m: re.Match[str]) -> str:
        return {"rs": STUDY, "ruleset": STUDY, "pid": PID, "job_id": job_id, **PARAMS}.get(m.group(1), "1")

    return re.sub(r"\{(\w+)(?::\w+)?\}", one, path)


# ---------------------------------------------------------------------------------------------- the tracer
#: call sites of ``permit`` that every page passes through and that decide nothing about the route: the account's
#: construction (its scope), the session's scope check, the menu's PI tasks and the generated role descriptions
CONTEXT_SITES = ("<string>:", "app.py:_pi_tasks", "authz.py:role_rights")
#: where the delegation log's standing is computed: every ``task.*`` row is asked there at once
STANDING_SITES = ("team.py:standing", "team.py:<genexpr>", "team.py:on_log")
#: rows that are restrictions, not rights (``report.aggregate_only``: "a restriction, not a right"; the sponsor form:
#: "never a site page of one study"): a route may be gated by their negation
RESTRICTIONS = ("report.aggregate_only", "report.sponsor_form")


class Tracer:
    """Wraps ``tb_common.authz.permit`` in every module that imported it, and records each call made while
    :meth:`recording` is open: ``(action, allowed, call site, in a template)``."""

    def __init__(self) -> None:
        from tb_common import authz

        self.authz = authz
        self.orig = authz.permit
        self.calls: list[tuple[str, bool, str, bool]] | None = None
        self.patched: list[tuple[Any, Any]] = []

    def _site(self) -> tuple[str, bool]:
        f: Any = sys._getframe(2)
        site, in_template = "", False
        while f is not None:
            fn = f.f_code.co_filename
            if "/starlette/" in fn or "/fastapi/" in fn:
                break  # the framework's routing: the handler and all it called are below this frame
            if fn.endswith((".html", ".j2")) or "/jinja2/" in fn:
                in_template = True
            if not site and not fn.endswith(("tb_common/authz.py", "console/auth.py")):
                site = f"{fn.rsplit('/', 1)[-1]}:{f.f_code.co_name}"
            f = f.f_back
        return site, in_template

    def install(self) -> None:
        orig = self.orig

        def permit(role: str, action: str, standing: Any = None) -> Any:
            d = orig(role, action) if standing is None else orig(role, action, standing)
            if self.calls is not None:
                site, tpl = self._site()
                self.calls.append((action, bool(d.allowed), site, tpl))
            return d

        for m in list(sys.modules.values()):  # under any name (``console.home`` imports it as ``permit_row``)
            for name, value in list(getattr(m, "__dict__", {}).items()):
                if value is orig:
                    self.patched.append((m, name))
                    setattr(m, name, permit)

    def uninstall(self) -> None:
        for m, name in self.patched:
            setattr(m, name, self.orig)
        self.patched.clear()

    @contextmanager
    def recording(self) -> Iterator[list[tuple[str, bool, str, bool]]]:
        self.calls = []
        try:
            yield self.calls
        finally:
            self.calls = None


def shows(resp: Any) -> list[str]:
    """The seeded pseudonyms a 2xx text answer carries (a file download is not read)."""
    kind = resp.headers.get("content-type", "")
    if not 200 <= resp.status_code < 300 or not kind.startswith(("text/", "application/json")):
        return []
    return [p for p in PSEUDONYMS if p in resp.text]


def asked(calls: Iterable[tuple[str, bool, str, bool]]) -> list[tuple[str, bool, str]]:
    """The calls that may guard the route: not in a template, not at a context site."""
    return [(a, ok, s) for a, ok, s, tpl in calls if not tpl and not s.startswith(CONTEXT_SITES)]


# ---------------------------------------------------------------------------------------------- the rules
VALIDATION = (400, 409, 410, 422, 429)


def classify(col: Column, path: str, status: int, location: str) -> str:
    """The walked answer before the gate is known: ``A`` allowed, ``R`` refused, ``V`` a validation answer (allowed
    only if the gate was asked and said yes), ``N`` not found for a column that sees the study, ``U`` unclear.

    * refused: 401, 403; a redirect to the sign-in page; 404 for a column that does not see GZQO on a route that
      names GZQO's data (the product answers a study one does not see with 404, ``study_or_404``);
    * allowed: 2xx; a redirect anywhere but the sign-in page;
    * 400, 409, 410, 422, 429: ``V``; every other answer (5xx: the in-process box has no study store): ``U``."""
    if status in (401, 403):
        return "R"
    if 300 <= status < 400:
        return "R" if location.split("?", maxsplit=1)[0].endswith("/login") else "A"
    if 200 <= status < 300:
        return "A"
    if status == 404:
        return "R" if (col.role is None or (STUDY_PATH.search(path) and not sees(col))) else "N"
    if status in VALIDATION:
        return "V"
    return "U"


@dataclass(frozen=True)
class Gate:
    actions: tuple[str, ...]  # () open to every signed-in account
    mode: str = "one"  # "one", "all" (both asked and both yes), "any"

    def label(self) -> str:
        if not self.actions:
            return "(any signed-in account)"
        return {"one": "", "all": " & ", "any": " | "}[self.mode].join(self.actions) if len(self.actions) > 1 \
            else self.actions[0]  # fmt: skip


def expected(col: Column, path: str, gate: Gate, method: str = "GET") -> bool:
    """The matrix's answer for the column: signed out, nothing; a route that names GZQO's data, only for a column
    that sees GZQO; then ``permit`` with the column's role and standing for the gate's action(s)."""
    if col.role is None:
        return path in PUBLIC
    if STUDY_PATH.search(path) and not sees(col):
        return False
    if col.studies and CROSS_STUDY.match(path):
        return False
    if method in CHANGING and FORM_FIELDS.get(path, {}).get("ruleset") and not sees(col):
        return False  # the form names GZQO
    if not gate.actions:
        return True
    answers = [_permit(col, a.lstrip("!")) != a.startswith("!") for a in gate.actions]
    return any(answers) if gate.mode == "any" else all(answers)


@functools.cache
def _permit(col: Column, action: str) -> bool:
    from tb_common.authz import MATRIX_WHAT, permit

    if col.affiliation != "hospital" and "hospital staff only" in MATRIX_WHAT.get(action, ""):
        return False  # the row's own words (``irb.edit``): an SMO or CRO account is not hospital staff
    return bool(permit(str(col.role), action, standing(col)).allowed)


def _provisional(cls: str) -> bool | None:
    """For choosing the gate: a validation answer, a 404 and a 503 count as let in (``test_role_route_matrix``'s
    reading); the final answer then asks the trace (:func:`final`)."""
    return {"A": True, "R": False}.get(cls, True)


def _permits_row(col: Column, gate: Gate) -> bool:
    """The gate's row(s) alone allow the column (the scope rules left out)."""
    if col.role is None:
        return False
    answers = [_permit(col, a.lstrip("!")) != a.startswith("!") for a in gate.actions]
    return not answers or (any(answers) if gate.mode == "any" else all(answers))


def infer(path: str, cells: dict[str, dict[str, Any]], hint: str | None = None,
          method: str = "GET") -> tuple[Gate, list[str]]:  # fmt: skip
    """The route's gate: among the actions it asked (over every column), the one (or two, both or either) whose
    matrix answers agree with the most walked answers (a validation answer, a 404 and a 503 count as let in here).
    Ties: the ``hint`` (a row the product's tests name); else one action before none before two, an action asked
    by name before one asked only for the delegation log's standing, then the order first asked. Returns the gate
    and the candidates."""
    rights: list[str] = []
    limits: list[str] = []
    direct: set[str] = set()
    for c in cells.values():
        for a, _, site in c["asked"]:
            if not site.startswith(STANDING_SITES):
                direct.add(a)
            for x in (f"!{a}", a) if a in RESTRICTIONS else (a,):
                into = limits if a in RESTRICTIONS else rights
                if x not in into:
                    into.append(x)
    # the rights asked by name first, then those asked only while the delegation log's standing is computed (every
    # task row at once), then the restriction rows (asked on every page by the scope check)
    cand = [a for a in rights if a in direct] + [a for a in rights if a not in direct] + limits
    cols = [
        BY_NAME[n] for n, c in cells.items() if BY_NAME[n].role is not None and _provisional(c["class"]) is not None
    ]
    gates = [Gate((a,)) for a in cand] + [Gate(())]
    gates += [Gate(p, m) for p in itertools.combinations(cand[:14], 2) for m in ("all", "any")
              if p[0].lstrip("!") != p[1].lstrip("!")]  # fmt: skip
    want = [_provisional(cells[col.name]["class"]) for col in cols]

    def score(g: Gate) -> int:
        return sum(expected(col, path, g, method) == w for col, w in zip(cols, want, strict=True))

    best = max(gates, key=lambda g: (score(g), -gates.index(g)))
    if hint in cand and score(Gate((hint,))) == score(best):  # a tie: the row the product's own tests name
        best = Gate((hint,))
    return best, cand


def final(col: Column, cell: dict[str, Any], gate: Gate) -> str:
    """The walked answer once the gate is known: ``A``, ``R`` or ``?`` (unclear). A validation answer is allowed when
    the gate was asked in this very request and every action of it said yes (``any``: one said yes), refused when it
    was asked and said no; with no gate (an open route) it is allowed; else unclear. ``N`` and ``U`` are unclear."""
    cls = cell["class"]
    if cls in ("A", "R"):
        return str(cls)
    if cls not in ("V", "N"):
        return "?"  # a 5xx is never counted, whatever the trace says
    if not gate.actions:
        return "A"
    said: dict[str, bool] = {}
    for a, ok, _ in cell["asked"]:
        said.setdefault(a, ok)
        said.setdefault(f"!{a}", not ok)
    if not all(a in said for a in gate.actions) and gate.mode != "any":
        return "?"
    got = [said[a] for a in gate.actions if a in said]
    if not got:
        return "?"
    return "A" if (any(got) if gate.mode == "any" else all(got)) else "R"


ALLOWED_X, REFUSED_X = "ALLOWED-BUT-MATRIX-REFUSES", "REFUSED-BUT-MATRIX-ALLOWS"


# ---------------------------------------------------------------------------------------------- the declared table
#: the committed table of what each console route must ask (one row per route; the walk never infers)
DECLARED = ROOT / "tests" / "console" / "data" / "route_actions.yaml"
KINDS = ("actions", "public", "signed_in", "scope")


@dataclass(frozen=True)
class Declared:
    """One row of :data:`DECLARED`: the matrix action(s) a route must ask (``mode`` all or any; ``!row`` for a
    restriction row such as ``report.aggregate_only``), or ``public`` (anyone), ``signed_in`` (every signed-in
    account) or ``scope`` (every account that sees the study), with ``why``: the decision or document."""

    kind: str
    actions: tuple[str, ...] = ()
    mode: str = "all"
    why: str = ""

    def gate(self) -> Gate:
        return Gate(self.actions, "any" if self.mode == "any" else ("all" if len(self.actions) > 1 else "one"))

    def label(self) -> str:
        return self.gate().label() if self.kind == "actions" else f"({self.kind})"


def load_declared(path: Path = DECLARED) -> dict[tuple[str, str], Declared]:
    import yaml
    from tb_common.authz import MATRIX

    raw = yaml.safe_load(path.read_text("utf-8")) or {}
    out: dict[tuple[str, str], Declared] = {}
    for key, row in (raw.get("routes") or {}).items():
        method, _, route = str(key).partition(" ")
        kind = str(row.get("kind") or "actions")
        acts = tuple(str(a) for a in row.get("actions") or ())
        if kind not in KINDS or (kind == "actions") != bool(acts) or not str(row.get("why") or "").strip():
            raise ValueError(f"{key}: a row names actions, or a kind ({', '.join(KINDS[1:])}), and why")
        bad = [a for a in acts if a.lstrip("!") not in MATRIX]
        if bad:
            raise ValueError(f"{key}: not rows of the matrix: {bad}")
        out[(method, route)] = Declared(kind, acts, str(row.get("mode") or "all"), str(row["why"]))
    return out


def table_problems(routes: list[dict[str, Any]], declared: dict[tuple[str, str], Declared]) -> list[str]:
    """A walked route with no row, and a row with no route: the walk cannot go stale."""
    have = {(r["method"], r["path"]) for r in routes if r["walked"]}
    return [f"{m} {p}: a route with no row in route_actions.yaml" for m, p in sorted(have - set(declared))] + [
        f"{m} {p}: a row of route_actions.yaml with no route" for m, p in sorted(set(declared) - have)
    ]


def expected_of(col: Column, method: str, path: str, d: Declared) -> bool:
    """The declared answer for the column: :func:`expected` with the declared gate; ``public`` lets anyone in,
    ``signed_in`` and ``scope`` every signed-in account (the scope rules still apply)."""
    if d.kind == "public":
        return True
    if col.role is None:
        return False
    return expected(col, path, d.gate() if d.kind == "actions" else Gate(()), method)


def decide(col: Column, path: str, status: int, location: str) -> tuple[str, str]:
    """The walked answer: ``A`` allowed, ``R`` refused, ``?`` the check was not seen to be reached; with why.

    * allowed: 2xx; a redirect to another page (not to sign-in, and not back with ``err=``: a validation answer);
    * refused: 401, 403; a redirect to sign-in; 404 for a column that does not see GZQO on a route of GZQO's data;
    * everything else (4xx validation, 404, 5xx, a redirect with ``err=``) is not counted either way."""
    if status in (401, 403):
        return "R", ""
    if 300 <= status < 400:
        if location.split("?", maxsplit=1)[0].endswith("/login"):
            return "R", ""
        return ("?", "redirect with err=") if "err=" in location else ("A", "")
    if 200 <= status < 300:
        return "A", ""
    if status == 404 and (col.role is None or (STUDY_PATH.search(path) and not sees(col))):
        return "R", ""
    return "?", ("5xx" if status >= 500 else str(status))


def judge_declared(raw: list[dict[str, Any]], declared: dict[tuple[str, str], Declared]) -> list[dict[str, Any]]:
    """Every walked route with its declared row, and every cell with expected, got, verdict and why unclear."""
    out = []
    for r in raw:
        d = declared.get((r["method"], r["path"]))
        if not r["walked"] or d is None:
            out.append({**{k: v for k, v in r.items() if k != "cells"}, "gate": None, "cells": {}})
            continue
        cells = {}
        for name, c in r["cells"].items():
            exp = expected_of(BY_NAME[name], r["method"], r["path"], d)
            got, why = decide(BY_NAME[name], r["path"], c["status"], c.get("location", ""))
            cells[name] = {"status": c["status"], "expected": "A" if exp else "R", "got": got,
                           "verdict": verdict(exp, got), "unclear": why, "audited": c.get("audited", 0),
                           "shows": c.get("shows", []), "backend": bool(c.get("backend")) if got == "R" else None,
                           "probe": c.get("probe")}  # fmt: skip
        out.append({**{k: v for k, v in r.items() if k != "cells"}, "gate": {"kind": d.kind, "actions": list(d.actions),
                    "mode": d.mode}, "gate_label": d.label(), "why": d.why, "cells": cells})  # fmt: skip
    return out


def draft_table(raw: list[dict[str, Any]], hints: dict[tuple[str, str], str] | None = None) -> str:
    """A first draft of :data:`DECLARED` from a traced walk (:func:`infer`): to be checked row by row against the
    documents and the handler before it is committed. The tests never call this."""
    lines = ["# DRAFT from infer(): check every row before committing", "routes:"]
    for r in judge(raw, hints):
        if not r.get("gate"):
            continue
        g = r["gate"]
        key = f"{r['method']} {r['path']}"
        if not g["actions"]:
            lines.append(f"  '{key}': {{kind: signed_in, why: DRAFT}}")
        else:
            mode = "any" if g["mode"] == "any" else "all"
            lines.append(f"  '{key}': {{actions: {json.dumps(g['actions'])}, mode: {mode}, why: DRAFT}}")
    return "\n".join(lines) + "\n"


def verdict(exp: bool, got: str) -> str:
    if got == "?":
        return "unclear"
    if got == "A":
        return "allowed" if exp else "ALLOWED-BUT-MATRIX-REFUSES"
    return "refused" if not exp else "REFUSED-BUT-MATRIX-ALLOWS"


def judge(raw: list[dict[str, Any]], hints: dict[tuple[str, str], str] | None = None) -> list[dict[str, Any]]:
    """Every route of a walk with its gate, and every cell with expected, got and verdict. ``hints``: the rows the
    product's own tests name for some routes (``test_role_route_matrix.ROUTE_ACTIONS``), used only to break a tie."""
    out = []
    for r in raw:
        if not r["walked"]:
            out.append({**r, "gate": None, "candidates": [], "cells": {}})
            continue
        gate, cand = infer(r["path"], r["cells"], (hints or {}).get((r["method"], r["path"])), r["method"])
        cells = {}
        for name, c in r["cells"].items():
            col = BY_NAME[name]
            exp = expected(col, r["path"], gate, r["method"])
            got = final(col, c, gate)
            if got == "A" and c["class"] in ("V", "N") and not exp and _permits_row(col, gate):
                got = "?"  # refused by scope alone, answered by a validation first: the scope check may come later
            cells[name] = {"status": c["status"], "class": c["class"], "expected": "A" if exp else "R", "got": got,
                           "verdict": verdict(exp, got), "audited": c.get("audited", 0),
                           "shows": c.get("shows", [])}  # fmt: skip
        out.append({**{k: v for k, v in r.items() if k != "cells"}, "gate": asdict(gate), "gate_label": gate.label(),
                    "candidates": cand, "cells": cells})  # fmt: skip
    return out


# ---------------------------------------------------------------------------------------------- the in-process walk
TAG_HEADER = "x-role-walk"
_TAG: Any = None


def current_tag() -> str:
    """The walk's tag of the request being served (:class:`Tagged`), "" outside one."""
    return _TAG.get() if _TAG is not None else ""


class Tagged:
    """An ASGI wrapper that puts the walk's request tag (header :data:`TAG_HEADER`) in a context variable for the
    request's whole life, so an audit record is counted for the request that wrote it (:class:`AuditTap`). A sync
    handler runs in a thread with a copy of the context, so it sees the tag too."""

    def __init__(self, app: Any) -> None:
        global _TAG
        import contextvars

        if _TAG is None:
            _TAG = contextvars.ContextVar("role_walk_tag", default="")
        self.app = app

    def __getattr__(self, name: str) -> Any:
        return getattr(self.app, name)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        tag = ""
        for k, v in scope.get("headers") or ():
            if k.decode("latin-1").lower() == TAG_HEADER:
                tag = v.decode("latin-1")
        token = _TAG.set(tag)
        try:
            await self.app(scope, receive, send)
        finally:
            _TAG.reset(token)


class AuditTap:
    """Counts the audit records written by each tagged request (wraps an ``AuditLog``'s ``append``)."""

    def __init__(self, audit: Any) -> None:
        self.by_tag: Counter[str] = Counter()
        self.audit, self.orig = audit, audit.append

        def append(*a: Any, **kw: Any) -> Any:
            tag = current_tag()
            if tag:
                self.by_tag[tag] += 1
            return self.orig(*a, **kw)

        audit.append = append

    def close(self) -> None:
        self.audit.append = self.orig


class BackendTap:
    """Counts the calls a tagged console request makes to the in-process stand-ins of the orchestrator (any test
    client called while the request is served). A refusal the console owes itself (D-483: it cannot sign what it
    would not allow) comes before any such call; one that comes from the backend shows a call."""

    def __init__(self) -> None:
        from starlette.testclient import TestClient

        self.by_tag: Counter[str] = Counter()
        self.cls, self.orig = TestClient, TestClient.request
        tap = self

        def request(client: Any, *a: Any, **kw: Any) -> Any:
            tag = current_tag()
            if tag:
                tap.by_tag[tag] += 1
            return tap.orig(client, *a, **kw)

        TestClient.request = request  # type: ignore[method-assign,assignment]

    def close(self) -> None:
        self.cls.request = self.orig  # type: ignore[method-assign]


def _param(given: dict[str, Any], m: re.Match[str]) -> str:
    return str(given.get(m.group(1), m.group(0)))


#: ``prepare(method, path, column) ->{"params": {...}, "form": {...}, "json": {...}}`` or None: a valid body (and
#: fresh state) for a changing route, so an allowed column gets past validation; an upload route may give ``files``
#: (the page's file parts) and an ``/api/v1`` route that takes a file as its body ``content`` and ``content_type``
#: (10D-16a, D-1373)
Prepare = Callable[[str, str, str], dict[str, Any] | None]


def console_walk(app: Any, clients: dict[str, tuple[Any, str, Any]], tap: AuditTap, job_id: str,
                 prepare: Prepare = lambda m, p, c: None,
                 tracer: Tracer | None = None, backend: BackendTap | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """Walk every route as every column; GET rows first, then the changing rows, each column in turn (the order of
    ``test_role_route_matrix``). A changing call sends the column's CSRF token and, where :data:`Prepare` gives
    one, a valid body (``/api/v1``: its bearer token and a JSON body, ``{}`` by default). The clients are on
    :class:`Tagged` (the tag of each request is ``<method> <path> <column>``)."""
    routes = console_routes(app)
    raw: dict[tuple[str, str], dict[str, Any]] = {(r["method"], r["path"]): {**r, "cells": {}} for r in routes}
    for changing in (False, True):
        for col in COLUMNS:
            page, csrf, api = clients[col.name]
            for r in routes:
                if not r["walked"] or (r["method"] in CHANGING) != changing:
                    continue
                prep = (prepare(r["method"], r["path"], col.name) if changing else None) or {}
                params = dict(prep.get("params", {}))
                url = re.sub(r"\{(\w+)(?::\w+)?\}", functools.partial(_param, params), r["path"])
                url = fill(url, job_id)
                tag = f"{r['method']} {r['path']} {col.name}"
                probe = None
                if prep.get("probe"):  # a refused column: first with no body (the refusal must come first)
                    ptag = {TAG_HEADER: f"{tag} probe"}
                    if r["path"].startswith("/api/v1/"):
                        pr = api.request(r["method"], url, json={}, headers=ptag, follow_redirects=False)
                    else:
                        pr = page.request(r["method"], url, data={"csrf": csrf}, headers=ptag, follow_redirects=False)
                    first, _ = decide(col, r["path"], pr.status_code, pr.headers.get("location", ""))
                    probe = "refused" if first == "R" else pr.status_code
                headers = {TAG_HEADER: tag}
                recorder: Any = tracer.recording() if tracer else nullcontext([])
                with recorder as calls:
                    if r["path"].startswith("/api/v1/"):
                        if changing and "content" in prep:  # a file as the body (10D-16a)
                            resp = api.request(r["method"], url, content=prep["content"], follow_redirects=False,
                                               headers={**headers, "content-type": prep["content_type"]})  # fmt: skip
                        else:
                            body = prep.get("json", {}) if changing else None
                            resp = api.request(r["method"], url, json=body, headers=headers, follow_redirects=False)
                    else:
                        data = None
                        if changing and csrf:
                            data = {"csrf": csrf, **FORM_FIELDS.get(r["path"], {}), **prep.get("form", {})}
                        resp = page.request(r["method"], url, data=data, files=prep.get("files") if changing else None,
                                            headers=headers, follow_redirects=False)  # fmt: skip
                loc = resp.headers.get("location", "")
                raw[(r["method"], r["path"])]["cells"][col.name] = {
                    "status": resp.status_code, "location": loc,
                    "class": classify(col, r["path"], resp.status_code, loc),
                    "asked": asked(calls), "audited": tap.by_tag.get(tag, 0), "shows": shows(resp),
                    "backend": backend.by_tag.get(tag, 0) if backend else 0,
                    "prepared": bool(prep), "probe": probe,
                }  # fmt: skip
    return list(raw.values())


# ---------------------------------------------------------------------------------------------- the orchestrator
ORCH_COLUMNS = tuple(c for c in COLUMNS if c.role is not None and c.name not in ("smo_out", "cro_out", "cro_in"))


#: a body that passes the route's own model, where a second check in the handler comes after the model is read
ORCH_BODIES: dict[str, dict[str, Any]] = {"/setup/instruments/{iid}": {}}


def orch_body(template: str) -> dict[str, Any]:
    return dict(ORCH_BODIES.get(template, {"x": 1}))


def orch_fill(template: str) -> str:
    path = template.replace("{rs}", STUDY).replace("{ruleset}", STUDY).replace("{record}", f"{STUDY}-0001")
    path = path.replace("{event}", "ae1").replace("{fmt}", "csv").replace("{job_id}", "J1").replace("{ref}", "rc1")
    return re.sub(r"\{(\w+)(?::\w+)?\}", "1", path)


def orchestrator_walk(app: Any, client: Any, events: list[dict[str, Any]],
                      sign: Callable[..., dict[str, str]]) -> list[dict[str, Any]]:  # fmt: skip
    """Every ``require_actor`` route of the orchestrator, for each action it names, as each role with its standing
    in GZQO (and signed out): the dependency's answer against ``permit``. Refused = 403 with the dependency's
    reason ``right``; past it = any other answer (the stand-in behind it has no data); 403 for another reason or no
    ``actor.refused`` record is listed. ``sign(action, study, method, path, body, role=, standing=, sub=)`` mints."""
    from orchestrator import actor as ra
    from tb_common.authz import permit

    out = []
    for method, template, stage, action, _ in ra.walk(app):
        if stage != "refuse":
            continue
        path = orch_fill(template)
        named = "{rs}" in template or "{ruleset}" in template
        study = STUDY if named else ""
        body = None if method == "GET" else orch_body(template)
        kw: dict[str, Any] = {} if body is None else {"json": body}
        for act in (action,) if isinstance(action, str) else tuple(action):
            row: dict[str, Any] = {"method": method, "path": template, "action": act, "cells": {}}
            n = len(events)
            r = client.request(method, path, **kw)
            row["cells"]["anon"] = {"status": r.status_code, "reason": _reason(r), "expected": "R",
                                    "got": "R" if _reason(r) else "?", "audited": len(events) - n}  # fmt: skip
            for col in ORCH_COLUMNS:
                st = standing(col)
                hdr = sign(act, study, method, path, body, role=col.role, standing=st, sub=f"console:walk-{col.name}")
                n = len(events)
                r = client.request(method, path, headers=hdr, **kw)
                why = _reason(r)
                got = "R" if why == "right" else ("?" if why else "A")
                exp = "A" if permit(str(col.role), act, st).allowed else "R"
                row["cells"][col.name] = {"status": r.status_code, "reason": why, "expected": exp, "got": got,
                                          "audited": len(events) - n}  # fmt: skip
            for c in row["cells"].values():
                c["verdict"] = verdict(c["expected"] == "A", c["got"])
            out.append(row)
    return out


def _reason(r: Any) -> str:
    try:
        detail = r.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    if r.status_code == 403 and isinstance(detail, dict) and detail.get("code") == "ACTOR":
        return str(detail.get("reason") or "")
    return ""


# ---------------------------------------------------------------------------------------------- fragments, report
def fragment_dir() -> Path | None:
    d = os.environ.get(FRAGMENTS_ENV)
    return Path(d) if d else None


def save_fragment(name: str, data: Any) -> None:
    """A test leaves its result for the report when ``ROLE_WALK_OUT`` names a folder (the tool sets it)."""
    d = fragment_dir()
    if d is None:
        return
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", "utf-8")


def counts(rows: list[dict[str, Any]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for r in rows:
        for cell in r["cells"].values():
            c[cell["verdict"]] += 1
            c["cells"] += 1
    return c


def _matrix_dead(console: list[dict[str, Any]], orch: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Matrix rows that no route takes as its gate, and of those the ones no route even asks."""
    from tb_common.authz import MATRIX

    gated = {a for r in console if r.get("gate") for a in r["gate"]["actions"]} | {r["action"] for r in orch}
    seen = {a for r in console for a in r.get("candidates", [])} | gated
    dead = [a for a in MATRIX if a not in gated]
    return dead, [a for a in dead if a not in seen]


#: rows a service names by a prefix and a value it reads (``f"command.{type}"``, ``f"account.create.{cls}"``)
DYNAMIC_PREFIXES = ("command.", "account.create.", "task.", "edc.", "sae.")


def unreferenced_rows() -> list[str]:
    """Matrix rows that no file under ``services/`` or ``libs/`` names (the matrix and the role labels left out),
    neither whole nor by one of :data:`DYNAMIC_PREFIXES` that some file builds from a value (a static reading)."""
    from tb_common.authz import MATRIX

    files = [p for base in ("services", "libs") for p in (ROOT / base).rglob("*.py")]
    text = "\n".join(p.read_text("utf-8", "replace") for p in files
                     if not p.name.startswith("i18n"))  # fmt: skip
    built = {p for p in DYNAMIC_PREFIXES if re.search(r"f[\"']" + re.escape(p) + r"\{", text)}
    return [a for a in MATRIX if f'"{a}"' not in text and f"'{a}'" not in text
            and not any(a.startswith(p) for p in built)]  # fmt: skip


def build(frag: Path) -> dict[str, Any]:
    """``walk.json``: the fragments of the last run, judged."""
    con = json.loads((frag / "console.json").read_text("utf-8"))
    orch = json.loads((frag / "orchestrator.json").read_text("utf-8")) if (frag / "orchestrator.json").exists() else []

    def read(name: str) -> Any:
        f = frag / f"{name}.json"
        return json.loads(f.read_text("utf-8")) if f.exists() else None

    extra = {name: read(name) for name in ("two_person", "breakglass")}
    extra["forged"] = (read("forged_console") or []) + (read("forged_orchestrator") or [])
    dead, never = _matrix_dead(con["routes"], orch)
    return {"day": DAY, "columns": [asdict(c) for c in COLUMNS], "console": con, "orchestrator": orch,
            "matrix_rows_no_gate": dead, "matrix_rows_never_asked": never,
            "matrix_rows_unreferenced": unreferenced_rows(), **extra}  # fmt: skip


def _cell_mark(cell: dict[str, Any]) -> str:
    v = cell["verdict"]
    if v == "unclear":
        return "?"
    return str(cell["got"]) + ("!" if v.isupper() or v.startswith(("ALLOWED", "REFUSED")) else "")


def render(walk: dict[str, Any], findings: list[dict[str, Any]], verdict_text: str) -> str:
    """The page: verdict, counts, per-row tables, two-person, break-glass, forged sessions, findings."""
    con = walk["console"]["routes"]
    orch = walk["orchestrator"]
    walked = [r for r in con if r.get("gate")]
    cc, oc = counts(walked), counts(orch)
    names = [c["name"] for c in walk["columns"]]
    api_only = [r for r in walked if r["path"].startswith(("/api/",))]
    kinds = Counter(r["gate"]["kind"] for r in walked)
    prepared = walk["console"].get("prepared") or []
    n_orch = len({(r["method"], r["path"]) for r in orch})
    hand = sum(1 for r in walked if "not checked against a decision" not in r.get("why", ""))
    lines = [
        f"# The role walk, {DAY} (card V-2, plan 8 activity V8)",
        "",
        "**Reader:** the integrator and lane C2 (console, accounts, roles, audit), who own the matrix's routes.",
        "",
        f"**Verdict.** {verdict_text}",
        "",
        "Generated by `python -m tools.role_walk inproc` from the files in "
        f"`role-walk-{DAY}/` (`walk.json` every cell, `findings.json`). Every count below is read from `walk.json`.",
        "",
        "## What ran and what did not",
        "",
        "- **Ran:** the console's app and the orchestrator's app in process (the test boxes of "
        "`tests/console/test_console_app.py` and `tests/unit/test_actor_routes.py`), synthetic data only. The "
        "console's box has a study store in process: the orchestrator's data core, life-cycle, sponsor, EDC, "
        "conflict and instrument routers behind `study_api`, called with the console's own signatures.",
        "- **Built on `tests/console/test_role_route_matrix.py`** (its route list and parameters). That test compares "
        "each answer with a committed snapshot of the answers and holds 34 hand-named routes to `permit`. This walk "
        "adds: a committed table of what every route must ask (`tests/console/data/route_actions.yaml`), never "
        "inferred by the test; every cell compared with it both ways; signed-out, out-of-scope, sub-investigator and "
        "monitor-grant columns; valid bodies and fresh state for the changing routes that matter most; the audit "
        "record of each request; a search of every page for patient pseudonyms; the orchestrator's `require_actor` "
        "routes per role and standing; two-person rules, break-glass, forged sessions.",
        "- **Not run: the compose box.** `python -m tools.role_walk live --base-url URL` walks a running box with "
        "the committed table and accounts from the environment (`ROLE_WALK_<COLUMN>_USER`, `_PASSWORD` or `_TOKEN`).",
        "- **Not walked as roles:** the sign-in machinery (`/login`, `/logout`, `/lang`, `/role`, `/enrol`, "
        "`/api/v1/session`), `/static`, `/healthz`; the orchestrator's v2 groups (`POST /jobs`, the EDC router's "
        "own role check: only the cells V2-05 names were run).",
        "",
        "## Counts",
        "",
        "| | Console | Orchestrator |",
        "| --- | --- | --- |",
        f"| routes in the app | {len(con)} | {n_orch} (`require_actor` routes) |",
        f"| routes walked | {len(walked)} (of which {len(api_only)} API routes with no page) | {n_orch} |",
        f"| cells (route x column) | {cc['cells']} | {oc['cells']} |",
        f"| decided: allowed as declared | {cc['allowed']} | {oc['allowed']} |",
        f"| decided: refused as declared | {cc['refused']} | {oc['refused']} |",
        f"| allowed where the declared row refuses | {cc[ALLOWED_X]} | {oc[ALLOWED_X]} |",
        f"| refused where the declared row allows | {cc[REFUSED_X]} | {oc[REFUSED_X]} |",
        f"| unclear: the check was not seen to be reached | {cc['unclear']} | {oc['unclear']} |",
        "",
        f"The table's {len(walked)} console rows: "
        + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
        + f". {hand} rows were set from a decision or document by hand; the other {len(walked) - hand} were drafted "
        "once from a traced walk and agree with the design table, and their `why` says they were not checked "
        "against a decision by hand.",
        "",
        "## How a cell is decided",
        "",
        "- **Expected** comes from the committed table: `permit(role, action, standing)` for each declared action "
        "(all, or any), with the column's standing in GZQO read from the matrix's header; `public` lets anyone in; "
        "`signed_in` and `scope` every signed-in account. A route that names GZQO's data refuses a column that does "
        "not see GZQO (D-104, D-380). The orchestrator's routes declare their action on the route (`require_actor`).",
        "- **Got:** allowed = 2xx, or a redirect to another page (not to sign-in and not back with `err=`); "
        "refused = 401, 403, a redirect to sign-in, or 404 for a column that does not see GZQO on a route of "
        "GZQO's data. Anything else (a 4xx validation answer, another 404, a 5xx, a redirect with `err=`) is "
        "unclear, never counted. On the orchestrator: refused = 403 from the dependency with reason `right`.",
        f"- **Valid bodies** (fresh state per call) for {len(prepared)} changing routes: "
        + ", ".join(f"`{p}`" for p in prepared)
        + ". Every other changing route sends its CSRF token only; where a column passes the check, it stops at "
        "validation and the cell is unclear (pinned in `tests/console/data/role_walk_unclear.txt`).",
        "- **The check comes first:** on those routes a refused column is first sent no body; it must be refused "
        "then too (6 cells on the two reveal pages ask the purpose or reason before the role, and are listed in the "
        "test). A refused cell whose request reached the orchestrator's stand-in counts as refused by the backend, "
        "not the console (D-483: the console cannot sign what it would not allow); none was found.",
        "- **Audit:** each request carries a tag; the audit records written while it is served are counted for it.",
        "",
        "## Columns",
        "",
        "| Column | Account |",
        "| --- | --- |",
    ]
    lines += [f"| `{c['name']}` | {c['what']} |" for c in walk["columns"]]
    lines += ["", "## Per declared row and column (console pages)", "",
              "A allowed, R refused, `!` against the declared row, `?` unclear (`A?`: allowed where decided, some "
              "cells unclear). One row per declared gate; the routes of each are in `walk.json`.", ""]  # fmt: skip
    lines += _gate_table([r for r in walked if not r["path"].startswith("/api/")], names)
    lines += ["", "## Per declared row and column (console API routes with no page)", "",
              "`/api/v1/...` (a bearer token) and `/api/edc/...`, walked as the pages are.", ""]  # fmt: skip
    lines += _gate_table(api_only, names)
    lines += ["", "## Per action and column (orchestrator, `require_actor`)", "",
              "| Action | Routes | " + " | ".join(c.name for c in (BY_NAME["anon"], *ORCH_COLUMNS)) + " |",
              "|---|---|" + "---|" * (len(ORCH_COLUMNS) + 1)]  # fmt: skip
    ob: dict[str, list[dict[str, Any]]] = {}
    for r in orch:
        ob.setdefault(r["action"], []).append(r)
    for a in sorted(ob):
        row = []
        for n in ("anon", *(c.name for c in ORCH_COLUMNS)):
            marks = {_cell_mark(r["cells"][n]) for r in ob[a]}
            row.append("".join(sorted(marks)))
        lines.append(f"| `{a}` | {len(ob[a])} | " + " | ".join(row) + " |")
    seen = Counter(n for r in walked for n, c in r["cells"].items() if c.get("shows"))
    lines += ["", "## Patient rows on the pages", "",
              "Each 2xx text answer was searched for the two seeded pseudonyms. Answers that carried one, by column: "
              + (", ".join(f"`{n}` {seen[n]}" for n in names if seen[n]) or "none")
              + ". The steward's and the privacy office's are the audit pages (`audit.ids`); no other column without "
              "`phi.view` saw one (the test fails if one does).", ""]  # fmt: skip
    unclear: dict[str, set[str]] = {}
    n_unclear: Counter[str] = Counter()
    for r in walked:
        for c in r["cells"].values():
            if c["verdict"] == "unclear":
                unclear.setdefault(c["unclear"], set()).add(f"{r['method']} {r['path']}")
                n_unclear[c["unclear"]] += 1
    lines += ["## Unclear cells", "", "Never counted as a pass; pinned by route and column. By answer:", ""]
    for why, routes in sorted(unclear.items()):
        lines += [f"- **{why}**: {n_unclear[why]} cells on {len(routes)} routes."]
    lines += ["", "## Matrix rows", "",
              f"- Named by no file under `services/` or `libs/` (a static reading, `unreferenced_rows`): "
              f"{', '.join(walk['matrix_rows_unreferenced']) or 'none'}.", ""]  # fmt: skip
    lines += _section_two_person(walk.get("two_person"))
    lines += _section_breakglass(walk.get("breakglass"))
    lines += _section_forged(walk.get("forged"))
    lines += ["## Findings", "",
              "| Id | Severity | Basis | Lane | Ruling | Place | Expected (where written) | Happened |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in findings:
        lines.append(f"| {f['id']} | {f['severity']} | {f['basis']} | {f['lane']} | {f.get('ruling') or '-'} | "
                     f"`{f['place']}` | {f['expected']} | {f['happened']} |")  # fmt: skip
    lines.append("")
    return "\n".join(lines)


def _gate_table(rows: list[dict[str, Any]], names: list[str]) -> list[str]:
    out = ["| Gate | Routes | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    by_gate: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_gate.setdefault(r["gate_label"], []).append(r)
    for label in sorted(by_gate):
        rs = by_gate[label]
        row = []
        for n in names:
            marks = {_cell_mark(r["cells"][n]) for r in rs if n in r["cells"]}
            bang = sorted(m for m in marks if m.endswith("!"))
            core = sorted(m for m in marks if m in ("A", "R"))
            row.append("".join(bang) or ("".join(core) or "?") + ("?" if "?" in marks and core else ""))
        out.append(f"| `{label}` | {len(rs)} | " + " | ".join(row) + " |")
    return out


def _table(rows: list[dict[str, Any]] | None, cols: list[str], none: str) -> list[str]:
    if not rows:
        return [none, ""]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return [*out, ""]


def _section_two_person(rows: list[dict[str, Any]] | None) -> list[str]:
    return ["## Two-person rules", "",
            "One test per rule that compares two people (`tests/console/test_matrix_role_walk_rules.py`, the "
            "`test_two_person_*` tests). Searched for: \"second person\", \"four eyes\", \"two-person\", \"same "
            "person\", \"one's own\" in `services/`, `libs/` and the decisions. A step split by role only (a "
            "criteria approval after a coordinator prepares it; the EDC switch-on) is no two-person rule: D-877 "
            "records that one person holding both roles may do both on a test box.", "",
            *_table(rows, ["rule", "where", "same person", "second person, right role", "second person, wrong role",
                           "one person switching roles", "test"], "Not run.")]  # fmt: skip


def _section_breakglass(rows: list[dict[str, Any]] | None) -> list[str]:
    return ["## Break-glass and its review", "", *_table(rows, ["check", "result", "test"], "Not run.")]


def _section_forged(rows: list[dict[str, Any]] | None) -> list[str]:
    return ["## Forged and stale sessions", "",
            "A sample: one route of each kind. Each row: what was sent, what came back, whether it was refused and "
            "whether the refusal is in the audit trail. The orchestrator's rows assert the dependency's reason per "
            "kind. Audit rules that exist: a failed sign-in (`console.login_failed`, D-279; D-320 §5 for the API's "
            "second factor), a failed re-authentication (`console.reauth_failed`, D-391), every refused assertion "
            "(`actor.refused`, D-483). None was found for a made-up, ended or stale session cookie or bearer token: "
            "the console sends it to sign-in (D-777) and writes nothing. A claim the console minted before the "
            "account changed is good for one call within two minutes (D-483, `ACTOR_TTL`): the orchestrator reads "
            "no account, and the rows below show the one use, the replay refused, and the stale claim refused.", "",
            *_table(rows, ["service", "kind", "route", "status", "refused", "audited", "note"],
                    "Not run.")]  # fmt: skip


def dump(walk: dict[str, Any]) -> str:
    """``walk.json`` with one route per line (a diff of two runs reads route by route)."""

    def one(x: Any) -> str:
        return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    head = {k: v for k, v in walk.items() if k not in ("console", "orchestrator")}
    parts = [f" {json.dumps(k)}: {json.dumps(v, sort_keys=True, ensure_ascii=False)}" for k, v in sorted(head.items())]
    parts.append(' "console": {"routes": [\n  ' + ",\n  ".join(one(r) for r in walk["console"]["routes"]) + "\n ]}")
    parts.append(' "orchestrator": [\n  ' + ",\n  ".join(one(r) for r in walk["orchestrator"]) + "\n ]")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def write_report(frag: Path) -> dict[str, Any]:
    walk = build(frag)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "walk.json").write_text(dump(walk), "utf-8")
    fj = json.loads((OUT / "findings.json").read_text("utf-8")) if (OUT / "findings.json").exists() else {}
    PAGE.write_text(render(walk, fj.get("findings", []), fj.get("verdict", "(no verdict written yet)")), "utf-8")
    return walk


# ---------------------------------------------------------------------------------------------- live mode
def live(base: str, walk_json: Path, out: Path) -> int:
    """Walk a running box by URL with the gates of a committed ``walk.json`` (classified by status alone: a live
    box gives no trace, so a validation answer is unclear there)."""
    import httpx

    walk = json.loads(walk_json.read_text("utf-8"))
    declared = load_declared()
    routes = [r for r in walk["console"]["routes"] if (r["method"], r["path"]) in declared]
    clients: dict[str, tuple[httpx.Client, str, httpx.Client]] = {}
    for col in COLUMNS:
        key = f"ROLE_WALK_{col.name.upper()}"
        page = httpx.Client(base_url=base, follow_redirects=False, timeout=30)
        api = httpx.Client(base_url=base, follow_redirects=False, timeout=30)
        csrf = ""
        if col.role is not None:
            user, pw, tok = (
                os.environ.get(f"{key}_USER"),
                os.environ.get(f"{key}_PASSWORD"),
                os.environ.get(f"{key}_TOKEN"),
            )
            if tok:
                api.headers["Authorization"] = f"Bearer {tok}"
            if user and pw:
                m = re.search(r'name="login_csrf" value="([^"]+)"', page.get("/login").text)
                r = page.post("/login", data={"username": user, "password": pw, "login_csrf": m.group(1) if m else ""})
                if r.status_code != 303 or r.headers.get("location", "").startswith("/login"):
                    print(f"{col.name}: sign-in did not succeed (status {r.status_code}); column skipped")
                    continue
                m = re.search(r'name="csrf" value="([^"]+)"', page.get("/").text)
                csrf = m.group(1) if m else ""
            elif not tok:
                continue
        clients[col.name] = (page, csrf, api)
    cells = []
    for r in routes:
        if r["method"] in CHANGING:
            continue  # a live box is not changed by the walk: reads only
        for name, (page, _, api) in clients.items():
            col = BY_NAME[name]
            url = fill(r["path"], "0" * 26)
            resp = (api if r["path"].startswith("/api/v1/") else page).get(url)
            got, _ = decide(col, r["path"], resp.status_code, resp.headers.get("location", ""))
            row = declared[(r["method"], r["path"])]
            cells.append({"method": r["method"], "path": r["path"], "column": name, "status": resp.status_code,
                          "verdict": verdict(expected_of(col, r["method"], r["path"], row), got)})  # fmt: skip
    out.write_text(json.dumps({"base": base, "cells": cells}, indent=1) + "\n", "utf-8")
    c = Counter(x["verdict"] for x in cells)
    print(f"live walk: {len(cells)} cells, " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) + f"; {out}")
    return 1 if any(k.isupper() for k in c) else 0


# ---------------------------------------------------------------------------------------------- main
TESTS = ("tests/console/test_matrix_role_walk.py", "tests/console/test_matrix_role_walk_rules.py",
         "tests/unit/test_matrix_role_walk_orchestrator.py")  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.role_walk", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inproc", help="run the walk's tests in process and write the report")
    sub.add_parser("report", help="write the report from the fragments of the last run")
    lv = sub.add_parser("live", help="walk a running box by URL (reads only)")
    lv.add_argument("--base-url", required=True)
    lv.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    # the tests leave their results here and the report is built from them: a scratch folder, never committed
    frag = Path(os.environ.get("TB_SCRATCH") or tempfile.gettempdir()) / "role-walk-fragments"
    if a.cmd == "inproc":
        shutil.rmtree(frag, ignore_errors=True)  # nothing of an earlier run is mixed in
        env = {**os.environ, FRAGMENTS_ENV: str(frag), "PYTHONPATH": "libs:services:.", "TB_ENV": "TEST"}
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "0", *TESTS]
        rc = subprocess.call(cmd, cwd=ROOT, env=env)
        if rc != 0:
            print(f"role walk: the tests did not pass (exit {rc}); the report is written from what they left")
        if not (frag / "console.json").exists():
            return rc or 1
    if a.cmd in ("inproc", "report"):
        walk = write_report(frag)
        c = counts([r for r in walk["console"]["routes"] if r.get("gate")]) + counts(walk["orchestrator"])
        print(
            f"role walk: {c['cells']} cells, allowed {c['allowed']}, refused {c['refused']}, against the matrix "
            f"{c['ALLOWED-BUT-MATRIX-REFUSES']} + {c['REFUSED-BUT-MATRIX-ALLOWS']}, unclear {c['unclear']}; {PAGE}"
        )
        return 0
    host = re.sub(r"[^A-Za-z0-9.-]", "_", a.base_url.split("//")[-1])[:60]
    return live(a.base_url.rstrip("/"), OUT / "walk.json", a.out or OUT / f"live-{host}.json")


if __name__ == "__main__":
    raise SystemExit(main())

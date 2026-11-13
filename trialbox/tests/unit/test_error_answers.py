"""NEW-TRUST-3 (D-555): an error answer built from an error's own text carries no value of the request.

Three rules, held by reading the code (so a new route cannot slip past) and by a few calls:

1. in the orchestrator, the text of a caught error (``str(exc)``, ``f"{exc}"``, ``exc.args``, ``"{}".format(exc)``:
   in a raise, a return or an assignment) is used only for the error classes listed here, whose texts are written
   in this repository; the few other places are listed one by one with what they are;
2. every text of those classes, wherever it is raised, is a fixed sentence or names only the values listed here (a
   status, a role, a job type, a limit: the box's own words, never what the caller typed);
3. the console's ``Unavailable`` (shown on pages and in ``/api/v1`` answers) never holds the text a service
   answered with: it is built from the service's name and its status.

A refusal's text that the console passes on (``Refused``, a ``Problem``'s message) is the orchestrator's, held by
rules 1 and 2. An error that is handed whole to a helper (``_fail(exc)``) or read by its own ``message`` field is
not judged here (D-555, "What it does not do"). Synthetic data only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "services"
LIBS = ROOT.parent / "libs" / "tb_common"
CHART = "A1234567"

#: error classes whose text may go into an answer, and what a text of the class may name
OWN_TEXT: dict[str, frozenset[str]] = {
    "ActorError": frozenset(),
    "RegistryError": frozenset({"prev['status']", "upd.status"}),
    "Rejected": frozenset({"role", "jtype", "limit", "role or 'unnamed'"}),
    "NotRetryable": frozenset({"failed.type", "busy[0]"}),
}
#: where those classes are raised (rule 2 reads every file of these). The two library files raise ActorError;
#: ``service_auth`` has a RegistryError of its own (the token registry's), which no answer repeats.
ORCH = sorted((ROOT / "orchestrator").glob("*.py"))
RAISED_IN = {cls: [*ORCH, LIBS / "service_auth.py", LIBS / "actor_v3.py"] if cls == "ActorError" else ORCH
             for cls in OWN_TEXT}  # fmt: skip

#: rule 1's other places, each with what it is. A place leaves this list when its text is made fixed; none joins.
KNOWN = {
    ("jobs.py", "StaleSnapshotError"): "a failed job's own error record (the job page of its staff), no request",
    ("jobs.py", "LlmPromptUnqualified"): "the same record: which prompt the gateway refused as unqualified",
    ("clients.py", "JobLost"): "the same record, from the nightly ingest's follow-up",
    ("canary_gate.py", "LlmError"): "the wake check's own line of the model gate (no request)",
    ("selftest.py", "LlmError"): "the self-test's report lines (no request)",
    ("datacore_api.py", "ValueError"): "datacore.forms' CTCAE check: a fixed sentence that lists the versions",
    ("migrate.py", "DatabaseError"): "the migration tool's own stderr",
    ("migrate.py", "EdcError"): "the migration tool's own stderr",
}


def _uses_text_of(node: ast.AST, name: str) -> bool:
    """Does ``node`` take the text of the caught error ``name``? ``str(name)``, ``repr(name)``, ``f"{name}"``,
    ``name.args``, ``"...".format(name)``. A log call is not an answer and is skipped by the caller."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            args = [a for a in n.args if isinstance(a, ast.Name) and a.id == name]
            if args and isinstance(n.func, ast.Name) and n.func.id in ("str", "repr"):
                return True
            if args and isinstance(n.func, ast.Attribute) and n.func.attr == "format":
                return True
        if isinstance(n, ast.FormattedValue) and isinstance(n.value, ast.Name) and n.value.id == name:
            return True
        if isinstance(n, ast.Attribute) and n.attr == "args" and isinstance(n.value, ast.Name) and n.value.id == name:
            return True
    return False


def _is_log(stmt: ast.stmt) -> bool:
    call = stmt.value if isinstance(stmt, ast.Expr) else None
    return (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and ast.unparse(call.func.value) in ("log", "logger", "logging", "self.log"))  # fmt: skip


def _caught(handler: ast.ExceptHandler) -> list[str]:
    t = handler.type
    items = t.elts if isinstance(t, ast.Tuple) else [t]
    return [ast.unparse(i).split(".")[-1] for i in items if i is not None]


def _text_uses(files: list[Path]) -> list[tuple[str, int, tuple[str, ...]]]:
    """Every statement of an ``except ... as <name>`` block that takes the caught error's text, logs apart."""
    found: list[tuple[str, int, tuple[str, ...]]] = []
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
            assert handler.name is not None
            for stmt in (n for b in handler.body for n in ast.walk(b) if isinstance(n, ast.stmt)):
                answers = isinstance(
                    stmt, ast.Raise | ast.Return | ast.Assign | ast.AnnAssign | ast.AugAssign | ast.Expr
                )
                if answers and not _is_log(stmt) and _uses_text_of(stmt, handler.name):
                    found.append((f.name, stmt.lineno, tuple(_caught(handler))))
    return sorted(set(found))


def test_the_orchestrator_uses_an_errors_text_only_for_the_listed_classes() -> None:
    found = _text_uses(sorted((ROOT / "orchestrator").glob("*.py")))
    assert len(found) >= 12, found  # the registry's, the job routes', the signed-person checks, the known places
    bad = [(f, line, list(classes)) for f, line, classes in found
           if not set(classes) <= set(OWN_TEXT) and not all((f, c) in KNOWN for c in classes if c not in OWN_TEXT)]  # fmt: skip
    assert bad == [], f"an answer repeats the text of an error not written here: {bad}"
    seen = {(f, c) for f, _, classes in found for c in classes}
    assert set(KNOWN) <= seen, f"no longer there, take them off the list: {sorted(set(KNOWN) - seen)}"


@pytest.mark.parametrize("cls", sorted(OWN_TEXT))
def test_every_text_of_a_listed_class_names_only_the_boxs_own_words(cls: str) -> None:
    made = 0
    for f in RAISED_IN[cls]:
        for call in (n for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.Call)):
            if ast.unparse(call.func).split(".")[-1] != cls:  # raised at once or kept in a name first
                continue
            made += 1
            for arg in call.args:
                assert isinstance(arg, ast.Constant | ast.JoinedStr), (f.name, call.lineno, ast.unparse(arg))
                named = {ast.unparse(v.value) for v in ast.walk(arg) if isinstance(v, ast.FormattedValue)}
                assert named <= OWN_TEXT[cls], f"{f.name}:{call.lineno}: the text names {sorted(named - OWN_TEXT[cls])}"
    assert made, cls


#: what the text of the console's Unavailable may be built from
UNAVAILABLE_NAMES = frozenset({"exc.service", "exc.status", "status", "type(exc).__name__"})


def test_the_consoles_unavailable_never_holds_a_services_text() -> None:
    made = 0
    for f in sorted((ROOT / "console").glob("*.py")):
        for call in (n for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.Call)):
            if ast.unparse(call.func).split(".")[-1] != "Unavailable":
                continue
            made += 1
            for arg in call.args:
                assert not (isinstance(arg, ast.Constant) and arg.value is None)
                assert all(isinstance(x, ast.Constant | ast.JoinedStr | ast.IfExp | ast.FormattedValue | ast.expr_context)
                           or ast.unparse(x) in UNAVAILABLE_NAMES or isinstance(x, ast.Name | ast.Attribute | ast.Call)
                           for x in ast.walk(arg)), (f.name, call.lineno)  # fmt: skip
                named = {ast.unparse(v.value) for v in ast.walk(arg) if isinstance(v, ast.FormattedValue)}
                bare = {ast.unparse(arg)} if not isinstance(arg, ast.Constant | ast.JoinedStr | ast.IfExp) else set()
                assert named | bare <= UNAVAILABLE_NAMES, f"{f.name}:{call.lineno}: built from {sorted(named | bare)}"
    assert made >= 6


def test_what_the_console_keeps_of_a_call_that_failed() -> None:
    from console.backend import Problem, Unavailable, failed, problem_of, service_and_status
    from tb_common.http import ServiceError

    said = f'{{"detail":"no row for chart {CHART}"}}'
    kept = failed(ServiceError("orchestrator", 500, said))
    assert str(kept) == "orchestrator returned 500" and service_and_status(kept) == "orchestrator returned 500"
    # the study API's answers, as the console reads them
    for status, want in ((500, "orchestrator returned 500"), (503, "orchestrator returned 503"),
                         (0, "orchestrator did not answer")):  # fmt: skip
        out = problem_of(status, said)
        assert isinstance(out, Unavailable) and str(out) == want
    # a refusal is named by its code when it has the shape of one; a code that is the caller's text is not shown
    assert service_and_status(Problem(400, "RC-FIELD", "x", [], [], {})) == "RC-FIELD"
    assert service_and_status(Problem(400, CHART.lower(), "x", [], [], {})) == "-"
    assert service_and_status(ValueError(CHART)) == "-"


def test_a_ruleset_with_no_approved_version_is_answered_with_a_fixed_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from orchestrator import app as oapp

    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(oapp, "orch", lambda: SimpleNamespace(rulesets_dir=tmp_path / "nowhere"))
    r = TestClient(oapp.app, raise_server_exceptions=False).get("/rulesets/GZQO")
    assert r.status_code == 404 and r.json() == {"detail": "no approved version of that ruleset on this box"}
    assert str(tmp_path) not in r.text


def test_a_ruleset_id_that_is_not_one_is_not_repeated() -> None:
    from orchestrator.candidates import RegistryError, check_ruleset

    with pytest.raises(RegistryError) as e:
        check_ruleset("A1234567 x")
    assert "A1234567" not in str(e.value)

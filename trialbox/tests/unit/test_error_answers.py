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
import functools
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
    # D-746: the setting TB_LAKE_QUERY_LIMITS cannot be read: its own part as written (a setting, not a record's value)
    "QueryLimitsUnread": frozenset({"part", "MAX_QUERY_LIMIT_S"}),
    # NEW-TRUST-5 (D-557): a failed job's error record. What a text may be built from: the study and its version,
    # the job's own type, state and ids, a limit, the name of an option (never its value), the name of a file the
    # sender attached, a count, another error's type. Not a chart number, not a typed option value, not an address.
    "StepFailed": frozenset(
        {
            "', '.join(not_keepable)",
            "', '.join(unknown)",
            "='No valid alliance table:\\n' + '\\n'.join((f'- {p}' for p in problems[:20]))",
            "='No valid rows: ' + '; '.join(errors[:10])",
            "='Not submitted to NHI — ' + '; '.join(gaps) + '.'",  # D-707: the gaps hold no engine's words
            "len(problems)",
            "rep.filename",
            "=RESTORE_HELD",
            "=_optout.NO_REGISTRY_TABLE",  # D-654: a fixed sentence, no snapshot, date or chart in it
            "=_ingest_ended(st)",
            "=_ingest_errors(report)",
            "=message",
            "=step",
            "=str(exc)",
            "=why_unreadable(filename, exc)",
            "MAX_AGE_DAYS",
            "MAX_CHART_CHARS",
            "MAX_ICF_CHARS",
            "OUTAGE_ENV",
            "_target(ctx)",
            "b.seconds_left()",
            "b.settings.failures",
            "body.get('resourceType')",
            "exc",
            "exc.label",
            "exc.reason",
            "exc.service",
            "exc.status",
            "f.filename",
            "failures",
            "head",
            "job.type",
            "judge.failures",
            "key",
            "len(bad)",
            "meta['ruleset']",
            "meta['version']",
            "name",
            "nav.job_id",
            "nav.state",
            "on['run']",
            "out.filename",
            "pid[:12]",
            "prior['job_id']",
            "prior['outcome']",
            "prompt",
            "recorded",
            "resp.status_code",
            "rid",
            "round(exc.allowance_s)",
            "round(exc.spent_s)",
            "rs.id",
            "rs.manifest.kind",
            "rs.version",
            "ruleset",
            "ruleset.upper()",
            "s.nct_id",
            "self._label",
            "so_far",
            "src.state",
            "state",
            "target",
            "target or 'the job'",
            "tid",
            "total",
            "type(exc).__name__",
            "wb.filename",
        }
    ),
    "FeasError": frozenset({"key", "len(hits)", "rs.id"}),
    # D-705: the re-run's own refusal (D-666). Its sentences are written in rerun.py and name the earlier job.
    "ReplayUnknown": frozenset({"job.job_id"}),
}
#: where those classes are raised (rule 2 reads every file of these). The two library files raise ActorError;
#: ``service_auth`` has a RegistryError of its own (the token registry's), which no answer repeats.
ORCH = sorted((ROOT / "orchestrator").rglob("*.py"))  # the scenarios and the reports too (D-557)
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
    ("rerun.py", "ReplayUnsure"): "the same refusal, from the store's record (D-670, D-648): job ids and site ids",
    ("rerun.py", "RecordChanged"): "the same: a recorded table that cannot be read, named by its job id",
    # the scenarios (D-557): another error's text inside a failed job's record, each an error written in this
    # repository about the study's own files (a prompt registry, a cascade, an approval workbook, a routing table)
    ("approve.py", "ValueError"): "the approval workbook's own reading errors (tb_common.ruleset)",
    ("screen.py", "PromptRegistryError"): "which prompt of the study's registry is not usable",
    ("screen.py", "LlmPromptUnqualified"): "the same: why this box may not use the study's judge prompt",
    ("screen.py", "LlmError"): "the same, for any other refusal of the box's prompt registry",
    ("screen_cascade.py", "CascadeError"): "why the cascade could not run for the study",
    ("twpas.py", "BundleDataMissing"): "which element of a TWPAS bundle has no data (element names)",
    ("twpas_bundle.py", "Exception"): "the first line of the FHIR validator's message for a built resource",
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
    found = _text_uses(ORCH)
    assert len(found) >= 12, found  # the registry's, the job routes', the signed-person checks, the known places
    bad = [(f, line, list(classes)) for f, line, classes in found
           if not set(classes) <= set(OWN_TEXT) and not all((f, c) in KNOWN for c in classes if c not in OWN_TEXT)]  # fmt: skip
    assert bad == [], f"an answer repeats the text of an error not written here: {bad}"
    seen = {(f, c) for f, _, classes in found for c in classes}
    assert set(KNOWN) <= seen, f"no longer there, take them off the list: {sorted(set(KNOWN) - seen)}"


@functools.cache
def _with_subclasses(cls: str) -> frozenset[str]:
    """The class and every class of the orchestrator made from it (``NotSubmitted(StepFailed)``): the same list."""
    names = {cls}
    for _ in range(3):
        for f in ORCH:
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.ClassDef) and any(ast.unparse(b).split(".")[-1] in names for b in n.bases):
                    names.add(n.name)
    return frozenset(names)


def _built_from(arg: ast.expr) -> set[str]:
    """What one argument of an error is built from: nothing for a literal, the interpolated expressions of an
    f-string, else the whole expression (written ``=<expression>``), which must be on the class's list."""
    if isinstance(arg, ast.Constant):
        return set()
    if isinstance(arg, ast.JoinedStr):  # an f-string itself; one inside a larger expression hides nothing
        return {ast.unparse(v.value) for v in ast.walk(arg) if isinstance(v, ast.FormattedValue)}
    return {"=" + ast.unparse(arg)}


@pytest.mark.parametrize("cls", sorted(OWN_TEXT))
def test_every_text_of_a_listed_class_names_only_the_boxs_own_words(cls: str) -> None:
    made = 0
    for f in RAISED_IN[cls]:
        for call in (n for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.Call)):
            if ast.unparse(call.func).split(".")[-1] not in _with_subclasses(cls):  # raised or kept in a name
                continue
            made += 1
            for arg in [*call.args, *[k.value for k in call.keywords]]:
                named = _built_from(arg)
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


# ------------------------------------------------------------------------------------ NEW-TRUST-5 (D-557)
def test_a_failed_jobs_record_keeps_the_errors_type_not_its_text() -> None:
    """Any error a job did not expect was kept in the job's record with 300 characters of its own text, which the
    job page shows: a database error quotes its values, a validation error prints its input."""
    from orchestrator.core import _error

    err = _error(RuntimeError(f"no row for chart {CHART}"), "running")
    assert err.message == "Internal error while processing the job." and err.detail == "RuntimeError"
    assert CHART not in err.model_dump_json()


def test_a_case_request_with_a_chart_number_of_the_wrong_shape_does_not_keep_it() -> None:
    import inspect

    from orchestrator.scenarios import case

    src = inspect.getsource(case)
    assert "mrn={mrn!r}" not in src and "does not look like a chart number of this site" in src


def test_two_more_answers_that_named_what_was_sent() -> None:
    """A notice refused for an outside address named the address; a source that does not exist named the path's
    value. Both are fixed sentences now (read from the code: neither route can be called without the whole box)."""
    import inspect

    from orchestrator import app as oapp
    from orchestrator import datacore_api

    assert "not {external[0]}" not in inspect.getsource(oapp)
    assert 'f"no source {name}"' not in inspect.getsource(datacore_api)


def test_the_rule_sees_a_value_beside_an_f_string_and_a_class_made_from_a_listed_one() -> None:
    """The review: an f-string anywhere in an argument hid the rest of it (``f"..." + repr(mrn)``), and the three
    classes made from StepFailed were not read at all."""
    arg = ast.parse('f"mrn= is not a chart number: " + repr(mrn)', mode="eval").body
    assert _built_from(arg) == {"=f'mrn= is not a chart number: ' + repr(mrn)"}
    assert _built_from(ast.parse('f"a {x}" if ok else secret', mode="eval").body) != {"x"}
    assert {"NotSubmitted", "ModelOutage", "BreakerOpen"} <= _with_subclasses("StepFailed")


def test_an_ingest_that_failed_leaves_the_errors_type_in_the_jobs_record() -> None:
    from orchestrator.clients import _ingest_ended, _step_error
    from tb_common.http import ServiceError

    said = _ingest_ended({"state": "failed", "detail": f"ConversionException: Could not convert '{CHART}' to INT32"})
    assert said == "The nightly ingest failed (ConversionException); the adapter's log has it."
    assert CHART not in _ingest_ended({"state": "failed", "detail": f"duckdb.ConversionException: bad {CHART}"})
    assert CHART not in _ingest_ended({"state": "failed", "detail": f"KeyError: '{CHART}'"})
    # the adapter's own sentences stay: they are its words for the operator
    assert _ingest_ended({"state": "failed", "detail": "the source folder is empty"}) == "the source folder is empty"
    assert "site key" in _ingest_ended({"state": "refused", "detail": "night refused: the site key changed"})
    assert _ingest_ended({"state": CHART}) == "the ingest ended not done"
    # another service's answer: its own message when it has the shape of one, else which service did not do it
    own = _step_error(ServiceError("parser", 422, '{"detail": {"step": "parsing", "message": "no text layer"}}'), "x")
    assert (own.step, own.message) == ("parsing", "no text layer")
    busy = _step_error(ServiceError("adapter", 409, '{"detail": "an ingest is already running"}'), "ingest")
    assert busy.message == "an ingest is already running"
    for status, body in ((500, f"Traceback ... {CHART}"), (500, f'{{"detail": "no row for {CHART}"}}'),
                         (0, f"unreachable: http://x/{CHART}"), (400, f"plain text {CHART}")):  # fmt: skip
        raw = _step_error(ServiceError("parser", status, body), "parsing")
        assert raw.message == "The parser service did not do this step." and CHART not in raw.message

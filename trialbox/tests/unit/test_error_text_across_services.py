"""NEW-TRUST-6 (D-700): across every service, the text of an error nobody wrote is used only in the listed places.

D-555 and D-557 hold the orchestrator's answers and job records. The same fault can sit in any service: a general
error (``Exception``, ``ValueError``, ``KeyError``, a file or OS error ...) is caught and its text is put into an
answer, a stored record or a report. Such a text is whatever the failing code put in it: a database engine quotes
the value it could not cast, a validator prints its input.

This test reads every service. A statement inside ``except <a general error> as e`` that takes the error's text
(``str(e)``, an f-string, ``.args``, ``.format``), outside a log call, must be on the list below, by service, file
and the error caught, with what it is. The list only shrinks: a card that makes a place say the error's type takes
its line off; a new place fails here. The lines of other lanes are theirs to take off (the integrator has them).

And one rule for a failure recorded by another service as ``"<Type>: <text>"``: whoever copies it into a record a
person reads keeps the type (``tb_common.http.kept_failure``). Synthetic data only."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from tests.unit.test_error_answers import _caught, _is_log, _uses_text_of

ROOT = Path(__file__).resolve().parents[2] / "services"
CHART = "A1234567"
GENERAL = {"Exception", "BaseException", "ValueError", "KeyError", "FileNotFoundError", "OSError", "RuntimeError",
           "TypeError", "LookupError", "AttributeError", "IndexError"}  # fmt: skip

#: this lane's places (the console, the orchestrator, the site set-up):
#: (file, the general errors caught) -> (how many statements, what it is). Exact.
MINE: dict[tuple[str, str], tuple[int, str]] = {
    ("console/app.py", "RuntimeError"): (1, "the cascade runs' own refusal: 'a cascade run is already running'"),
    ("console/approval.py", "ValueError"): (1, "a catalogue key raised by the approval form's own checks"),
    ("console/cli.py", "OSError"): (1, "the console's command-line tool, to its own stderr"),
    ("console/edc_pages.py", "OSError/ValueError"): (1, "the sign-in provider's own error class, else the type"),
    ("console/identity.py", "OSError/ValueError"): (1, "the same guard: the provider's own class, else the type"),
    ("orchestrator/datacore_api.py", "ValueError"): (1, "the CTCAE check's sentence that lists the versions (D-555)"),
    ("orchestrator/reports/twpas_bundle.py", "Exception"): (1, "the first line of the FHIR validator's message"),
    ("orchestrator/scenarios/approve.py", "ValueError"): (1, "the approval workbook's own reading errors (D-557)"),
}
#: other lanes' services, by reading, not judged here: file -> whose. Theirs to take off; the integrator has them.
THEIRS: dict[str, str] = {
    "adapter/app.py": "adapter", "adapter/backfill.py": "adapter", "adapter/mapping/sharereport.py": "adapter",
    "adapter/pipeline.py": "adapter", "adapter/publish.py": "adapter", "adapter/run_job.py": "adapter",
    "adapter/sources/ssmix2/source.py": "adapter", "adapter/validate/jpcore.py": "adapter",
    "adapter/validate/validator.py": "adapter",
    "embed_service/embedder.py": "models", "gateway/app.py": "models", "llm_stub/app.py": "models",
    "model_guard/__init__.py": "models",
    "lake/app.py": "lake (its own card, D-664)", "lake/store.py": "lake (its own card, D-664)",
    "mail_gateway/admin.py": "mail", "mail_gateway/app.py": "mail", "mail_gateway/gateway.py": "mail",
    "matching/proposed.py": "matching",
    "tracestore/app.py": "trace store",
}  # fmt: skip


def _found() -> Counter[tuple[str, str]]:
    """How many statements take a general error's text, by (file, the general errors caught)."""
    out: Counter[tuple[str, str]] = Counter()
    for f in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for h in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
            caught = sorted(set(_caught(h)) & GENERAL)
            if not caught:
                continue
            assert h.name is not None
            for stmt in (n for b in h.body for n in ast.walk(b) if isinstance(n, ast.stmt)):
                takes = isinstance(stmt, ast.Raise | ast.Return | ast.Assign | ast.AnnAssign | ast.AugAssign | ast.Expr)
                if takes and not _is_log(stmt) and _uses_text_of(stmt, h.name):
                    out[(str(f.relative_to(ROOT)), "/".join(caught))] += 1
    return out


def test_a_general_errors_text_is_used_only_in_the_listed_places() -> None:
    files = {f for f, _ in _found()}
    new = sorted(files - {f for f, _ in MINE} - set(THEIRS))
    assert new == [], f"an error's own text goes into an answer or a record here: {new}"
    assert not {f for f, _ in MINE} & set(THEIRS)


def test_this_lanes_places_are_exactly_the_listed_ones() -> None:
    """By file, the errors caught and how many statements: a new statement in a listed file fails too (the review:
    the first list was exact by file only, and the console's largest file has one listed place)."""
    found = {k: n for k, n in _found().items() if k[0].split("/")[0] in ("console", "orchestrator", "sitesetup")}
    listed = {k: n for k, (n, _) in MINE.items()}
    assert found == listed, sorted(set(found.items()) ^ set(listed.items()))
    # the two this card took off
    assert not [k for k in found if k[0] == "console/cascade.py" or k[0].startswith("sitesetup/")]


@pytest.mark.parametrize(
    ("recorded", "kept"),
    [
        (f"ConversionException: Could not convert string '{CHART}' to INT32", "ConversionException"),
        (f"duckdb.duckdb.ConversionException: bad {CHART}", "duckdb.duckdb.ConversionException"),
        (f"KeyError: '{CHART}'", "KeyError"),
        ("the source folder is empty", "the source folder is empty"),
        ("night refused: the site key changed", "night refused: the site key changed"),
        # the review: a name without a capital, or with a leading underscore, is an error's type too
        (f"error: Error -3 while decompressing data {CHART}", "error"),
        (f"gaierror: [Errno -2] {CHART}", "gaierror"),
        (f"_Refused: chart {CHART}", "_Refused"),
        (f"IO: {CHART}", "IO"),
        (f"ConversionException:\n{CHART}", "ConversionException"),
        ("lake snapshot 2026-10-04 is held by a running job", "lake snapshot 2026-10-04 is held by a running job"),
        (
            "the ingest's process ended with exit code 2 and no answer",
            "the ingest's process ended with exit code 2 and no answer",
        ),
        ("OSError", "OSError"),  # applying it twice changes nothing
        ("refused", "refused"),
        ("", ""),
    ],
)
def test_a_failure_recorded_as_type_and_text_is_kept_as_its_type(recorded: str, kept: str) -> None:
    from tb_common.http import kept_failure

    assert kept_failure(recorded) == kept
    assert CHART not in kept_failure(recorded) and kept_failure(kept) == kept


def test_a_failed_publish_of_the_site_set_up_keeps_the_engines_type() -> None:
    """The site set-up follows the lake's rebuild; a rebuild that broke is recorded by the lake as the engine's
    error, type and text, and the publish kept 300 characters of it in its answer and its record. (The path
    through a real publish is held by tests/unit/test_polled_jobs.py.) A record kept before this card is reduced
    when it is read."""
    from sitesetup.service import _failed

    old = {"state": "failed", "detail": f"ConversionException: Could not convert string '{CHART}' to INT32"}
    assert _failed(None, old)["detail"] == "ConversionException"
    assert _failed(None, {"detail": "lake snapshot 2026-10-04 is held"})["detail"] == "lake snapshot 2026-10-04 is held"


def test_a_cascade_run_that_broke_keeps_the_errors_type(tmp_path: Path) -> None:
    import time

    from console.cascade import CascadeRuns

    def broke(source: Path, trial: str, out: Path) -> dict[str, object]:
        raise RuntimeError(f"no row for chart {CHART}")

    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "patient.csv").write_text("pid\n", encoding="utf-8")  # a synthetic site drop is "mounted"
    runs = CascadeRuns(tmp_path / "runs", drop, runner=broke)
    run = runs.start("GZQO", "crc")
    for _ in range(200):
        got = runs.get(run.run_id)
        if got is not None and got.state != "running":
            break
        time.sleep(0.02)
    got = runs.get(run.run_id)
    assert got is not None and got.state == "failed" and got.error == "RuntimeError"
    # a run kept before this card holds the type and the text: shown as its type
    import json

    meta = tmp_path / "runs" / run.run_id / "run.json"
    kept = json.loads(meta.read_text(encoding="utf-8"))
    meta.write_text(json.dumps({**kept, "error": f"RuntimeError: no row for chart {CHART}"}), encoding="utf-8")
    again = runs.get(run.run_id)
    assert again is not None and again.error == "RuntimeError"


def test_a_subject_that_cannot_be_read_is_refused_without_repeating_what_was_typed() -> None:
    """The rejection reply of a mailed request, and the mail gateway's record of it, repeated the typed command,
    job id, ruleset, option and value (``unknown command 'A1234567'``). The texts name the rule; an option's NAME
    is said only once it is one of the allowed names."""
    from tb_common.subject import SubjectError, parse_subject

    for subject in (f"{CHART} GZQO", f"SCREEN {CHART}!", f"STATUS {CHART}", f"SCREEN GZQO {CHART}",
                    f"SCREEN GZQO {CHART}=1", f"SCREEN GZQO window={CHART}!"):  # fmt: skip
        with pytest.raises(SubjectError) as said:
            parse_subject(subject)
        assert CHART not in str(said.value), subject
    with pytest.raises(SubjectError, match="window"):  # the option's name, which is one of the allowed
        parse_subject(f"SCREEN GZQO window={CHART}!")


def test_a_command_line_that_cannot_be_read_is_refused_without_repeating_what_was_typed() -> None:
    """NEW-TRUST-7 (D-702): the command grammar of the console's request box and the chat channels refused a line
    with the typed token in the text (``'A1234567' must be key=value``, ``invalid study code 'A1234567'``), which
    the console shows and audits. The same rule as the mail subject's (D-700)."""
    from channels.grammar import GrammarError, _params, _study

    for tokens in ([CHART], [f"{CHART}=1"], [f"window={CHART}!"]):
        with pytest.raises(GrammarError) as said:
            _params(tokens)
        assert CHART not in str(said.value), tokens
    with pytest.raises(GrammarError, match="window"):  # a parameter's name, once it is one of the allowed
        _params([f"window={CHART}!"])
    with pytest.raises(GrammarError) as said:
        _study(f"{CHART}!")
    assert CHART not in str(said.value)

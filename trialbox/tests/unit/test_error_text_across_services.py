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
from pathlib import Path

import pytest

from tests.unit.test_error_answers import _caught, _is_log, _uses_text_of

ROOT = Path(__file__).resolve().parents[2] / "services"
CHART = "A1234567"
GENERAL = {"Exception", "BaseException", "ValueError", "KeyError", "FileNotFoundError", "OSError", "RuntimeError",
           "TypeError", "LookupError", "AttributeError", "IndexError"}  # fmt: skip

#: this lane's places (the console, the orchestrator, the site set-up): file -> what it is
MINE: dict[str, str] = {
    "console/app.py": "the cascade runs' own refusal: 'a cascade run is already running'",
    "console/approval.py": "a catalogue key raised by the approval form's own checks, translated before it is shown",
    "console/cli.py": "the console's command-line tool, to its own stderr",
    "console/edc_pages.py": "the text only of the sign-in provider's own error class, else the error's type",
    "console/identity.py": "the same guard: the provider's own error class, else the type",
    "orchestrator/reports/twpas_bundle.py": "the first line of the FHIR validator's message for a built resource",
    "orchestrator/scenarios/approve.py": "the approval workbook's own reading errors (D-557)",
    "orchestrator/datacore_api.py": "the CTCAE check's sentence that lists the versions (D-555)",
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


def _found() -> set[str]:
    out: set[str] = set()
    for f in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for h in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
            caught = set(_caught(h)) & GENERAL
            if not caught:
                continue
            assert h.name is not None
            for stmt in (n for b in h.body for n in ast.walk(b) if isinstance(n, ast.stmt)):
                takes = isinstance(stmt, ast.Raise | ast.Return | ast.Assign | ast.AnnAssign | ast.AugAssign | ast.Expr)
                if takes and not _is_log(stmt) and _uses_text_of(stmt, h.name):
                    out.add(str(f.relative_to(ROOT)))
    return out


def test_a_general_errors_text_is_used_only_in_the_listed_places() -> None:
    new = sorted(_found() - set(MINE) - set(THEIRS))
    assert new == [], f"an error's own text goes into an answer or a record here: {new}"
    assert not set(MINE) & set(THEIRS)


def test_this_lanes_services_have_no_place_left_but_the_listed_ones() -> None:
    found = _found()
    mine = {f for f in found if f.split("/")[0] in ("console", "orchestrator", "sitesetup")}
    assert mine == set(MINE), sorted(mine ^ set(MINE))  # exactly: a place made type-only leaves the list
    # the two this card took off
    assert "console/cascade.py" not in found and not [f for f in found if f.startswith("sitesetup/")]


@pytest.mark.parametrize(
    ("recorded", "kept"),
    [
        (f"ConversionException: Could not convert string '{CHART}' to INT32", "ConversionException"),
        (f"duckdb.duckdb.ConversionException: bad {CHART}", "duckdb.duckdb.ConversionException"),
        (f"KeyError: '{CHART}'", "KeyError"),
        ("the source folder is empty", "the source folder is empty"),
        ("night refused: the site key changed", "night refused: the site key changed"),
        ("refused", "refused"),
        ("", ""),
    ],
)
def test_a_failure_recorded_as_type_and_text_is_kept_as_its_type(recorded: str, kept: str) -> None:
    from tb_common.http import kept_failure

    assert kept_failure(recorded) == kept
    assert CHART not in kept_failure(recorded)


def test_a_failed_publish_of_the_site_set_up_keeps_the_engines_type() -> None:
    """The site set-up follows the lake's rebuild; a rebuild that failed is recorded by the lake as the engine's
    error, type and text, and the publish kept 300 characters of it for the page."""
    import inspect

    from sitesetup import service

    src = inspect.getsource(service)
    assert 'detail = str(st.get("detail") or state)[:300]' not in src and "kept_failure(" in src


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

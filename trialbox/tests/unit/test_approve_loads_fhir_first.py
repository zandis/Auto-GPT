"""G3 of the integrator's second review of the P1b run (#639, 2026-11-16), D-952: on NCT00910715 and NCT02380352 the
FHIR server refused the approval's load (FhirEvalError). ``Compiler.approve`` loaded after it had written, tagged and
promoted the ruleset, unguarded: the ruleset was left approved and released while the job failed with an HTTP 500.

* The load runs before anything is written: a refusal is a ``CompileFailed`` at the approve step (a 422), with the
  server's text, and the repo has no tag, no promotion and no approved manifest.
* A load that succeeds approves as before.
* The refusal says what the server said through ``server_said`` (D-959): a patient's id in it is masked; a transport
  error is named by its type.

The shipped GZQO protocol with the stub model; a FHIR stand-in.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from criteria_compiler.service import CompileFailed
from tb_common.fhir import FhirEvalError

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401


class Fhir:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.loads = error, 0

    def load(self, libraries: list[dict[str, Any]], valuesets: Any) -> None:
        self.loads += 1
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    "error",
    [FhirEvalError("PUT ValueSet/x: 422 HAPI-0450: id is too long"), httpx.ConnectError("connection refused")],
)
def test_a_refused_load_fails_the_approval_and_releases_nothing(env: dict[str, Any], error: Exception) -> None:  # noqa: F811
    res = _compile(env)
    env["deps"].fhir = Fhir(error)
    repo = env["deps"].repo
    before = (repo.tags("GZQO/"), repo.ref("main"))
    with pytest.raises(CompileFailed) as exc:
        _approve(env, _decisions(env["store"], res.review_xlsx_key))
    said = str(error)[:20] if isinstance(error, FhirEvalError) else type(error).__name__
    assert exc.value.step == "approve" and said in str(exc.value)
    assert (repo.tags("GZQO/"), repo.ref("main")) == before  # no tag, no promotion, nothing written to main
    assert "GZQO/v1.0.0" not in repo.tags("GZQO/")


def test_a_load_that_succeeds_approves_as_before(env: dict[str, Any]) -> None:  # noqa: F811
    res = _compile(env)
    env["deps"].fhir = fhir = Fhir()
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert out.status == "approved" and out.tag == "GZQO/v1.0.0" and fhir.loads == 1


def test_a_patients_id_in_the_servers_refusal_is_masked(env: dict[str, Any]) -> None:  # noqa: F811
    """D-952 with D-959: the job's error and the log carry the server's text, never a patient's id in it."""
    res = _compile(env)
    env["deps"].fhir = Fhir(FhirEvalError("PUT Library/x: 422 evaluating Patient/P00012345 failed"))
    with pytest.raises(CompileFailed) as exc:
        _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert "422" in str(exc.value) and "P00012345" not in str(exc.value)

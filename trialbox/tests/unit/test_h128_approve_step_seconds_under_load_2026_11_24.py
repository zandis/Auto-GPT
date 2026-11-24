"""Card H-128: the FHIR libraries built for the load (FHIRHelpers read from the translator's jar, each library's CQL
and ELM encoded) were in no named step of ``Compiler.approve``: the time between ``compiler.files`` and the
``compiler.fhir_load`` lap went to ``compiler.unaccounted``. It is the only part of approve outside every named step
that reads a file, and on a loaded runner it took 0.79 s (H-45's test, unit shard 6/8). It is now under
``compiler.fhir_load``. Stand-ins only: the stub model, no FHIR server; the slow part is a sleep planted in the test's
wrapper, never in product code."""

from __future__ import annotations

import time
from typing import Any

import pytest
from criteria_compiler import service

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 - env is a fixture

SLOW = 0.5


class Fhir:
    def load(self, libraries: list[dict[str, Any]], valuesets: Any) -> None:
        return None


def test_the_fhir_libraries_built_for_the_load_are_under_fhir_load(
    env: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    res = _compile(env)
    env["deps"].fhir = Fhir()
    real = service.library_resource
    built: list[str] = []

    def slow_library(name: str, *a: Any) -> dict[str, Any]:  # the test's sleep where a loaded runner waited
        built.append(name)
        if name == "FHIRHelpers":
            time.sleep(SLOW)
        return real(name, *a)

    monkeypatch.setattr(service, "library_resource", slow_library)
    out = _approve(env, _decisions(env["store"], res.review_xlsx_key))
    assert out.status == "approved" and built.count("FHIRHelpers") == 1
    steps = out.step_seconds or {}
    assert steps["compiler.fhir_load"] >= SLOW  # the planted wait lands under the load's own name
    assert steps["compiler.unaccounted"] < SLOW  # and not in the remainder

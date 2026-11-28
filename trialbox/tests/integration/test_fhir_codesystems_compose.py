"""V-18 (D-1182) on the FHIR store of the stack: the code systems the box carries are loaded into it, and the store then
validates codes and gives their names and hierarchy; an update names the version it replaces, and a rollback puts it
back from the store's own history."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.stack import url

pytestmark = pytest.mark.integration


def _fhir() -> str:
    """H-139: read from the running test stack when a test runs, not at import (a collection asks no engine)."""
    return url("FHIR", "/fhir")


TERM = Path("/nonexistent-terminology")  # nothing loaded at install: the shipped tables answer


def _params(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in body.get("parameter") or []:
        if p["name"] == "property":
            parts = {x["name"]: x.get("valueCode") or x.get("valueString") for x in p.get("part") or []}
            out.setdefault("property", {})[parts.get("code")] = parts.get("value")
        else:
            out[p["name"]] = next((v for k, v in p.items() if k.startswith("value")), None)
    return out


def test_the_store_validates_names_and_places_a_loaded_code() -> None:
    from tools import fhir_codesystems as fc

    store = fc.Store(_fhir())
    keys = ("icd10cm", "department", "atc")
    out = {o.key: o for o in fc.load(store, TERM, [s for s in fc.SOURCES if s.key in keys], wait=600)}
    assert out["icd10cm"].state in ("loaded", "unchanged") and out["department"].state in ("loaded", "unchanged")
    assert out["atc"].state == "skipped" and "permission-to-ask" in out["atc"].detail
    # asked once each, right after the load: the load waited until the store had stored every code, so no early
    # "not found" is cached (the store keeps a validation answer for minutes)
    http = httpx.Client(timeout=60)
    ask = {"system": fc.ICD10CM, "code": "A00.0", "property": "parent"}
    got = _params(http.get(f"{_fhir()}/CodeSystem/$lookup", params=ask).json())
    assert got.get("display") == "Cholera due to Vibrio cholerae 01, biovar cholerae"
    assert got.get("property", {}).get("parent") == "A00" and str(got.get("version")).startswith("FY2026+")
    ok = _params(http.get(f"{_fhir()}/CodeSystem/$validate-code", params={"url": fc.ICD10CM, "code": "M10.0"}).json())
    assert ok.get("result") is True and ok.get("display") == "Idiopathic gout"
    bad = _params(
        http.get(f"{_fhir()}/CodeSystem/$validate-code", params={"url": fc.ICD10CM, "code": "SYN.ZZ9"}).json()
    )
    assert bad.get("result") is False


def test_an_update_and_its_rollback_in_the_store() -> None:
    from tools import fhir_codesystems as fc

    store = fc.Store(_fhir())
    dept = next(s for s in fc.SOURCES if s.key == "department")
    fc.load(store, TERM, [dept])
    before = store.get("CodeSystem", "tb-department")
    assert before is not None
    newer = replace(dept, reader=lambda p: [*fc._parquet(p), {"code": "SYN-V18", "display": "Synthetic department"}])
    (o,) = fc.load(store, TERM, [newer])
    after = store.get("CodeSystem", "tb-department")
    assert o.state == "loaded" and after is not None and fc.replaced(after)[0] == before["version"]
    assert {r["key"]: r for r in fc.status(store)}["department"]["replaces"] == before["version"]
    fc.rollback(store, "department")
    back = store.get("CodeSystem", "tb-department")
    assert back is not None and back["version"] == before["version"] and fc.digest_of(back) == fc.digest_of(before)
    assert "SYN-V18" not in {c["code"] for c in back["concept"]}

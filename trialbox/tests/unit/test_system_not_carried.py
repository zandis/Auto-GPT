"""F11 of the first look at a real site export (#639, 2026-11-15): a value set in a code system the site's data does not
carry is said plainly, never a silent FALSE.

A site that has no ATC on any table (drugs only as NHI claim lines) matched every ATC value set against nothing: an
inclusion on a drug read FALSE for everyone, an exclusion on a drug never fired, and nobody was told. The runtime now
reads, once per run, which code systems each domain's rows carry. A coded criterion whose value set has no system the
domain carries cannot answer: a FALSE that a record could have made TRUE (and a TRUE that a record could have made
FALSE, under "none") becomes unknown with the reason ``code_system_not_carried``, on the cascade and on the SQL engine
of NAV / MICROBATCH / CASE. The approved SQL is unchanged. Synthetic fixture (the off-list one, D-113 / D-130).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.carried import NOT_CARRIED, Carried
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.evaluate import SqlEngine
from tb_common.reasons import CODES, LABELS
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

from tests.offlist_fixture import FIX, SNAPSHOT, index_date, offlist_ruleset

ROOT = Path(__file__).resolve().parents[2]
ATC = "http://www.whocc.no/atc"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"


def _crit(cid: str, kind: str, quantifier: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "OFFL", "kind": kind, "class": "structured", "text": cid,
         "logic": {"domain": "medication", "quantifier": quantifier, "valueset": "VS_URATE_LOWERING_THERAPY"}}
    )  # fmt: skip


def _lake(tmp: Path, with_drugs: bool) -> LakeLocal:
    from lake.store import Lake

    src = tmp / "src"
    src.mkdir()
    for f in FIX.glob("*.ndjson"):
        if with_drugs or f.name != "MedicationRequest.ndjson":
            shutil.copy(f, src / f.name)
    Lake(tmp / "lake").rebuild(SNAPSHOT, HashEmbedder(), src)
    return LakeLocal(tmp / "lake", HashEmbedder())


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    crit, vs, vsi, expected = offlist_ruleset()
    crit = [*crit, _crit("OFFL-EXC-02", "exclusion", "any"), _crit("OFFL-INC-05", "inclusion", "none")]
    sql = SqlGenerator("OFFL", "1.0.0", vsi).render(crit)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "OFFL", "library": None, "criteria": [c.id for c in crit]})
    rs = Ruleset(manifest=manifest, criteria=crit, valuesets=vs, sql=sql)
    return {
        "rs": rs,
        "day": index_date(expected),
        "drugs": _lake(tmp_path_factory.mktemp("with-drugs"), True),
        "none": _lake(tmp_path_factory.mktemp("no-drugs"), False),
    }


def test_the_systems_each_domain_carries_are_read_from_the_snapshot(world: dict[str, Any]) -> None:
    full = Carried.load(world["drugs"], SNAPSHOT)
    assert ICD in full.systems["condition"] and ATC in full.systems["medication"]
    bare = Carried.load(world["none"], SNAPSHOT)
    assert ICD in bare.systems["condition"] and not bare.systems["medication"]
    by = {c.id: c for c in world["rs"].criteria}
    vs = world["rs"].valuesets
    assert full.missing(by["OFFL-INC-02"], vs) == ([], [])
    assert bare.missing(by["OFFL-INC-02"], vs) == ([f"medication: {ATC}"], [])
    assert bare.missing(by["OFFL-INC-05"], vs) == ([], [f"medication: {ATC}"])  # "none": a record makes it falser
    assert bare.missing(by["OFFL-INC-01"], vs) == ([], [])  # ICD-10-CM is carried
    assert Carried().missing(by["OFFL-INC-02"], vs) == ([], [])  # not read: no check


def test_the_sql_engine_says_a_drug_set_cannot_answer_where_no_drug_is_coded(world: dict[str, Any]) -> None:
    rs, day = world["rs"], world["day"]
    ids = [c.id for c in rs.criteria]
    pids = sorted({r["pid"] for r in world["none"].query("SELECT pid FROM patient", None, SNAPSHOT).to_pylist()})
    got = SqlEngine(world["none"], SNAPSHOT).evaluate(rs, pids, day, ids)
    for pid, ev in got.items():
        why = ev.reasons or {}
        assert ev.results["OFFL-INC-02"] is None and why.get("OFFL-INC-02") == NOT_CARRIED, pid
        assert ev.results["OFFL-EXC-02"] is None and why.get("OFFL-EXC-02") == NOT_CARRIED, pid
        assert ev.results["OFFL-INC-05"] is None and why.get("OFFL-INC-05") == NOT_CARRIED, pid
        assert why.get("OFFL-INC-01") != NOT_CARRIED  # the diagnoses answer as before
    full = SqlEngine(world["drugs"], SNAPSHOT).evaluate(rs, pids, day, ids)
    assert not any(NOT_CARRIED in (e.reasons or {}).values() for e in full.values())  # drugs coded: as before


def test_the_cascade_sends_the_criterion_to_a_person_and_never_excludes_on_it(world: dict[str, Any]) -> None:
    rs, day = world["rs"], world["day"]
    pids = sorted({r["pid"] for r in world["none"].query("SELECT pid FROM patient", None, SNAPSHOT).to_pylist()})
    # v1 semantics: an inclusion's FALSE is a hard exclusion, so the old silent FALSE would drop every patient here
    cfg = CascadeConfig(study_id="OFFL", run_date=day, index_mode="single", population=pids, semantics="v1",
                        snapshot=None)  # fmt: skip
    res = run_cascade(world["none"], rs, cfg)
    scoped = [t for t in res.traces.values() if t.in_scope and "OFFL-INC-02" in t.outcomes]
    assert scoped
    for t in scoped:
        if "OFFL-INC-02" in t.outcomes:
            o = t.outcomes["OFFL-INC-02"]
            assert (o.status, o.reason) == ("unknown", NOT_CARRIED), t.pid
        if "OFFL-EXC-02" in t.outcomes:
            o = t.outcomes["OFFL-EXC-02"]
            assert o.status == "pass" and o.reason == NOT_CARRIED and o.unknown_kind == "data_gap", t.pid
        assert t.exit_criterion not in ("OFFL-INC-02", "OFFL-INC-05"), t.pid


def test_the_reason_is_a_code_with_three_labels() -> None:
    assert NOT_CARRIED in CODES and set(LABELS[NOT_CARRIED]) == {"en", "ja", "zh-TW"}

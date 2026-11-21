"""Lane G's scorer review, point 4 (#639, 2026-11-15), D-917: SCREEN's compiled SQL read condition rows whatever their
clinical status, so a resolved cancer still answered an "active malignancy" exclusion TRUE.

* A condition atom may say which clinical statuses count (``clinical_status``). A row recorded with one of them, or
  with none (most hospital sources record none), counts as it always did. A row recorded with another status
  (resolved, inactive, in remission) cannot settle the atom: where nothing else does, the answer is unknown, reason
  ``condition_not_active``. It is never a silent "active", and never a silent "not there" either.
* The SQL (runtime) and the CQL (the approval's equivalence gate) say the same.
* The compiler sets it when the criterion's line says active or current and not past (en, ja, zh-TW), flagged for the
  reviewer. "History of X" keeps every row. A shipped ruleset keeps its approved IR, so nothing shipped changes.

Synthetic FHIR conditions; the lake in-process; the local CQL engine where it is fetched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from doc_parser.parser import language
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from pydantic import ValidationError
from tb_common.audit import AuditLog
from tb_common.reasons import LABELS, Reason
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, LlmExtractOutput
from tb_contracts.criterion_ir import ACTIVE_STATUSES, downgrade_to_v1, upgrade_v1

ROOT = Path(__file__).resolve().parents[2]
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
CLIN = "http://terminology.hl7.org/CodeSystem/condition-clinical"
IDX = date(2026, 10, 5)
ACTIVE: list[str] = list(ACTIVE_STATUSES)


def _cond(pid: str, cid: str, code: str, status: str | None, onset: str | None = "2026-01-10") -> dict[str, Any]:
    c: dict[str, Any] = {"resourceType": "Condition", "id": cid, "subject": {"reference": f"Patient/{pid}"},
                         "code": {"coding": [{"system": ICD, "code": code}]}}  # fmt: skip
    if onset:
        c["onsetDateTime"] = onset
    if status:
        c["clinicalStatus"] = {"coding": [{"system": CLIN, "code": status}]}
    return c


CONDITIONS = [
    _cond("P-ACTIVE", "c1", "C34.9", "active"),
    _cond("P-RESOLVED", "c2", "C34.9", "resolved"),  # a cured cancer
    _cond("P-REMISSION", "c3", "C50.9", "remission"),
    _cond("P-NOSTATUS", "c4", "C34.9", None),  # the source records no status: as it always counted
    _cond("P-BOTH", "c5", "C34.9", "resolved"),
    _cond("P-BOTH", "c6", "C50.9", "relapse"),  # an earlier one cured, a relapse now: active
    _cond("P-RES-UNDATED", "c7", "C34.9", "resolved"),
    _cond("P-RES-UNDATED", "c8", "C34.9", None, onset=None),
    _cond("P-SPACE", "c9", "C34.9", " Active "),  # a padded code: the CQL engine's parser trims it, so does the SQL
    _cond("P-MIX", "c10", "C34.9", "active"),
    _cond("P-MIX", "c11", "C34.9", "resolved"),
    _cond("P-MIX", "c12", "C50.9", "resolved"),
]
PIDS = ["P-ACTIVE", "P-RESOLVED", "P-REMISSION", "P-NOSTATUS", "P-BOTH", "P-RES-UNDATED", "P-SPACE", "P-MIX", "P-NONE"]
VS = {"VS_MALIG": valueset("CS", "VS_MALIG", "malignancy", [Concept(ICD, "C34.9", "lung"), Concept(ICD, "C50.9", "breast")],
                           "1.0.0")}  # fmt: skip


def _crit(
    cid: str, kind: str, statuses: list[str] | None, quantifier: str = "any", count: int | None = None
) -> CriterionIR:
    atom: dict[str, Any] = {"domain": "condition", "quantifier": quantifier, "valueset": "VS_MALIG",
                            "window": {"anchor": "index", "from_days": None, "to_days": 0}}  # fmt: skip
    if statuses is not None:
        atom["clinical_status"] = statuses
    if count is not None:
        atom["count"] = count
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "CS", "kind": kind, "class": "structured", "text": cid, "logic": atom}
    )


CRIT = [
    _crit("CS-EXC-01", "exclusion", ACTIVE),  # active malignancy
    _crit("CS-EXC-02", "exclusion", None),  # history of malignancy: every row, as before
    _crit("CS-INC-01", "inclusion", ACTIVE, "none"),  # no active malignancy
    _crit("CS-INC-02", "inclusion", ACTIVE, "count>=", 2),  # two active malignancy records
]
IDS = [c.id for c in CRIT]


@pytest.fixture(scope="module")
def setup(tmp_path_factory: pytest.TempPathFactory) -> tuple[LakeLocal, Ruleset, Path]:
    tmp = tmp_path_factory.mktemp("clinical-status")
    nd = tmp / "ndjson"
    nd.mkdir()
    pats = [{"resourceType": "Patient", "id": p, "birthDate": "1960-01-01", "gender": "male"} for p in PIDS]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p in pats) + "\n", encoding="utf-8")
    (nd / "Condition.ndjson").write_text("\n".join(json.dumps(c) for c in CONDITIONS) + "\n", encoding="utf-8")
    (nd / "Observation.ndjson").write_text("", encoding="utf-8")
    Lake(tmp / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    sql = SqlGenerator("CS", "1.0.0", ValueSets("CS", VS, Terminology())).render(CRIT)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "CS", "library": None, "criteria": IDS})
    return LakeLocal(tmp / "lake", HashEmbedder()), Ruleset(manifest=manifest, criteria=CRIT, valuesets=VS, sql=sql), nd


# what each patient's criteria answer (the compiled predicate: TRUE, FALSE or unknown)
EXPECTED: dict[str, dict[str, bool | None]] = {
    "P-ACTIVE": {"CS-EXC-01": True, "CS-EXC-02": True, "CS-INC-01": False, "CS-INC-02": False},
    # one resolved row cannot reach two records, counted or not: FALSE, as before
    "P-RESOLVED": {"CS-EXC-01": None, "CS-EXC-02": True, "CS-INC-01": None, "CS-INC-02": False},
    "P-REMISSION": {"CS-EXC-01": None, "CS-EXC-02": True, "CS-INC-01": None, "CS-INC-02": False},
    "P-NOSTATUS": {"CS-EXC-01": True, "CS-EXC-02": True, "CS-INC-01": False, "CS-INC-02": False},
    "P-BOTH": {"CS-EXC-01": True, "CS-EXC-02": True, "CS-INC-01": False, "CS-INC-02": None},
    "P-RES-UNDATED": {"CS-EXC-01": None, "CS-EXC-02": True, "CS-INC-01": None, "CS-INC-02": None},
    "P-SPACE": {"CS-EXC-01": True, "CS-EXC-02": True, "CS-INC-01": False, "CS-INC-02": False},
    # one active and two resolved: two active records cannot be told, so unknown
    "P-MIX": {"CS-EXC-01": True, "CS-EXC-02": True, "CS-INC-01": False, "CS-INC-02": None},
    "P-NONE": {"CS-EXC-01": False, "CS-EXC-02": False, "CS-INC-01": True, "CS-INC-02": False},
}


def test_the_sql_counts_active_or_unstated_rows_and_a_resolved_one_is_unknown(
    setup: tuple[LakeLocal, Ruleset, Path],
) -> None:
    lake, rs, _ = setup
    rows = lake.query(rs.sql, [[IDX.isoformat()], None]).to_pylist()
    got = {r["pid"]: {k[2:]: v for k, v in r.items() if k.startswith("C_")} for r in rows}
    assert got == EXPECTED


def test_a_resolved_condition_is_unknown_with_its_own_reason_never_an_exclusion(
    setup: tuple[LakeLocal, Ruleset, Path],
) -> None:
    lake, rs, _ = setup
    ev = SqlEngine(lake).evaluate(rs, PIDS, IDX, IDS)
    exc = rs.criteria[0]
    for pid in ("P-RESOLVED", "P-REMISSION"):
        v = structured_verdict(exc, ev[pid])
        assert v.verdict == "unknown" and v.evidence is not None, pid
        assert v.evidence.reason == Reason.CONDITION_NOT_ACTIVE.value and v.evidence.resource_refs, pid
        assert "condition_not_active" not in v.evidence.resource_refs  # the token is read, not shown as a record
    assert structured_verdict(exc, ev["P-ACTIVE"]).verdict == "fail"
    assert structured_verdict(exc, ev["P-NOSTATUS"]).verdict == "fail"
    assert structured_verdict(rs.criteria[1], ev["P-RESOLVED"]).verdict == "fail"  # history of: as before
    # review of D-917: two active records asked, one active and two resolved: unknown for the resolved rows, which
    # are shown; a decided answer shows only the rows that decided it
    mix = structured_verdict(rs.criteria[3], ev["P-MIX"])
    assert mix.verdict == "unknown" and mix.evidence is not None
    assert mix.evidence.reason == Reason.CONDITION_NOT_ACTIVE.value
    assert {r.split("|")[0] for r in mix.evidence.resource_refs or []} == {"c10", "c11", "c12"}
    both = structured_verdict(exc, ev["P-BOTH"])
    assert both.verdict == "fail" and both.evidence is not None
    assert {r.split("|")[0] for r in both.evidence.resource_refs or []} == {"c6"}
    assert set(LABELS[Reason.CONDITION_NOT_ACTIVE.value]) == {"en", "ja", "zh-TW"}


def test_the_cql_says_the_same(setup: tuple[LakeLocal, Ruleset, Path]) -> None:
    gen = CqlGenerator("CS", "1.0.0", ValueSets("CS", VS, Terminology()))
    cql = gen.render(CRIT)
    assert 'define "S_CS-EXC-01_1"' in cql and 'define "S_CS-EXC-02_1"' not in cql
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source
    from tb_common.fhir import FhirEvaluator, library_resource

    from tools import cql_eval

    if not (available() and cql_eval.available()):
        pytest.skip("CQL translator or local CQL engine not available (python -m tools.cql_eval --fetch)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    head = next(x for x in cql.splitlines() if x.startswith("library "))
    version = head.split(" version ")[1].strip().strip("'")
    libs = [library_resource("TB_Common", "1.0.0", render_common(), tr.elm.get("TB_Common")),
            library_resource(gen.library, version, cql, tr.elm.get(gen.library))]  # fmt: skip
    _, _, nd = setup
    pats = (nd / "Patient.ndjson").read_text(encoding="utf-8").splitlines()
    lines = [*pats, *map(json.dumps, CONDITIONS), *(json.dumps(v) for v in VS.values()), *map(json.dumps, libs)]
    exprs = CqlGenerator.expression_names(CRIT)
    bodies = cql_eval.run(lines, gen.library, version, IDX, exprs, PIDS)
    got = {}
    for body in bodies:
        pid = str(body.get("id"))
        got[pid] = {k: v for k, v in FhirEvaluator.parse(pid, IDX, body, exprs).results.items() if k in IDS}
    assert got == EXPECTED


def _extracted(text: str, kind: str = "exclusion") -> LlmExtractOutput:
    return LlmExtractOutput.model_validate({"criteria": [{
        "kind": kind, "class": "structured", "text": text,
        "logic": {"domain": "condition", "concept": "malignancy", "quantifier": "any"},
        "concept_candidates": [{"name": "malignancy", "domain": "condition"}]}]})  # fmt: skip


@pytest.mark.parametrize(
    ("text", "active"),
    [
        ("Active malignancy", True),
        ("Current or ongoing cancer", True),
        ("活動性の悪性腫瘍", True),
        ("一年內有活動性結核病。", True),
        ("目前有惡性腫瘍", True),
        ("History of malignancy", False),
        ("History of active tuberculosis", False),  # past: every row counts
        ("悪性腫瘍の既往", False),
        ("曾罹患惡性腫瘍", False),
        ("Inactive hepatitis B carrier", False),  # "inactive" is not "active"
        # review of D-917: lines that say it is over, or ever, keep every row
        ("Currently in remission from AML", False),
        ("Non-active hepatitis B carrier", False),
        ("No longer active disease", False),
        ("Patients whose cancer is currently cured", False),
        ("非活動性B型肝炎", False),
        ("活動性のない結核", False),
        ("現在までに悪性腫瘍と診断された", False),
    ],
)
def test_the_compiler_reads_active_from_the_line(text: str, active: bool, tmp_path: Path) -> None:
    post = pp.postprocess(
        "T",
        _extracted(text),
        Terminology(),
        "1.0.0",
        audit=AuditLog(tmp_path),
        sources=[pp.PresenceSource(text, "exclusion", language([text]))],
    )
    (c,) = post.criteria
    status = c.logic.clinical_status  # type: ignore[union-attr]
    assert (status == ACTIVE) is active, (text, status)
    assert ("clinical_status_from_text" in (c.flags or [])) is active
    assert any("recorded as active" in w for w in post.warnings) is active


def test_the_reviewer_sees_the_restriction() -> None:
    from criteria_compiler.review import atom_summary

    assert "only recorded as active, recurrence, relapse, or with no status" in atom_summary(CRIT[0].logic, VS)  # type: ignore[arg-type]
    assert "only recorded" not in atom_summary(CRIT[1].logic, VS)  # type: ignore[arg-type]


def test_only_condition_atoms_take_a_status_and_the_library_keeps_it() -> None:
    with pytest.raises(ValidationError):
        CriterionIR.model_validate({"id": "T-EXC-01", "ruleset": "T", "kind": "exclusion", "class": "structured",
                                    "text": "t", "logic": {"domain": "condition", "valueset": "V", "clinical_status": ["cured"]}})  # fmt: skip
    from tb_contracts.criterion_ir import Atom

    with pytest.raises(ValidationError):
        Atom(id="a1", domain="medication", valueset="V", clinical_status=["active"])
    v1 = CRIT[0]
    assert downgrade_to_v1(upgrade_v1(v1))["logic"]["clinical_status"] == ACTIVE  # v1 <-> v3, nothing lost


def test_no_shipped_ruleset_says_a_status() -> None:
    """Shipped rulesets keep their approved IR: none sets the field, so their SQL and CQL are unchanged."""
    for path in sorted((ROOT / "rulesets").glob("*/ir/*.json")):
        assert "clinical_status" not in path.read_text(encoding="utf-8"), path

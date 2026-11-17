"""D-989 step 2b: ``ai.used`` where a model's answer becomes part of a record, ``ai.confirmed`` where a person decides
on one; the events the provenance index (step 2c) is built from.

* a record names a patient only by pseudonym: free text, a space or a part the registry does not know is refused;
* a record no model answered writes nothing (its ``prov: []`` says so), and a call is named once;
* a person's decision is confirmed, changed, rejected or withdrawn (a confirmation taken back), nothing else;
* the compiler writes ``ai.used`` for each criterion a model extracted, and ``ai.confirmed`` for each decision of
  the review sheet on one (approve: confirmed, edit: changed, reject: rejected); a person's own line writes neither;
* a screening run writes ``ai.used`` for each verdict a model answered, by the patient's pseudonym;
* every database role that hosts a model call may send the ``ai`` family through the journal.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tb_common import provenance
from tb_common.audit import AuditLog
from tb_common.audit_writer import foreign

from tests.unit.test_compiler_service import _approve, _compile, _decisions, env  # noqa: F401 (the fixture)

PID = "0ca5381cfa6bdf1c22961d65579f93b3"


def _events(directory: Path, name: str) -> list[dict[str, Any]]:
    out = [json.loads(x) for p in sorted(directory.glob("*.jsonl")) for x in p.read_text("utf-8").splitlines() if x]
    return [{**e, **e.get("detail", {})} for e in out if e.get("event") == name]  # the fields are in ``detail``


@pytest.mark.parametrize("bad", ["Taro Yamada", "12345678 ", "pid/../x", "", "x" * 97])
def test_a_record_is_named_by_ids_never_free_text(bad: str) -> None:
    with pytest.raises(ValueError):
        provenance.ref(pid=bad)


def test_a_record_names_only_the_parts_the_registry_knows() -> None:
    assert provenance.ref(ruleset="GZQO", version="1.0.0", pid=PID, crit="INC-01") == {
        "ruleset": "GZQO", "version": "1.0.0", "pid": PID, "crit": "INC-01"}  # fmt: skip
    with pytest.raises(ValueError, match="mrn"):
        provenance.ref(mrn="SYNTHETIC-X")


def test_no_model_writes_nothing_and_a_call_is_named_once(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    rec = provenance.ref(ruleset="GZQO", version="1.0.0", crit="INC-01")
    assert not provenance.used(log, "criterion", rec, [])
    assert not provenance.used(None, "criterion", rec, ["c1"])
    assert provenance.used(log, "criterion", rec, ["c1", "c2", "c1", ""])
    (e,) = _events(tmp_path, provenance.USED)
    assert (e["record_kind"], e["record_ref"], e["calls"]) == ("criterion", rec, ["c1", "c2"])


def test_a_decision_is_confirmed_changed_or_rejected(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    rec = provenance.ref(draft="D1", field="AE_TERM")
    with pytest.raises(ValueError):
        provenance.confirmed(log, "edc_field", rec, ["c1"], "crc1@hospa.test", "approved")
    with pytest.raises(ValueError):
        provenance.used(log, "note", rec, ["c1"])
    assert provenance.confirmed(log, "edc_field", rec, ["c1"], "crc1@hospa.test", "changed")
    (e,) = _events(tmp_path, provenance.CONFIRMED)
    assert (e["by"], e["decision"], e["calls"]) == ("crc1@hospa.test", "changed", ["c1"])
    assert provenance.confirmed(log, "edc_field", rec, ["c1"], "crc1@hospa.test", "withdrawn")  # D-1152: an Undo
    assert [e["decision"] for e in _events(tmp_path, provenance.CONFIRMED)] == ["changed", "withdrawn"]


def test_a_screening_run_records_each_verdict_a_model_answered(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    v = SimpleNamespace
    rows = [
        v(pid=PID, criteria=[v(id="N-INC-01", prov=["c1", "c2"]), v(id="S-INC-01", prov=[]), v(id="X", prov=None)]),
        v(pid="1afe78d42518132b113c5858cedcbb54", criteria=[v(id="S-INC-01", prov=[])]),
    ]
    assert provenance.verdicts_used(log, "GZQO", "1.0.0", "01JOB", rows) == 1
    (e,) = _events(tmp_path, provenance.USED)
    assert e["record_ref"] == {"ruleset": "GZQO", "version": "1.0.0", "job": "01JOB", "pid": PID, "crit": "N-INC-01"}


@pytest.mark.parametrize("role", ["tb_orchestrator", "tb_console", "tb_criteria_compiler"])
def test_each_role_that_hosts_a_model_call_may_send_the_ai_family(role: str) -> None:
    assert foreign(role, provenance.USED) == "" and foreign(role, provenance.CONFIRMED) == ""


def test_the_compiler_records_each_extracted_criterion_and_each_decision_on_one(
    env: dict[str, Any],  # noqa: F811 (the fixture)
) -> None:
    res = _compile(env)
    audit_dir = env["tmp"] / "audit"
    used = {e["record_ref"]["crit"]: e for e in _events(audit_dir, provenance.USED)}
    extracted = {c.id for c in res.criteria if c.provenance is not None and c.provenance.calls}
    assert extracted and set(used) == extracted  # a person's own line (no calls) writes nothing
    some = sorted(extracted)[0]
    assert used[some]["record_ref"] == {"ruleset": "GZQO", "version": "1.0.0", "crit": some}
    assert used[some]["calls"] == next(c.provenance.calls for c in res.criteria if c.id == some and c.provenance)
    _approve(env, _decisions(env["store"], res.review_xlsx_key, {some: ("reject", "not this one")}))
    got = {e["record_ref"]["crit"]: e["decision"] for e in _events(audit_dir, provenance.CONFIRMED)}
    assert got[some] == "rejected" and set(got) == extracted
    assert all(d == "confirmed" for k, d in got.items() if k != some)

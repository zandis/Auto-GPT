"""E-PROV-1 (D-1047, D-989): an EDC draft names the model call its value came from.

D-989 (the owner's ruling D-1037): a record that holds a model-derived answer carries ``prov``, a list of call ids, by
reference. For the pre-fill, each draft field from a model takes ``prov: [result.call_id]``; a field read from the
record (patient, observation, condition, medication) carries an explicit empty list, which says "no model".
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from edc.store import draft_sha

from tests import edc_kit as k


class CallLlm:
    """The stub's answer, with the call id the gateway gives every answer (D-989 step 1)."""

    def __init__(self, call_id: str, data: dict[str, Any] | None = None) -> None:
        self.call_id, self.data, self.stub = call_id, data, k.StubLlm()

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: Any = None, **kw: Any) -> Any:
        data = self.data if self.data is not None else self.stub.chat_json(prompt_id, variables, schema, **kw).data
        return SimpleNamespace(data=data, prompt_version="1", call_id=self.call_id)


def _draft(svc: Any) -> dict[str, dict[str, Any]]:
    return {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}


def test_a_note_drafted_value_names_its_call_and_a_mapped_value_names_none(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path, llm=CallLlm("call-7f3a"))
    k.ready(svc)
    d = _draft(svc)
    assert d["tophus"]["state"] == "drafted" and d["tophus"]["prov"] == ["call-7f3a"]
    for item in ("brthdat", "sex", "weight", "urate", "mh_gout", "cm_allo", "comments"):
        assert d[item]["prov"] == [], item  # read from the record, or not mapped: no model, said explicitly


def test_a_model_answer_that_was_refused_still_names_its_call(tmp_path: Path) -> None:
    liar = CallLlm("call-0b11", {"found": True, "value": "1", "note": "n1", "date": "2026-10-20",
                                 "quote": "Large tophus seen"})  # fmt: skip
    svc, _, _ = k.service(tmp_path, llm=liar)
    k.ready(svc)
    t = _draft(svc)["tophus"]
    assert (t["state"], t["why"], t["prov"]) == ("unknown", "quote_not_found", ["call-0b11"])


def test_an_answer_without_a_call_id_names_none_and_none_is_made_up(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)  # the kit's stub gives no call id
    k.ready(svc)
    assert _draft(svc)["tophus"]["prov"] == []


def test_no_model_names_no_call(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path)
    svc.drafter = lambda _job: None  # the box has no model
    k.ready(svc)
    t = _draft(svc)["tophus"]
    assert (t["why"], t["prov"]) == ("no_model", [])


def test_the_signature_does_not_cover_the_pointer(tmp_path: Path) -> None:
    svc, _, _ = k.service(tmp_path, llm=CallLlm("call-7f3a"))
    k.ready(svc)
    t = _draft(svc)["tophus"]
    row = {**t, "final": t["value"], "final_citation": t["citation"]}
    assert draft_sha(row) == draft_sha({**row, "prov": ["another-call"]})

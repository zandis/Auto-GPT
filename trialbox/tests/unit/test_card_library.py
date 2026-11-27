"""The library record writer: protocol line -> card + params -> instantiate -> approved library record -> compile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.cards import CardError, instantiate, load, to_library
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.library.repository import CriterionLibrary, LibraryError
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from tb_contracts.criterion_ir import CriterionIRv3, upgrade_v1

from tools.check_cards import lake

LOINC = "http://loinc.org"
VS: dict[str, Any] = {
    "VS_ALT": {"url": "urn:tb:vs:VS_ALT", "compose": {"include": [{"system": LOINC, "concept": [{"code": "1742-6"}]}]}}
}
CARD: dict[str, Any] = {
    "card_id": "lab.liver.alt_uln",
    "version": "1.0.0",
    "sources": ["tpl_3f2a"],
    "params": {
        "multiple": {"type": "number", "min": 1, "max": 10, "default": 3, "observed_p10_p90": [2.5, 5]},
        "days": {"type": "integer", "min": 1, "max": 3650, "observed_p10_p90": [28, 180]},
    },
    "ir_template": {
        "id": "CARD-EXC-01",
        "ruleset": "CARD",
        "kind": "exclusion",
        "class": "structured",
        "text": {"source": "ALT > {{multiple}} x ULN within {{days}} days"},
        "logic": "a1",
        "atoms": [
            {
                "id": "a1",
                "domain": "observation",
                "valueset": "VS_ALT",
                "quantifier": "latest",
                "value": {"op": ">", "ref": {"kind": "uln", "multiple": "{{multiple}}"}},
                "window": {"from_days": "-{{days}}", "to_days": 0, "anchor": "index"},
            }
        ],
    },
}
LINE = "Exclusion 7: ALT above 3 times the upper limit of normal within the last 90 days."
# what the proposal step returns for LINE (the local model is not part of this test): a card, its version, params
PROPOSAL: dict[str, Any] = {"card_id": "lab.liver.alt_uln", "version": "1.0.0", "params": {"multiple": 3, "days": 90}}


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    for doc in (CARD, {**CARD, "version": "1.1.0"}):
        p = tmp_path / doc["card_id"] / f"{doc['version']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def _instance(cards: Path, version: str = "1.0.0", ruleset: str = "SYN", **params: Any) -> CriterionIRv3:
    card = load(PROPOSAL["card_id"], version, cards)
    return instantiate(card, {**PROPOSAL["params"], **params}, criterion_id=f"{ruleset}-EXC-07", ruleset=ruleset)


def test_protocol_line_to_card_to_record_to_compiled_ruleset(cards: Path) -> None:
    ir = _instance(cards)
    lib = CriterionLibrary()
    rec = to_library(lib, ir, gate="G1-0412", approval="ap_01", valuesets=VS, text_source="protocol v2, " + LINE)
    assert (
        rec.status == "approved" and rec.approved and (rec.approved.gate, rec.approved.approval) == ("G1-0412", "ap_01")
    )
    assert rec.canonical_hash == lib.hash_of(ir, VS) and rec.ir.canonical_hash == rec.canonical_hash
    assert rec.ir.card_ref == ir.card_ref and rec.used_by == ["SYN"] and rec.valuesets[0].id == "VS_ALT"
    assert lib.by_hash(rec.canonical_hash) == rec and lib.records("approved") == [rec]  # persisted
    # the ruleset compiles from the stored record, in both languages
    sql = SqlGenerator("SYN", "1.0.0", ValueSets("SYN", VS, Terminology()), None).render([rec.ir])
    cql = CqlGenerator("SYN", "1.0.0", ValueSets("SYN", VS, Terminology()), 36).render([rec.ir])
    assert '"C_SYN-EXC-07"' in sql and "SYN-EXC-07" in cql
    con = lake([{"table": "observation", "oid": "o1", "code": "1742-6", "system": LOINC, "effective": "2026-10-01",
                 "value_num": 150, "unit": "U/L", "ref_high": 40}])  # fmt: skip
    row = con.execute(sql, [["2026-10-05"], None]).fetchone()
    con.close()
    assert row is not None and row[2] is True  # 150 > 3 x 40
    lib.close()


def test_the_writer_refuses_what_is_not_an_approved_card_instance(cards: Path) -> None:
    lib = CriterionLibrary()
    plain = upgrade_v1(json.loads((Path(__file__).resolve().parents[2] / "rulesets/RA-COH/ir/RA-COH-INC-01.json")
                                  .read_text("utf-8")))  # fmt: skip
    with pytest.raises(CardError, match="is not a card instance"):
        to_library(lib, plain, gate="G1-0412", approval="ap_01")
    for gate, approval in (("", "ap_01"), ("G1-0412", " ")):
        with pytest.raises(CardError, match="names its gate and its approval"):
            to_library(lib, _instance(cards), gate=gate, approval=approval)
    with pytest.raises(LibraryError, match="unknown library record cl_01JB7AAAAAAAAAAAAAAAAAAAAA"):
        to_library(lib, _instance(cards), gate="G1-0412", approval="ap_01", supersedes="cl_01JB7AAAAAAAAAAAAAAAAAAAAA")
    assert lib.count() == 0  # a refused write leaves nothing behind
    lib.close()


def test_the_same_atoms_from_another_ruleset_reuse_the_approved_record(cards: Path) -> None:
    lib = CriterionLibrary()
    first = to_library(lib, _instance(cards), gate="G1-0412", approval="ap_01", valuesets=VS)
    again = to_library(lib, _instance(cards, ruleset="OTHER"), gate="G2-0001", approval="ap_09", valuesets=VS)
    assert again.lib_id == first.lib_id and again.used_by == ["SYN", "OTHER"] and lib.count() == 1
    assert again.approved == first.approved  # an approved record keeps its own approval
    lib.deprecate(first.lib_id)
    with pytest.raises(LibraryError, match="is deprecated and cannot be approved again"):
        to_library(lib, _instance(cards), gate="G1-0413", approval="ap_02", valuesets=VS)
    lib.close()


def test_a_draft_with_the_same_hash_is_approved_in_one_write(cards: Path) -> None:
    lib = CriterionLibrary()
    draft, created = lib.add(_instance(cards), seed_source="site", valuesets=VS)
    assert created and draft.status == "draft"
    rec = to_library(lib, _instance(cards), gate="G1-0412", approval="ap_01", valuesets=VS)
    assert rec.lib_id == draft.lib_id and rec.status == "approved" and lib.get(draft.lib_id) == rec
    lib.close()


def test_a_card_reversion_never_alters_the_approved_record_and_supersedes_names_it(cards: Path) -> None:
    lib = CriterionLibrary()
    old = to_library(lib, _instance(cards), gate="G1-0412", approval="ap_01", valuesets=VS)
    same_atoms = to_library(lib, _instance(cards, version="1.1.0"), gate="G1-0500", approval="ap_05", valuesets=VS)
    assert (
        same_atoms.lib_id == old.lib_id and same_atoms.ir.card_ref == old.ir.card_ref
    )  # the record stands as approved
    moved = to_library(
        lib, _instance(cards, version="1.1.0", multiple=4), gate="G1-0501", approval="ap_06", valuesets=VS,
        supersedes=old.lib_id,
    )  # fmt: skip
    assert moved.lib_id != old.lib_id and moved.supersedes == old.lib_id and moved.status == "approved"
    assert lib.get(old.lib_id) == old  # superseding changes nothing on the old record
    lib.close()

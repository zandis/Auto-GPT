"""NEW-EDC-6 (D-696, deep-review EDC-006): a value whose item an amendment removed can be retired.

After a protocol amendment renamed or dropped a field that was signed (and sent), the study's ODM export was refused
for good (`edc.odm_gap`): the value could not be rejected (it was sent) nor edited (its item left the dictionary).
Now such a value can be retired: by a person, with a reason, re-authenticated when signed; the value and its
signature stay in the trail, and the export leaves it out and lists it in its audit line. Case 13. Synthetic data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc.store import EdcError

from tests import edc_kit as k
from tests.unit.test_edc_t302b import MAP, SCREEN1, _drafts, _enter, _held, _service


def _amended(svc: Any) -> None:
    """The amendment: `urate` leaves the study's map."""
    svc.put_map(k.STUDY, [m for m in MAP if m["item"] != "urate"], k.TARGET, "crc")


def test_a_sent_value_whose_item_left_the_map_is_retired_and_the_export_works_again(tmp_path: Path) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    assert _held(svc.send_redcap(k.STUDY, "crc"), "sent") == {(SCREEN1, "weight"), (SCREEN1, "urate")}
    _amended(svc)
    with pytest.raises(EdcError) as e:
        svc.export_odm(k.STUDY, "crc")
    assert e.value.code == "edc.odm_gap"
    d = _drafts(svc, "S-001", SCREEN1)["urate"]
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "retire", reason="the amendment removed uric acid", by="crc")
    assert e.value.code == "edc.locked"  # signed: the password again
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "retire", by="crc", unlock=True)
    assert e.value.code == "edc.reason"
    out = svc.decide(k.STUDY, d["id"], "retire", reason="the amendment removed uric acid", by="crc", unlock=True)
    assert out["fate"] == "retired" and out["final"] == d["final"]  # the value itself is kept
    seen: list[tuple[str, dict[str, Any]]] = []
    real = svc._audit

    def spy(ev: str, rs: str, by: str, detail: dict[str, Any]) -> None:
        seen.append((ev, detail))
        real(ev, rs, by, detail)

    svc._audit = spy  # type: ignore[method-assign,assignment]
    odm = svc.export_odm(k.STUDY, "crc")
    assert 'ItemOID="IT.weight"' in odm or "weight" in odm
    assert "urate" not in odm.split("<ClinicalData", 1)[-1].split("</ClinicalData>", 1)[0]
    line = next(x for ev, x in seen if ev == "edc.export")
    assert line["retired"] == ["S-001 screening_arm_1 urate"]
    trail = [x for x in svc.trail(k.STUDY, "S-001")["decisions"] if x["item"] == "urate"]
    assert trail[-1]["action"] == "retire" and trail[-1]["reason"] == "the amendment removed uric acid"


def test_a_value_whose_item_is_still_in_the_study_cannot_be_retired(tmp_path: Path) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    d = _drafts(svc, "S-001", SCREEN1)["weight"]
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "retire", reason="x", by="crc", unlock=True)
    assert e.value.code == "edc.not_removed"


def test_an_open_draft_of_a_removed_item_is_already_set_aside_and_not_retired(tmp_path: Path) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    d = _drafts(svc, "S-001", SCREEN1)["urate"]
    _amended(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "retire", reason="removed", by="crc")
    assert e.value.code == "edc.superseded"  # the map change already set the open draft aside: nothing to retire


def test_a_retired_value_is_neither_sent_nor_copied_nor_retired_twice(tmp_path: Path) -> None:
    from edc import copyassist

    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"urate"}))
    _amended(svc)
    d = _drafts(svc, "S-001", SCREEN1)["urate"]
    svc.decide(k.STUDY, d["id"], "retire", reason="removed", by="crc", unlock=True)
    assert svc.store.sendable(k.STUDY) == [] and copyassist._values(svc, k.STUDY, "S-001") == []
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "retire", reason="again", by="crc", unlock=True)
    assert e.value.code == "edc.retired"


def test_the_review_page_offers_retire_for_a_value_whose_item_left() -> None:
    from console.i18n_edc import EN, JA, ZH

    page = (Path(__file__).resolve().parents[2] / "services/console/templates/edc_review.html").read_text("utf-8")
    assert 'value="retire"' in page
    for lang in (EN, JA, ZH):
        assert {"edc.action.retire", "edc.fate.retired"} <= set(lang)


# ------------------------------------------------------------------ the adversarial review
def test_an_item_back_in_the_study_is_drafted_again_and_nothing_is_blocked(tmp_path: Path) -> None:
    """Review finding (high): a second current draft beside the retired one blocked every send and export."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    svc.send_redcap(k.STUDY, "crc")
    _amended(svc)
    d = _drafts(svc, "S-001", SCREEN1)["urate"]
    svc.decide(k.STUDY, d["id"], "retire", reason="removed", by="crc", unlock=True)
    svc.put_map(k.STUDY, MAP, k.TARGET, "crc")  # a later amendment brings it back
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    cur = [x for x in svc.store.drafts(k.STUDY, "S-001", SCREEN1) if x["item"] == "urate"]
    assert [x["fate"] for x in cur] == ["open"]
    svc.store.sendable(k.STUDY)
    svc.export_odm(k.STUDY, "crc")  # no edc.duplicate
    trail = [x["action"] for x in svc.trail(k.STUDY, "S-001")["decisions"] if x["item"] == "urate"]
    assert trail[-1] == "reopened"


def test_a_retired_value_is_not_changed_or_withdrawn(tmp_path: Path) -> None:
    """Review finding: retired is final until the item comes back; no edit, confirm or reject on it."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"urate"}))
    d = _drafts(svc, "S-001", SCREEN1)["urate"]
    _amended(svc)
    svc.decide(k.STUDY, d["id"], "retire", reason="removed", by="crc", unlock=True)
    for action in ("reject", "edit", "confirm", "keep"):
        with pytest.raises(EdcError) as e:
            svc.decide(k.STUDY, d["id"], action, value="9", reason="x", by="crc", unlock=True)
        assert e.value.code == "edc.retired", action


def test_a_value_whose_item_is_still_mapped_is_not_retired_while_the_dictionary_lacks_it(tmp_path: Path) -> None:
    """Review finding: a dictionary gap (a bad re-import, a field mid-rename) is not an amendment; the map says."""
    from edc.service import EdcService

    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"urate"}))
    d = _drafts(svc, "S-001", SCREEN1)["urate"]
    real = svc.dc.fields
    svc.dc.fields = lambda rs: {n: f for n, f in real(rs).items() if n != "urate"}  # type: ignore[method-assign,assignment]
    with pytest.raises(EdcError) as e:
        EdcService.decide(svc, k.STUDY, d["id"], "retire", reason="x", by="crc", unlock=True)
    assert e.value.code == "edc.not_removed"


def test_a_retired_value_is_not_counted_as_waiting_on_the_copy_sheet_and_is_a_known_fate(tmp_path: Path) -> None:
    from edc import copyassist
    from edc.store import FATES

    assert "retired" in FATES
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"urate"}))
    _amended(svc)
    d = _drafts(svc, "S-001", SCREEN1)["urate"]

    def waiting() -> list[int]:
        return [v["waiting"] for r in copyassist.sheet(svc, k.STUDY, "S-001", "crc")["records"] for v in r["visits"]]

    before = waiting()
    svc.decide(k.STUDY, d["id"], "retire", reason="removed", by="crc", unlock=True)
    assert sum(waiting()) <= sum(before)  # the retired value never waits

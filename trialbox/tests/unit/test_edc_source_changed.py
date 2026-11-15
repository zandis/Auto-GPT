"""NEW-EDC-4 (D-694, deep-review EDC-004): new source data after a confirmation is shown and holds the value.

A re-draft skipped every item a person had confirmed or edited. The source could change after (a late lab
correction: 72.5 became 82.5) and the review page still said "confirmed 72.5"; it was signed and sent, with a
signature that says "I compared each value with the source cited". Now each draft run compares the source with the
one the decision was made against; when it differs, the value is marked "source changed since", held from signing
and sending, until a person keeps it (with a reason) or changes it. Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from edc import copyassist
from edc.store import EdcError

from tests import edc_kit as k
from tests.unit.test_edc_attempt_ledger import _correct
from tests.unit.test_edc_t302b import SCREEN1, SHEET, _drafts, _enter, _held, _rows, _service


def _lab_corrected(svc: Any, monkeypatch: pytest.MonkeyPatch, value: float = 82.5) -> None:
    """The lake's weight row is corrected after the person confirmed it."""

    def facts() -> k.FakeFacts:
        f = k.FakeFacts()
        f.data["observation"][0] = {**f.data["observation"][0], "value_num": value}
        return f

    monkeypatch.setattr(svc, "facts", facts)


def _redraft(svc: Any) -> dict[str, dict[str, Any]]:
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    return _drafts(svc, "S-001", SCREEN1)


def _sign(svc: Any) -> None:
    svc.sign(k.STUDY, "S-001", SCREEN1, signer="crc", printed_name="Chen Mei", role="coordinator",
             meaning="transcribed", meaning_text="I checked each value.", lang="en",
             seen=k.seen(svc, "S-001", SCREEN1))  # fmt: skip


def test_a_signed_value_whose_source_changed_is_marked_and_not_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    _lab_corrected(svc, monkeypatch)
    d = _redraft(svc)["weight"]
    assert d["fate"] == "confirmed" and d["final"] == "72.5"  # the decision stands, and is marked
    assert d["source_changed"]["value"] == "82.5" and d["source_changed"]["citation"]["row"] == "o1"
    out = svc.send_redcap(k.STUDY, "crc")
    assert _held(out, "source_changed") == {(SCREEN1, "weight")} and _held(out, "sent") == {(SCREEN1, "urate")}
    assert not _rows(sim, token)[("1", SCREEN1, "", "")].get("weight")
    trail = [x for x in svc.trail(k.STUDY, "S-001")["decisions"] if x["item"] == "weight"]
    assert trail[-1]["action"] == "source_changed" and (trail[-1]["old"], trail[-1]["new"]) == ("72.5", "82.5")


def test_an_unsigned_value_whose_source_changed_cannot_be_signed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    svc.decide(k.STUDY, _drafts(svc, "S-001", SCREEN1)["weight"]["id"], "confirm", by="crc")
    _lab_corrected(svc, monkeypatch)
    _redraft(svc)
    with pytest.raises(EdcError) as e:
        _sign(svc)
    assert e.value.code == "edc.source_changed"


def test_keeping_the_value_needs_a_reason_and_then_it_is_signed_and_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, sim, token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _lab_corrected(svc, monkeypatch)
    d = _redraft(svc)["weight"]
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "keep", by="crc", unlock=True, mark=d["source_changed"]["id"])
    assert e.value.code == "edc.reason"
    with pytest.raises(EdcError) as e:  # signed: the password again, as for any change of a signed value
        svc.decide(
            k.STUDY,
            d["id"],
            "keep",
            reason="the correction was for another visit",
            by="crc",
            mark=d["source_changed"]["id"],
        )
    assert e.value.code == "edc.locked"
    kept = svc.decide(
        k.STUDY,
        d["id"],
        "keep",
        reason="the correction was for another visit",
        by="crc",
        unlock=True,
        mark=d["source_changed"]["id"],
    )
    assert not kept["source_changed"] and kept["final"] == "72.5" and kept["signature_id"] is not None
    assert _held(svc.send_redcap(k.STUDY, "crc"), "sent") == {(SCREEN1, "weight")}
    assert _rows(sim, token)[("1", SCREEN1, "", "")]["weight"] == "72.5"
    assert [x["action"] for x in svc.trail(k.STUDY, "S-001")["decisions"] if x["item"] == "weight"][-1] == "keep"
    assert not _redraft(svc)["weight"]["source_changed"]  # the same source again is not a change


def test_keep_is_only_for_a_value_whose_source_changed(tmp_path: Path) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, _drafts(svc, "S-001", SCREEN1)["weight"]["id"], "keep", reason="x", by="crc", unlock=True)
    assert e.value.code == "edc.not_changed"


def test_changing_the_value_clears_the_mark_and_the_next_change_of_source_marks_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _lab_corrected(svc, monkeypatch)
    _redraft(svc)
    _correct(svc, "S-001", SCREEN1, "weight", "82.5")
    assert not _redraft(svc)["weight"]["source_changed"]
    _lab_corrected(svc, monkeypatch, 92.5)
    assert _redraft(svc)["weight"]["source_changed"]["value"] == "92.5"


def test_the_same_source_on_every_run_marks_nothing_and_writes_no_line(tmp_path: Path) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    assert not _redraft(svc)["weight"]["source_changed"]
    assert all(x["action"] != "source_changed" for x in svc.trail(k.STUDY, "S-001")["decisions"])


def test_a_new_snapshot_of_the_same_row_and_value_is_not_a_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))

    class Tomorrow(k.FakeFacts):
        def snapshot(self) -> str:
            return "snap-2"

    monkeypatch.setattr(svc, "facts", Tomorrow)
    assert not _redraft(svc)["weight"]["source_changed"]


def test_a_marked_value_shows_on_the_review_page_with_a_keep_form() -> None:
    from console.i18n_edc import EN, JA, ZH

    page = (Path(__file__).resolve().parents[2] / "services/console/templates/edc_review.html").read_text("utf-8")
    assert "source_changed" in page and 'value="keep"' in page
    for lang in (EN, JA, ZH):
        assert {"edc.review.source_changed", "edc.action.keep", "edc.result.source_changed",
                "edc.result.keep"} <= set(lang)  # fmt: skip


# ------------------------------------------------------------------ the adversarial review
def test_a_marked_value_is_not_offered_for_copying_and_the_odm_export_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 1: copy-assist is a send by hand; the ODM file a copy a person can import."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight", "urate"}))
    _lab_corrected(svc, monkeypatch)
    _redraft(svc)
    assert {d["item"] for d in copyassist._values(svc, k.STUDY, "S-001")} == {"urate"}
    with pytest.raises(EdcError) as e:
        svc.export_odm(k.STUDY, "crc")
    assert e.value.code == "edc.source_changed" and "weight" in str(e.value)


def test_a_run_that_could_not_read_the_source_marks_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 2: no model (or notes past the window) is not "the source changed"."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {"tophus": "1", "tophus_site": "right ear"}, confirm=frozenset({"weight"}))
    monkeypatch.setattr(svc, "drafter", lambda _run: None)
    d = _redraft(svc)
    assert not any(x["source_changed"] for x in d.values())


def test_keep_answers_only_the_mark_the_person_saw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 3: a run in between marks another change; the keep of the old one is refused."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _lab_corrected(svc, monkeypatch)
    shown = _redraft(svc)["weight"]
    _lab_corrected(svc, monkeypatch, 92.5)
    _redraft(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, shown["id"], "keep", reason="the 82.5 was another visit", by="crc", unlock=True,
                   mark=shown["source_changed"]["id"])  # fmt: skip
    assert e.value.code == "edc.mark_changed"
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, shown["id"], "keep", reason="x", by="crc", unlock=True)
    assert e.value.code == "edc.mark_changed"


def test_confirming_a_site_fact_does_not_mark_the_value_drawn_from_it() -> None:
    """Review finding 4: the citation's kind (record or confirmed) is not the source."""
    from edc.store import source_key

    row = {"table": "condition", "row": "c1", "day": "2024-01-10", "text": "Gout"}
    assert source_key("1", "drafted", {**row, "kind": "record"}) == source_key("1", "drafted", {**row, "kind": "fact"})


def test_keeping_a_signed_value_is_audited_as_unlocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding 6."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _lab_corrected(svc, monkeypatch)
    d = _redraft(svc)["weight"]
    seen: list[dict[str, Any]] = []
    real = svc._audit

    def spy(ev: str, rs: str, by: str, detail: dict[str, Any]) -> None:
        seen.append(detail)
        real(ev, rs, by, detail)

    monkeypatch.setattr(svc, "_audit", spy)
    svc.decide(k.STUDY, d["id"], "keep", reason="another visit", by="crc", unlock=True, mark=d["source_changed"]["id"])
    assert seen[-1]["action"] == "keep" and seen[-1]["unlocked"] is True


def test_a_marked_value_is_not_answered_by_an_edit_that_reuses_the_old_machine_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 7: the change names its own source."""
    svc, _sim, _token, _pid = _service(tmp_path)
    svc.build(k.STUDY, "S-001", k.PID, SCREEN1, k.VISIT_DATE, "crc")
    d = _drafts(svc, "S-001", SCREEN1)["weight"]
    svc.decide(k.STUDY, d["id"], "edit", value="73", reason="scale", citation=SHEET, by="crc")
    _lab_corrected(svc, monkeypatch)
    _redraft(svc)
    with pytest.raises(EdcError) as e:
        svc.decide(k.STUDY, d["id"], "edit", value="72.5", reason="back", by="crc")
    assert e.value.code == "edc.edit_source"


def test_an_opted_out_patients_marked_value_is_listed_as_opted_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 8."""
    svc, _sim, _token, _pid = _service(tmp_path)
    _enter(svc, "S-001", SCREEN1, {}, confirm=frozenset({"weight"}))
    _lab_corrected(svc, monkeypatch)
    _redraft(svc)
    monkeypatch.setattr(svc, "optouts", lambda: frozenset({k.PID}))
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["source_changed"] == [] and _held(out, "opted_out") == {(SCREEN1, "weight")}

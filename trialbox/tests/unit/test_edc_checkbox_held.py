"""EDC-003: a checkbox (``multi``) item is written as REDCap's ``___`` columns, never as one bare column.

Before (deep review of 2026-11-12, case 14): a typed and signed ``joints = 1,3`` was sent as the import row
``{"joints": "1,3"}``. REDCap's flat format is ``joints___1``, ``joints___2``, ``joints___3``: a real REDCap refuses
the whole import, and every other value of the send with it. The first half held the item; the second half
(NEW-EDC-3b, D-842) writes one column per choice: ``1`` for each code chosen, ``0`` for each other code of the field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests import edc_kit as k

JOINTS = {"field_name": "joints", "form_name": "baseline", "field_type": "checkbox", "field_label": "Joints involved",
          "select_choices_or_calculations": "1, Toe | 2, Ankle | 3, Knee"}  # fmt: skip


@pytest.fixture
def kit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(k, "CRF", [*k.CRF, JOINTS])
    monkeypatch.setattr(k, "MAP", [*k.MAP, {"item": "joints"}])


def _signed(svc: Any, typed: str) -> dict[str, dict[str, Any]]:
    d = {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}
    for r in d.values():
        if r["state"] == "drafted":
            svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    svc.decide(k.STUDY, d["joints"]["id"], "edit", value=typed, reason="seen in clinic", by="crc",
               citation={"text": "clinic note", "day": "2026-11-05"})  # fmt: skip
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc))  # fmt: skip
    return d


@pytest.mark.parametrize(("typed", "ticks"), [("1,3", ("1", "0", "1")), ("2", ("0", "1", "0")),
                                              ("3,1,2", ("1", "1", "1"))])  # fmt: skip
def test_a_checkbox_item_is_written_one_column_per_choice(kit: None, tmp_path: Path, typed: str,
                                                          ticks: tuple[str, str, str]) -> None:  # fmt: skip
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    _signed(svc, typed)
    imported: list[list[dict[str, str]]] = []
    client = svc.client

    def spying(ref: str) -> Any:
        c = client(ref)
        real = c.import_records

        def import_records(rows: list[dict[str, str]], *a: Any, **kw: Any) -> Any:
            imported.append([dict(r) for r in rows])
            return real(rows, *a, **kw)

        c.import_records = import_records  # type: ignore[method-assign]
        return c

    svc.client = spying
    out = svc.send_redcap(k.STUDY, "crc")
    assert {b["item"] for b in out["sent"]} >= {"weight", "urate", "sex", "joints"} and out["format"] == []
    assert imported and all("joints" not in row for rows in imported for row in rows)  # never a bare column
    sent = next({c: v for c, v in row.items() if c.startswith("joints___")} for rows in imported for row in rows
                if any(c.startswith("joints___") for c in row))  # fmt: skip
    # 1 for each code chosen; REDCap held no box, so no 0 is written (review F2: never a 0 for a box not held)
    assert sent == {f"joints___{c}": "1" for c, t in zip("123", ticks, strict=True) if t == "1"}
    row = next(r for r in k.client_for(sim, token).records() if "joints___1" in r)
    assert (row["joints___1"], row["joints___2"], row["joints___3"]) == ticks and "joints" not in row
    ledger = [s for s in svc.store.sent_rows(k.STUDY) if s["item"] == "joints"]
    assert ledger[-1]["result"] == "sent" and ledger[-1]["detail"] == "read back equal"
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0  # written once, read back equal: nothing more to send


def test_the_simulator_refuses_a_bare_checkbox_column_as_redcap_does(kit: None, tmp_path: Path) -> None:
    from rc_bridge.client import RcError

    _svc, sim, token = k.service(tmp_path)
    c = k.client_for(sim, token)
    rid = next(iter(c.records()[0])) if c.records() else "record_id"
    with pytest.raises(RcError) as e:
        c.import_records([{rid: "1", "joints": "1,3"}])
    assert e.value.refused and "joints" in e.value.message
    with pytest.raises(RcError):
        c.import_records([{rid: "1", "joints___9": "1"}])  # no such choice


def test_a_persons_tick_is_not_overwritten(kit: None, tmp_path: Path) -> None:
    """A box a person ticked in REDCap before TrialBox wrote anything is theirs: a conflict, never unticked."""
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    c = k.client_for(sim, token)
    first = c.records()[0]
    rid = next(iter(first))
    c.import_records([{rid: first[rid], **({"redcap_event_name": first["redcap_event_name"]} if
                       "redcap_event_name" in first else {}), "joints___2": "1"}])  # fmt: skip
    _signed(svc, "1,3")
    out = svc.send_redcap(k.STUDY, "crc")
    assert [b["item"] for b in out["conflict"]] == ["joints"]
    row = next(r for r in c.records() if r.get("joints___2") == "1")
    assert (row["joints___1"], row["joints___3"]) == ("0", "0")  # nothing of TrialBox's was written into it


def test_branching_logic_reads_the_ticks_the_send_lays_not_the_ones_it_clears() -> None:
    """NEW-EDC-3b: REDCap holds ``sx___2`` ticked; the send lays ``sx`` = ``1`` (2 unticked). A field shown on
    ``[sx(2)] = '1'`` is then hidden on the row REDCap will hold, and ``[sx(1)]`` is ticked."""
    from datetime import date

    from edc.layout import Layout, row_slot
    from edc.rows import Rows

    meta = {"record_id": {"form_name": "f"},
            "sx": {"form_name": "f", "field_type": "checkbox", "select_choices_or_calculations": "1, A | 2, B"},
            "why": {"form_name": "f", "branching_logic": "[sx(2)] = '1'"},
            "one": {"form_name": "f", "branching_logic": "[sx(1)] = '1'"}}  # fmt: skip
    lay = Layout.read({"is_longitudinal": 0}, [], [], [])
    held = {"record_id": "1", "sx___1": "0", "sx___2": "1"}
    rows, at = Rows(lay, meta, "record_id", [held], date(2026, 11, 15)), row_slot(held, False)
    assert rows.shown("1", at, "why") and not rows.shown("1", at, "one")  # what REDCap holds
    rows.lay("1", at, "sx", "1")
    assert not rows.shown("1", at, "why") and rows.shown("1", at, "one")


def test_erase_hidden_values_unticks_every_choice_of_a_checkbox_trialbox_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEW-EDC-3b: a checkbox TrialBox wrote, then hidden by its branching logic, is erased as ``0`` in each column
    REDCap held ticked (never a bare column, never a blank REDCap might read as "leave it"), and read back empty."""
    from tests.unit import test_edc_t302b as t

    sites = {"field_name": "tophus_joints", "form_name": "baseline", "field_type": "checkbox",
             "field_label": "Tophus joints", "select_choices_or_calculations": "1, Toe | 2, Ankle | 3, Knee",
             "branching_logic": "[tophus] = '1'"}  # fmt: skip
    monkeypatch.setattr(t, "MAP", [*t.MAP, {"item": "tophus_joints"}])
    svc, sim, token, pid = t._service(tmp_path, crf=[*t.CRF, sites])
    t._enter(svc, "S-001", t.SCREEN1, {"tophus": "1", "tophus_joints": "1,3"})
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 2
    row = t._rows(sim, token)[("1", t.SCREEN1, "", "")]
    assert (row["tophus_joints___1"], row["tophus_joints___2"], row["tophus_joints___3"]) == ("1", "0", "1")
    t._edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": t.SCREEN1, "tophus": "0"})
    imported: list[dict[str, str]] = []
    client = svc.client

    def spying(ref: str) -> Any:
        c = client(ref)
        real = c.import_records

        def import_records(rows: list[dict[str, str]], *a: Any, **kw: Any) -> Any:
            imported.extend(dict(r) for r in rows)
            return real(rows, *a, **kw)

        c.import_records = import_records  # type: ignore[method-assign]
        return c

    svc.client = spying
    assert svc.erase_hidden(k.STUDY, "S-001", t.SCREEN1, "crc") == {"erased": ["tophus_joints"], "kept": []}
    row = t._rows(sim, token)[("1", t.SCREEN1, "", "")]
    assert (row["tophus_joints___1"], row["tophus_joints___2"], row["tophus_joints___3"]) == ("0", "0", "0")
    assert [r["result"] for r in svc.store.sent_rows(k.STUDY, "S-001")][-1] == "erased"
    sent = [{c: v for c, v in r.items() if c.startswith("tophus_joints")} for r in imported]
    assert sent == [{"tophus_joints___1": "0", "tophus_joints___3": "0"}]  # each box held, and only those (F2)


# ------------------------------------------------------------------ the adversarial review of NEW-EDC-3b
@pytest.mark.parametrize(("code", "col"), [("A", "sx___a"), ("-99", "sx____99"), ("1.5", "sx___1_5")])
def test_a_checkbox_column_is_named_as_redcap_names_it(code: str, col: str) -> None:
    """Review F1: REDCap names a choice's column from the code lowercased, ``-`` and ``.`` written ``_``
    (``Unknown, -99`` is ``sx____99``). A box ticked under that name is read as ticked."""
    from datetime import date

    from datacore import forms
    from edc.layout import Layout, row_slot
    from edc.rows import Rows

    assert forms.checkbox_column("sx", code) == col
    meta = {"record_id": {"form_name": "f"},
            "sx": {"form_name": "f", "field_type": "checkbox",
                   "select_choices_or_calculations": f"1, One | {code}, Other"}}  # fmt: skip
    held = {"record_id": "1", "sx___1": "0", col: "1"}
    rows = Rows(Layout.read({"is_longitudinal": 0}, [], [], []), meta, "record_id", [held], date(2026, 11, 15))
    assert rows.held("1", row_slot(held, False), "sx") == code


def test_the_simulator_takes_and_gives_redcaps_names_for_a_negative_or_letter_code(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    from rc_bridge.client import RcError
    from rc_sim.app import create_app

    sim = create_app()
    meta = [{"field_name": "record_id", "form_name": "f", "field_type": "text"},
            {"field_name": "sx", "form_name": "f", "field_type": "checkbox",
             "select_choices_or_calculations": "1, One | -99, Unknown | A, Other"}]  # fmt: skip
    token = TestClient(sim).post("/sim/projects", json={"metadata": meta}).json()["token"]
    c = k.client_for(sim, token)
    c.import_records([{"record_id": "1", "sx____99": "1", "sx___a": "1"}])
    row = c.records()[0]
    assert (row["sx___1"], row["sx____99"], row["sx___a"]) == ("0", "1", "1")
    with pytest.raises(RcError):
        c.import_records([{"record_id": "1", "sx___-99": "1"}])  # the raw code is not a column of the project


def _racing(monkeypatch: pytest.MonkeyPatch, when: Any, then: Any) -> None:
    from rc_bridge.client import RedcapClient

    real = RedcapClient.import_records
    done: list[bool] = []

    def racing(self: Any, rows: list[dict[str, str]], *a: Any, **kw: Any) -> Any:
        if not done and when(rows, kw):
            done.append(True)
            then(real)
        return real(self, rows, *a, **kw)

    monkeypatch.setattr(RedcapClient, "import_records", racing)


def test_a_box_a_person_ticks_during_the_send_is_kept_and_not_booked_sent(
    kit: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review F2: the send writes ``0`` only for a code REDCap held when it was read. A box a person ticks between
    that read and the import is left as it is, and the read-back differs: never booked ``sent``."""
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    _signed(svc, "1,3")
    c = k.client_for(sim, token)
    first = c.records()[0]
    rid = next(iter(first))
    key = {rid: first[rid], **({"redcap_event_name": first["redcap_event_name"]} if "redcap_event_name" in first
                               else {})}  # fmt: skip
    _racing(
        monkeypatch,
        lambda rows, kw: any("joints___1" in r for r in rows),
        lambda real: real(k.client_for(sim, token), [{**key, "joints___2": "1"}]),
    )
    svc.send_redcap(k.STUDY, "crc")
    row = next(r for r in k.client_for(sim, token).records() if "joints___1" in r)
    assert (row["joints___1"], row["joints___2"], row["joints___3"]) == ("1", "1", "1")
    assert [s["result"] for s in svc.store.sent_rows(k.STUDY) if s["item"] == "joints"][-1] != "sent"


def test_a_box_a_person_ticks_during_an_erase_is_kept_and_not_booked_erased(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit import test_edc_t302b as t

    sites = {"field_name": "tophus_joints", "form_name": "baseline", "field_type": "checkbox",
             "field_label": "Tophus joints", "select_choices_or_calculations": "1, Toe | 2, Ankle | 3, Knee",
             "branching_logic": "[tophus] = '1'"}  # fmt: skip
    monkeypatch.setattr(t, "MAP", [*t.MAP, {"item": "tophus_joints"}])
    svc, sim, token, pid = t._service(tmp_path, crf=[*t.CRF, sites])
    t._enter(svc, "S-001", t.SCREEN1, {"tophus": "1", "tophus_joints": "1"})
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 2
    t._edit_in_redcap(sim, pid, {"record_id": "1", "redcap_event_name": t.SCREEN1, "tophus": "0"})
    _racing(monkeypatch, lambda rows, kw: bool(kw.get("erase")),
            lambda real: real(k.client_for(sim, token), [{"record_id": "1", "redcap_event_name": t.SCREEN1,
                                                          "tophus_joints___3": "1"}]))  # fmt: skip
    res = svc.erase_hidden(k.STUDY, "S-001", t.SCREEN1, "crc")
    row = t._rows(sim, token)[("1", t.SCREEN1, "", "")]
    assert (row["tophus_joints___1"], row["tophus_joints___3"]) == ("0", "1") and res["erased"] == []
    assert [r["result"] for r in svc.store.sent_rows(k.STUDY, "S-001")][-1] != "erased"


def test_the_odm_copy_of_a_checkbox_is_one_item_per_choice_and_redcap_takes_it(kit: None, tmp_path: Path) -> None:
    """Review F3: the signed values' ODM file wrote ``joints`` = ``1,3`` as one item; REDCap refuses it."""
    from fastapi.testclient import TestClient
    from rc_sim.app import create_app

    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    _signed(svc, "1,3")
    text = svc.export_odm(k.STUDY, "crc")
    assert 'ItemOID="joints"' not in text
    assert all(f'ItemOID="joints___{c}" Value="{v}"' in text for c, v in (("1", "1"), ("2", "0"), ("3", "1")))
    sim2 = create_app()
    token2 = k.sim_project(sim2, [{"record_id": "1", "tb_screening_no": k.RECORD}])
    r = TestClient(sim2).post("/api/", data={"token": token2, "content": "record", "format": "odm", "type": "flat",
                                             "data": text, "returnContent": "ids"})  # fmt: skip
    assert r.status_code == 200, r.text

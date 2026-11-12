"""EDC-003, first half: a checkbox (``multi``) item is held at send, never written as one bare column.

Before (deep review of 2026-11-12, case 14): a typed and signed ``joints = 1,3`` was sent as the import row
``{"joints": "1,3"}``. REDCap's flat format is ``joints___1``, ``joints___2``, ``joints___3``: a real REDCap refuses
the whole import, and every other value of the send with it. The simulator took it, so no test saw it. Until the send
writes the ``___`` columns (the card's second half), the item is held with its own words and the rest is sent.
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


@pytest.mark.parametrize("typed", ["1,3", "2", "1,2,3"])
def test_a_checkbox_item_is_held_and_the_other_values_are_sent(kit: None, tmp_path: Path, typed: str) -> None:
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
    assert [b["item"] for b in out["format"]] == ["joints"]
    assert {b["item"] for b in out["sent"]} >= {"weight", "urate", "sex"}  # the rest of the send is not blocked
    assert imported and all("joints" not in row for rows in imported for row in rows)  # never a bare column
    assert all(not col.startswith("joints") for rows in imported for row in rows for col in row)
    rows = k.client_for(sim, token).records()
    assert all(not r.get("joints") for r in rows)
    ledger = [s for s in svc.store.sent_rows(k.STUDY) if s["item"] == "joints"]
    assert [s["result"] for s in ledger] == ["format"] and "checkbox" in ledger[0]["detail"]
    again = svc.send_redcap(k.STUDY, "crc")  # still held, still said, on every send until the columns are written
    assert [b["item"] for b in again["format"]] == ["joints"] and not again["sent"]

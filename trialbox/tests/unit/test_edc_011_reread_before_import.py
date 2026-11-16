"""EDC-011 (D-856): a value a person saves in REDCap while TrialBox's send runs is not overwritten.

Deep review EDC-011 (Medium, case 9b): a person saved ``weight=80`` between TrialBox's read of the record and its
import; the send wrote 72.5 over it and booked ``sent``, and only REDCap's own log showed the person's value.
REDCap's API has no conditional write, so the window cannot be closed, only narrowed: the planned values are read
once more just before the import, and one that changed is held as a conflict, the value seen first kept in its line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rc_bridge.client import RedcapClient

from tests import edc_kit as k


def _signed(tmp_path: Path) -> tuple[Any, Any, str]:
    svc, sim, token = k.service(tmp_path)
    k.ready(svc)
    svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    for d in svc.store.drafts(k.STUDY, k.RECORD):
        if d["state"] == "drafted" and d["fate"] == "open":
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc))  # fmt: skip
    return svc, sim, token


def test_a_value_a_person_saves_during_the_send_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, sim, token = _signed(tmp_path)
    real = RedcapClient.records
    done: list[bool] = []

    def person_saves_after_the_read(self: RedcapClient, fields: list[str] | None = None, events: list[str] | None = None,
                                    since: str | None = None, records: list[str] | None = None,
                                    dags: bool = False) -> list[dict[str, Any]]:  # fmt: skip
        out = real(self, fields=fields, events=events, since=since, records=records, dags=dags)
        if records and fields and "weight" in fields and not done:
            done.append(True)  # the person types in REDCap right after TrialBox read the record
            k.client_for(sim, token).import_records([{"record_id": "1", "weight": "80"}])
        return out

    monkeypatch.setattr(RedcapClient, "records", person_saves_after_the_read)
    out = svc.send_redcap(k.STUDY, "crc")
    assert done
    assert "weight" not in {x["item"] for x in out["sent"]}
    held = [x for x in out["conflict"] if x["item"] == "weight"]
    assert held and held[0]["redcap"] == "80"
    assert k.client_for(sim, token).records()[0]["weight"] == "80"  # the person's value stands
    lines = [r for r in svc.store.sent_rows(k.STUDY, k.RECORD) if r["item"] == "weight"]
    assert lines and lines[-1]["result"] == "conflict" and "while the send ran" in lines[-1]["detail"]


def test_values_nobody_touched_are_still_sent(tmp_path: Path) -> None:
    svc, _sim, _token = _signed(tmp_path)
    out = svc.send_redcap(k.STUDY, "crc")
    assert "weight" in {x["item"] for x in out["sent"]} and not out["conflict"]

"""Review B-03 (D-142): a longitudinal REDCap project read with no event set never blanks TrialBox's values.

REDCap exports one row per record and event; a field lives on one event and comes back blank on every other one. The
source used to hand every row to the sync, so the last (blank) row of another event wrote "" over the enrolment
date on every sync. Now, with no event set, the rows of one record are one row: a blank in another event is never a
value, and two events that disagree are refused (listed), not guessed. The repro is
``scratch-02/repro_sync_blank.py``, run against the real data core twice in a row.
"""

from __future__ import annotations

import csv
import io
from typing import Any, ClassVar

from datacore import forms
from datacore.sources import RedcapSource
from datacore.store import DataCore
from datacore.sync import attach, enter, sync
from fastapi.testclient import TestClient
from rc_bridge.client import RedcapClient
from rc_sim.app import create_app, load_projects

AT1, AT2, AT3 = "2026-11-01T08:00:00+09:00", "2026-11-02T08:00:00+09:00", "2026-11-03T08:00:00+09:00"


class FakeRc:
    """A longitudinal project: the enrolment date lives on event baseline_arm_1; every other event row is blank."""

    rows: ClassVar[list[dict[str, str]]] = []

    def __enter__(self) -> FakeRc:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def metadata(self) -> list[dict[str, str]]:
        return [{"field_name": "record_id"}]

    def records(self, fields: list[str], dags: bool = False) -> list[dict[str, str]]:
        return [dict(r) for r in self.rows]


def _rows(en_date: str, visit2: str = "") -> list[dict[str, str]]:
    base = {"record_id": "1", "redcap_event_name": "baseline_arm_1", "tb_screening_no": "GZQO-0001"}
    return [
        {**base, "en_date": en_date},
        {"record_id": "1", "redcap_event_name": "visit_1_arm_1", "tb_screening_no": "", "en_date": ""},
        {"record_id": "1", "redcap_event_name": "visit_2_arm_1", "tb_screening_no": "", "en_date": visit2},
    ]


def _history(dc: DataCore) -> list[Any]:
    return [h["new"] for h in dc.history("GZQO", "GZQO-0001") if h["field"] == "en_date"]


def test_two_syncs_keep_the_enrolment_date_and_a_change_is_still_taken() -> None:
    dc = DataCore()  # TB_DB_URL: the test's own schemas
    FakeRc.rows = _rows("2026-10-04")
    src = RedcapSource(client=FakeRc, field_map={"en_date": "en_date"})  # no event configured
    attach(dc, "GZQO", src, ["en_date"])  # REDCap owns the enrolment date
    r1 = sync(dc, "GZQO", src, "crc", AT1, push=False)
    r2 = sync(dc, "GZQO", src, "crc", AT2, push=False)
    assert (r1.pulled, r1.taken, r2.taken) == (1, 1, 0)
    assert dc.record("GZQO", "GZQO-0001")["en_date"] == "2026-10-04"
    assert _history(dc) == ["2026-10-04"]  # no flip to "" and back
    # a real change in REDCap is still taken
    FakeRc.rows = _rows("2026-10-05")
    assert sync(dc, "GZQO", src, "crc", AT3, push=False).taken == 1
    assert dc.record("GZQO", "GZQO-0001")["en_date"] == "2026-10-05"


def test_events_that_disagree_are_refused_not_guessed() -> None:
    dc = DataCore()
    FakeRc.rows = _rows("2026-10-04", visit2="2026-12-01")
    src = RedcapSource(client=FakeRc, field_map={"en_date": "en_date"})
    attach(dc, "GZQO", src, ["en_date"])
    res = sync(dc, "GZQO", src, "crc", AT1, push=False)
    assert res.taken == 0 and "en_date" not in dc.record("GZQO", "GZQO-0001")
    assert any("set the REDCap event" in x["reason"] for x in res.refused)


def test_a_configured_event_reads_that_event_only() -> None:
    FakeRc.rows = _rows("2026-10-04", visit2="2026-12-01")
    src = RedcapSource(client=FakeRc, field_map={"en_date": "en_date"}, event="baseline_arm_1")
    got = [r.values for r in src.pull() if r.values]
    assert got == [{"en_date": "2026-10-04"}]


def test_push_to_a_longitudinal_project_with_no_event_lands_on_each_fields_event() -> None:
    """The scenario run's B-03: TrialBox's own fields pushed to a longitudinal project linked with no event. REDCap
    refuses a row with no event, so each field goes to the event its form is designated for; two syncs keep them."""
    proj = next(p for p in load_projects().values() if p["project"]["project_id"] == 202)
    sim = create_app()

    def client() -> RedcapClient:
        rc = RedcapClient("https://rc.example/", proj["token"], http=TestClient(sim, base_url="http://rc"))
        rc.url = "/api/"
        return rc

    dc = DataCore()
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=list(proj["metadata"][0]))
    wr.writeheader()
    wr.writerows(proj["metadata"])
    for q in forms.questionnaires("RA-COH", forms.read_dictionary(buf.getvalue()), record_field="rec_id"):
        dc.put_form("RA-COH", q, "redcap-dictionary", AT1)
    mine = {f"RL{3000 + i}": {"tb_status": "2", "tb_screen_date": f"2026-11-0{i + 1}"} for i in range(3)}
    for no, vals in mine.items():
        enter(dc, "RA-COH", no, "", vals, "crc", AT1)
    fields = ["icf_dt", "rand_yn", "withdrawn", "tb_status", "tb_screen_date"]
    src = RedcapSource(client, field_map={f: f for f in fields}, create=True, dag="cgmh_linkou")
    attach(dc, "RA-COH", src, ["icf_dt", "rand_yn", "withdrawn"])
    for at in (AT2, AT3):
        res = sync(dc, "RA-COH", src, "crc", at)
        assert not res.refused, res.refused
    rows = client().records()
    for no, vals in mine.items():
        got = [r for r in rows if r.get("tb_screening_no") == no]
        assert len(got) == 1 and got[0]["redcap_event_name"] == "screening_arm_1"
        assert {k: got[0][k] for k in vals} == vals
        assert {k: dc.record("RA-COH", no)[k] for k in vals} == vals

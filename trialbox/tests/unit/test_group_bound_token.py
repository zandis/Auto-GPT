"""RC13-D (D-849): a link with a data access group works with a group user's token.

On the private REDCap 13.7 instance (D-521; synthetic projects), a token of a user who is in a data access group
exports only that group's records and **never the group column**, even when asked for it; and any import carrying
the group column is refused whole, even naming the user's own group. A site coordinator's token is such a token.
TrialBox filtered on the group column, so every record counted as outside the group, and its create mode sent the
group column, so every write was refused. The simulator now plays a group user's token (``/sim/token_group``)."""

from __future__ import annotations

from typing import Any

from datacore.sources import RedcapSource
from datacore.store import DataCore
from datacore.sync import attach, enter, sync
from fastapi.testclient import TestClient
from rc_bridge.client import RedcapClient
from rc_bridge.link import ProjectLink, read_back
from rc_bridge.writeback import LinkSource
from rc_sim.app import create_app, load_projects

AT1, AT2 = "2026-11-01T08:00:00+09:00", "2026-11-02T08:00:00+09:00"
PROJ = next(p for p in load_projects().values() if p["project"]["project_id"] == 202)


def _bound_sim() -> tuple[Any, Any]:
    sim = create_app()
    assert TestClient(sim).post("/sim/token_group", json={"project_id": 202, "group": "cgmh_linkou"}).status_code == 200

    def client() -> RedcapClient:
        rc = RedcapClient("https://rc.example/", PROJ["token"], http=TestClient(sim, base_url="http://rc"))
        rc.url = "/api/"
        return rc

    return sim, client


def test_the_simulator_plays_a_group_users_token() -> None:
    _sim, client = _bound_sim()
    rows = client().records(dags=True)
    assert {r["rec_id"] for r in rows} == {"7"} and all("redcap_data_access_group" not in r for r in rows)


def test_read_back_joins_the_rows_of_a_group_users_export() -> None:
    link = ProjectLink("RA-BIO", 202, "proj-b", link_field="tb_screening_no", dag="cgmh_linkou")
    rows = [{"rec_id": "7", "redcap_event_name": "screening_arm_1", "tb_screening_no": "RB0901"}]
    rb = read_back(link, rows, {"RB0901": "P1"}, "rec_id")
    assert rb.outside_dag == 0 and [j.record_id for j in rb.joined] == ["7"]


def test_read_back_still_leaves_out_another_groups_rows_when_the_column_is_there() -> None:
    link = ProjectLink("RA-BIO", 202, "proj-b", link_field="tb_screening_no", dag="cgmh_linkou")
    rows = [{"rec_id": "8", "redcap_event_name": "screening_arm_1", "redcap_data_access_group": "jp_head",
             "tb_screening_no": "RB0902"}]  # fmt: skip
    assert read_back(link, rows, {"RB0902": "P2"}, "rec_id").outside_dag == 1


def test_the_link_source_reads_and_creates_with_a_group_users_token() -> None:
    sim, client = _bound_sim()
    link = ProjectLink("RA-BIO", 202, "proj-b", link_field="tb_screening_no", dag="cgmh_linkou",
                       write_mode="create", write_event="screening_arm_1")  # fmt: skip
    src = LinkSource(client, link, {"RB0901", "RB0950"}, id_field="rec_id")
    pulled = src.pull()
    assert [r.record for r in pulled] == ["RB0901"]
    src.push([type(pulled[0])("RB0950", "", {"tb_status": "2", "tb_screen_date": "2026-11-01"}, "")])
    assert set(src.created) == {"RB0950"}
    admin = [r for r in sim.state.sim.projects[PROJ["token"]]["records"] if r.get("tb_screening_no") == "RB0950"]
    assert admin and admin[0]["redcap_data_access_group"] == "cgmh_linkou"


def test_the_data_core_source_syncs_with_a_group_users_token() -> None:
    _sim, client = _bound_sim()
    import csv
    import io

    from datacore import forms

    dc = DataCore()
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=list(PROJ["metadata"][0]))
    wr.writeheader()
    wr.writerows(PROJ["metadata"])
    for q in forms.questionnaires("RA-COH", forms.read_dictionary(buf.getvalue()), record_field="rec_id"):
        dc.put_form("RA-COH", q, "redcap-dictionary", AT1)
    enter(dc, "RA-COH", "RB0901", "", {"tb_status": "2"}, "crc", AT1)
    enter(dc, "RA-COH", "RL4000", "", {"tb_status": "2", "tb_screen_date": "2026-11-01"}, "crc", AT1)
    fields = ["icf_dt", "rand_yn", "withdrawn", "tb_status", "tb_screen_date"]
    src = RedcapSource(client, field_map={f: f for f in fields}, create=True, dag="cgmh_linkou")
    attach(dc, "RA-COH", src, ["icf_dt", "rand_yn", "withdrawn"])
    res = sync(dc, "RA-COH", src, "crc", AT2)
    assert not res.refused, res.refused
    assert dc.record("RA-COH", "RB0901").get("icf_dt") == "2026-10-02"  # read from REDCap through the group token
    assert any(r.get("tb_screening_no") == "RL4000" for r in client().records())

"""CGRD-B5c (D-845): the simulator locks a form and keeps a log, as a real REDCap does.

A real REDCap refuses, whole, an import that touches a locked form, and its log names the user and the words of each
write ("Create record (import) 1", "Update record (import) (Auto calculation)", "Lock instrument ..."). The
simulator had neither: R3 and R9 of the stand-in run could not pass, and the send's handling of a locked form was
tested only against a REDCap answer written by hand. A form is locked through the simulator's admin route (on a real
REDCap a person or an administrator locks it); a refused import writes nothing and logs nothing. Synthetic only."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from rc_bridge.client import RcError
from rc_sim.app import create_app

from tests import edc_kit as k

META = [
    {"field_name": "record_id", "form_name": "base", "field_type": "text"},
    {"field_name": "w", "form_name": "base", "field_type": "text", "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "h", "form_name": "base", "field_type": "text", "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "dbl", "form_name": "base", "field_type": "calc", "select_choices_or_calculations": "[w]*2"},
    {"field_name": "note", "form_name": "visit", "field_type": "text"},
]  # fmt: skip


def _project() -> tuple[TestClient, Any, int]:
    http = TestClient(create_app())
    p = http.post("/sim/projects", json={"metadata": META, "username": "tb_api"}).json()
    return http, k.client_for(http.app, p["token"]), int(p["project_id"])


def _log(http: TestClient, c: Any) -> list[dict[str, Any]]:
    r = http.post("/api/", data={"token": c.token, "content": "log", "format": "json", "logtype": "record"})
    assert r.status_code == 200
    return list(r.json())


def test_an_import_touching_a_locked_form_is_refused_whole_and_logged_not() -> None:
    http, c, pid = _project()
    c.import_records([{"record_id": "1", "w": "70"}, {"record_id": "2", "w": "60"}])
    before = len(_log(http, c))
    assert http.post("/sim/lock", json={"project_id": pid, "record": "1", "form": "base", "lock": True,
                                        "username": "tb_locker"}).status_code == 200  # fmt: skip
    with pytest.raises(RcError) as e:
        c.import_records([{"record_id": "1", "w": "71"}, {"record_id": "2", "w": "61"}])
    assert e.value.refused and "locked" in e.value.message
    assert {r["record_id"]: r["w"] for r in c.records()} == {"1": "70", "2": "60"}  # nothing of the file written
    assert len(_log(http, c)) == before  # a refused import is not logged
    assert c.import_records([{"record_id": "1", "note": "another form"}]) == ["1"]  # the other form is open
    http.post("/sim/lock", json={"project_id": pid, "record": "1", "form": "base", "lock": False})
    assert c.import_records([{"record_id": "1", "w": "71"}]) == ["1"]


def test_the_log_names_the_user_and_the_words_of_each_write() -> None:
    http, c, pid = _project()
    c.import_records([{"record_id": "1", "w": "70"}])
    c.import_records([{"record_id": "1", "h": "175"}])
    http.post(
        "/sim/lock", json={"project_id": pid, "record": "1", "form": "base", "lock": True, "username": "tb_locker"}
    )
    entries = [e for e in _log(http, c) if e["record"] == "1"]
    actions = [(e["username"], e["action"]) for e in entries]
    assert ("tb_api", "Create record (import) 1") in actions
    assert ("tb_api", "Update record (import) (Auto calculation) 1") in actions  # dbl was computed
    assert ("tb_api", "Update record (import) 1") in actions
    created = next(e for e in entries if e["action"] == "Create record (import) 1")
    assert "w = '70'" in created["details"]
    locks = [e for e in http.post("/api/", data={"token": c.token, "content": "log", "format": "json"}).json()
             if e["action"].startswith("Lock instrument")]  # fmt: skip
    assert locks and locks[0]["username"] == "tb_locker" and "base" in locks[0]["details"]

"""E-EDCB-2 (D-1044): the EDC door's three stores are in the trial database, so they hold across processes.

The owner's brief (D-1060): an OIDC code works once across two app instances on one database and not after it
expires; a held write is confirmed once, by the person who held it; an event id is taken in once, also when two
deliveries of it race, and a re-read that fails leaves the id unrecorded; no storage configured is 503, never a file
in the system's temp folder.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from edc_backend import oidc, tools
from edc_backend import store as door

EVENT = {"id": "evt-1", "type": "record.saved", "project_id": "proj-1", "record_id": "1001", "instrument": "dm"}


def test_a_code_works_once_across_two_app_instances_on_one_database(db_url: str) -> None:
    one, two = door.DoorStore(db_url), door.DoorStore(db_url)
    code = one.issue_code("pi", client_id="edc", redirect_uri="https://edc.example/cb")
    got = two.take_code(code)
    assert got == door.Code("pi", "edc", "https://edc.example/cb")
    assert one.take_code(code) is None and two.take_code(code) is None


def test_an_expired_code_is_refused(db_url: str) -> None:
    now = [1000.0]
    s = door.DoorStore(db_url, clock=lambda: now[0])
    code = s.issue_code("crc")
    now[0] += door.CODE_S + 1
    assert s.take_code(code) is None
    assert s.db.fetchval("SELECT count(*) FROM oidc_code") == 0  # gone, not kept


def test_the_module_functions_keep_their_signatures_and_use_the_database(db_url: str) -> None:
    code = oidc.issue_code("pi")
    assert door.DoorStore(db_url).take_code(code) is not None  # another instance sees it
    code2 = oidc.issue_code("crc")
    assert oidc.take_code(code2) == "crc" and oidc.take_code(code2) is None


def test_a_held_write_is_confirmed_once_by_its_holder_until_it_expires(db_url: str) -> None:
    now = [1000.0]
    one = door.DoorStore(db_url, clock=lambda: now[0])
    two = door.DoorStore(db_url, clock=lambda: now[0])
    pid = one.hold("admin", "open_query", "proj-1", "1001")
    assert pid in two.open_ids()
    assert two.take("someone-else", pid) is None  # another person: not theirs
    assert two.take("admin", pid) == {"actor": "admin", "tool": "open_query", "project_id": "proj-1",
                                      "record_id": "1001"}  # fmt: skip
    assert one.take("admin", pid) is None  # once
    late = one.hold("admin", "apply_draft", "proj-1", "1002")
    now[0] += door.PROPOSAL_S + 1
    assert one.take("admin", late) is None and late not in one.open_ids()


def test_proposals_keep_their_interface_on_the_database(db_url: str) -> None:
    held = tools.Proposals()
    pid = held.hold("admin", "open_query", "proj-1", "1001")
    assert pid in tools.Proposals().ids()  # another instance sees it
    with pytest.raises(tools.ToolError):
        held.take("viewer", pid)
    assert held.take("admin", pid)["tool"] == "open_query"
    with pytest.raises(tools.ToolError):
        held.take("admin", pid)
    with pytest.raises(tools.ToolError):
        held.hold("admin", "find_patient", "proj-1", "1001")  # a read does not wait


def test_the_same_event_id_twice_is_one_reread(db_url: str) -> None:
    s = door.DoorStore(db_url)
    reads: list[str] = []
    assert s.take_event(EVENT, lambda: reads.append("read")) is True
    assert s.take_event(EVENT, lambda: reads.append("read")) is False
    assert reads == ["read"] and [e["id"] for e in s.events()] == ["evt-1"]


def test_two_racing_deliveries_of_one_id_are_one_reread(db_url: str) -> None:
    stores = [door.DoorStore(db_url), door.DoorStore(db_url)]
    reads: list[int] = []
    started = threading.Barrier(2)
    answers: list[bool] = []

    def deliver(i: int) -> None:
        def reread() -> None:
            reads.append(i)
            time.sleep(0.3)  # the other delivery arrives while this one is still reading

        started.wait()
        answers.append(stores[i].take_event(EVENT, reread))

    threads = [threading.Thread(target=deliver, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert len(reads) == 1 and sorted(answers) == [False, True]


def test_a_reread_that_fails_leaves_the_id_unrecorded(db_url: str) -> None:
    s = door.DoorStore(db_url)

    def broken() -> Any:
        raise RuntimeError("the read did not finish")

    with pytest.raises(RuntimeError):
        s.take_event(EVENT, broken)
    assert s.events() == []
    reads: list[str] = []
    assert s.take_event(EVENT, lambda: reads.append("read")) is True  # the EDC's next delivery is taken
    assert reads == ["read"]


def test_no_database_is_no_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_DB_URL", raising=False)
    with pytest.raises(door.NoStorage):
        door.default_store()
    with pytest.raises(door.NoStorage):
        oidc.issue_code("pi")

"""NEW-SEC-1 (D-717): what its adversarial review broke, held by a test each.

1. The morning mail lost the registry's statuses: its registry read was outside ``reading_as``, the orchestrator
   refused it, and ``registry_map`` read the refusal as "no status", so a declined patient came back as new. Now the
   whole round (``notify.collect``) reads as the mail's principal, and a refused read in a round is an error.
4. The console signed a patient read for a study the account does not see, or where the delegation log does not let
   an investigator read; the claim carries no study list, so the orchestrator could not tell. Now the console
   refuses it.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any

import pytest
from console import actor as ca
from console import notify
from console.auth import Session
from console.backend import Refused

from tests.actor3 import signed
from tests.console.test_console_app import CRC_PW
from tests.console.test_orch_box import site  # noqa: F401
from tests.orch_box import STUDY, OrchBox


def test_the_console_signs_no_read_for_a_study_the_account_may_not_read(site: dict[str, Any]) -> None:  # noqa: F811
    h = site["app"].state.helpers
    users = site["users"]
    users.create("smo", "coordinator", CRC_PW, "smo@hospa.test")
    users.set_scope("smo", affiliation="smo", studies="OTHER1")  # an SMO coordinator of another study
    users.create("inv", "investigator", CRC_PW, "inv@hospa.test")  # the GZQO log does not name them
    for name in ("smo", "inv"):
        u = users.get(name)
        tok = ca._READER.set((h, Session(u, "", "en", "x" * 64)))
        try:
            with pytest.raises(Exception) as got:
                ca.read_headers("GET", f"/studies/{STUDY}/records")
        finally:
            ca._READER.reset(tok)
        assert getattr(got.value, "status", None) == 403 or "403" in repr(got.value), (name, got.value)
    crc = users.get("crc")
    tok = ca._READER.set((h, Session(crc, "", "en", "x" * 64)))
    try:
        assert ca.read_headers("GET", f"/studies/{STUDY}/records")  # the study's coordinator still signs
    finally:
        ca._READER.reset(tok)


def test_the_morning_mail_reads_as_its_principal_and_keeps_the_registry_statuses(site: dict[str, Any]) -> None:  # noqa: F811
    ob: OrchBox = site["ob"]
    h = site["app"].state.helpers
    ob.screen()
    pid = ob.listed()[0]
    path = f"/registry/{STUDY}"
    for st in ("contacted", "declined"):
        body = {"pid": pid, "status": st, "reason": "phone"}
        assert (
            ob.client("console")
            .post(path, json=body, headers=signed("request.prepare", STUDY, "POST", path, body))
            .status_code
            == 200
        )
    crc = site["users"].get("crc")
    sess = Session(crc, "", "en", "")

    def row_of(wk: Any) -> list[Any]:
        return [r for r in (wk or {}).get("rows", []) if r["pid"] == pid]

    got: dict[str, Any] = {}

    def timer() -> None:
        with ca.reading_as(ca.NOTIFY):  # as notify.collect does
            got["map"] = h.registry_map(STUDY)
            got["wk"] = row_of(h.week_bundle(sess, STUDY))
        try:
            h.registry_map(STUDY)  # a round's read with nobody: an error, never "no status"
        except Refused as exc:
            got["bare"] = exc

    t = threading.Thread(target=timer)
    t.start()
    t.join()
    assert got["map"].get(pid) == "declined"
    assert got["wk"] == []  # a declined patient is no new candidate in the mail
    assert isinstance(got.get("bare"), Refused)


def test_a_round_reads_as_the_mail_whoever_started_it(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    h = site["app"].state.helpers
    seen: list[Any] = []

    def spy(*_a: Any, **_k: Any) -> list[Any]:
        seen.append(ca._READER.get())
        return []

    monkeypatch.setattr(notify, "_collect", spy)
    admin = site["users"].get("admin")
    tok = ca._READER.set((h, Session(admin, "", "en", "")))  # the administrator's "Send notices now"
    try:
        notify.collect(h, date(2026, 11, 14))
    finally:
        ca._READER.reset(tok)
    assert seen == [(None, ca.NOTIFY)]

# ruff: noqa: F811 - the svc fixture is imported from test_site_setup and taken by name
"""ERASE-A1 (D-866): the site set-up's facts by pseudonym leave the owed list.

* the opt-out worker's ``owed_tables`` clear deletes ``sitesetup.fact`` rows of an opted-out patient;
* the review of D-866: the site set-up never writes one again. A re-read of a sheet (from its file on disk) leaves
  out the opted-out patients' facts, a chart of one is refused before it is read or kept, and a register that does
  not answer stops both (fail closed).

Synthetic chart numbers and pseudonyms only."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.unit.test_site_setup import WS, pid, svc  # noqa: F401 - the fixture is used by name

A, C = "a1b2c3d4e5f6e001" * 2, "c3d4e5f6a1b2e003" * 2  # A opts out; C does not


def _env(db_url: str) -> Any:
    from datacore.optout_worker import WorkerEnv
    from tb_common.optout import OptOutRegister

    return WorkerEnv(register=OptOutRegister(db_url), audit=None, now=datetime(2026, 11, 16, tzinfo=UTC))


def test_the_worker_deletes_a_fact_by_the_pseudonym(db_url: str) -> None:
    from datacore.optout_worker import clear_tables, verify_tables
    from sitesetup.store import SetupStore
    from tb_common.db import Database

    SetupStore(db_url).close()
    with Database.connect(db_url, "sitesetup") as db:
        for p in (A, C):
            db.execute(
                "INSERT INTO fact (ws, input_id, pid, domain, status, at) VALUES ('main', 1, ?, 'dx', 'ok', 'now')",
                (p,),
            )
    env = _env(db_url)
    gone = frozenset({A})
    assert verify_tables(gone, env)["sitesetup.fact"] == 1
    assert clear_tables(gone, env)["sitesetup.fact"] == 1
    assert verify_tables(gone, env)["sitesetup.fact"] == 0
    with Database.connect(db_url, "sitesetup") as db:
        assert [str(r[0]) for r in db.fetchall("SELECT pid FROM fact")] == [C]
    env.register.close()


def _sheet() -> bytes:
    b = io.StringIO()
    csv.writer(b).writerows([["患者番号", "生年月日"], ["10000001", "1961/04/03"], ["10000002", "1970/01/02"]])
    return b.getvalue().encode("utf-8")


def test_a_reread_of_a_sheet_leaves_out_an_opted_out_patient(svc: Any) -> None:
    svc.gone = frozenset
    out = svc.add_sheet(WS, "sheet", "b.csv", _sheet(), {}, "crc")
    assert {f["pid"] for f in svc.store.facts(WS)} == {pid("10000001"), pid("10000002")}
    svc.gone = lambda: frozenset({pid("10000001").upper()})  # opted out since (any case)
    svc.reread(out["input"], "crc")
    assert {f["pid"] for f in svc.store.facts(WS)} == {pid("10000002")}  # the file on disk does not bring it back


def test_a_chart_of_an_opted_out_patient_is_neither_read_nor_kept(svc: Any) -> None:
    from sitesetup.store import SetupError

    svc.gone = lambda: frozenset({pid("10000001")})
    before = len(svc.store.inputs(WS))
    with pytest.raises(SetupError) as e:
        svc.add_chart(WS, "10000001", "chart.txt", "診断: 関節リウマチ".encode(), "crc")
    assert e.value.code == "SETUP-OPTED-OUT"
    assert len(svc.store.inputs(WS)) == before and not svc.store.facts(WS)


def test_a_register_that_does_not_answer_stops_the_write(svc: Any) -> None:
    from sitesetup.store import SetupError

    def down() -> frozenset[str]:
        raise ConnectionError("the trial database did not answer")

    svc.gone = down
    with pytest.raises(SetupError) as e:
        svc.add_chart(WS, "10000001", "chart.txt", "診断: 関節リウマチ".encode(), "crc")
    assert e.value.code == "SETUP-OPTOUT"
    assert not svc.store.facts(WS)


def test_the_registry_lists_the_facts_on_the_clear() -> None:
    from tb_common import erasure

    e = erasure.entries()["sitesetup.fact"]
    assert e.kind == erasure.ERASE and e.clear == "owed_tables" and not e.owed_by
    for k in ("edc.draft", "recall.recall_observation", "recall.recall_known_positive"):  # the review of D-866
        assert erasure.entries()[k].owed_by, k


def test_a_sheet_is_not_kept_when_the_register_does_not_answer(svc: Any) -> None:
    """The re-check of D-866: the register is read before anything of the sheet is stored."""
    from sitesetup.store import SetupError

    def down() -> frozenset[str]:
        raise ConnectionError("the trial database did not answer")

    svc.gone = down
    with pytest.raises(SetupError) as e:
        svc.add_sheet(WS, "sheet", "b.csv", _sheet(), {}, "crc")
    assert e.value.code == "SETUP-OPTOUT" and svc.store.inputs(WS) == []


class _Published(Exception):
    pass


def test_a_publish_leaves_out_a_patient_opted_out_since(svc: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The re-check of D-866: a fact (or a chart's text) kept before the opt-out is never published after it."""
    from sitesetup import publish

    svc.gone = frozenset
    svc.add_sheet(WS, "sheet", "b.csv", _sheet(), {}, "crc")
    seen: dict[str, Any] = {}

    def resources(facts: Any, mapping: Any, texts: Any) -> Any:
        seen.update(facts=list(facts), texts=list(texts))
        raise _Published

    monkeypatch.setattr(publish, "resources", resources)
    svc.gone = lambda: frozenset({pid("10000001")})
    with pytest.raises(_Published):
        svc.publish(WS, "crc", force=True)
    assert {f["pid"] for f in seen["facts"]} == {pid("10000002")}

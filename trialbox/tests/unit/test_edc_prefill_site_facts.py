"""D-684: the EDC prefill reads "this snapshot has no site facts" from the lake's own answer, never from the words
of an error. Until this card any failure whose text named ``site_fact`` gave no site facts, silently: a proposed
fact then no longer held a draft back (``only_proposed``), and a confirmed one no longer labelled its citation.
Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest
from edc.prefill import LakeFacts

PID = "a1b2c3d4e5f60001"
ROOT = Path(__file__).resolve().parents[2]


class Lake:
    """An in-process lake (DuckDB, as the lake runs it); ``fail`` makes every query of ``site_fact`` fail."""

    def __init__(self, ddl: str | None, fail: str | None = None) -> None:
        self.con = duckdb.connect()
        self.fail = fail
        self.asked: list[str] = []
        if ddl:
            self.con.execute(ddl)

    def snapshot(self) -> str:
        return "2026-11-02"

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        self.asked.append(sql)
        if self.fail and " FROM site_fact " in sql:
            raise RuntimeError(self.fail)
        return self.con.execute(sql, params or []).to_arrow_table()


TABLE = "CREATE TABLE site_fact (fid VARCHAR, pid VARCHAR, domain VARCHAR, code VARCHAR, d DATE, basis VARCHAR)"


def test_a_snapshot_built_before_the_site_facts_holds_none() -> None:
    lake = Lake(None)
    assert LakeFacts(lake).site_facts(PID) == []
    assert any("duckdb_tables()" in sql for sql in lake.asked)  # the lake was asked; nothing was read from a text


def test_the_site_facts_are_read() -> None:
    lake = Lake(TABLE)
    lake.con.execute(
        "INSERT INTO site_fact VALUES ('f1', ?, 'condition', 'M10.9', DATE '2026-10-01', 'proposed')", [PID]
    )
    assert [(r["fid"], r["basis"]) for r in LakeFacts(lake).site_facts(PID)] == [("f1", "proposed")]


@pytest.mark.parametrize(
    "text",
    [
        "IO Error: cannot read the file of table site_fact",
        "Catalog Error: Table with name site_fact does not exist!",  # the words of a missing table, and it is there
        "connection reset while reading site_fact",
    ],
)
def test_a_failure_that_names_the_table_is_not_read_as_no_facts(text: str) -> None:
    lake = Lake(TABLE, fail=text)
    with pytest.raises(RuntimeError, match="site_fact"):
        LakeFacts(lake).site_facts(PID)


def test_a_table_that_lacks_a_column_stops_the_draft() -> None:
    """A real failure of the engine whose text names the table: a snapshot with an older shape of it."""
    lake = Lake("CREATE TABLE site_fact (fid VARCHAR, pid VARCHAR)")
    with pytest.raises(duckdb.Error):
        LakeFacts(lake).site_facts(PID)


def test_a_lake_that_cannot_say_whether_the_table_is_there_stops_the_draft() -> None:
    class Down(Lake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            raise ConnectionError("the lake does not answer (site_fact)")

    with pytest.raises(ConnectionError):
        LakeFacts(Down(None)).site_facts(PID)


# ------------------------------------------------------------------------------------------------ the review
def test_a_lake_that_names_no_snapshot_gives_no_reader() -> None:
    """Without a snapshot's name every read of one draft would go to "current", each possibly another night, and
    the citations would name no snapshot: the reader is not built."""
    from edc.prefill import NoSnapshot

    class Unnamed(Lake):
        def snapshot(self) -> Any:
            return None

    with pytest.raises(NoSnapshot):
        LakeFacts(Unnamed(TABLE))


def test_a_record_that_could_not_be_read_is_a_coded_refusal_audited_and_nothing_is_drafted(tmp_path: Any) -> None:
    """The lake failing under a draft was a bare 500 with no audit line. It is the EDC's own refusal ``edc.lake``
    (503), audited with the error's type only, and no draft is stored."""
    import json

    from edc.store import EdcError

    from tests import edc_kit as k

    class Broken(k.FakeFacts):
        def site_facts(self, pid: str) -> list[dict[str, Any]]:
            raise ConnectionError(f"lake down while reading {pid} site_fact")

    svc, _, _ = k.service(tmp_path, facts=Broken())
    k.ready(svc)
    with pytest.raises(EdcError) as e:
        svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    assert e.value.code == "edc.lake" and e.value.status == 503
    assert k.PID not in e.value.message and "site_fact" not in e.value.message
    assert svc.store.drafts(k.STUDY, k.RECORD) == []
    lines = [json.loads(x) for p in sorted((tmp_path / "audit").rglob("*")) if p.is_file()
             for x in p.read_text(encoding="utf-8").splitlines() if x.strip().startswith("{")]  # fmt: skip
    refused = [x["detail"] for x in lines if x.get("event") == "edc.drafts" and x["detail"].get("refused")]
    assert [(d["refused"], d["error"]) for d in refused] == [("edc.lake", "ConnectionError")]
    assert k.PID not in json.dumps(refused)


def test_every_language_has_the_sentence_for_a_record_that_could_not_be_read() -> None:
    from console import i18n_edc

    text = (ROOT / "services/console/i18n_edc.py").read_text(encoding="utf-8")
    assert text.count('"edc.err.edc.lake"') == 3 and i18n_edc is not None


def test_prefill_refuses_identifying_choice_before_storing_any_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edc.store import EdcError
    from tb_common.output_gate import IDENTIFIER_MESSAGE, IDENTIFIER_REFUSAL

    from tests import edc_kit as k

    choice = {"field_type": "radio", "select_choices_or_calculations": "1, Present | AB1234567, Other"}
    monkeypatch.setattr(k, "CRF", [row | choice if row["field_name"] == "tophus" else row for row in k.CRF])
    svc, _, _ = k.service(tmp_path)
    k.ready(svc)
    with pytest.raises(EdcError) as refusal:
        svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    assert (refusal.value.status, refusal.value.code, refusal.value.message) == (
        422,
        IDENTIFIER_REFUSAL,
        IDENTIFIER_MESSAGE["en"],
    )
    assert svc.store.drafts(k.STUDY, k.RECORD) == []

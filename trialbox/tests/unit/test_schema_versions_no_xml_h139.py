"""H-139: the update path reads every store's applied schema version on a PostgreSQL built without libxml.

The full-set run on the bench host met a server without libxml, which refuses every XML function with
"unsupported XML feature". The update path read the versions through ``query_to_xml`` and ``xpath``, so on such a
server ``installed_state`` (the compat check, the free-space preflight) stopped. Here a stand-in for that server
refuses any statement that names an XML function, as the real one does, and lets every other statement through to
the test cluster. Both boxes must still read each store's version: the in-process box (psycopg) and the compose box
(``psql`` in the db container, played here by the test cluster). The rehearsal's row count (tools/rehearse_box/box.sh)
runs only against a real box, so its statement is checked by its text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import psycopg
import pytest
from tb_common.db import Database, split_url

from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
#: what a server built without libxml refuses (PostgreSQL's NO_XML_SUPPORT: the XML type's input and its functions)
XML_SQL = re.compile(r"\b(xpath|xpath_exists|xmlexists|query_to_xml\w*|table_to_xml\w*|cursor_to_xml\w*|xmlparse|"
                     r"xmlelement|xmlforest|xmlagg|xmlconcat|xmlroot|xmlpi|xmlcomment|xmlserialize)\s*\(|::\s*xml\b",
                     re.IGNORECASE)  # fmt: skip
NO_XML = "unsupported XML feature"


def _no_libxml(sql: Any) -> None:
    text = sql if isinstance(sql, str) else sql.as_string(None)
    if XML_SQL.search(text):
        raise psycopg.errors.FeatureNotSupported(NO_XML)


@pytest.fixture
def stores(db_url: str) -> dict[str, int]:
    """Two stores of this test's prefix with their migrations applied: ``release`` at 2, ``other`` at 1."""
    for schema, n in (("release", 2), ("other", 1)):
        with Database.connect(db_url, schema) as db:
            db.migrate([f"CREATE TABLE t{i} (id INT)" for i in range(1, n + 1)])
    return {"release": 2, "other": 1}


def test_the_in_process_box_reads_the_versions_on_a_server_without_libxml(
    tmp_path: Path, db_url: str, stores: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    box = up.InProcessBox(tmp_path / "work", db_url, tmp_path / "backups")
    real = box._pg
    sent: list[str] = []

    def pg(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        sent.append(sql)
        _no_libxml(sql)
        return real(sql, params)

    monkeypatch.setattr(box, "_pg", pg)
    got = box.installed_state()
    assert {k: got.get(k) for k in stores} == stores, got
    assert sent and not any(XML_SQL.search(s) for s in sent)


def test_the_compose_box_reads_the_versions_on_a_server_without_libxml(
    tmp_path: Path, db_url: str, stores: dict[str, int]
) -> None:
    dsn, prefix = split_url(db_url)
    sent: list[str] = []

    def psql(argv: list[str], **_: Any) -> str:
        """``docker compose exec -T db psql -X -At -F | ... -c <sql>``, answered by the test cluster as psql would."""
        assert "psql" in argv and "-At" in argv and "-c" in argv, argv
        sql = argv[argv.index("-c") + 1]
        sent.append(sql)
        try:
            _no_libxml(sql)
        except psycopg.Error as exc:
            raise up.UpdateFailed(f"psql ... exit 1: ERROR:  {exc}") from None
        sep = argv[argv.index("-F") + 1] if "-F" in argv else "|"
        with psycopg.connect(dsn, autocommit=True) as con:
            rows = con.execute(sql).fetchall()
        return "".join(sep.join("" if v is None else str(v) for v in r) + "\n" for r in rows)

    (tmp_path / "deploy").mkdir()
    box = up.ComposeBox(tmp_path / "deploy", run=psql)
    got = box.installed_state()
    assert {k: got.get(prefix + k) for k in stores} == stores, got
    assert sent and not any(XML_SQL.search(s) for s in sent)


def test_a_server_without_libxml_refuses_what_the_stand_in_refuses() -> None:
    """The stand-in's pattern takes the statement the update path sent before H-139 (and the rehearsal's count)."""
    before = ("SELECT table_schema, (xpath('/row/m/text()', query_to_xml(format('SELECT max(version) AS m FROM %I."
              "_schema_version', table_schema), false, true, '')))[1]::text FROM information_schema.tables "
              "WHERE table_name = '_schema_version'")  # fmt: skip
    with pytest.raises(psycopg.errors.FeatureNotSupported, match=NO_XML):
        _no_libxml(before)


def test_the_rehearsals_row_count_names_no_xml_function() -> None:
    text = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    rows = text[text.index("  rows() {") :]
    rows = rows[: rows.index("\n  }\n")]
    code = "\n".join(ln for ln in rows.splitlines() if not ln.lstrip().startswith("#"))
    assert "\\gexec" in code and "count(*)" in code
    assert not XML_SQL.search(code), code

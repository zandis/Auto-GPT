from __future__ import annotations

import pytest
from lake.sqlguard import SqlRejected, check_select
from lake.textproc import chunk, token_string, tokens


def test_tokens_cjk_bigrams_and_latin() -> None:
    assert tokens("痛風發作 DAS28 5.1") == ["痛風", "風發", "發作", "das28", "5.1"]
    assert tokens("風") == ["風"]
    assert token_string("ＡＢＣ") == "abc"  # NFKC full-width


def test_chunk_sizes_and_overlap() -> None:
    text = "".join(chr(0x4E00 + i % 500) for i in range(1234))
    parts = chunk(text, 500, 100)
    assert [len(p) for p in parts] == [500, 500, 434]
    assert parts[0][-100:] == parts[1][:100]
    assert chunk("短", 500, 100) == ["短"] and chunk("   ", 500, 100) == []
    with pytest.raises(ValueError):
        chunk("x", 100, 100)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH a AS (SELECT pid FROM patient) SELECT * FROM a WHERE pid = ?",
        "SELECT pid FROM patient UNION SELECT pid FROM condition",
        "SELECT count(*) FILTER (WHERE sex = 'female') FROM patient",
    ],
)
def test_select_allowed(sql: str) -> None:
    check_select(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM patient",
        "SELECT 1; SELECT 2",
        "COPY patient TO '/tmp/x.csv'",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "ATTACH '/tmp/x.db' AS x",
        "PRAGMA database_list",
        "INSTALL httpfs",
        "CREATE TABLE x AS SELECT 1",
        "SELECT * FROM read_parquet('s3://bucket/x')",
        "SELECT getenv('HOME')",
    ],
)
def test_non_select_rejected(sql: str) -> None:
    with pytest.raises(SqlRejected):
        check_select(sql)


def test_unknown_tables_rejected_but_ctes_allowed() -> None:
    check_select("WITH x AS (SELECT 1 AS a) SELECT a FROM x")
    with pytest.raises(SqlRejected):
        check_select("SELECT * FROM information_schema.tables")
    with pytest.raises(SqlRejected):
        check_select("SELECT * FROM secret_table")

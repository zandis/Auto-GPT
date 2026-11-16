"""Lane D's nightly triage (#639, 2026-11-16, T-653), D-942: the cascade at 5,000 patients took twice its baseline.
The bisect named train 19 (#665): since D-748 the cascade's S1 sends its compiled query once per batch of patients,
and the lake's guard parsed that query (about 500 KB for GZQO) with sqlglot every time.

The guard keeps its verdict for a text it accepted: the same text is accepted without a second parse. A refused text
is parsed and refused every time; a different text, however close, is parsed on its own.

Synthetic queries, no lake.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlglot
from lake import sqlguard
from lake.sqlguard import SqlRejected, check_select


def test_an_accepted_text_is_not_parsed_again(monkeypatch: pytest.MonkeyPatch) -> None:
    sqlguard._accepted.cache_clear()
    parses: list[str] = []
    real = sqlglot.parse

    def counting(sql: str, *a: Any, **k: Any) -> Any:
        parses.append(sql)
        return real(sql, *a, **k)

    monkeypatch.setattr(sqlglot, "parse", counting)
    q = "SELECT pid FROM patient WHERE pid = ANY(?)"
    for _ in range(5):
        check_select(q)
    assert parses == [q]
    check_select(q + " ")  # another text: its own parse
    assert len(parses) == 2


def test_a_refusal_is_never_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    sqlguard._accepted.cache_clear()
    bad = "SELECT * FROM read_csv('/etc/passwd')"
    for _ in range(3):
        with pytest.raises(SqlRejected, match="forbidden function"):
            check_select(bad)
    with pytest.raises(SqlRejected):
        check_select("DROP TABLE patient")
    assert sqlguard._accepted.cache_info().currsize == 0  # nothing refused is held

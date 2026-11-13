"""Security review 2026-11-13: one malformed journal row never stops the audit drain.

Any service role may call ``audit.append(text, text, jsonb)``. Before the fix a row whose fields held ``ts`` or
``event``, a ``detail`` that was not an object, or a time with no zone or no date stopped ``Drain.step`` with a
TypeError or ValueError, on every start; the journal is append-only, so no later event reached the chain. Now the row
is written with its values kept under ``detail`` and marked ``journal.unreadable``, and the rows after it follow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tb_common.audit import verify
from tb_common.audit_writer import Drain

AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


class _Res:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def fetchall(self) -> list[Any]:
        return self.rows

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None


class _Con:
    """The journal queries of :class:`Drain`, over a list of rows."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, q: str, args: tuple[Any, ...] = ()) -> _Res:
        if q.startswith("LISTEN"):
            return _Res([])
        if "WHERE seq >" in q:
            return _Res([r for r in self.rows if r[0] > args[0]][: args[1]])
        if "WHERE seq =" in q:
            return _Res([(r[1],) for r in self.rows if r[0] == args[0]])
        return _Res([(max(r[0] for r in self.rows),)])


BAD = {
    "ts in fields": ({"ts": "x"}, AT.isoformat()),
    "event in fields": ({"event": "x"}, AT.isoformat()),
    "detail not an object": ({"detail": "abc"}, AT.isoformat()),
    "fields not an object": ('["a"]', AT.isoformat()),
    "time without a zone": ({}, AT.replace(tzinfo=None).isoformat()),
    "time that is not a time": ({}, "not-a-time"),
}


@pytest.mark.parametrize("label", sorted(BAD))
def test_a_malformed_row_is_written_marked_and_the_next_rows_follow(tmp_path: Path, label: str) -> None:
    fields, ts = BAD[label]
    rows = [
        (1, AT, "tb_console", "console.login", AT.isoformat(), {"actor": "console:a"}),
        (2, AT, "tb_mail_gateway", "mail.received", ts, fields),
        (3, AT, "tb_console", "console.denied", AT.isoformat(), {"actor": "console:b"}),
    ]
    drain = Drain("postgresql://x@h/db", tmp_path, "Asia/Taipei", connect=lambda: _Con(rows))
    drain.open()
    assert drain.run(once=True, alive=None) == 3
    assert verify(tmp_path).ok
    events = [json.loads(x) for f in sorted(tmp_path.glob("*.jsonl")) for x in f.read_text().splitlines()]
    events = [e for e in events if e.get("journal")]
    assert [e["event"] for e in events] == ["console.login", "mail.received", "console.denied"]
    assert events[1]["journal"]["unreadable"] and "unreadable" in events[1]["journal"]["flag"], events[1]
    assert "unreadable" not in events[0]["journal"] and "unreadable" not in events[2]["journal"]


def test_a_well_formed_row_is_written_as_before(tmp_path: Path) -> None:
    rows = [(1, AT, "tb_console", "console.login", AT.isoformat(), {"actor": "console:a", "detail": {"k": 1}})]
    drain = Drain("postgresql://x@h/db", tmp_path, "Asia/Taipei", connect=lambda: _Con(rows))
    drain.open()
    assert drain.run(once=True, alive=None) == 1
    events = [json.loads(x) for f in sorted(tmp_path.glob("*.jsonl")) for x in f.read_text().splitlines()]
    ev = next(e for e in events if e.get("event") == "console.login")
    assert ev["actor"] == "console:a" and ev["detail"] == {"k": 1} and ev["journal"]["seq"] == 1
    assert "unreadable" not in ev["journal"]


def test_a_planted_sent_time_does_not_hide_the_time_that_was_sent(tmp_path: Path) -> None:
    """The adversarial review: the text of a malformed time is kept in the drain's own record, never under a key of
    ``detail`` that the sender could have set first."""
    rows = [(1, AT, "tb_console", "console.login", "yesterday", {"detail": {"sent_ts": "2026-11-12T09:00:00+00:00"}})]
    drain = Drain("postgresql://x@h/db", tmp_path, "Asia/Taipei", connect=lambda: _Con(rows))
    drain.open()
    assert drain.run(once=True, alive=None) == 1
    events = [json.loads(x) for f in sorted(tmp_path.glob("*.jsonl")) for x in f.read_text().splitlines()]
    ev = next(e for e in events if e.get("event") == "console.login")
    assert ev["journal"]["sent_ts"] == "yesterday" and ev["journal"]["unreadable"] == ["time"]

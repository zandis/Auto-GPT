"""T-697 (F-12 of docs/reviews/2026-11-11-scale-timeouts.md): the audit writer at a million events a day.

Each append read the whole day file to look for a torn last line (``path.read_bytes()``), and the drain's start read
every day file whole for its last journal row: over a day of a million events that is quadratic, and a day file
larger than the writer's memory cap (256 MB) would have had it killed. Only the tail is read now. The drain touched
its heartbeat once a batch; a batch of slow writes then read as a dead writer to the health check."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit as audit_mod
from tb_common.audit import AuditLog, lines_backward

MB = 1 << 20


def _no_whole_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """A day file read whole fails the test."""
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def read_bytes(self: Path) -> bytes:
        assert not self.name.endswith(".jsonl"), f"read whole: {self.name}"
        return real_bytes(self)

    def read_text(self: Path, *a: Any, **kw: Any) -> str:
        assert not self.name.endswith(".jsonl"), f"read whole: {self.name}"
        return real_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)


def _big_day(tmp_path: Path, mb: int) -> tuple[AuditLog, Path]:
    """A chain whose day file carries ``mb`` MB of earlier lines before its last event (only the tail is the
    chain's end: an append reads nothing else)."""
    log = AuditLog(tmp_path / "audit", "UTC")
    log.append("test.first", ts=datetime(2026, 11, 17, 1, tzinfo=UTC), actor="t")
    day = next((tmp_path / "audit").glob("*.jsonl"))
    tail = day.read_bytes()
    filler = (json.dumps({"event": "test.filler", "hash": "0" * 64, "pad": "x" * 900}) + "\n").encode()
    with day.open("wb") as fh:
        for _ in range(mb * MB // len(filler)):
            fh.write(filler)
        fh.write(tail)
    return log, day


def test_an_append_reads_the_tail_of_the_day_file_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    small_log, _ = _big_day(tmp_path / "s", 0)
    big_log, day = _big_day(tmp_path / "b", 100)
    _no_whole_reads(monkeypatch)
    times = {}
    for name, log in (("small", small_log), ("big", big_log)):
        t0 = time.perf_counter()
        for i in range(20):
            log.append("test.next", ts=datetime(2026, 11, 17, 2, i, tzinfo=UTC), actor="t")
        times[name] = time.perf_counter() - t0
    assert day.stat().st_size > 100 * MB
    assert times["big"] < 3 * times["small"] + 0.5, times  # linear over a day: an append costs the same at 100 MB


def test_a_torn_line_at_the_end_of_a_large_day_is_cut_from_the_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log, day = _big_day(tmp_path, 50)
    whole = day.stat().st_size
    with day.open("ab") as fh:
        fh.write(b'{"event": "half a li')
    _no_whole_reads(monkeypatch)
    log.append("test.after", ts=datetime(2026, 11, 17, 3, tzinfo=UTC), actor="t")
    torn = day.with_name(day.name + ".torn-1")
    assert torn.exists() and torn.stat().st_size == len(b'{"event": "half a li')
    events = [json.loads(x)["event"] for x in list(lines_backward(day))[:2]]
    assert events == ["test.after", "audit.repaired"] and day.stat().st_size > whole


def test_a_complete_but_unreadable_last_line_is_cut_too(tmp_path: Path) -> None:
    log, day = _big_day(tmp_path, 1)
    with day.open("ab") as fh:
        fh.write(b"not json\n")
    log.append("test.after", ts=datetime(2026, 11, 17, 3, tzinfo=UTC), actor="t")
    assert day.with_name(day.name + ".torn-1").read_bytes() == b"not json\n"


def test_the_drain_finds_its_last_journal_row_from_the_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.audit_writer import last_drained

    log, day = _big_day(tmp_path, 20)
    log.append("x.y", ts=datetime(2026, 11, 17, 4, tzinfo=UTC), actor="t", journal={"seq": 41, "at": "A"})
    log.append("x.z", ts=datetime(2026, 11, 17, 5, tzinfo=UTC), actor="t")  # no journal row after it
    with day.open("ab") as fh:
        fh.write(b'{"torn')
    _no_whole_reads(monkeypatch)
    got = last_drained(tmp_path / "audit")
    assert got is not None and got.seq == 41 and got.at == "A"


def test_lines_backward_gives_every_line_from_the_end(tmp_path: Path) -> None:
    p = tmp_path / "2026-11-17.jsonl"
    for data in (b"", b"\n", b"a", b"a\n", b"a\nb", b"\nb\n", b"x" * 70000 + b"\n" + b"y" * 3 + b"\n"):
        p.write_bytes(data)
        want = (data[:-1] if data.endswith(b"\n") else data).split(b"\n")[::-1] if data else []
        assert list(lines_backward(p)) == want, data[:8]
    assert audit_mod._TAIL_STEP == 1 << 16


class _Alive:
    def __init__(self) -> None:
        self.n = 0

    def touch(self) -> None:
        self.n += 1


class _Con:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, _q: str, _args: Any = None) -> Any:
        rows, self.rows = self.rows, []
        return type("R", (), {"fetchall": lambda _s: rows})()


def test_the_drain_touches_its_heartbeat_after_each_event(tmp_path: Path) -> None:
    from tb_common.audit_writer import Drain

    at = datetime(2026, 11, 17, 6, tzinfo=UTC)
    rows = [(i, at, "tb_orchestrator", "job.started", at, {"job_id": f"J{i}"}) for i in range(1, 6)]
    drain = Drain("postgresql://" + "aw@db/x", tmp_path / "audit", "UTC", connect=lambda: _Con(rows))
    drain.con = _Con(rows)
    seen: list[int] = []
    alive = _Alive()
    real = drain.chain.append

    def append(*a: Any, **kw: Any) -> Any:
        seen.append(alive.n)  # how many beats before this event was written
        return real(*a, **kw)

    drain.chain.append = append  # type: ignore[method-assign]
    assert drain.step(alive) == 5  # type: ignore[arg-type]
    assert seen == [0, 1, 2, 3, 4] and alive.n == 5

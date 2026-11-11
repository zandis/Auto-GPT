"""T-112b (D-443): the readiness page names the feed tier the box serves (survey question 26: tier 1 or 2 structured,
tier 3 with notes and reports) and the newest night's state from ``dataops``; a night a steward rejected is no longer
a held light; without a trial database the light is read from the audit chain as before."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from datacore.dataops import REJECTED, DataOps
from sitesetup import readiness
from tb_common.audit import AuditLog

AT = "2026-11-11T02:00:00+09:00"


class _Rows:
    def __init__(self, n: int) -> None:
        self.n = n

    def to_pylist(self) -> list[dict[str, Any]]:
        return [{"n": self.n}]


class _Lake:
    def __init__(self, snap: str | None, docs: int = 0, broken: bool = False) -> None:
        self.snap, self.docs, self.broken = snap, docs, broken

    def snapshot(self) -> str | None:
        return self.snap

    def query(self, sql: str, args: list[Any]) -> _Rows:
        if self.broken:
            raise RuntimeError("lake down")
        assert sql == readiness.DOCS_SQL
        return _Rows(self.docs)


class _Svc:
    def __init__(self, lake: _Lake, audit_dir: Path) -> None:
        self._lake = lake

        class _A:
            directory = audit_dir

        self.audit = _A()

    def lake(self, ws: str) -> _Lake:
        return self._lake


def test_the_tier_is_read_from_what_is_loaded(tmp_path: Path) -> None:
    assert readiness.feed_loaded(_Svc(_Lake(None), tmp_path)) is None  # type: ignore[arg-type]
    s = readiness.feed_loaded(_Svc(_Lake("2026-11-10"), tmp_path))  # type: ignore[arg-type]
    assert s == {"snapshot": "2026-11-10", "tier": "structured", "documents": 0}
    n = readiness.feed_loaded(_Svc(_Lake("2026-11-10", docs=12), tmp_path))  # type: ignore[arg-type]
    assert n is not None and n["tier"] == "notes" and n["documents"] == 12
    assert readiness.feed_loaded(_Svc(_Lake("2026-11-10", broken=True), tmp_path)) is None  # type: ignore[arg-type]


def test_the_light_and_the_night_come_from_dataops(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit", "UTC")
    ops = DataOps()
    try:
        assert readiness.newest_batch() is None  # schema there, no night yet
        b, _ = ops.record_night(audit, "ingest.held", source="csv", snapshot="2026-11-10", passed=False, held=True,
                                by="adapter", at=AT, actor="adapter", detail={"incomplete": ["lab: missing"]})  # fmt: skip
        svc = _Svc(_Lake("2026-11-09"), tmp_path / "audit")
        night = readiness.newest_batch()
        assert night is not None and night.id == b.id
        from_ops = readiness.feed_held(svc, night)  # type: ignore[arg-type]
        assert from_ops == readiness.feed_held(svc)  # type: ignore[arg-type]  # the audit chain says the same
        assert from_ops is not None and from_ops["tables"] == "lab" and from_ops["snapshot"] == "2026-11-10"
        loaded = readiness.feed_loaded(svc, night)  # type: ignore[arg-type]
        assert loaded is not None and loaded["snapshot"] == "2026-11-09"  # the box serves the night before
        assert loaded["night"] == {"snapshot": "2026-11-10", "state": "HELD", "attempt": 1}
        ops.decide(audit, b.id, "reject", by="console:stw", at=AT, reason="truncated file")
        night = readiness.newest_batch()
        assert night is not None and night.state == REJECTED
        assert readiness.feed_held(svc, night) is None  # type: ignore[arg-type]  # decided: no longer a held light
    finally:
        ops.close()


def test_without_a_trial_database_the_audit_chain_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TB_DB_URL", raising=False)
    assert readiness.newest_batch() is None
    monkeypatch.setenv("TB_DB_URL", "postgresql://127.0.0.1:1/none")
    assert readiness.newest_batch() is None  # unreachable: the caller reads the audit chain

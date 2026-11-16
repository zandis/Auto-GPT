"""ERASE-D (D-873): a CASE job checks its subject against the opt-out register before the chart is read.

D-862 named the gap: the CASE scenario read and parsed the attached chart (the parser, the model's text) before it
resolved the chart number and refused an opted-out subject. The refusal now comes first, so an opted-out
patient's chart never reaches the parser. Synthetic data only."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


class _Refused(Exception):
    pass


def test_an_opted_out_subjects_chart_is_never_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios import case

    calls: list[str] = []
    rs = SimpleNamespace(
        id="GZQO", version="1", manifest=SimpleNamespace(routing=SimpleNamespace(list_to=["pi@h.test"]))
    )
    monkeypatch.setattr("orchestrator.scheduler.require_released", lambda: None)
    monkeypatch.setattr(case, "require_approved", lambda *_a: rs)
    monkeypatch.setattr(case, "pick_lang", lambda *_a: "en")
    monkeypatch.setattr(case, "is_internal", lambda *_a: True)

    def resolve(_ctx: Any, _mrn: str | None) -> Any:
        calls.append("resolve")
        return case.Subject(pid="p" * 32)

    monkeypatch.setattr(case, "resolve_subject", resolve)

    def refuse(_ctx: Any, pid: str | None) -> None:
        calls.append("refuse")
        raise _Refused

    monkeypatch.setattr(case, "refuse_opted_out", refuse)

    def read(_ctx: Any) -> tuple[list[Any], list[Any]]:
        calls.append("read")
        return [], []

    monkeypatch.setattr(case, "read_charts", read)
    ctx = SimpleNamespace(job=SimpleNamespace(options={"mrn": "10000001"}, ruleset="GZQO", requested_by="crc@h.test",
                                              job_id="J1"),
                          cfg=SimpleNamespace(settings=SimpleNamespace(internal_domains=["h.test"])),
                          update=lambda **_k: None)  # fmt: skip
    with pytest.raises(_Refused):
        case.run(ctx)  # type: ignore[arg-type]
    assert calls == ["resolve", "refuse"]  # the chart was never read

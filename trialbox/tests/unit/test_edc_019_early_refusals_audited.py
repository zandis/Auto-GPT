"""EDC-019 (D-857): every refusal of the EDC service is audited, the early ones too.

Deep review EDC-019 (Medium, E-20): "every refusal is audited" was not true for the early refusals of several entry
points (a missing target, an empty dictionary, a bad visit date, no item map, a REDCap error on the dictionary read,
no REDCap record...). Each case below is refused and must leave one audit line with ``refused`` and its code."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from edc.store import EdcError
from rc_bridge.client import RcError

from tests import edc_kit as k


def _audit(svc: Any) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(svc.audit.directory).glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


class _Down:
    def __enter__(self) -> _Down:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        def fail(*_a: Any, **_k: Any) -> Any:
            raise RcError("RC-UPSTREAM", "REDCap did not answer (ConnectError)")

        return fail


class _Empty(_Down):
    def metadata(self) -> list[dict[str, Any]]:
        return []


def _down(svc: Any) -> Any:
    svc.client = lambda _r: _Down()
    return svc


def _empty(svc: Any) -> Any:
    svc.client = lambda _r: _Empty()
    return svc


CASES: list[tuple[str, Callable[[Any], Any], bool]] = [
    ("dictionary: REDCap does not answer", lambda s: _down(s).import_dictionary(k.STUDY, "edc", "crc", "record_id"),
     False),
    ("dictionary: empty", lambda s: _empty(s).import_dictionary(k.STUDY, "edc", "crc", "record_id"), False),
    ("map: the target lacks a field", lambda s: s.put_map(k.STUDY, k.MAP, {"token_ref": "edc"}, "crc"), False),
    ("build: a visit date that is not a date", lambda s: s.build(k.STUDY, k.RECORD, k.PID, "", "05/11/2026", "crc"), True),
    ("build: a visit date in the future", lambda s: s.build(k.STUDY, k.RECORD, k.PID, "", "2099-01-01", "crc"), True),
    ("build: no map", lambda s: s.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc"), False),
    ("preview: REDCap does not answer", lambda s: _down(s).preview(k.STUDY, k.RECORD, "", "crc"), True),
]  # fmt: skip


@pytest.mark.parametrize(("what", "act", "ready"), CASES, ids=[c[0] for c in CASES])
def test_an_early_refusal_leaves_an_audit_line(tmp_path: Path, what: str, act: Callable[[Any], Any],
                                               ready: bool) -> None:  # fmt: skip
    svc, _sim, _tok = k.service(tmp_path)
    if ready:
        k.ready(svc)
    before = len(_audit(svc))
    with pytest.raises(EdcError) as e:
        act(svc)
    lines = _audit(svc)[before:]
    assert any(str((x.get("detail") or {}).get("refused") or "") == e.value.code for x in lines), (what, lines)

"""Plan 8 criterion 6 (card V-15, finding V15-06): after a withdrawal with "data may not be used", decide, sign, send
and export are each refused and audited.

The withdrawal is recorded the way the console records it: the subject steps to ``withdrawn`` in the data core's
lifecycle, and the withdrawal form's ``wd_data_use`` is written "0" (No) on the same data core the EDC service reads.
Each action is its own test. The EDC service reads ``wd_data_use`` at each gate (V15-06, M7).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from datacore.lifecycle import Lifecycle
from edc.store import EdcError

from tests import edc_kit as k

AT = "2026-11-11T09:00:00"


def _withdraw(svc: Any) -> None:
    life = Lifecycle(svc.dc)
    life.ensure(k.STUDY, k.RECORD, k.PID, "crc", AT)
    for to in ("approached", "consented", "enrolled", "on_study", "withdrawn"):
        life.step(k.STUDY, k.RECORD, to, by="crc", at=AT, reason="3")
    svc.dc.write(k.STUDY, k.RECORD, "withdrawal", "wd_date", "2026-11-11", "crc", AT, "manual")
    svc.dc.write(k.STUDY, k.RECORD, "withdrawal", "wd_data_use", "0", "crc", AT, "manual")
    state = (life.subject(k.STUDY, k.RECORD) or {}).get("state")
    if state != "withdrawn":  # not an AssertionError: a broken set-up must fail the test, never pass as the xfail
        raise RuntimeError(f"the withdrawal was not recorded: state {state!r}")


def _box(tmp_path: Path, *, decided: bool = False, signed: bool = False) -> tuple[Any, dict[str, Any]]:
    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    drafts = {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}
    if decided or signed:  # the real order: decided (and signed) before the withdrawal is recorded
        for r in drafts.values():
            if r["state"] == "drafted":
                svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    if signed:
        _sign(svc)
    _withdraw(svc)
    return svc, drafts


def _sign(svc: Any) -> Any:
    return svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator",
                    meaning="transcribed", meaning_text="I checked each value.", lang="en",
                    seen=k.seen(svc))  # fmt: skip


def _audit(svc: Any) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(svc.audit.directory).glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def _refusals(svc: Any) -> int:
    return sum("refused" in (e.get("detail") or {}) for e in _audit(svc))


def _refused_and_audited(svc: Any, call: Callable[[], Any]) -> None:
    before = _refusals(svc)
    try:
        out = call()
    except EdcError:
        pass
    else:
        raise AssertionError(f"not refused: {str(out)[:200]}")
    assert _refusals(svc) > before, "refused but no refusal in the audit"


def test_decide_is_refused_after_a_withdrawal_without_data_use(tmp_path: Path) -> None:
    svc, drafts = _box(tmp_path)
    first = next(r for r in drafts.values() if r["state"] == "drafted")
    _refused_and_audited(svc, lambda: svc.decide(k.STUDY, first["id"], "confirm", by="crc"))


def test_sign_is_refused_after_a_withdrawal_without_data_use(tmp_path: Path) -> None:
    svc, _ = _box(tmp_path, decided=True)
    _refused_and_audited(svc, lambda: _sign(svc))


def test_send_is_refused_after_a_withdrawal_without_data_use(tmp_path: Path) -> None:
    svc, _ = _box(tmp_path, signed=True)
    sent: list[int] = []

    def send() -> Any:
        out = svc.send_redcap(k.STUDY, "crc")
        sent.append(out["count"])
        return out

    try:
        _refused_and_audited(svc, send)
    except AssertionError:
        assert not sent or sent[0] == 0, f"sent {sent[0]} value(s) of a participant who withdrew the use of their data"
        raise


def test_export_is_refused_after_a_withdrawal_without_data_use(tmp_path: Path) -> None:
    svc, _ = _box(tmp_path, signed=True)
    _refused_and_audited(svc, lambda: svc.export_odm(k.STUDY, "crc"))

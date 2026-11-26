"""M7 (EDC door): the EDC service's whole path against a real REDCap, through its documented API only.

Runs only where a REDCap test instance is given: ``TB_EDC_REAL_URL`` (its address, ending before ``/api/``) and
``TB_EDC_REAL_TOKEN_FILE`` (a file holding the API token of the conformance project that ``tools/redcap_instance.py``
builds: ``tests/edc_kit.py``'s ``CONF_CRF``, arms, events and the repeating ``ae``). The token is read from the file
and never printed. Each run makes one new record (the next free number, a fresh screening number), so runs do not meet.
Proves, per door: the same pre-fill as the simulator; write and read back equal; REDCap's own log line kept with each
value sent; a value someone typed in REDCap in between listed as a conflict and never overwritten; the PRODUCTION
rule (RC-RC1 while the study is not recorded open, one write once it is); no token in any output. Synthetic data only.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from datacore.store import DataCore
from edc.prefill import gateway_drafter
from edc.service import EdcService
from edc.store import EdcError, EdcStore
from rc_bridge.client import RedcapClient
from rc_sim.app import create_app
from tb_common.audit import AuditLog

from tests import edc_kit as k
from tests.unit.test_edc_t302b import MAP, SCREEN1, _project

URL, TOKEN_FILE = os.environ.get("TB_EDC_REAL_URL", ""), os.environ.get("TB_EDC_REAL_TOKEN_FILE", "")
# not marked e2e: it needs a REDCap test instance, not the compose stack that marker asks for
pytestmark = pytest.mark.skipif(
    not (URL and TOKEN_FILE), reason="no REDCap test instance given (TB_EDC_REAL_URL, TB_EDC_REAL_TOKEN_FILE)"
)
CONFIRM = frozenset({"weight", "urate", "brthdat", "sex"})


def _token() -> str:
    return Path(TOKEN_FILE).read_text(encoding="utf-8").strip()


def _real() -> RedcapClient:
    return RedcapClient(URL, _token(), http=httpx.Client(timeout=60), loopback_http=True)


def _service(tmp_path: Path, client: Any, rs: str = k.STUDY, ref: str = "edc") -> EdcService:
    svc = EdcService(EdcStore(sign_key=k.SIGN_KEY), DataCore(), AuditLog(tmp_path / "audit"), lambda: k.STAMP,
                     lambda: k.TODAY, lambda _ref: client(), k.FakeFacts,
                     lambda job: gateway_drafter(k.StubLlm(), job))  # fmt: skip
    svc.import_dictionary(rs, ref, "crc", "record_id")
    svc.put_map(rs, MAP, {**k.TARGET, "token_ref": ref}, "crc")
    svc.set_switch(rs, True, by="pi", role="investigator", **k.ACK)
    return svc


def _new_record(c: RedcapClient) -> str:
    """One new subject on arm 1's screening event, under a screening number no earlier run used."""
    sno = "S-" + uuid.uuid4().hex[:10].upper()
    taken = {str(r["record_id"]) for r in c.records(fields=["record_id"])}
    new = str(max((int(x) for x in taken if x.isdigit()), default=0) + 1)  # a project need not auto-number
    got = c.import_records([{"record_id": new, "redcap_event_name": SCREEN1, "tb_screening_no": sno, "height": "175"}])
    assert got == [new], got
    return sno


def _drafted(svc: EdcService, record: str, rs: str = k.STUDY) -> dict[str, tuple[str, str, str]]:
    rows = svc.build(rs, record, k.PID, SCREEN1, k.VISIT_DATE, "crc")
    return {r["item"]: (str(r["state"]), str(r.get("value") or ""), str(r.get("why") or "")) for r in rows}


def _confirm_and_sign(svc: EdcService, record: str) -> None:
    for d in svc.store.drafts(k.STUDY, record, SCREEN1):
        if d["item"] in CONFIRM and d["state"] == "drafted" and d["fate"] != "superseded":
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    svc.sign(k.STUDY, record, SCREEN1, signer="crc", printed_name="Chen Mei", role="coordinator",
             meaning="transcribed", meaning_text="I checked each value.", lang="en",
             seen=k.seen(svc, record, SCREEN1))  # fmt: skip


def _outputs(tmp_path: Path, svc: EdcService, *outs: Any) -> str:
    audit = "".join(f.read_text(encoding="utf-8") for f in sorted((tmp_path / "audit").glob("*.jsonl")))
    return audit + json.dumps([svc.store.sent_rows(k.STUDY), *outs], default=str)


def test_the_same_prefill_on_the_simulator_and_on_redcap(tmp_path: Path) -> None:
    sim = create_app()
    token, _pid = _project(sim, crf=k.CONF_CRF)
    on_sim = _drafted(
        _service(tmp_path / "sim", lambda: k.client_for(sim, token), "SIMDOOR", "sim"), "S-001", "SIMDOOR"
    )
    real = _real()
    sno = _new_record(real)
    on_real = _drafted(_service(tmp_path / "real", _real), sno)
    assert on_real == on_sim, {i: (on_sim.get(i), on_real.get(i)) for i in set(on_sim) | set(on_real)
                               if on_sim.get(i) != on_real.get(i)}  # fmt: skip


def test_send_read_back_log_line_conflict_and_no_token(tmp_path: Path) -> None:
    real = _real()
    sno = _new_record(real)
    svc = _service(tmp_path, _real)
    _drafted(svc, sno)
    _confirm_and_sign(svc, sno)
    rec = svc._one_record(real, svc.store.target(k.STUDY) or {}, sno)
    # someone types the uric acid in REDCap after TrialBox's value was signed and before it is sent
    real.import_records([{"record_id": rec, "redcap_event_name": SCREEN1, "urate": "9.9"}])
    out = svc.send_redcap(k.STUDY, "crc")
    said = {key: v for key, v in out.items() if v and isinstance(v, list)}
    assert {x["item"] for x in out["sent"]} == CONFIRM - {"urate"} and out["readback"] == [], said
    assert [x["item"] for x in out["conflict"]] == ["urate"]
    row = next(r for r in real.records(records=[rec]) if r["redcap_event_name"] == SCREEN1)
    assert row["urate"] == "9.9"  # never overwritten
    sent = [r for r in svc.store.sent_rows(k.STUDY) if r["result"] == "sent"]
    assert sent and all(r["redcap_log"] for r in sent), [r["redcap_log"] for r in sent]
    assert _token() not in _outputs(tmp_path, svc, out)


@pytest.mark.parametrize("state", [None, True])
def test_the_production_rule_on_redcap(tmp_path: Path, state: bool | None, monkeypatch: pytest.MonkeyPatch) -> None:
    real = _real()
    sno = _new_record(real)
    svc = _service(tmp_path, _real)
    _drafted(svc, sno)
    _confirm_and_sign(svc, sno)
    svc.study_open = lambda _rs: state
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    if state is None:
        with pytest.raises(EdcError) as e:
            svc.send_redcap(k.STUDY, "crc")
        assert e.value.code == "RC-RC1" and "study_open" in e.value.message
        assert svc.store.sent_rows(k.STUDY) == []
    else:
        out = svc.send_redcap(k.STUDY, "crc")
        assert out["count"] == len(CONFIRM), {key: v for key, v in out.items() if v and isinstance(v, list)}
        assert svc.send_redcap(k.STUDY, "crc")["count"] == 0
    assert _token() not in _outputs(tmp_path, svc)

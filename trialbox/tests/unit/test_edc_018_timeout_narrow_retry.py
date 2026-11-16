"""EDC-018 (D-853): the REDCap client's timeout is a setting, a rate-limited call waits once, and the send exports
only the records it touches.

Deep review EDC-018 (Medium): a fixed 10 s timeout, no retry, and a whole-project export of every sent item on each
send; the prefill paths answered ``RC-RATE`` with 409 while the client's register says 503. A large project or a slow
hospital proxy made every send fail. On REDCap 13.7 (D-521) a burst past the rate limit gets the address banned, so
the client waits once and never loops."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from rc_bridge import client as rcc
from rc_bridge.client import RcError, RedcapClient

from tests import edc_kit as k
from tests.rc_kit import TOKEN_A


def test_the_timeout_is_a_setting_with_a_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_REDCAP_TIMEOUT_S", raising=False)
    assert rcc.timeout_s() == 30.0
    monkeypatch.setenv("TB_REDCAP_TIMEOUT_S", "90")
    assert rcc.timeout_s() == 90.0
    monkeypatch.setenv("TB_REDCAP_TIMEOUT_S", "nonsense")
    assert rcc.timeout_s() == 30.0


class _Seq(httpx.BaseTransport):
    def __init__(self, answers: list[tuple[int, dict[str, str], str]]) -> None:
        self.answers = answers
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        status, headers, body = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return httpx.Response(status, headers=headers, text=body)


def _client(seq: _Seq, slept: list[float]) -> RedcapClient:
    c = RedcapClient("https://rc.example/", TOKEN_A, http=httpx.Client(transport=seq))
    c.sleep = slept.append
    return c


def test_a_rate_limited_call_waits_once_as_told_and_is_sent_again() -> None:
    seq = _Seq([(429, {"Retry-After": "7"}, "Too many"), (200, {}, "13.7.23")])
    slept: list[float] = []
    assert _client(seq, slept).version() == "13.7.23"
    assert seq.calls == 2 and slept == [7.0]


def test_a_second_refusal_is_rate_limited_and_there_is_no_third_call() -> None:
    seq = _Seq([(429, {}, "Too many"), (429, {}, "banned")])
    slept: list[float] = []
    with pytest.raises(RcError) as e:
        _client(seq, slept).version()
    assert e.value.code == "RC-RATE" and e.value.status == 503 and seq.calls == 2 and len(slept) == 1


def test_the_wait_is_capped() -> None:
    seq = _Seq([(429, {"Retry-After": "3600"}, ""), (200, {}, "17.0.0")])
    slept: list[float] = []
    _client(seq, slept).version()
    assert slept == [rcc.MAX_WAIT_S]


def test_an_import_answered_503_is_not_sent_again() -> None:
    """A 503 may come after REDCap applied the import: sending it again could write twice (a 429 is refused before)."""
    seq = _Seq([(503, {}, "busy"), (200, {}, "[]")])
    slept: list[float] = []
    with pytest.raises(RcError) as e:
        _client(seq, slept).import_records([{"record_id": "1", "x": "1"}])
    assert e.value.code == "RC-RATE" and seq.calls == 1 and slept == []


def test_the_send_never_exports_the_sent_items_of_every_record(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    others = [{"record_id": str(n), "tb_screening_no": f"S-{n:03d}"} for n in range(2, 40)]
    svc, _sim, _tok = k.service(tmp_path, records=[{"record_id": "1", "tb_screening_no": k.RECORD}, *others])
    k.ready(svc)
    seen: list[tuple[list[str], list[str]]] = []
    real = RedcapClient.records

    def spy(
        self: RedcapClient,
        fields: list[str] | None = None,
        events: list[str] | None = None,
        since: str | None = None,
        records: list[str] | None = None,
        dags: bool = False,
    ) -> list[dict[str, Any]]:
        seen.append((list(fields or []), list(records or [])))
        return real(self, fields=fields, events=events, since=since, records=records, dags=dags)

    svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")
    for d in svc.store.drafts(k.STUDY, k.RECORD):
        if d["state"] == "drafted" and d["fate"] == "open":
            svc.decide(k.STUDY, d["id"], "confirm", by="crc")
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc))  # fmt: skip
    monkeypatch.setattr(RedcapClient, "records", spy)
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["sent"]
    wide = [f for f, recs in seen if not recs and set(f) - {"record_id", "tb_screening_no"}]
    assert seen and wide == []  # a call over every record asks for the id and the key only


def test_a_rate_limit_on_the_dictionary_read_is_answered_503(tmp_path: Any) -> None:
    svc, _sim, _tok = k.service(tmp_path)

    class Limited:
        def __enter__(self) -> Limited:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def metadata(self) -> list[dict[str, Any]]:
            raise RcError("RC-RATE", "REDCap's API rate limit was reached; try again later")

    svc.client = lambda _ref: Limited()  # type: ignore[assignment,return-value]
    from edc.store import EdcError

    with pytest.raises(EdcError) as e:
        svc.import_dictionary(k.STUDY, "edc", "crc", "record_id")
    assert e.value.status == 503

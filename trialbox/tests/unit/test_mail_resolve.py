"""T-108c (D-401, CR-085): the mail outbox. A send key never stays in ``sending``; an MTA outage queues the mail and
the job stays done; ``trialbox mail resolve`` sends the queue when the MTA is back and settles held keys; the limits
per recipient (outbound), per refused sender (replies) and per job type (intake, D-146 J-02)."""

from __future__ import annotations

import datetime as dt
import io
import json
import smtplib
import socket
import ssl
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import pytest
from mail_gateway import admin, intake
from mail_gateway import gateway as gwmod
from mail_gateway.gateway import Gateway
from mail_gateway.outbound import NotSent, smtp_transport
from mail_gateway.store import KeyRow, MailDB
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import SendRequest

from tests.unit.test_mail_unit import _msg, _read

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = load_settings(ROOT / "deploy" / "settings.example.yaml")
Transport = Callable[[str, list[str], bytes], None]


class MTA:
    """A transport that is down (raising ``NotSent`` of ``cause``) until ``up`` is set."""

    def __init__(self) -> None:
        self.cause: BaseException | None = ConnectionRefusedError("connection refused")
        self.sent: list[tuple[list[str], bytes]] = []

    def __call__(self, _frm: str, to: list[str], data: bytes) -> None:
        if self.cause is not None:
            raise NotSent(self.cause)
        self.sent.append((list(to), data))


def _gw(tmp_path: Path, transport: Transport, per_recipient: int = 200) -> Gateway:
    env = load_env(dotenv=tmp_path / "none.env", environ={"MAIL_FROM_ADDR": "trialbox@hospa.test"})
    store = FsStore(tmp_path / "obj")
    store.put("outputs/J/list.xlsx", b"PK candidate list")
    return Gateway(
        Config(env=env, settings=SETTINGS),
        store,
        MailDB(),
        AuditLog(tmp_path / "audit", "Asia/Taipei"),
        transport,
        jobs=lambda req: pytest.fail("no job"),
        secrets_dir=tmp_path,
        authserv_id="mx",
        per_recipient_per_day=per_recipient,
    )


def _req(key: str, to: str = "pi@hospa.test") -> SendRequest:
    return SendRequest.model_validate(
        {
            "job_id": "01JB0000000000000000000000",
            "to": [to],
            "subject": "Done 01JB · FEAS GZQO",
            "body_md": "**Done.**",
            "tag": "aggregate",
            "idempotency_key": key,
        }
    )


def _row(gw: Gateway, key: str) -> KeyRow:
    row = gw.db.get(key)
    assert row is not None, key
    return row


def _events(tmp_path: Path, name: str) -> list[dict[str, Any]]:
    lines = [ln for f in sorted((tmp_path / "audit").glob("*.jsonl")) for ln in f.read_text().splitlines()]
    return [e for e in map(json.loads, lines) if e["event"] == name]


def _states(gw: Gateway) -> set[str]:
    return {str(r[0]) for r in gw.db.db.fetchall("SELECT state FROM send_keys")}


# ----------------------------------------------------------------------------------------------- the outbox
@pytest.mark.parametrize(
    "cause",
    [
        socket.gaierror(-2, "Name or service not known"),
        ConnectionRefusedError("refused"),
        TimeoutError("connect timed out"),
        ssl.SSLError("handshake failed"),
        smtplib.SMTPServerDisconnected("closed before DATA"),
    ],
    ids=["dns", "refused", "timeout", "tls", "disconnect"],
)
def test_an_outage_queues_the_mail_and_resolve_sends_it_when_the_mta_is_back(
    tmp_path: Path, cause: BaseException
) -> None:
    mta = MTA()
    mta.cause = cause
    gw = _gw(tmp_path, mta)
    first = gw.deliver(_req("k-out"))
    assert first.state == "queued" and first.result.sent_to == [] and mta.sent == []
    row = _row(gw, "k-out")
    assert (
        row.state == "queued" and row.attempts == 1 and row.next_at and type(cause).__name__ in (row.last_error or "")
    )
    assert "sending" not in _states(gw)
    deferred = _events(tmp_path, "mail.deferred")
    assert deferred and deferred[0]["detail"]["key"] == "k-out" and deferred[0]["recipients"] == ["pi@hospa.test"]
    assert gw.deliver(_req("k-out")).state == "queued" and mta.sent == []  # a re-run of the step sends nothing
    assert gw.drain() == {}  # not due yet: the back-off holds
    mta.cause = None
    out = io.StringIO()
    assert admin.main("resolve", gw=gw, out=out) == 0
    assert "1 sent" in out.getvalue()
    assert len(mta.sent) == 1 and _row(gw, "k-out").state == "sent"
    # the mail that left carries the Message-ID the caller was given while it waited
    assert f"Message-ID: {first.result.message_id}".encode() in mta.sent[0][1]
    assert gw.db.sent(first.result.message_id) is not None
    assert gw.db.db.fetchval("SELECT request FROM send_keys WHERE key = 'k-out'") is None  # the body is not kept
    assert gw.deliver(_req("k-out")).state == "duplicate" and len(mta.sent) == 1


def test_the_dispatcher_tries_again_with_back_off_then_fails_and_waits_for_a_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gwmod, "MAX_ATTEMPTS", 3)
    mta = MTA()
    gw = _gw(tmp_path, mta)
    gw.deliver(_req("k-b"))
    first_next = _row(gw, "k-b").next_at
    assert gw.drain(force=True) == {"queued": 1}
    assert _row(gw, "k-b").attempts == 2 and (_row(gw, "k-b").next_at or "") > (first_next or "")
    assert gw.drain(force=True) == {"failed": 1}
    assert _row(gw, "k-b").state == "failed" and _events(tmp_path, "mail.failed")
    mta.cause = None
    assert gw.drain(force=True) == {} and mta.sent == []  # failed is never sent again by itself
    out = io.StringIO()
    assert admin.main("status", gw=gw, out=out) == 1  # one waits for a person
    assert "failed" in out.getvalue() and "k-b" in out.getvalue()
    assert admin.main("resolve", "k-b", "resend", by="it-admin", gw=gw, out=io.StringIO()) == 0
    assert len(mta.sent) == 1 and _row(gw, "k-b").state == "sent"
    ev = _events(tmp_path, "mail.resolved")
    assert ev[-1]["actor"] == "it-admin" and ev[-1]["detail"] == {"key": "k-b", "from": "failed", "decision": "resend"}
    assert admin.main("status", gw=gw, out=io.StringIO()) == 0


def test_a_permanent_refusal_fails_at_once() -> None:
    assert gwmod.permanent(smtplib.SMTPRecipientsRefused({"a@x": (550, b"no such user")}))
    assert not gwmod.permanent(smtplib.SMTPRecipientsRefused({"a@x": (451, b"try later")}))
    assert gwmod.permanent(smtplib.SMTPDataError(554, b"rejected"))
    assert not gwmod.permanent(smtplib.SMTPDataError(421, b"busy"))
    assert not gwmod.permanent(ConnectionRefusedError())


def test_a_lost_answer_is_uncertain_and_a_person_decides(tmp_path: Path) -> None:
    calls: list[int] = []

    def lost(_f: str, _to: list[str], _d: bytes) -> None:
        calls.append(1)
        raise TimeoutError("no answer after the final dot")

    gw = _gw(tmp_path, lost)
    assert gw.deliver(_req("k-u")).state == "uncertain"
    assert gw.drain(force=True) == {} and len(calls) == 1  # never resent automatically
    assert _events(tmp_path, "mail.uncertain")[0]["detail"]["key"] == "k-u"
    assert admin.main("resolve", "k-u", "sent", by="it-admin", gw=gw, out=io.StringIO()) == 0
    assert _row(gw, "k-u").state == "sent" and gw.db.db.fetchval("SELECT request FROM send_keys") is None
    gw.deliver(_req("k-v"))
    assert admin.main("resolve", "k-v", "drop", by="it-admin", gw=gw, out=io.StringIO()) == 0
    assert _row(gw, "k-v").state == "dropped" and gw.db.open_keys() == []
    assert gw.db.prune("2999-01-01T00:00:00+00:00")["send_keys"] == 2  # sent and dropped go with the mail log
    err = io.StringIO()
    assert admin.main("resolve", "k-nothing", "sent", gw=gw, out=err) == 1
    assert admin.main("resolve", "k-u", gw=gw, out=err) == 2  # a key needs a decision


def test_a_failure_after_the_message_left_is_uncertain_not_sending(tmp_path: Path) -> None:
    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta)

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("database gone")

    gw.db.record_sent = boom  # type: ignore[method-assign]
    assert gw.deliver(_req("k-after")).state == "uncertain" and len(mta.sent) == 1
    assert "after the message left" in (_row(gw, "k-after").last_error or "")


def test_a_key_left_in_sending_by_a_dead_process_becomes_uncertain(tmp_path: Path) -> None:
    gw = _gw(tmp_path, MTA())
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
    gw.db.claim_send("k-dead", "J", old)  # the claim was written, then the process died
    gw.db.claim_send("k-live", "J", gw._ts())  # in flight right now in another request
    assert gw.drain() == {"stale": 1}
    assert _row(gw, "k-dead").state == "uncertain" and _row(gw, "k-live").state == "sending"
    from mail_gateway.store import SendUncertain

    with pytest.raises(SendUncertain):  # a duplicate of a send in flight is still refused (409), never sent twice
        gw.deliver(_req("k-live"))


def test_resolve_on_an_empty_queue_is_a_no_op(tmp_path: Path) -> None:
    mta = MTA()
    gw = _gw(tmp_path, mta)
    out = io.StringIO()
    assert admin.main("resolve", gw=gw, out=out) == 0
    assert "nothing was queued" in out.getvalue() and mta.sent == [] and _states(gw) == set()
    assert admin.main("resolve", None, "sent", gw=gw, out=out) == 2
    js = io.StringIO()
    assert admin.main("status", as_json=True, gw=gw, out=js) == 0 and json.loads(js.getvalue()) == []


# ----------------------------------------------------------------------------------------------- the transport
class FakeSMTP:
    """smtplib.SMTP with a script: which call fails, and how."""

    fail: ClassVar[dict[str, BaseException]] = {}
    rcpt_code = 250
    final = 250
    sent: ClassVar[list[bytes]] = []

    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        if "connect" in self.fail:
            raise self.fail["connect"]

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def _maybe(self, step: str) -> None:
        if step in self.fail:
            raise self.fail[step]

    def starttls(self) -> None:
        self._maybe("starttls")

    def login(self, _u: str, _p: str) -> None:
        self._maybe("login")

    def ehlo_or_helo_if_needed(self) -> None:
        self._maybe("ehlo")

    def mail(self, _s: str) -> tuple[int, bytes]:
        self._maybe("mail")
        return 250, b"ok"

    def rcpt(self, _r: str) -> tuple[int, bytes]:
        return self.rcpt_code, b"rcpt"

    def docmd(self, _c: str) -> tuple[int, bytes]:
        self._maybe("data")
        return 354, b"go"

    def send(self, data: bytes) -> None:
        self._maybe("body")
        FakeSMTP.sent.append(data)

    def getreply(self) -> tuple[int, bytes]:
        self._maybe("answer")
        return self.final, b"queued"


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeSMTP]]:
    FakeSMTP.fail, FakeSMTP.rcpt_code, FakeSMTP.final, FakeSMTP.sent = {}, 250, 250, []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    yield FakeSMTP


@pytest.mark.parametrize(
    ("step", "exc"),
    [
        ("connect", socket.gaierror(-2, "Name or service not known")),
        ("connect", TimeoutError("timed out")),
        ("starttls", ssl.SSLCertVerificationError("certificate verify failed")),
        ("login", smtplib.SMTPAuthenticationError(535, b"bad")),
        ("mail", smtplib.SMTPServerDisconnected("gone")),
        ("data", TimeoutError("no 354")),
    ],
)
def test_smtp_failures_before_the_body_are_not_sent(fake_smtp: type[FakeSMTP], step: str, exc: BaseException) -> None:
    fake_smtp.fail = {step: exc}
    with pytest.raises(NotSent) as ei:
        smtp_transport("mta.hospa.test", 25, "box", "pw")("trialbox@hospa.test", ["pi@hospa.test"], b"x\r\n")
    assert ei.value.cause is exc and fake_smtp.sent == []


def test_smtp_refusals_are_not_sent_and_a_lost_answer_is_not_classified(fake_smtp: type[FakeSMTP]) -> None:
    send = smtp_transport("mta.hospa.test", 25)
    fake_smtp.rcpt_code = 550
    with pytest.raises(NotSent) as ei:
        send("trialbox@hospa.test", ["pi@hospa.test"], b"x\r\n")
    assert isinstance(ei.value.cause, smtplib.SMTPRecipientsRefused) and gwmod.permanent(ei.value.cause)
    fake_smtp.rcpt_code, fake_smtp.final = 250, 451
    with pytest.raises(NotSent):  # the server answered the body with an error: it did not take it
        send("trialbox@hospa.test", ["pi@hospa.test"], b"x\r\n")
    fake_smtp.final, fake_smtp.fail = 250, {"answer": TimeoutError("answer lost")}
    with pytest.raises(TimeoutError):  # may have arrived: the gateway holds it as uncertain
        send("trialbox@hospa.test", ["pi@hospa.test"], b"x\r\n")
    fake_smtp.fail = {}
    send("trialbox@hospa.test", ["pi@hospa.test"], b"Subject: x\r\n\r\n.dot line\r\n")
    assert fake_smtp.sent[-1].endswith(b"\r\n..dot line\r\n.\r\n")  # dot-stuffed, ended by the final dot


# ----------------------------------------------------------------------------------------------- the limits
def test_a_recipient_over_the_daily_limit_waits_without_using_a_try(tmp_path: Path) -> None:
    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta, per_recipient=2)
    assert [gw.deliver(_req(f"k-{i}")).state for i in range(2)] == ["sent", "sent"]
    held = gw.deliver(_req("k-2"))
    assert held.state == "queued" and len(mta.sent) == 2
    row = _row(gw, "k-2")
    assert row.attempts == 0 and "recipient limit" in (row.last_error or "")
    assert gw.deliver(_req("k-3", to="crc1@hospa.test")).state == "sent"  # another recipient is not held
    gw.per_recipient_per_day = 0  # 0: no limit
    assert gw.drain(force=True) == {"sent": 1} and len(mta.sent) == 4


def test_refusal_replies_to_one_address_stop_after_the_daily_cap(tmp_path: Path) -> None:
    replies: list[list[str]] = []
    gw = _gw(tmp_path, lambda _f, to, _d: replies.append(list(to)))
    for i in range(gwmod.REPLIES_PER_SENDER_PER_DAY + 3):
        assert gw.handle(_msg(f"NOT A COMMAND {i}")) == "Rejected"
    assert len(replies) == gwmod.REPLIES_PER_SENDER_PER_DAY
    assert len(_events(tmp_path, "mail.rejected")) == gwmod.REPLIES_PER_SENDER_PER_DAY + 3  # each still audited


def test_the_intake_limit_counts_each_heavy_type_on_its_own() -> None:
    """D-146 (J-02) for mail: 20 FEAS do not stop a SCREEN, and STATUS is never counted."""
    db = MailDB()
    now = dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.UTC)
    for i in range(20):
        db.record_intake(f"<f{i}@x>", "crc1@hospa.test", now.isoformat(), "job", "J", cmd="FEAS")
    feas = intake.decide(_read(_msg("FEAS GZQO")), SETTINGS, db, now)
    assert feas.action == "reject" and "daily limit of 20 FEAS" in feas.reason
    assert intake.decide(_read(_msg("SCREEN GZQO version=1.0.0")), SETTINGS, db, now).action == "job"
    for i in range(30):
        db.record_intake(f"<s{i}@x>", "crc1@hospa.test", now.isoformat(), "job", "J", cmd="STATUS")
    assert intake.decide(_read(_msg("STATUS 01JB0000000000000000000000")), SETTINGS, db, now).action == "job"


# ----------------------------------------------------------------------------------------------- the job
def test_an_mta_outage_during_a_run_leaves_the_job_done(tmp_path: Path) -> None:
    from tests.inproc_box import make_box

    sec = tmp_path / "sec"
    sec.mkdir()
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))
    assert box.mail("STATUS 01JB0000000000000000000000") == "Processed"  # a first job (it fails: no such job)
    box.orch.drain()
    (first,) = box.orch.db.find()
    mta = MTA()
    good = box.gw.transport
    box.gw.transport = mta  # the MTA goes down
    assert box.mail(f"STATUS {first.job_id}") == "Processed"
    box.orch.drain()
    jobs = [j for j in box.orch.db.find() if j.job_id != first.job_id]
    assert jobs and all(j.state == "done" for j in jobs), [(j.state, j.error) for j in jobs]
    held = box.gw.db.open_keys()
    assert held and {r.state for r in held} == {"queued"}
    box.gw.transport = good
    assert box.gw.drain(force=True) == {"sent": len(held)}
    assert box.gw.db.open_keys() == [] and box.sent

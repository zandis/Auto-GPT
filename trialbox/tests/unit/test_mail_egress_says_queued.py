"""P-11 (E2E, MAIL): the egress record never says ``sent`` for a mail the outbox has not delivered.

The journey: a box installed without a mail relay queues every notice; the outbox tries it again and again until it
fails for a person. Each try passes the egress edge, and each record says the mail went to the outbox (``queued``),
never ``sent``: the delivery is the outbox's own events (``mail.deferred``, ``mail.failed``, ``mail.sent``). Once the
relay answers, the mail is sent and ``mail.sent`` says so. Every address and subject here is made up.
"""

from __future__ import annotations

from pathlib import Path

from mail_gateway import gateway as gwmod
from tb_common import egress_record

from tests.unit.test_mail_resolve import MTA, _events, _gw, _req, _row

SAYS_DELIVERED = {"sent", "masked", "exception"}


def test_a_mail_that_never_left_is_never_recorded_as_sent(tmp_path: Path) -> None:
    mta = MTA()  # no relay: every try is refused before anything leaves
    gw = _gw(tmp_path, mta)
    assert gw.deliver(_req("k-norelay")).state == "queued"
    while _row(gw, "k-norelay").state == "queued":
        gw.drain(force=True)
    assert _row(gw, "k-norelay").state == "failed" and mta.sent == []
    leave = _events(tmp_path, egress_record.EVENT)
    assert len(leave) == gwmod.MAX_ATTEMPTS  # one record per try at the edge
    assert {e["detail"]["route"] for e in leave} == {"mail.staff"}
    assert not {e["detail"]["result"] for e in leave} & SAYS_DELIVERED, leave
    assert {e["detail"]["result"] for e in leave} == {"queued"}
    assert len(_events(tmp_path, "mail.deferred")) == gwmod.MAX_ATTEMPTS - 1
    assert len(_events(tmp_path, "mail.failed")) == 1 and _events(tmp_path, "mail.sent") == []


def test_once_the_relay_answers_the_delivery_is_mail_sent(tmp_path: Path) -> None:
    mta = MTA()
    gw = _gw(tmp_path, mta)
    assert gw.deliver(_req("k-later")).state == "queued"
    mta.cause = None  # the relay is set
    assert gw.drain(force=True) == {"sent": 1} and len(mta.sent) == 1
    assert [e["detail"]["result"] for e in _events(tmp_path, egress_record.EVENT)] == ["queued", "queued"]
    assert len(_events(tmp_path, "mail.sent")) == 1


def test_the_page_names_the_outbox_not_a_departure() -> None:
    from console.i18n_egress import EN, JA, ZH

    for table in (EN, JA, ZH):
        for result in ("queued", "queued_masked", "queued_exception"):
            assert table[f"egress.{result}"] and table[f"egress.{result}"] != table["egress.sent"]

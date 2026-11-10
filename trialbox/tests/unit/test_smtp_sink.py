"""The rehearsal's SMTP sink (D-176) takes mail the way the mail-gateway sends it, and refuses STARTTLS."""

from __future__ import annotations

import smtplib
import threading
from collections.abc import Iterator

import pytest

from tools.rehearse_box.smtp_sink import Sink


@pytest.fixture
def sink() -> Iterator[Sink]:
    srv = Sink(("127.0.0.1", 0))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_takes_a_message(sink: Sink) -> None:
    port = sink.server_address[1]
    with smtplib.SMTP("127.0.0.1", port, timeout=5) as s:
        s.sendmail("tb@hospa.test", ["crc1@hospa.test", "pi@hospa.test"], b"Subject: x\r\n\r\nbody\r\n..dot\r\n")
    assert len(sink.messages) == 1
    m = sink.messages[0]
    assert m["from"] == "<tb@hospa.test>" and m["to"] == ["<crc1@hospa.test>", "<pi@hospa.test>"] and m["bytes"] > 0


def test_refuses_starttls(sink: Sink) -> None:
    with smtplib.SMTP("127.0.0.1", sink.server_address[1], timeout=5) as s, pytest.raises(smtplib.SMTPException):
        s.starttls()
    assert sink.messages == []

"""LOG-JA (D-927): the log scrubber masks what the note masker masks (synthetic, fictional values only).

``tb_common.logging.redact`` had its own short list (a Taiwan ID, My Number, insurance and phone numbers, a postcode,
the chart number): a name, an address or a date of birth in a log line went out as written, in every language the
note masker reads (Japanese since #1091, English Taiwan charts since D-923). The scrubber now ends with the masker's
own spans, so a rule added to the masker reaches the logs too."""

from __future__ import annotations

import json
import logging
import time

import pytest
from tb_common import logging as tblog

# (a log line, what must not be in it after the scrubber)
LEAKS = [
    ("job J1 failed for 患者：山田 太郎 様", ["山田", "太郎"]),
    ("住所: 〒100-0001 東京都千代田区千代田1-1 と記載", ["千代田区千代田1-1"]),
    ("Patient: CHEN, MEI-LING was seen by Dr. Lin Chien-Hung", ["CHEN", "MEI-LING", "Lin Chien-Hung"]),
    ("brought by son 曾冠宇 (Tseng Kuan-Yu)", ["曾冠宇", "Tseng Kuan-Yu"]),
    ("Address: No. 12, Wenhua 1st Rd., Guishan Dist., Taoyuan City 333", ["Wenhua 1st Rd.", "Guishan"]),
    ("主治醫師：王大明查房後評估", ["王大明"]),
    ("DOB: 1957/03/14 on the form", ["1957/03/14"]),
]
# operational lines a service writes: left as they are
KEPT = [
    "lake query ran 2.3 s over 5000 rows",
    "no such snapshot 2026-10-04",
    "ingest finished: 155713 resources, passed",
    "Lung Cancer criterion compiled to 3 concepts",
    "audit chain at 1000 lines, head 3f2a",
]


@pytest.mark.parametrize(("line", "gone"), LEAKS)
def test_what_the_masker_masks_the_logs_mask(line: str, gone: list[str]) -> None:
    out = tblog.redact(line)
    for g in gone:
        assert g not in out, out


@pytest.mark.parametrize("line", KEPT)
def test_an_operational_line_is_left(line: str) -> None:
    assert tblog.redact(line) == line


def test_the_kind_is_said_in_place_of_the_value() -> None:
    assert tblog.redact("Patient: CHEN, MEI-LING") == "Patient: [NAME]"
    assert tblog.redact("Address: No. 12, Zhongshan Rd., Banqiao Dist., New Taipei City") == "Address: [ADDRESS]"


def test_a_scrubber_that_fails_withholds_the_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import phi_guard

    def broken(_text: str) -> list[tuple[str, int, int]]:
        raise RuntimeError("a rule failed")

    monkeypatch.setattr(phi_guard, "note_spans", broken)
    assert tblog.redact("Patient: CHEN, MEI-LING") == tblog.WITHHELD  # never the line unscrubbed


def test_the_json_line_and_its_traceback_are_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    log = tblog.setup_logging("test-scrubber")
    try:
        raise ValueError("no chart for 患者：山田 太郎 様")
    except ValueError:
        log.exception("recompute failed for Patient: CHEN, MEI-LING", extra={"who": "son 曾冠宇"})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert "CHEN" not in rec["msg"] and "曾冠宇" not in rec["who"] and "山田" not in rec["exc"]
    logging.getLogger().handlers.clear()


def test_a_long_line_is_scrubbed_in_linear_time() -> None:
    line = ("lake row 12345 ok; " * 20000) + "Patient: CHEN, MEI-LING"
    start = time.monotonic()
    out = tblog.redact(line)
    assert time.monotonic() - start < 2.0 and "MEI-LING" not in out

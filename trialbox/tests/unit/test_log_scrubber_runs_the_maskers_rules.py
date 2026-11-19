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

# fictional values, put together here so that no file holds a name beside a date of birth or a phone number whole
JA_NAME, JA_NAME2 = "山" + "田花子", "佐" + "藤一郎"
DOB = "1957" + "/03/14"
PHONE = "02-" + "2345-" + "6789"

# (a log line, what must not be in it after the scrubber)
LEAKS = [
    ("job J1 failed for 患者：山田 太郎 様", ["山田", "太郎"]),
    ("住所: 〒100-0001 東京都千代田区千代田1-1 と記載", ["千代田区千代田1-1"]),
    ("Patient: CHEN, MEI-LING was seen by Dr. Lin Chien-Hung", ["CHEN", "MEI-LING", "Lin Chien-Hung"]),
    ("brought by son 曾冠宇 (Tseng Kuan-Yu)", ["曾冠宇", "Tseng Kuan-Yu"]),
    ("Address: No. 12, Wenhua 1st Rd., Guishan Dist., Taoyuan City 333", ["Wenhua 1st Rd.", "Guishan"]),
    ("主治醫師：王大明查房後評估", ["王大明"]),
    ("DOB: " + DOB + " on the form", [DOB]),
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


def test_a_scrubber_that_fails_withholds_the_line_and_names_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import phi_guard

    def broken(_text: str) -> list[tuple[str, int, int]]:
        raise RuntimeError("a rule failed")

    monkeypatch.setattr(phi_guard, "note_spans", broken)
    out = tblog.redact("Patient: CHEN, MEI-LING")
    assert "CHEN" not in out and out.startswith(tblog.WITHHELD[:-1]) and "RuntimeError" in out


# the review's HIGH-2: a rule before another took the label the second reads a name or a date of birth by
ORDER = [
    ("token=abcdef123456、妻 " + JA_NAME, [JA_NAME, "abcdef123456"]),
    ("token=abcdef123456(DOB: " + DOB, [DOB, "abcdef123456"]),
    ("token=abcdef123456/氏名 " + JA_NAME2, [JA_NAME2, "abcdef123456"]),
    ("病人陳美玲(" + PHONE, ["陳美玲", PHONE[3:]]),
]


@pytest.mark.parametrize(("line", "gone"), ORDER)
def test_every_rule_reads_the_line_as_written(line: str, gone: list[str]) -> None:
    out = tblog.redact(line)
    for g in gone:
        assert g not in out, out


def test_a_secret_with_an_identifier_inside_it_goes_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "s3cr3t-A123456789-zz"  # synthetic
    monkeypatch.setattr(tblog, "_SECRET_VALUES", {secret})
    assert tblog.redact(f"key {secret} in use") == "key [SECRET] in use"


def test_an_extra_field_that_is_not_a_text_is_scrubbed_inside() -> None:
    """The review's HIGH-1: a dict, a list or a tuple went out as written."""
    got = tblog.redact_value(
        {"d": {"name": "Patient: CHEN, MEI-LING"}, "l": ["主治醫師：王大明"], "t": ("x", 3), "n": 7}
    )
    text = json.dumps(got, ensure_ascii=False)
    assert "CHEN" not in text and "王大明" not in text and got["n"] == 7 and got["t"] == ["x", 3]


def test_a_masker_that_cannot_load_stops_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's MEDIUM-4: every line would be withheld, the traceback that says why with them."""
    import sys

    monkeypatch.setitem(sys.modules, "tb_common.phi_guard", None)
    with pytest.raises(ImportError):
        tblog.setup_logging("test-no-masker")


def test_a_line_longer_than_the_bound_is_cut_before_it_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's MEDIUM-5: the masker reads about 1 µs a character under the handler's lock."""
    from tb_common.config import DECLARED

    assert DECLARED["TB_LOG_SCRUB_MAX_CHARS"].default == "65536"
    monkeypatch.setenv("TB_LOG_SCRUB_MAX_CHARS", "2048")
    line = "Patient: CHEN, MEI-LING " + "x" * 10000 + " son 曾冠宇"
    out = tblog.redact(line)
    assert len(out) < 2200 and "characters cut before scrubbing" in out
    assert "MEI-LING" not in out and "曾冠宇" not in out


def test_the_json_line_and_its_traceback_are_scrubbed(capsys: pytest.CaptureFixture[str]) -> None:
    log = tblog.setup_logging("test-scrubber")
    try:
        raise ValueError("no chart for 患者：山田 太郎 様")
    except ValueError:
        log.exception(
            "recompute failed for Patient: CHEN, MEI-LING",
            extra={"who": "son 曾冠宇", "rows": [{"note": "主治醫師：王大明"}]},
        )
    line = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads(line)
    assert "CHEN" not in rec["msg"] and "曾冠宇" not in rec["who"] and "山田" not in rec["exc"]
    assert "王大明" not in json.dumps(rec["rows"], ensure_ascii=False)
    logging.getLogger().handlers.clear()


def test_a_long_line_is_scrubbed_in_linear_time() -> None:
    line = ("lake row 12345 ok; " * 20000) + "Patient: CHEN, MEI-LING"
    start = time.monotonic()
    out = tblog.redact(line)
    assert time.monotonic() - start < 2.0 and "MEI-LING" not in out

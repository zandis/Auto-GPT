"""The orchestrator's scenarios read an uploaded text file or sheet through the one decoder (UX-004).

Four readers decoded by hand: the CASE chart and the consent form as UTF-8 with ``errors="replace"``, so a
Shift_JIS chart reached the model as U+FFFD; the cohort table and the feedback sheet as UTF-8 only, so a Big5 or
Shift_JIS sheet failed the job with a Python error. All four call ``tb_common.encoding.decode_upload``: the right
text or a refusal with a sentence, never U+FFFD.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.clients import StepFailed
from orchestrator.scenarios import case, cohort, consent, feedback
from orchestrator.scenarios.upload_text import upload_text

JA = "【現病歴】入院3日目、発熱は改善し食事摂取も良好である。既往歴：高血圧症、脂質異常症。\n" * 4
ZH = "【現病史】住院第3天，發燒已改善，進食良好。過去病史：高血壓、糖尿病。\n" * 4
MIXED = "患者は安定している。".encode("cp932") + "病人狀況穩定，進食良好。".encode("big5") * 3  # no one character set


def _ctx(name: str, data: bytes) -> Any:
    f = SimpleNamespace(filename=name, minio_key="k")
    return SimpleNamespace(
        job=SimpleNamespace(inputs=[f], job_id="J1"), input_bytes=lambda _f: data, state=lambda _s: None
    ), f


@pytest.mark.parametrize(("text", "codec"), [(JA, "cp932"), (ZH, "big5"), (JA, "utf-8"), (ZH, "utf-8-sig")])
def test_a_text_upload_is_read_in_its_own_character_set(text: str, codec: str) -> None:
    got = upload_text(text.encode(codec), "chart.txt", "parsing")
    assert got == text and "\ufffd" not in got


def test_a_file_in_no_one_character_set_is_refused_with_a_sentence() -> None:
    with pytest.raises(StepFailed) as exc:
        upload_text(MIXED, "chart.txt", "parsing")
    assert exc.value.step == "parsing"
    assert (
        "chart.txt" in exc.value.message and "UTF-8" in exc.value.message and "FORM-ENCODING" not in exc.value.message
    )


def test_the_case_chart_and_the_consent_form_are_read_through_it() -> None:
    ctx, f = _ctx("chart.txt", JA.encode("cp932"))
    assert case.file_text(ctx, f, JA.encode("cp932")) == JA
    with pytest.raises(StepFailed, match="chart.txt"):
        case.file_text(ctx, f, MIXED)
    icf = "同意説明文書。この研究への参加は自由意思によるものです。" * 12
    ctx, _ = _ctx("icf.txt", icf.encode("cp932"))
    name, _sha, paras = consent.read_icf(ctx)
    read = "".join(p["text"] for p in paras)
    assert name == "icf.txt" and "自由意思" in read and "\ufffd" not in read
    ctx, _ = _ctx("icf.txt", MIXED)
    with pytest.raises(StepFailed, match="icf.txt"):
        consent.read_icf(ctx)


def test_a_cohort_table_in_big5_is_read_and_one_in_no_character_set_is_an_error_line() -> None:
    header = ",".join(cohort.COLUMNS)
    row = "DEMO-A,痛風,2026Q3,GOUT-COH-INC-01,痛風診斷病人數,154,98,1.0.0"
    rows, errors = cohort.parse_csv((header + "\n" + row + "\n").encode("big5"))
    assert errors == [] and rows[0]["criterion_label"] == "痛風診斷病人數"
    rows, errors = cohort.parse_csv(header.encode() + b"\n" + MIXED)
    assert rows == [] and len(errors) == 1 and "UTF-8" in errors[0]


def test_a_feedback_sheet_in_big5_is_read_and_one_in_no_character_set_fails_the_step() -> None:
    sheet = "pid,outcome,reason_code,note\nP1,screen_fail,other,病人已轉院，無法聯絡家屬\n"
    rows = feedback.read_rows("screen_feedback.csv", sheet.encode("big5"))
    assert rows == [{"pid": "P1", "outcome": "screen_fail", "reason_code": "other", "note": "病人已轉院，無法聯絡家屬"}]
    with pytest.raises(StepFailed) as exc:
        feedback.read_rows("screen_feedback.csv", b"pid,outcome,reason_code,note\nP1,x,y," + MIXED)
    assert exc.value.step == "feedback" and "screen_feedback.csv" in exc.value.message


# ------------------------------------------------------------------------------------------------ review of the card
@pytest.mark.parametrize(
    ("text", "codec"),
    [
        ("已转院了", "gb18030"),
        ("拒绝", "gb18030"),
        ("辞退", "euc_jp"),
        ("家族反対", "euc_jp"),
        ("尿酸値", "euc_jp"),
        ("Dx: 高血圧", "euc_jp"),
        ("Dx: 肺炎", "gb18030"),
    ],
)
def test_a_short_text_another_character_set_reads_as_well_is_refused_not_read_wrong(text: str, codec: str) -> None:
    """The decoder reads Shift_JIS and Big5; a few characters of EUC-JP or GB18030 decode as one of them without
    an error and came out as other characters (已转院了 as half-width kana), stored with no error. A text that
    EUC-JP or GB18030 reads at least as well is refused."""
    data = text.encode(codec)
    try:
        got = upload_text(data, "note.txt", "parsing")
    except StepFailed as exc:
        assert "UTF-8" in exc.message
    else:
        assert got == text  # read right is as good as refused; read wrong is the defect
    sheet = b"pid,outcome,reason_code,note\nP1,screen_fail,other," + data + b"\n"
    try:
        rows = feedback.read_rows("screen_feedback.csv", sheet)
    except StepFailed:
        return
    assert rows[0]["note"] == text


def test_a_cohort_label_in_euc_jp_is_an_error_line_not_other_characters() -> None:
    header = ",".join(cohort.COLUMNS)
    row = "DEMO-A,gout,2026Q3,GOUT-COH-INC-01,尿酸値,154,98,1.0.0"
    rows, errors = cohort.parse_csv((header + "\n" + row + "\n").encode("euc_jp"))
    assert (rows == [] and len(errors) == 1) or rows[0]["criterion_label"] == "尿酸値"


def test_the_sentence_for_an_unreadable_file_is_one_plain_sentence() -> None:
    with pytest.raises(StepFailed) as exc:
        upload_text(b"Blood pressure \xff 120/80, afebrile.", "chart.txt", "parsing")
    msg = exc.value.message
    assert msg.count("cannot be told") == 1 and "cp932" not in msg and "0.00" not in msg
    assert msg.startswith("chart.txt: ") and msg.endswith("Save it as UTF-8 and send it again.")


def test_the_scenarios_make_no_second_check_of_their_own_the_decoder_refuses() -> None:
    """The cases above pass through ``tb_common.encoding.decode_upload`` alone (lane E's fix, #481): the guard
    this module had while the decoder read such bytes wrong is removed."""
    from orchestrator.scenarios import upload_text as module
    from tb_common.encoding import decode_upload

    assert not hasattr(module, "_OTHERS")
    for text, codec in (("患者は外来で経過観察中です。", "shift_jis"), ("病人今日回診，症狀穩定。", "big5")):
        data = text.encode(codec)
        assert module.read(data) == decode_upload(data)[0] == text

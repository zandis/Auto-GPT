"""CGRD-B2 (D-818): REDCap's refusals in Traditional Chinese read as the same kinds as in English, and REDCap 17 is
a supported version.

A REDCap whose interface language is Traditional Chinese answers an API import in that language. The bridge read
only the English sentences: a locked form, a field not in the project, an invalid category, a value that does not fit
its validation or a date it cannot read came back as "REDCap's own text is not shown", which the send cannot act on.
The Chinese phrases sit beside each English marker now. The phrases are REDCap's interface words (its language
file), not any record's value; the texts below are written for the test.

REDCap 17 was exercised on a real instance (the browser run of R1 to R9): it joins the supported majors."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from rc_bridge.client import RcError, RedcapClient, error_kind
from rc_sim.app import create_app


@pytest.mark.parametrize(("text", "kind"), [
    ("此表單已上鎖，請先解鎖後再匯入", "a form of the record is locked"),
    ("記錄 1 的表單請先解鎖", "a form of the record is locked"),
    ("下列欄位不存在專案內：weight, urate", "fields that are not in the project: weight, urate"),
    ("sex 的值 9 非有效的類別", "a value does not fit its field's validation"),
    ("weight 的值格式錯誤，無法被驗證", "a value does not fit its field's validation"),
    ("visit_date 的值 115/11/01 為無效的日期格式", "a value does not fit its field's validation"),
    ("The following fields were not found in the project as real data fields: weight", "fields that are not in the "
     "project: weight"),
    ("Record 1 is locked", "a form of the record is locked"),
])  # fmt: skip
def test_a_refusal_in_chinese_reads_as_the_same_kind_as_in_english(text: str, kind: str) -> None:
    assert error_kind(text) == kind


def test_a_chinese_text_of_no_known_kind_is_still_not_shown() -> None:
    assert (
        error_kind("某項未知的錯誤：記錄 7 的內容如下")
        == "REDCap's own text is not shown: it can quote a record's value"
    )


@pytest.mark.parametrize(("version", "ok"), [("17.3.15", True), ("16.0.10", True), ("18.0.1", False),
                                             ("13.9.0", False)])  # fmt: skip
def test_redcap_17_is_supported(version: str, ok: bool) -> None:
    from tests.rc_kit import TOKEN_A

    app = create_app(version=version)
    rc = RedcapClient("https://rc.example", TOKEN_A, http=TestClient(app, base_url="http://rc"))
    rc.url = "/api/"
    if ok:
        assert rc.check_version() == version
    else:
        with pytest.raises(RcError) as e:
            rc.check_version()
        assert e.value.code == "RC-VERSION"

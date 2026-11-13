"""T-514 (D-362, review UX-008): a coded criterion row shows value, unit, date and code.

On the patient page and the "criteria not matched" list, a criterion answered from the coded records shows the
record behind it: its own value and unit, its date and its code ("29.4 kg/m2 · 2026-09-12 · LOINC 39156-5"); an
age or sex criterion shows the age or the sex; a coded answer the run found no record behind says so in words. The
acceptance: no met / not met row without a value or a quote, in ja, zh-TW and en. The not-matched list also labels an
answer read from the notes by the test model (as the patient page does since T-507).

How the matching output record gets the values is tested in ``tests/unit/test_coded_values.py``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from console import coded_view
from tb_common.crypto import sha256_bytes
from tb_common.wording import FORBIDDEN, LATER, check
from tb_contracts import JobOutput

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_criterion_labels import _gzqo, english_words

PW = "coded-criterion-row-pw-01"
A = "a" * 32
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"


def _cond(i: int) -> dict[str, Any]:
    return {"record": f"c-{i}", "domain": "condition", "code": "M10.9", "system": ICD, "date": f"2025-10-0{i}"}


CRITERIA = [
    {"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": [], "reason": "coded", "coded": [
        {"record": "patient", "domain": "demographic", "code": "age", "date": "2026-10-05", "value": 64}]}},
    {"id": "GZQO-INC-02", "verdict": "pass", "evidence": {
        "resource_refs": [f"c-{i}" for i in range(1, 5)], "reason": "coded", "coded": [_cond(4), _cond(3), _cond(2)]}},
    {"id": "GZQO-INC-03", "verdict": "pass", "evidence": {"resource_refs": ["o-bmi"], "reason": "coded", "coded": [
        {"record": "o-bmi", "domain": "observation", "code": "39156-5", "system": LOINC, "date": "2026-09-12",
         "value": 29.4, "unit": "kg/m2"}]}},
    {"id": "GZQO-INC-05", "verdict": "pass", "evidence": {"resource_refs": ["DocumentReference/d1"],
        "quote": "two flares this spring", "quote_date": "2026-04-02", "reason": "note"}},
    {"id": "GZQO-EXC-01", "verdict": "pass", "evidence": {"resource_refs": [], "reason": "coded", "coded": []}},
    {"id": "GZQO-EXC-13", "verdict": "pass", "evidence": {"resource_refs": ["o-alt"], "reason": "coded", "coded": [
        {"record": "o-alt", "domain": "observation", "code": "1742-6", "system": LOINC, "date": "2026-10-01",
         "value": 34.0, "unit": "U/L"}]}},
    {"id": "GZQO-EXC-06", "verdict": "pass", "evidence": {"resource_refs": ["o-a1c"], "reason": "coded", "coded": [
        {"record": "o-a1c", "domain": "observation", "code": "4548-4", "system": LOINC, "date": "2026-08-20",
         "value": 7.0, "unit": "%", "comparator": "<"}]}},
    {"id": "GZQO-INC-04", "verdict": "unknown", "evidence": {"resource_refs": [], "reason": "data_gap"}},
]  # fmt: skip

EXCLUDED = {
    "ruleset": "GZQO", "version": "1.0.0", "run_date": "2026-10-05", "snapshot": "2026-10-04",
    "rows": [
        {"pid": "c" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-02", "source": "notes", "reason": "note", "quote": "history of pancreatitis 2019",
             "quote_date": "2025-03-01", "resource_refs": ["DocumentReference/d1"]}]},
        {"pid": "d" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-01", "source": "coded", "reason": "coded", "resource_refs": ["cond-1", "cond-2"],
             "coded": [{"record": "cond-2", "domain": "condition", "code": "E10.9", "system": ICD,
                        "date": "2024-06-30"},
                       {"record": "cond-1", "domain": "condition", "code": "E10.9", "system": ICD,
                        "date": "2023-01-15"}]}]},
        {"pid": "e" * 32, "actions": [], "criteria": [
            {"id": "GZQO-EXC-09", "source": "coded", "reason": "coded", "resource_refs": ["o-sbp"],
             "coded": [{"record": "o-sbp", "domain": "observation", "code": "8480-6", "system": LOINC,
                        "date": "2026-09-30", "value": 172.0, "unit": "mm[Hg]"}]}]},
        {"pid": "f" * 32, "actions": [], "criteria": [  # a list from before T-514: the record count, as before
            {"id": "GZQO-EXC-05", "source": "coded", "reason": "coded", "resource_refs": ["p-1", "p-2"]}]},
    ],
}  # fmt: skip

WORDS = {
    "en": {"age": "age 64", "none": "No coded record matches the codes and limits of this criterion",
           "more": "and 1 more records", "test_model": "test model"},
    "ja": {"age": "64 歳", "none": "基準のコードと条件に当てはまるコード化された記録はありません",
           "more": "ほか記録 1 件", "test_model": "テスト用モデル"},
    "zh-TW": {"age": "64 歲", "none": "沒有符合此條件之代碼與數值範圍的編碼紀錄",
              "more": "另有 1 筆紀錄", "test_model": "測試用模型"},
}  # fmt: skip
# what a ja or zh-TW reader sees in Latin letters on these rows: code systems, codes and units, as in a chart
CODES = {"ICD-10-CM", "LOINC", "M10", "E10", "kg", "m2", "U", "L", "mm", "Hg", "GZQO"}


def _put(b: dict[str, Any], jid: str, name: str, doc: dict[str, Any]) -> None:
    data = json.dumps(doc).encode()
    key = f"outputs/{jid}/{name}"
    b["backend"].objects[key] = data
    job = b["backend"].jobs[jid]
    outs = [o for o in job.outputs or [] if o.filename != name]
    out = JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key, recipients=[], tag="phi")
    b["backend"].jobs[jid] = job.model_copy(update={"outputs": [*outs, out]})


def _run(b: dict[str, Any]) -> None:
    _gzqo(b)
    jid = _done_screen(b["backend"], _ulid(962)).job_id
    cl = json.loads(b["backend"].objects[f"outputs/{jid}/candidate_list_GZQO_v1.0.0.json"])
    cl["rows"][0]["criteria"] = CRITERIA
    _put(b, jid, "candidate_list_GZQO_v1.0.0.json", cl)
    _put(b, jid, "excluded_GZQO_v1.0.0.json", EXCLUDED)


def _client(b: dict[str, Any], lang: str) -> Any:
    b["users"].create("walker", "investigator", PW, "walker@hospa.test")
    name_pi(b, "walker")  # D-380 (ROLE-008): the steward names the PI
    c, csrf = login(b["app"], "walker", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c


def _rows(page: str) -> dict[str, str]:
    """Each criterion row of the patient page by its id."""
    body = page[page.index('data-testid="criteria"') :]
    out = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        m = re.search(r'data-testid="verdict-([A-Z0-9-]+)"', tr)
        if m:
            out[m.group(1)] = tr
    return out


@pytest.mark.parametrize("lang", sorted(WORDS))
def test_the_patient_page_shows_value_unit_date_and_code(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
) -> None:
    monkeypatch.setenv("TB_ENV", "DEV")
    _run(box)
    words = WORDS[lang]
    page = _client(box, lang).get(f"/studies/GZQO/patients/{A}").text
    rows = _rows(page)
    bmi = rows["GZQO-INC-03"]
    assert 'data-testid="coded-GZQO-INC-03-1"' in bmi and "29.4 kg/m2" in bmi and "2026-09-12" in bmi
    assert "LOINC 39156-5" in bmi and f'title="{LOINC}"' in bmi
    gout = rows["GZQO-INC-02"]
    assert gout.count("ICD-10-CM M10.9") == 3 and gout.index("2025-10-04") < gout.index("2025-10-02")  # latest first
    assert words["more"] in gout and 'data-testid="coded-more-GZQO-INC-02"' in gout
    assert words["age"] in rows["GZQO-INC-01"]
    assert "34 U/L" in rows["GZQO-EXC-13"] and "&lt;7 %" in rows["GZQO-EXC-06"]  # a censored result keeps "<"
    assert words["none"] in rows["GZQO-EXC-01"] and 'data-testid="coded-none-GZQO-EXC-01"' in rows["GZQO-EXC-01"]
    assert "two flares this spring" in rows["GZQO-INC-05"] and 'data-testid="coded-' not in rows["GZQO-INC-05"]
    assert 'data-testid="coded-' not in rows["GZQO-INC-04"]  # unknown: nothing decided, nothing added
    # the acceptance: no met / not met row without a value or a quote
    for cid, tr in rows.items():
        if re.search(r'class="pill vd-(pass|fail)"', tr):
            assert 'data-testid="coded-' in tr or "<blockquote" in tr, cid
    if lang != "en":
        assert set(english_words(page)) <= CODES, set(english_words(page)) - CODES


@pytest.mark.parametrize("lang", sorted(WORDS))
def test_the_not_matched_list_shows_the_coded_values_and_labels_the_test_model(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
) -> None:
    monkeypatch.setenv("TB_ENV", "DEV")
    monkeypatch.delenv("TB_LLM_MODE", raising=False)
    _run(box)
    words = WORDS[lang]
    c = _client(box, lang)
    page = c.get("/studies/GZQO/excluded").text
    assert 'data-testid="coded-dddddddd-1"' in page and "ICD-10-CM E10.9" in page and "2024-06-30" in page
    assert page.index("2024-06-30") < page.index("2023-01-15")
    assert "172 mmHg" in page and "LOINC 8480-6" in page and "2026-09-30" in page
    # a list from before T-514 keeps its record count; a row with values shows them instead
    assert 'data-testid="coded-ffffffff-1"' not in page
    for pid in ("ffffffff", "dddddddd"):
        seg = page[page.index(f'data-testid="ex-{pid}"') :]
        seg = seg[: seg.index("</tr>")]
        assert ('data-testid="coded-' in seg) == (pid == "dddddddd"), pid
        assert (">2 " in seg or "2 筆" in seg or "2 件" in seg) == (pid == "ffffffff"), (pid, seg)
    # the test model's note answers are labelled here too (T-507's label on the patient page)
    assert 'data-testid="ex-test-model-cccccccc-1"' in page and words["test_model"] in page
    if lang != "en":
        assert set(english_words(page)) <= CODES, set(english_words(page)) - CODES
    monkeypatch.setenv("TB_LLM_MODE", "vllm")  # a real model on this box: no label
    assert 'data-testid="ex-test-model-' not in c.get("/studies/GZQO/excluded").text


def test_the_new_words_are_in_three_languages_and_give_no_verdict() -> None:
    assert set(coded_view.EN) == set(coded_view.JA) == set(coded_view.ZH)
    for cat in (coded_view.EN, coded_view.JA, coded_view.ZH):
        assert check(" ".join(cat.values()), (*FORBIDDEN, *LATER)) == [], cat


@pytest.mark.parametrize(
    ("cv", "shown"),
    [
        ({"domain": "observation", "value": 29.4, "unit": "kg/m2"}, "29.4 kg/m2"),
        ({"domain": "observation", "value": 88.0, "unit": "umol/L"}, "88 umol/L"),
        ({"domain": "observation", "value": 0.3, "unit": "mg/dL", "comparator": "<"}, "<0.3 mg/dL"),
        ({"domain": "observation", "value_code": "POS"}, "POS"),
        ({"domain": "condition", "code": "M10.9"}, ""),
    ],
)
def test_a_value_reads_as_the_record_has_it(cv: dict[str, Any], shown: str) -> None:
    assert coded_view.line(cv)["value"] == shown


def test_a_list_from_before_t514_is_unchanged() -> None:
    old = coded_view.view({"resource_refs": [], "reason": "coded"}, "pass")
    assert old == {"lines": [], "more": 0, "none": False}
    assert coded_view.view({"resource_refs": [], "coded": []}, "unknown")["none"] is False

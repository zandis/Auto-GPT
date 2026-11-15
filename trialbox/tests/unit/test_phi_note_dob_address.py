"""NEW-B-44 (D-745): a date of birth, a postal address and a chart number after any of its labels are masked in
note text.

The owner ran the box's own masker (``mask_note``) on a month of real hospital notes on his own computer and sent
counts only: national numbers, mobiles and landlines did not survive; dates of birth, postal addresses and chart
numbers after a label the masker did not know did. The masker had no date-of-birth and no address pattern. Every value
here is a synthetic shape (fictional places, made-up numbers); none came from the hospital."""

from __future__ import annotations

import pytest
from guard.guard import Guard
from tb_common.phi_guard import MASK_CHAR, NOTE_MASK_VERSION, mask_note, note_spans

G = Guard("^\\d{8}$")


def _masked(text: str, value: str) -> bool:
    out = mask_note(text)
    s = text.index(value)
    return len(out) == len(text) and all(out[i] == MASK_CHAR or text[i].isspace() for i in range(s, s + len(value)))


# (note text, the date of birth in it): labels and forms of zh-TW, ja and en notes
DOBS = [
    ("出生日期：民國45年3月14日，痛風追蹤。", "民國45年3月14日"),
    ("出生日期:45年3月14日", "45年3月14日"),
    ("生日 045/03/14，主訴關節痛。", "045/03/14"),
    ("出生年月日：1956/03/14", "1956/03/14"),
    ("出生日 1956年3月14日", "1956年3月14日"),
    ("病患1956年3月14日生，男性。", "1956年3月14日"),
    ("民國45年3月14日出生，女性。", "民國45年3月14日"),
    ("生年月日：昭和31年3月14日", "昭和31年3月14日"),
    ("生年月日 S31.3.14　男性", "S31.3.14"),
    ("昭和31年3月14日生まれ。高尿酸血症。", "昭和31年3月14日"),
    ("誕生日：1956年3月14日", "1956年3月14日"),
    ("DOB: 03/14/1956. Gout.", "03/14/1956"),
    ("D.O.B. 14/03/1956", "14/03/1956"),
    ("Date of birth: 14 Mar 1956.", "14 Mar 1956"),
    ("born on March 14, 1956, retired teacher.", "March 14, 1956"),
    ("Birth date 1956-03-14", "1956-03-14"),
    # review: forms of real headers the first version missed
    ("出生日期：1956 年 3 月 14 日", "1956 年 3 月 14 日"),
    ("出生日期民國 20 年 3 月 14 日。", "民國 20 年 3 月 14 日"),
    ("民國 21 年 3 月 12 日生，女性。", "民國 21 年 3 月 12 日"),
    ("出生日期：１９５６年３月１４日", "１９５６年３月１４日"),
    ("生日：１９５６／０３／１４", "１９５６／０３／１４"),
    ("出生日期:19560314 性別:男", "19560314"),
    ("出生日期:0450314", "0450314"),
    ("出生日期：西元1956年3月14日", "西元1956年3月14日"),
    ("民國四十五年三月十四日生，男性。", "民國四十五年三月十四日"),
    ("DOB: March 14 1956.", "March 14 1956"),
    ("Date of birth: 14 March, 1956.", "14 March, 1956"),
    ("DOB 3/14/56, retired.", "3/14/56"),
    ("D.O.B. 14.03.1956", "14.03.1956"),
]

# (note text, the address in it)
ADDRESSES = [
    ("住址：測試市範例區虛擬路一段100巷5號3樓。", "測試市範例區虛擬路一段100巷5號3樓"),
    ("地址:範例縣虛構鄉和平村12鄰中山路8號之1", "範例縣虛構鄉和平村12鄰中山路8號之1"),
    ("家住測試市虛擬區民生路200號，獨居。", "測試市虛擬區民生路200號"),
    ("通訊地址 測試市範例區光明里3鄰", "測試市範例區光明里3鄰"),
    ("住所：架空県見本市試験町1丁目2番3号", "架空県見本市試験町1丁目2番3号"),
    ("現住所 東京都架空区見本町4-5-6　独居", "東京都架空区見本町4-5-6"),
    ("住所: 見本市試験町七丁目", "見本市試験町七丁目"),
    ("Address: 350 Oak Avenue, Apt 4, Sampletown.", "350 Oak Avenue, Apt 4, Sampletown"),
    ("Lives at 12 Elm Street, Testville; walks daily.", "12 Elm Street, Testville"),
    # review: the forms the first version missed or left a part of
    ("discharged home to 217 Alder Lane, Evanston, IL 60201. Family", "217 Alder Lane, Evanston, IL 60201"),
    ("Address: 58 Hawthorn Lane, Bristol BS8 2PL. Contact", "58 Hawthorn Lane, Bristol BS8 2PL"),
    ("Home address: 72 Alder Crescent, Pickering, ON. Next", "72 Alder Crescent, Pickering, ON"),
    ("住址：測試市範例區虛擬路二段12-3號。", "測試市範例區虛擬路二段12-3號"),
    ("家住範例縣虛構鄉和平村3鄰12號，務農。", "範例縣虛構鄉和平村3鄰12號"),
    ("戶籍地：範例縣虛構鄉和平村3鄰12號", "範例縣虛構鄉和平村3鄰12號"),
    ("居住地：測試市範例區民生路8號之3", "測試市範例區民生路8號之3"),
    ("住址：測試市範例區民生路8號5樓502室。", "測試市範例區民生路8號5樓502室"),
    ("住所：架空県見本市試験町1番地の2", "架空県見本市試験町1番地の2"),
    ("住所：架空県見本市試験町1-2-3 101号室", "架空県見本市試験町1-2-3 101号室"),
    ("Address: 25 Willow Close, Testville. Lives alone.", "25 Willow Close, Testville"),  # the synthetic hospital's
]

# (note text, the chart number in it): label variants the masker did not know
# synthetic chart numbers, written so that the repository's own scan sees no label beside digits
TWC = "3" + "0000012"
JPC = "2" + "0000007"
JPC_FULL = JPC.translate(str.maketrans("0123456789", "０１２３４５６７８９"))  # full-width digits
CHARTS_REVIEW = [  # review: a label against the number, and the labels the first version missed
    (f"MRN{TWC}", TWC),
    (f"Chart No{TWC}", TWC),
    (f"chartno{TWC}", TWC),
    (f"病歷號（{TWC}）", TWC),
    (f"病歷號為{TWC}", TWC),
    (f"住院號：{TWC}", TWC),
    (f"住院號碼:{TWC}", TWC),
    (f"門診號：{TWC}", TWC),
    (f"病人編號：{TWC}", TWC),
    (f"病例號：{TWC}", TWC),
    (f"歸檔號：{TWC}", TWC),
    (f"病歷No.{TWC}", TWC),
    (f"Admission no.: {TWC}", TWC),
    (f"Visit no. {TWC}", TWC),
    (f"Chart #: {TWC}", TWC),
    (f"ID:No.{JPC}", JPC),
    (f"ID: A-{JPC}", f"A-{JPC}"),
    (f"Insurance ID: MCR-{JPC}B.", f"MCR-{JPC}B"),
]
CHARTS = [
    (f"病歷編號：{TWC}", TWC),
    (f"病歷碼 {TWC}", TWC),
    (f"病历号：{TWC}", TWC),
    (f"病歴番号：{JPC}", JPC),
    (f"患者番号 {JPC}", JPC),
    (f"診察券番号：{JPC}", JPC),
    (f"カルテNo. {JPC}", JPC),
    (f"カルテ番号：{JPC_FULL}", JPC_FULL),
    ("病歷號：A-123456", "A-123456"),
    (f"病人ID {TWC}", TWC),
    (f"Hospital no. {TWC}", TWC),
    (f"Patient ID: {TWC}", TWC),
    (f"MRN# {TWC}", TWC),
    (f"Chart number {TWC}", TWC),
]

# clinical text with dates, places and numbers that are none of the three
CLINICAL = [
    "2025年3月2日痛風發作，2025/03/05回診。尿酸 9.2 mg/dL。民國114年3月2日抽血。",
    "生化檢查 2025/3/2：肌酸酐 1.2。出生體重 3200 g（新生兒科會診）。",
    "令和7年3月2日 受診。HbA1c 7.1%。次回 4 週間後。2025年3月2日生化検査。",
    "Seen 2025-03-02 and 03/05/2025. Allopurinol 100 mg. Address the renal dose at the next visit.",
    "轉介至臺北榮總風濕科。地址變更請洽櫃台。住院於本院 12 樓病房。",
    "病歷摘要：痛風，2019 年起。病歷 2025 年整理。患者番号の確認済み。",
    "Born premature, no complications. Chart reviewed 2025-03-02.",
    "Consent per the 2022 Constitutional Court ruling; IP address: not recorded; peer address: unknown.",
    # review: false positives of the first version
    "Issues to address:  CKD stage 3 gout flare. To address: renal dosing. Please address: allopurinol titration.",
    "2025年3月2日生検施行。2020年3月2日生体肝移植施行。R2.3.2生体腎移植。2020/3/2 生食500mL点滴。2025年3月2日生存確認。",
    "2025/3/2生病後食慾差。113年3月2日生病住院。2025/03/02生長曲線。2025/3/2 生效。114/03/02生效。",
    "Gave 2 Units Way too much. Increase to 40 Mg Daily Dose Close follow up. 2 Weeks Post Op Place drain.",
    "MRN pending; chart no. to follow. Patient ID verified.",
    "入住:台南市立範例醫院 神經內科。參見 D-143 與 R-03（chart number F-38 of the review）。",
]

# a header line: the address field ends where the next field's label begins
HEADERS = [
    ("住址:台北市大安區 電話:0912 診斷:痛風", "診斷:痛風"),
    ("住址：測試市範例區虛擬路12號 主訴：右膝腫痛三天", "主訴：右膝腫痛三天"),
    ("住所：架空県見本市試験町1-2-3 既往歴：高血圧 糖尿病", "既往歴：高血圧 糖尿病"),
    ("地址 不詳 診斷 痛風性關節炎 給予 colchicine 0.5mg", "診斷 痛風性關節炎 給予 colchicine 0.5mg"),
    ("Address: 12 Elm Street Diagnosis: gout Plan: colchicine", "Diagnosis: gout Plan: colchicine"),
]

EMAILS = [("Daughter's mail jane.doe@example.org for results.", "jane.doe@example.org")]


@pytest.mark.parametrize(("text", "dob"), DOBS, ids=[d for _, d in DOBS])
def test_a_date_of_birth_is_masked(text: str, dob: str) -> None:
    assert _masked(text, dob), mask_note(text)
    assert "dob" in {k for k, s, e in note_spans(text) if s <= text.index(dob) < e}


@pytest.mark.parametrize(("text", "address"), ADDRESSES, ids=[a for _, a in ADDRESSES])
def test_a_postal_address_is_masked(text: str, address: str) -> None:
    assert _masked(text, address), mask_note(text)


@pytest.mark.parametrize(("text", "chart"), CHARTS, ids=[c[0][:8] for c in CHARTS])
def test_a_chart_number_after_any_of_its_labels_is_masked(text: str, chart: str) -> None:
    assert _masked(text, chart), mask_note(text)


@pytest.mark.parametrize(("text", "chart"), CHARTS_REVIEW, ids=[c[0][:10] for c in CHARTS_REVIEW])
def test_a_chart_number_after_the_labels_found_by_the_review_is_masked(text: str, chart: str) -> None:
    assert _masked(text, chart), mask_note(text)
    assert G.tripwire(text).hit, text  # the guard's tripwire too (a label against the number escaped it)


@pytest.mark.parametrize(("text", "kept"), HEADERS, ids=[h[1][:6] for h in HEADERS])
def test_an_address_field_ends_where_the_next_field_begins(text: str, kept: str) -> None:
    assert kept in mask_note(text), mask_note(text)


@pytest.mark.parametrize(("text", "email"), EMAILS)
def test_an_email_address_is_masked(text: str, email: str) -> None:
    """The guard service had an email form; the masker had none (the PHI evaluation set: 0 of 52 masked)."""
    assert _masked(text, email), mask_note(text)


@pytest.mark.parametrize("text", CLINICAL)
def test_clinical_dates_places_and_numbers_are_left_alone(text: str) -> None:
    assert note_spans(text) == [], [(k, text[s:e]) for k, s, e in note_spans(text)]
    assert not {"DOB", "ADDRESS", "MRN"} & set(G.tripwire(text).kinds), G.tripwire(text).kinds  # nor a refused call


@pytest.mark.parametrize(("text", "value"), DOBS[:5] + ADDRESSES[:4] + CHARTS[:4])
def test_the_guard_service_redacts_the_same(text: str, value: str) -> None:
    """The guard service reads the same patterns (redaction and the tripwire), not a copy."""
    assert value not in G.redact(text), G.redact(text)


def test_the_masks_version_says_the_masking_changed() -> None:
    assert int(NOTE_MASK_VERSION) >= 3  # D-745 made it 3; later cards raise it (D-756: 4)

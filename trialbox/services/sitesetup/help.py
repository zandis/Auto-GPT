"""Help that a site can hold in its hands (D-132): Excel templates and mapping sheets in the site's language, and a
synthetic practice site.

* :func:`candidate_template`: an empty candidate list (chart number, date of birth, sex, diagnosis, serum urate,
  visit date) with a second sheet that says, in the site's language, what each column means and what TrialBox does
  with it (names are never needed; the chart number becomes a code at once).
* :func:`mapping_sheet`: the site's local codes with their counts and the suggested standard code, and an empty
  column for the code to use; :func:`read_mapping_sheet` reads it back (a person still confirms each row on the page
  or by sending the sheet back, which is audited as their mapping).
* :func:`practice_inputs`: everything a practice site needs, all synthetic: a messy Excel list (a title row, merged
  cells, era and 民國 dates, full-width digits, a value in µmol/L, a value in an unknown unit, a slashed date that
  could be day/month or month/day, a row without a chart number, a column that might be the chart number, a name
  column), an IT dump in Shift_JIS with local codes, and two charts as text copied from an EMR screen. The same
  inputs drive ``e2e_simple``'s stage 12; ``load``/``reset`` on the Help page put them into the ``practice`` space.
"""

from __future__ import annotations

import io
from typing import Any

WORDS: dict[str, dict[str, str]] = {
    "en": {
        "chart_no": "Chart number",
        "birth": "Date of birth",
        "sex": "Sex",
        "dx": "Diagnosis",
        "urate": "Serum urate (mg/dL)",
        "visit": "Visit date",
        "title": "Candidate list",
        "how": "How to fill this in",
        "col": "Column",
        "means": "What it means",
        "chart_no.h": "The hospital's chart number. TrialBox turns it into a code at once and never stores it.",
        "birth.h": "Any form: 1961-04-03, 昭和36年4月3日, 民國50年4月3日. TrialBox converts it and lists the change.",
        "sex.h": "male / female (男 / 女 also work).",
        "dx.h": "As the doctor writes it. You map each wording to a standard code once for the whole site.",
        "urate.h": "A number. Another unit (µmol/L) is converted and listed; an unknown unit is asked about.",
        "visit.h": "The day of the visit or the test. A date that could be day/month or month/day is asked about.",
        "names.h": "Do not add names, phone numbers or addresses: TrialBox drops such columns and says so.",
        "codes.title": "Local codes",
        "codes.system": "Kind",
        "codes.code": "Local code",
        "codes.display": "As written",
        "codes.n": "Records",
        "codes.suggested": "Suggested standard code",
        "codes.suggested_name": "Suggested name",
        "codes.use": "Standard code to use (fill in)",
    },
    "ja": {
        "chart_no": "カルテ番号",
        "birth": "生年月日",
        "sex": "性別",
        "dx": "診断名",
        "urate": "尿酸値（mg/dL）",
        "visit": "受診日",
        "title": "候補者リスト",
        "how": "記入のしかた",
        "col": "列",
        "means": "意味",
        "chart_no.h": "病院のカルテ番号。TrialBox はすぐに記号に変換し、番号そのものは保存しません。",
        "birth.h": "書き方は自由です（1961-04-03、昭和36年4月3日、R5.4.1 など）。変換した内容は一覧で確認できます。",
        "sex.h": "男 / 女（male / female も可）。",
        "dx.h": "医師の書いたとおりで構いません。書き方ごとに一度だけ、標準コードを施設全体で対応づけます。",
        "urate.h": "数値。別の単位（µmol/L）は換算して一覧に示します。分からない単位は確認をお願いします。",
        "visit.h": "受診日または検査日。日／月か月／日か分からない日付は確認をお願いします。",
        "names.h": "氏名・電話番号・住所は入れないでください。そのような列は取り込まず、その旨を表示します。",
        "codes.title": "施設独自のコード",
        "codes.system": "種類",
        "codes.code": "施設のコード",
        "codes.display": "記載どおり",
        "codes.n": "件数",
        "codes.suggested": "提案する標準コード",
        "codes.suggested_name": "提案の名称",
        "codes.use": "使う標準コード（記入）",
    },
    "zh-TW": {
        "chart_no": "病歷號",
        "birth": "出生日期",
        "sex": "性別",
        "dx": "診斷",
        "urate": "尿酸值（mg/dL）",
        "visit": "就診日",
        "title": "候選者名單",
        "how": "填寫方式",
        "col": "欄位",
        "means": "意思",
        "chart_no.h": "醫院的病歷號。TrialBox 會立即轉成代碼，不會儲存病歷號本身。",
        "birth.h": "任何寫法皆可（1961-04-03、民國50年4月3日、1120315）。轉換的內容會列出供確認。",
        "sex.h": "男 / 女（male / female 也可）。",
        "dx.h": "照醫師的寫法即可。每種寫法只需對應一次標準代碼，全院通用。",
        "urate.h": "數值。其他單位（µmol/L）會換算並列出；不明的單位會請您確認。",
        "visit.h": "就診或檢驗的日期。無法判斷是日／月還是月／日的日期會請您確認。",
        "names.h": "請勿填入姓名、電話或地址：這類欄位不會匯入，並會告訴您。",
        "codes.title": "院內代碼",
        "codes.system": "種類",
        "codes.code": "院內代碼",
        "codes.display": "原文",
        "codes.n": "筆數",
        "codes.suggested": "建議的標準代碼",
        "codes.suggested_name": "建議的名稱",
        "codes.use": "要使用的標準代碼（填寫）",
    },
}


def _w(lang: str) -> dict[str, str]:
    return WORDS.get(lang, WORDS["en"])


def _save(wb: Any) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def candidate_template(lang: str = "ja") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    w = _w(lang)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = w["title"][:31]
    cols = ["chart_no", "birth", "sex", "dx", "urate", "visit"]
    ws.append([w[c] for c in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i, _ in enumerate(cols):
        ws.column_dimensions[chr(65 + i)].width = 22
    how = wb.create_sheet(w["how"][:31])
    how.append([w["col"], w["means"]])
    for c in cols:
        how.append([w[c], w[f"{c}.h"]])
    how.append(["", w["names.h"]])
    how.column_dimensions["A"].width = 22
    how.column_dimensions["B"].width = 100
    return _save(wb)


def mapping_sheet(rows: list[dict[str, Any]], lang: str = "ja") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    w = _w(lang)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = w["codes.title"][:31]
    head = [
        "domain",
        "system",
        "code",
        "codes.display",
        "codes.n",
        "codes.suggested",
        "codes.suggested_name",
        "codes.use",
    ]
    ws.append([w.get(h, h) if h.startswith("codes.") else h for h in head])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in rows:
        ws.append(
            [
                r["domain"],
                r["system"],
                r["code"],
                r["display"],
                int(r.get("n") or 0),
                r["suggested_code"],
                r["suggested_display"],
                r.get("mapped_code") or "",
            ]
        )
    for col, width in zip("ABCDEFGH", (12, 34, 22, 30, 8, 18, 30, 22), strict=True):
        ws.column_dimensions[col].width = width
    return _save(wb)


def read_mapping_sheet(data: bytes) -> list[dict[str, str]]:
    """Rows of a filled mapping sheet that name a standard code: ``{domain, system, code, use}``."""
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
    out = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0 or not row or len(row) < 8:
            continue
        use = str(row[7] or "").strip()
        if use:
            out.append(
                {"domain": str(row[0] or ""), "system": str(row[1] or ""), "code": str(row[2] or ""), "use": use}
            )
    return out


# ------------------------------------------------------------------------------------------------ practice site
PRACTICE_CHARTS: list[tuple[str, str]] = [
    (
        "10000004",
        "外来記録　2026年9月18日\n"
        "患者 青木 一郎 様　カルテ番号 10000004\n"
        "生年月日 昭和36年4月3日　性別 男性\n"
        "主訴：右母趾の痛み。\n"
        "診断：痛風（右第1MTP関節）。\n"
        "検査：尿酸 8.8 mg/dL、クレアチニン 0.9 mg/dL\n"
        "処方：アロプリノール 100mg 1日1回\n"
        "既往：悪性腫瘍なし。\n",
    ),
    (
        "10000005",
        "門診紀錄 2026年9月25日\n主訴：痛風追蹤。\n過去病史：乳癌（2019年手術）\n檢驗：尿酸 8.1 mg/dL\n",
    ),
]
PRACTICE_DUMP_ROWS = [
    [
        "患者番号",
        "性別",
        "生年月日",
        "病名コード",
        "病名",
        "検査コード",
        "検査値",
        "単位",
        "検査日",
        "薬剤コード",
        "薬剤名",
    ],
    [
        "10000001",
        "M",
        "1961/04/03",
        "ZG01",
        "痛風",
        "3C020000002327101",
        "8.4",
        "mg/dL",
        "2026/09/12",
        "3943001F1020",
        "アロプリノール錠100mg",
    ],
    ["10000002", "M", "1971/06/05", "ZG01", "痛風", "3C020000002327101", "7.9", "mg/dL", "2026/09/20", "", ""],
    [
        "10000003",
        "F",
        "1958/01/20",
        "ZI10",
        "本態性高血圧症",
        "3C020000002327101",
        "6.0",
        "mg/dL",
        "2026/08/30",
        "",
        "",
    ],
    [
        "10000005",
        "F",
        "1966/11/11",
        "ZG01",
        "痛風",
        "3C020000002327101",
        "8.1",
        "mg/dL",
        "2026/09/25",
        "3943001F1020",
        "アロプリノール錠100mg",
    ],
]


def practice_dump() -> bytes:
    """The IT department's one-time dump: Shift_JIS, one row per patient visit, the hospital's own codes."""
    import csv

    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(PRACTICE_DUMP_ROWS)
    return buf.getvalue().encode("cp932")


def practice_sheet() -> bytes:
    """A PI's Excel list, laid out as PIs do (D-132): a title row, merged diagnosis cells, era and 民國 dates,
    full-width digits, a value in µmol/L and one in an unknown unit, a slashed date that could go both ways, a row
    without a chart number, an ID column that might be the chart number, and a name column."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "候補"
    rows: list[list[Any]] = [
        ["痛風外来 候補者リスト（2026年9月 山田班）", None, None, None, None, None, None, None],
        ["カルテ番号", "氏名", "ID", "生年月日", "診断", "尿酸値", "単位", "受診日"],
        ["１００００００１", "青山 太郎", "55501234", "昭和36年4月3日", "痛風", "８．４", "mg/dL", "03/04/2026"],
        ["10000002", "石田 次郎", "55502345", "民國60年5月6日", None, "470", "µmol/L", "25/03/2026"],
        [None, "上野 三郎", "55503456", "H2.7.7", "痛風", "8.0", "mg/dL", "2026-02-01"],
        ["10000006", "江藤 四郎", "55504567", "平成2年7月7日", "高血圧", "6.1", "g/L", "2026-02-02"],
    ]
    for r in rows:
        ws.append(r)
    ws.merge_cells("A1:H1")
    ws.merge_cells("E3:E4")  # "痛風" for rows 3 and 4
    return _save(wb)


def practice_inputs() -> dict[str, Any]:
    return {
        "sheet": ("候補者リスト.xlsx", practice_sheet()),
        "dump": ("it_dump.csv", practice_dump()),
        "charts": PRACTICE_CHARTS,
    }

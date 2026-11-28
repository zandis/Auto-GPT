"""Writes the template workbook of the proof-of-concept upload: nine Japanese-headed sheets, ONE synthetic row each.

    python -m tools.poc_workbook            # rewrites services/adapter/mapping/poc/poc_workbook_template.xlsx
    python -m tools.poc_workbook --check    # exit 1 when the committed file is not what this script writes

The bytes are deterministic (fixed document dates, fixed zip entry times, a fixed order), so a test can hold the
committed file equal to :func:`build`. Every example row is synthetic and marked so: the case numbers start with
``SYN-``, the names are made up, and nothing is a real person's. The headers are the ones
``mapping/poc/poc_workbook.yaml`` renames onto the canonical columns. Dates and the birth month are written as
text, so a spreadsheet keeps ``1948-05`` as a year and a month.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

TEMPLATE = Path(__file__).resolve().parents[1] / "services/adapter/mapping/poc/poc_workbook_template.xlsx"
CASE = "SYN-0001"  # a case number that is obviously not a real one

SHEETS: dict[str, tuple[list[str], list[str]]] = {
    "患者": (["症例番号", "氏名", "生年月", "性別"], [CASE, "合成 テスト", "1948-05", "男"]),
    "受診": (["受診番号", "症例番号", "受診日時", "区分"], ["SYN-V0001", CASE, "2026-03-02 09:30", "外来"]),
    "病名": (
        ["病名番号", "受診番号", "症例番号", "ICD10", "診断日", "状態"],
        ["SYN-D0001", "SYN-V0001", CASE, "G30.9", "2026-03-02", "有効"],
    ),
    "処方": (
        [
            "処方番号",
            "症例番号",
            "受診番号",
            "薬剤コード",
            "ATC",
            "薬剤名",
            "処方日",
            "開始日",
            "終了日",
            "用量",
            "単位",
            "状態",
        ],
        [
            "SYN-R0001",
            CASE,
            "SYN-V0001",
            "1190012F1020",
            "N06DA02",
            "合成ドネペジル錠",
            "2026-03-02",
            "2026-03-02",
            "",
            "5",
            "mg",
            "処方中",
        ],
    ),
    "検査": (
        ["検査番号", "症例番号", "検査コード", "検査名", "結果", "単位", "採取日時"],
        ["SYN-L0001", CASE, "3C020000002327101", "尿酸", "5.1", "mg/dL", "2026-03-02 08:45"],
    ),
    "スコア": (
        ["スコア番号", "症例番号", "尺度", "得点", "実施日"],
        ["SYN-S0001", CASE, "MMSE", "24", "2026-03-02"],
    ),
    "所見": (
        ["所見番号", "症例番号", "所見コード", "所見名", "所見内容", "所見日"],
        ["SYN-F0001", CASE, "FIND-HIPPO-ATROPHY", "海馬萎縮", "合成の例: 両側の海馬に軽度の萎縮", "2026-03-02"],
    ),
    "画像レポート": (
        ["レポート番号", "症例番号", "検査コード", "検査名", "検査日", "結論"],
        ["SYN-P0001", CASE, "MRI-HEAD", "頭部MRI", "2026-03-02", "合成の例: 年齢相応の変化"],
    ),
    "記録": (
        ["記録番号", "症例番号", "受診番号", "記録日時", "種別", "本文"],
        ["SYN-N0001", CASE, "SYN-V0001", "2026-03-02 10:00", "経過", "合成の例: 物忘れの相談。経過観察。"],
    ),
}
_FIXED = datetime(2026, 1, 1)


def build() -> bytes:
    """The template workbook's bytes, the same on every run."""
    wb = Workbook()
    wb.remove(wb["Sheet"])
    for name, (header, example) in SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(header)
        ws.append(example)
        for cell in ws[2]:
            cell.number_format = "@"  # text: a spreadsheet keeps 1948-05 and 0012 as typed
        for col in range(1, len(header) + 1):
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = 22
    wb.properties.creator = "TrialBox template"
    wb.properties.created = _FIXED
    wb.properties.modified = _FIXED
    raw = io.BytesIO()
    wb.save(raw)
    out = io.BytesIO()
    with zipfile.ZipFile(raw) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in sorted(zin.infolist(), key=lambda i: i.filename):
            entry = zipfile.ZipInfo(info.filename, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            body = zin.read(info.filename)
            if info.filename == "docProps/core.xml":  # openpyxl stamps the save time: the fixed one instead
                body = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*", rb"\g<1>2026-01-01T00:00:00Z", body)
            zout.writestr(entry, body)
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed template differs")
    args = ap.parse_args(argv)
    data = build()
    if args.check:
        same = TEMPLATE.is_file() and TEMPLATE.read_bytes() == data
        print("template is current" if same else "template differs: run python -m tools.poc_workbook")
        return 0 if same else 1
    tmp = TEMPLATE.with_suffix(".xlsx.tmp")
    with tmp.open("wb") as fh:  # write then rename, flushed
        fh.write(data)
        fh.flush()
        import os

        os.fsync(fh.fileno())
    tmp.replace(TEMPLATE)
    print(f"wrote {TEMPLATE.name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

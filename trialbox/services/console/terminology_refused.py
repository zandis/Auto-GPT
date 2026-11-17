"""E-TERM-3 (D-1048): a site code list that is not read is said where people work, and it stops approval.

The site's own code lists are the primary source (D-1028, D-1113). When one is refused (its file no longer matches its
manifest line, the manifest is damaged, its file is gone), the compile answers from the shipped tables. The compiler
records each refused table in the ruleset's manifest and in the review workbook's ``terminology`` sheet, and refuses
approval while a site list is refused (``criteria_compiler.service.site_list_blocks``). The console says the same in
the page's language: on the approval page (with **Approve all** held) and on the administrator's home, read from the
box's terminology folder now. A refused shipped or licensed table is said too, as a warning only.
"""

from __future__ import annotations

import io
from typing import Any

from criteria_compiler.terminology import installed

from console.i18n import CATALOGUES

EN: dict[str, str] = {
    "term.refused.title": "A code list was not read",
    "term.refused.site": "The site's code list {table} was not read: {reason}",
    "term.refused.other": "The code table {table} was not read: {reason}. The shipped tables answered; this does not "
    "stop approval.",
    "term.refused.approval": "The site's own code lists come first. While one is not read, the criteria were coded "
    "from the shipped tables instead, so they cannot be approved. Ask the box's IT to load the list again, or to "
    "remove it on purpose (the removal is recorded), then compile the protocol again.",
    "term.refused.admin": "No criteria can be approved while this list is not read. Load it again with python -m "
    "tools.terminology_install site-list, or remove it on purpose with python -m tools.terminology_install "
    "remove-site-list (recorded in the audit).",
}
JA: dict[str, str] = {
    "term.refused.title": "読み込めなかったコード表があります",
    "term.refused.site": "施設のコード表 {table} を読み込めませんでした: {reason}",
    "term.refused.other": (
        "コード表 {table} を読み込めませんでした: {reason}。同梱の表で対応しました。承認は止まりません。"
    ),
    "term.refused.approval": (
        "施設のコード表が最優先です。読み込めない間、基準は同梱の表でコード化されたため承認できません。"
        "ボックスの IT 担当者に表の再読み込み、または意図した削除（記録されます）を依頼し、"
        "プロトコルを再度コンパイルしてください。"
    ),
    "term.refused.admin": (
        "この表を読み込めない間、基準は承認できません。"
        "python -m tools.terminology_install site-list で再度読み込むか、"
        "python -m tools.terminology_install remove-site-list で意図して削除してください（監査に記録されます）。"
    ),
}
ZH: dict[str, str] = {
    "term.refused.title": "有代碼表未能讀取",
    "term.refused.site": "院內代碼表 {table} 未能讀取：{reason}",
    "term.refused.other": "代碼表 {table} 未能讀取：{reason}。已改用內建的表；不影響核准。",
    "term.refused.approval": (
        "院內代碼表優先。無法讀取期間，條件改以內建的表編碼，因此不能核准。"
        "請本機的資訊人員重新載入此表，或刻意移除（會留下紀錄），然後重新編譯計畫書。"
    ),
    "term.refused.admin": (
        "此表無法讀取期間，任何條件都不能核准。"
        "請以 python -m tools.terminology_install site-list 重新載入，"
        "或以 python -m tools.terminology_install remove-site-list 刻意移除（記入稽核紀錄）。"
    ),
}
for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)


def from_workbook(data: bytes) -> list[dict[str, Any]]:
    """The review workbook's ``terminology`` sheet: each table the compile could not read, ``{table, reason, site}``."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if "terminology" not in wb.sheetnames:
        return []
    rows = list(wb["terminology"].iter_rows(values_only=True))[1:]
    return [{"table": str(r[0]), "reason": str(r[1] or ""), "site": str(r[0]).startswith(installed.SITE_PREFIX)}
            for r in rows if r and r[0]]  # fmt: skip


def on_box() -> list[dict[str, Any]]:
    """The site lists not read on this box now (its terminology folder; none when the folder is not here)."""
    where = installed.installed_dir()
    if not where.is_dir():
        return []
    try:
        return [{**r, "site": True} for r in installed.refused_site_lists(where)]
    except OSError:
        return []


def for_approval(workbook: bytes) -> list[dict[str, Any]]:
    """What the approval page says: the compile's refusals, and a site list refused on the box since (once each)."""
    out = from_workbook(workbook)
    seen = {r["table"] for r in out}
    return out + [r for r in on_box() if r["table"] not in seen]

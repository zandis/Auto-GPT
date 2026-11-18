"""Strings of T-685 (D-402), the clinical UX polish of the 2026-11-10 deep review (the Lows): the coordinator's
worklist help, access keys of the mark bar, hidden headers of action columns, the date-format hint, the short
pseudonym with the full one to copy, the EDC error's technical details and the name of the REDCap link as an author.
Merged last into ``console.i18n`` (en, ja, zh-TW); every language has every key."""

from __future__ import annotations

EN: dict[str, str] = {
    # UX-035: the coordinator's words on the investigator's worklists
    "wb.list.review.help.coordinator": "Found by screening; the investigator has not decided yet.",
    "wb.list.info.help.coordinator": "The investigator asked you to find something out.",
    "wb.list.approached.help.coordinator": "The investigator approved contact. The state says whether you have "
    "contacted them yet.",
    # UX-026: access keys of the mark bar
    "mark.key": "Access key: {k}",
    # UX-027: header text of action and bar columns, read by screen readers only
    "col.actions": "Actions",
    "col.bar": "Bar",
    # UX-038, UX-039 (D-402): the expected format beside a date field; the western calendar
    "date.fmt": "YYYY-MM-DD",
    # UX-036: the short pseudonym; the full one to copy
    "team.id.full": "Full pseudonym (to copy)",
    # UX-030: the refusal code only under technical details
    "edc.err.details": "Technical details",
    # UX-033: the REDCap link as the author of a registry row
    "who.rc-bridge": "REDCap link",
}

JA: dict[str, str] = {
    "wb.list.review.help.coordinator": "スクリーニングで見つかり、治験医師がまだ判断していない患者。",
    "wb.list.info.help.coordinator": "治験医師から確認を依頼された患者。",
    "wb.list.approached.help.coordinator": "治験医師が声かけを承認した患者。"
    "あなたがもう連絡したかどうかは状態に表示されます。",
    "mark.key": "アクセスキー：{k}",
    "col.actions": "操作",
    "col.bar": "グラフ",
    "date.fmt": "西暦 年-月-日",
    "team.id.full": "仮名 ID の全体（コピー用）",
    "edc.err.details": "技術的な詳細",
    "who.rc-bridge": "REDCap 連携",
}

ZH: dict[str, str] = {
    "wb.list.review.help.coordinator": "篩選找到、主持人尚未決定的病人。",
    "wb.list.info.help.coordinator": "主持人請你查詢資料的病人。",
    "wb.list.approached.help.coordinator": "主持人已核准邀請的病人。你是否已聯絡，請看狀態。",
    "mark.key": "快速鍵：{k}",
    "col.actions": "操作",
    "col.bar": "圖示",
    "date.fmt": "西元 年-月-日",
    "team.id.full": "完整假名代碼（供複製）",
    "edc.err.details": "技術細節",
    "who.rc-bridge": "REDCap 連結",
}

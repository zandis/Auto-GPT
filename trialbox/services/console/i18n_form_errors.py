# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Strings of the field macro and the error summary (9k-6a, D-1376), and the messages of the forms converted to it
(the study's identifiers and its IRB record, ``study_state.html``). Joined into ``console.i18n`` by
``console.form_errors`` when a page module imports it. A message says what to write, in the words of the field's
label and hint, the same at the field and in the summary."""

from __future__ import annotations

EN: dict[str, str] = {
    "fe.summary": "There is a problem",
    "fe.title": "Error: {title}",
    "fe.error": "Error:",
    "fe.required": "required",
    # the study's identifiers (D-386): the form's fields by their input names
    "fe.sid.sponsor": "Write the sponsor on one line, in 120 characters or fewer.",
    "fe.sid.protocol_no": "Write the protocol number as the protocol does: a letter or a digit first, then up to 39 letters, digits, spaces and . _ / ( ) -.",
    "fe.sid.siv_date": "Write the site initiation visit (SIV) date as a real date, year-month-day (2026-10-01).",
    "fe.sid.registry_nct": "Write the ClinicalTrials.gov id as NCT and 8 digits.",
    "fe.sid.registry_jrct": "Write the jRCT id as jRCT and 10 digits, or jRCT, a letter and 9 digits.",
    "fe.sid.registry_umin": "Write the UMIN-CTR id as UMIN and 9 digits.",
    "fe.sid.registry_tw": "Write the Taiwan registry id as the registry shows it: 4 to 40 letters, digits and . / _ -.",
    # the IRB record (D-395)
    "fe.irbt.approval_ref": "Write the IRB approval number of that text as on the approval letter (for example IRB-2026-014): it is required when you tick the box.",
    "fe.irbt.text_version": "Write the version of the approved text: a letter or a digit first, then up to 39 letters, digits, spaces and . _ / ( ) -.",
    "fe.irbt.approved_on": "Write the approval date as a real date, year-month-day, not in the future.",
    "fe.irbt.note": "Write a note on one line, in 200 characters or fewer: it is required to take the record back.",
}

JA: dict[str, str] = {
    "fe.summary": "入力内容に問題があります",
    "fe.title": "エラー：{title}",
    "fe.error": "エラー：",
    "fe.required": "必須",
    "fe.sid.sponsor": "依頼者は 1 行、120 文字以内で入力してください。",
    "fe.sid.protocol_no": "プロトコル番号はプロトコルの記載どおりに入力してください：先頭は英数字、続けて英数字・空白・. _ / ( ) - を 39 文字以内。",
    "fe.sid.siv_date": "スタートアップミーティング（SIV）日は実在する日付を年-月-日（2026-10-01）で入力してください。",
    "fe.sid.registry_nct": "ClinicalTrials.gov 番号は NCT と数字 8 桁で入力してください。",
    "fe.sid.registry_jrct": "jRCT 番号は jRCT と数字 10 桁、または jRCT と英字 1 文字と数字 9 桁で入力してください。",
    "fe.sid.registry_umin": "UMIN-CTR 番号は UMIN と数字 9 桁で入力してください。",
    "fe.sid.registry_tw": "台湾の登録番号は登録サイトの表記どおり、英数字と . / _ - で 4〜40 文字で入力してください。",
    "fe.irbt.approval_ref": "その文書の承認番号を承認通知書のとおりに入力してください（例 IRB-2026-014）：チェックするときは必須です。",
    "fe.irbt.text_version": "承認された文書の版を入力してください：先頭は英数字、続けて英数字・空白・. _ / ( ) - を 39 文字以内。",
    "fe.irbt.approved_on": "承認日は実在する日付を年-月-日で入力してください。未来の日付は入力できません。",
    "fe.irbt.note": "メモは 1 行、200 文字以内で入力してください：記録を取り消すときは必須です。",
}

ZH: dict[str, str] = {
    "fe.summary": "輸入內容有問題",
    "fe.title": "錯誤：{title}",
    "fe.error": "錯誤：",
    "fe.required": "必填",
    "fe.sid.sponsor": "請以一行、120 個字以內填寫試驗委託者。",
    "fe.sid.protocol_no": "請依計畫書的寫法填寫計畫書編號：第一個字為英文字母或數字，其後最多 39 個英數字、空格與 . _ / ( ) -。",
    "fe.sid.siv_date": "請以真實存在的日期、年-月-日（2026-10-01）填寫試驗啟動訪視（SIV）日期。",
    "fe.sid.registry_nct": "請以 NCT 加 8 位數字填寫 ClinicalTrials.gov 編號。",
    "fe.sid.registry_jrct": "請以 jRCT 加 10 位數字，或 jRCT 加 1 個英文字母與 9 位數字填寫 jRCT 編號。",
    "fe.sid.registry_umin": "請以 UMIN 加 9 位數字填寫 UMIN-CTR 編號。",
    "fe.sid.registry_tw": "請依登錄網站的寫法填寫台灣登錄編號：4 到 40 個英數字與 . / _ -。",
    "fe.irbt.approval_ref": "請依核准函填寫該文件之 IRB 核准編號（例如 IRB-2026-014）：勾選時必填。",
    "fe.irbt.text_version": "請填寫核准文件版本：第一個字為英文字母或數字，其後最多 39 個英數字、空格與 . _ / ( ) -。",
    "fe.irbt.approved_on": "請以真實存在的日期、年-月-日填寫核准日期，不可為未來日期。",
    "fe.irbt.note": "請以一行、200 個字以內填寫備註：撤回紀錄時必填。",
}

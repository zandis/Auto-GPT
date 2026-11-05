"""Language of a job's mail and reports (D-100).

The console and the e-mail front door speak English, Japanese and Traditional Chinese; the box's replies used to be
English only. A job's language is the ``lang=`` option when given (the console sets it from the signed-in user's
language), else the site locale. Subjects keep their ASCII kind tokens (``done``, ``failed``) because
:func:`tb_common.subject.is_job_mail` parses them; the headline and the body are in the job's language.
"""

# ruff: noqa: E501

from __future__ import annotations

import re
from typing import Any

LANGS = ("en", "ja", "zh-TW")


def norm_lang(raw: str | None) -> str:
    """``ja``, ``ja-JP``, ``zh``, ``zh-Hant`` ... -> one of :data:`LANGS` (unknown -> ``en``)."""
    v = (raw or "").strip()
    if not v:
        return "en"
    if v in LANGS:
        return v
    low = v.lower()
    if low.startswith("ja"):
        return "ja"
    if low.startswith("zh"):
        return "zh-TW"
    return "en"


def job_lang(options: dict[str, Any] | None, site_locale: str | None) -> str:
    """The job's language: the first ``lang=`` value (CONSENT lists several), else the site locale."""
    raw = str((options or {}).get("lang") or "").split(",")[0].strip()
    return norm_lang(raw) if raw else norm_lang(site_locale)


_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")


def detect_lang(text: str) -> str:
    """Language of a chart from its script: kana -> ja, Han without kana -> zh-TW, else en."""
    sample = text[:4000]
    if _KANA.search(sample):
        return "ja"
    if len(_HAN.findall(sample)) >= 5:
        return "zh-TW"
    return "en"


T: dict[str, dict[str, str]] = {
    "en": {
        "mail.received": "Your request **{title}** was received at {at} and queued as job `{job}`.\n\nResults follow by "
        "email. Reply `STATUS {job}` for progress or `CANCEL {job}` to cancel.",
        "mail.failed": "Job `{job}` (**{title}**) failed.\n\n- Step: **{step}**\n- Reason: {reason}\n\nNothing was sent to "
        "other recipients. Fix the request and send it again, or reply `STATUS {job}` for the job record.",
        "mail.status": "Job `{job}` is **{state}**.",
        "screen.scope1": "Ruleset {rs} v{ver}, run {run}, snapshot {snapshot}.",
        "screen.scope2": "Scope: practitioners {pract}; appointments in the next {window} days or an encounter in the "
        "last 12 months; {scoped} patients evaluated.",
        "screen.judging.none": "Note criteria were not judged (no model on this box): they go to review.",
        "screen.judging.pair": "Note criteria: judged by {judge} and checked by {verifier}; a note answer excludes a "
        "patient only when both models agree.",
        "screen.judging.single": "Note criteria: judged by {judge} alone; note answers could not exclude anyone on this "
        "run ({why}). Patients with a failing note answer are listed for review.",
        "screen.done": "Screening **{rs} v{ver}** finished: {scoped} patients in scope, {high} likely eligible, {review} "
        "to review, {excluded} excluded. The encrypted candidate list went to {to}{referrals}. {judging}",
        "screen.referrals": "; referrals: {items}",
        "screen.headline": "{high} likely eligible, {review} to review",
        "screen.list": "Candidate list for **{rs} v{ver}**: {n} patients ({high} likely eligible, {review} to review). "
        "The workbook is encrypted; the password follows separately. Coordinators also see this list, with the note "
        "quotes, on the job page of the console.",
        "screen.list.headline": "{n} patients",
        "screen.referral": "{n} patients of department {dept} may be eligible for **{rs}**. Please consider a referral to "
        "the study team ({to}).",
        "screen.referral.headline": "{dept}, {n} patients",
        "feas.intro": "Feasibility for **{trial}** (ruleset {rs} v{ver}, snapshot {snapshot}).",
        "feas.enrol": "- Estimated {months}-month enrolment: **{low}–{high}** (most likely {mid})",
        "feas.population": "- Population: {population}: {n}",
        "feas.eligible": "- Eligible on structured criteria (any month-end): {n}",
        "feas.barriers": "- Biggest barriers: {items}",
        "feas.attached": "Attached: feasibility report (PDF), workbook (XLSX) and the machine-readable result (JSON).",
        "feas.headline": "{low}–{high} in {months} mo",
        # PDF labels
        "pdf.feas.title": "Feasibility report — {trial}",
        "pdf.item": "Item",
        "pdf.value": "Value",
        "pdf.trial": "Trial",
        "pdf.trial.value": "{title} (ruleset {rs} v{ver})",
        "pdf.sponsor": "Sponsor",
        "pdf.site": "Site",
        "pdf.run_date": "Run date",
        "pdf.snapshot": "Data snapshot",
        "pdf.population": "Population",
        "pdf.lookback": "Lookback",
        "pdf.lookback.value": "{months} months (month-end index dates)",
        "pdf.contact": "Contact",
        "pdf.answer": "Answer",
        "pdf.answer.text": "Estimated {months}-month enrolment at {site}: <b>{low}–{high}</b> participants (most likely "
        "{mid}; P10–P90 of {iterations} simulations). ",
        "pdf.answer.barriers": "The biggest barriers are {items}.",
        "pdf.and": " and ",
        "pdf.funnel": "Eligibility funnel",
        "pdf.step": "Step",
        "pdf.criterion": "Criterion",
        "pdf.remaining": "Remaining",
        "pdf.dropped": "Dropped",
        "pdf.pct_start": "% of start",
        "pdf.unknown": "Unknown",
        "pdf.not_applied": "{label} (not applied in counts)",
        "pdf.sensitivity": "Sensitivity",
        "pdf.variant": "Variant",
        "pdf.delta": "Δ vs base",
        "pdf.monthly": "New eligible patients per month ({n} months)",
        "pdf.assumptions": "Simulation assumptions",
        "pdf.parameter": "Parameter",
        "pdf.source": "Source",
        "pdf.reach": "Reach rate",
        "pdf.accept": "Accept rate",
        "pdf.capacity": "Investigator capacity",
        "pdf.capacity.unlimited": "not limited",
        "pdf.capacity.value": "{n} per month",
        "pdf.monthly_eligible": "New eligible per month",
        "pdf.monthly_eligible.source": "funnel, last 12 months",
        "pdf.horizon": "Horizon",
        "pdf.horizon.value": "{months} months",
        "pdf.iterations": "Iterations",
        "pdf.iterations.source": "Beta-distributed rates, Poisson arrivals",
        "pdf.result": "Result (P10 / P50 / P90)",
        "pdf.simulation": "simulation",
        "pdf.default": "default",
        "pdf.notes": "Notes",
        "pdf.appendix_a": "Appendix A — criterion definitions",
        "pdf.id": "Id",
        "pdf.protocol_text": "Protocol text",
        "pdf.how": "How computed",
        "pdf.class": "Class",
        "pdf.how.structured": "{logic}. Codes: {codes}",
        "pdf.how.mixed": "Not applied in counts (coded pre-check at screening: {logic}; the notes decide the rest)",
        "pdf.how.note": "Not applied in counts (chart review / note judge)",
        "pdf.how.human": "Not applied in counts (asked at screening)",
        "pdf.fallback": ". Fallback: {text}",
        "pdf.appendix_b": "Appendix B — site capabilities",
        "pdf.capability": "Capability",
        "pdf.available": "Available",
        "pdf.yes": "yes",
        "pdf.no": "no",
        "pdf.screen.title": "Screening summary — {trial}",
        "pdf.screen.tiers": "Candidates by tier",
        "pdf.tier": "Tier",
        "pdf.patients": "Patients",
        "pdf.tier.high": "likely eligible",
        "pdf.tier.review": "to review",
        "pdf.tier.excluded": "excluded",
        "pdf.screen.by_practitioner": "Listed candidates by practitioner",
        "pdf.practitioner": "Practitioner",
        "pdf.screen.open": "Open items among listed candidates",
        "pdf.label": "Label",
        "pdf.to_ask": "To ask",
        "pdf.screen.footer": "Patient lists were sent encrypted to the internal list recipients only.",
        "pdf.screen.footer.cells": " Cells 1–{hi} are shown as '<{t}'.",
    },
    "ja": {
        "mail.received": "リクエスト **{title}** を {at} に受け付け、ジョブ `{job}` として待ち行列に入れました。\n\n結果はメールで届きます。"
        "進行状況は `STATUS {job}`、取り消しは `CANCEL {job}` と返信してください。",
        "mail.failed": "ジョブ `{job}`（**{title}**）は失敗しました。\n\n- 工程: **{step}**\n- 理由: {reason}\n\n他の宛先には何も送られて"
        "いません。リクエストを修正して再送するか、`STATUS {job}` と返信してジョブ記録を確認してください。",
        "mail.status": "ジョブ `{job}` の状態は **{state}** です。",
        "screen.scope1": "ルールセット {rs} v{ver}、実行日 {run}、スナップショット {snapshot}。",
        "screen.scope2": "対象：担当医 {pract}；今後 {window} 日以内の予約、または過去 12 か月の受診がある患者；{scoped} 名を評価。",
        "screen.judging.none": "記録基準は判定していません（この装置にモデルなし）：確認待ちに回します。",
        "screen.judging.pair": "記録基準：{judge} が判定し {verifier} が検証。両モデルが一致したときのみ記録の回答で除外します。",
        "screen.judging.single": "記録基準：{judge} のみが判定。この実行では記録の回答で除外した患者はいません（{why}）。"
        "記録基準に該当しない患者は確認待ちに載せています。",
        "screen.done": "スクリーニング **{rs} v{ver}** が完了：対象 {scoped} 名、適格の可能性が高い {high} 名、確認待ち {review} 名、"
        "除外 {excluded} 名。暗号化した候補者リストは {to} に送付{referrals}。{judging}",
        "screen.referrals": "；紹介：{items}",
        "screen.headline": "適格の可能性が高い {high} 名、確認待ち {review} 名",
        "screen.list": "**{rs} v{ver}** の候補者リスト：{n} 名（適格の可能性が高い {high} 名、確認待ち {review} 名）。ワークブックは"
        "暗号化されており、パスワードは別送します。コーディネーターはコンソールのジョブページでも、記録の引用付きで同じリストを見られます。",
        "screen.list.headline": "{n} 名",
        "screen.referral": "{dept} の患者 {n} 名が **{rs}** に適格な可能性があります。研究チーム（{to}）への紹介をご検討ください。",
        "screen.referral.headline": "{dept}、{n} 名",
        "feas.intro": "**{trial}** のフィージビリティ（ルールセット {rs} v{ver}、スナップショット {snapshot}）。",
        "feas.enrol": "- {months} か月の推定登録数：**{low}–{high}**（最尤 {mid}）",
        "feas.population": "- 母集団：{population}：{n}",
        "feas.eligible": "- 構造化基準で適格（いずれかの月末）：{n}",
        "feas.barriers": "- 最大の障壁：{items}",
        "feas.attached": "添付：フィージビリティ報告書（PDF）、ワークブック（XLSX）、機械可読の結果（JSON）。",
        "feas.headline": "{months} か月で {low}–{high}",
        "pdf.feas.title": "フィージビリティ報告書 — {trial}",
        "pdf.item": "項目",
        "pdf.value": "値",
        "pdf.trial": "試験",
        "pdf.trial.value": "{title}（ルールセット {rs} v{ver}）",
        "pdf.sponsor": "依頼者",
        "pdf.site": "施設",
        "pdf.run_date": "実行日",
        "pdf.snapshot": "データのスナップショット",
        "pdf.population": "母集団",
        "pdf.lookback": "遡及期間",
        "pdf.lookback.value": "{months} か月（月末を基準日）",
        "pdf.contact": "連絡先",
        "pdf.answer": "結論",
        "pdf.answer.text": "{site} における {months} か月の推定登録数：<b>{low}–{high}</b> 名（最尤 {mid}；{iterations} 回シミュレーションの "
        "P10–P90）。",
        "pdf.answer.barriers": "最大の障壁は {items} です。",
        "pdf.and": " と ",
        "pdf.funnel": "適格性の絞り込み",
        "pdf.step": "段階",
        "pdf.criterion": "基準",
        "pdf.remaining": "残り",
        "pdf.dropped": "除外",
        "pdf.pct_start": "開始時比 %",
        "pdf.unknown": "不明",
        "pdf.not_applied": "{label}（件数に未適用）",
        "pdf.sensitivity": "感度分析",
        "pdf.variant": "条件変更",
        "pdf.delta": "基準との差",
        "pdf.monthly": "月ごとの新規適格患者（{n} か月）",
        "pdf.assumptions": "シミュレーションの前提",
        "pdf.parameter": "パラメータ",
        "pdf.source": "出典",
        "pdf.reach": "連絡到達率",
        "pdf.accept": "同意率",
        "pdf.capacity": "治験責任医師の受入能力",
        "pdf.capacity.unlimited": "制限なし",
        "pdf.capacity.value": "月 {n} 名",
        "pdf.monthly_eligible": "月ごとの新規適格",
        "pdf.monthly_eligible.source": "絞り込み、過去 12 か月",
        "pdf.horizon": "期間",
        "pdf.horizon.value": "{months} か月",
        "pdf.iterations": "反復回数",
        "pdf.iterations.source": "ベータ分布の率、ポアソン到着",
        "pdf.result": "結果（P10 / P50 / P90）",
        "pdf.simulation": "シミュレーション",
        "pdf.default": "既定値",
        "pdf.notes": "注記",
        "pdf.appendix_a": "付録 A — 基準の定義",
        "pdf.id": "ID",
        "pdf.protocol_text": "プロトコルの文言",
        "pdf.how": "判定方法",
        "pdf.class": "区分",
        "pdf.how.structured": "{logic}。コード：{codes}",
        "pdf.how.mixed": "件数に未適用（スクリーニング時にコードで事前確認：{logic}；残りは記録で判定）",
        "pdf.how.note": "件数に未適用（カルテ確認／記録判定モデル）",
        "pdf.how.human": "件数に未適用（スクリーニング時に確認）",
        "pdf.fallback": "。代替：{text}",
        "pdf.appendix_b": "付録 B — 施設の体制",
        "pdf.capability": "体制",
        "pdf.available": "有無",
        "pdf.yes": "あり",
        "pdf.no": "なし",
        "pdf.screen.title": "スクリーニング概要 — {trial}",
        "pdf.screen.tiers": "区分別の候補者",
        "pdf.tier": "区分",
        "pdf.patients": "患者数",
        "pdf.tier.high": "適格の可能性が高い",
        "pdf.tier.review": "確認待ち",
        "pdf.tier.excluded": "除外",
        "pdf.screen.by_practitioner": "担当医別のリスト掲載候補者",
        "pdf.practitioner": "担当医",
        "pdf.screen.open": "リスト掲載候補者の未確定事項",
        "pdf.label": "名称",
        "pdf.to_ask": "確認事項",
        "pdf.screen.footer": "患者リストは院内のリスト宛先にのみ暗号化して送付しました。",
        "pdf.screen.footer.cells": " 1–{hi} のセルは「<{t}」と表示します。",
    },
    "zh-TW": {
        "mail.received": "您的請求 **{title}** 已於 {at} 收到，排入工作 `{job}`。\n\n結果將以郵件送達。回覆 `STATUS {job}` 查看進度，"
        "或回覆 `CANCEL {job}` 取消。",
        "mail.failed": "工作 `{job}`（**{title}**）失敗。\n\n- 步驟：**{step}**\n- 原因：{reason}\n\n未寄送任何內容給其他收件人。"
        "請修正請求後重送，或回覆 `STATUS {job}` 查看工作紀錄。",
        "mail.status": "工作 `{job}` 目前為 **{state}**。",
        "screen.scope1": "規則集 {rs} v{ver}，執行日 {run}，快照 {snapshot}。",
        "screen.scope2": "範圍：主治醫師 {pract}；未來 {window} 天內有預約或過去 12 個月內有就診的病人；共評估 {scoped} 位。",
        "screen.judging.none": "病歷條件未經判讀（本機沒有模型）：列為待確認。",
        "screen.judging.pair": "病歷條件：由 {judge} 判讀、{verifier} 驗證；兩個模型一致時病歷判讀才會排除病人。",
        "screen.judging.single": "病歷條件：僅由 {judge} 判讀；本次執行中病歷判讀未排除任何人（{why}）。病歷條件不符的病人列入待確認。",
        "screen.done": "篩選 **{rs} v{ver}** 完成：範圍內 {scoped} 位，{high} 位可能符合、{review} 位待確認、{excluded} 位排除。"
        "加密的候選名單已寄給 {to}{referrals}。{judging}",
        "screen.referrals": "；轉介：{items}",
        "screen.headline": "{high} 位可能符合、{review} 位待確認",
        "screen.list": "**{rs} v{ver}** 的候選名單：{n} 位（{high} 位可能符合、{review} 位待確認）。活頁簿已加密，密碼另寄。協調員也可在"
        "主控台的工作頁面看到同一份名單與病歷引文。",
        "screen.list.headline": "{n} 位",
        "screen.referral": "{dept} 的 {n} 位病人可能符合 **{rs}**。請考慮轉介給研究團隊（{to}）。",
        "screen.referral.headline": "{dept}，{n} 位",
        "feas.intro": "**{trial}** 的可行性（規則集 {rs} v{ver}，快照 {snapshot}）。",
        "feas.enrol": "- 預估 {months} 個月收案：**{low}–{high}**（最可能 {mid}）",
        "feas.population": "- 母體：{population}：{n}",
        "feas.eligible": "- 結構化條件符合（任一月底）：{n}",
        "feas.barriers": "- 最大障礙：{items}",
        "feas.attached": "附件：可行性報告（PDF）、活頁簿（XLSX）與機器可讀結果（JSON）。",
        "feas.headline": "{months} 個月 {low}–{high}",
        "pdf.feas.title": "可行性報告 — {trial}",
        "pdf.item": "項目",
        "pdf.value": "數值",
        "pdf.trial": "試驗",
        "pdf.trial.value": "{title}（規則集 {rs} v{ver}）",
        "pdf.sponsor": "贊助者",
        "pdf.site": "試驗機構",
        "pdf.run_date": "執行日",
        "pdf.snapshot": "資料快照",
        "pdf.population": "母體",
        "pdf.lookback": "回溯期間",
        "pdf.lookback.value": "{months} 個月（以月底為基準日）",
        "pdf.contact": "聯絡人",
        "pdf.answer": "結論",
        "pdf.answer.text": "{site} 預估 {months} 個月收案：<b>{low}–{high}</b> 位（最可能 {mid}；{iterations} 次模擬的 P10–P90）。",
        "pdf.answer.barriers": "最大的障礙是 {items}。",
        "pdf.and": " 與 ",
        "pdf.funnel": "資格篩選漏斗",
        "pdf.step": "步驟",
        "pdf.criterion": "條件",
        "pdf.remaining": "剩餘",
        "pdf.dropped": "篩除",
        "pdf.pct_start": "佔起始 %",
        "pdf.unknown": "不明",
        "pdf.not_applied": "{label}（未納入計數）",
        "pdf.sensitivity": "敏感度分析",
        "pdf.variant": "變化情境",
        "pdf.delta": "相對基準差異",
        "pdf.monthly": "每月新增符合病人（{n} 個月）",
        "pdf.assumptions": "模擬假設",
        "pdf.parameter": "參數",
        "pdf.source": "來源",
        "pdf.reach": "聯絡到達率",
        "pdf.accept": "同意率",
        "pdf.capacity": "試驗主持人收案量",
        "pdf.capacity.unlimited": "不限",
        "pdf.capacity.value": "每月 {n} 位",
        "pdf.monthly_eligible": "每月新增符合",
        "pdf.monthly_eligible.source": "漏斗，過去 12 個月",
        "pdf.horizon": "期間",
        "pdf.horizon.value": "{months} 個月",
        "pdf.iterations": "模擬次數",
        "pdf.iterations.source": "Beta 分布率、Poisson 到達",
        "pdf.result": "結果（P10 / P50 / P90）",
        "pdf.simulation": "模擬",
        "pdf.default": "預設值",
        "pdf.notes": "備註",
        "pdf.appendix_a": "附錄 A — 條件定義",
        "pdf.id": "編號",
        "pdf.protocol_text": "計畫書原文",
        "pdf.how": "判定方式",
        "pdf.class": "類別",
        "pdf.how.structured": "{logic}。代碼：{codes}",
        "pdf.how.mixed": "未納入計數（篩選時以代碼預先檢查：{logic}；其餘由病歷判定）",
        "pdf.how.note": "未納入計數（病歷審閱／病歷判讀模型）",
        "pdf.how.human": "未納入計數（篩選時詢問）",
        "pdf.fallback": "。替代方式：{text}",
        "pdf.appendix_b": "附錄 B — 機構能力",
        "pdf.capability": "能力",
        "pdf.available": "具備",
        "pdf.yes": "是",
        "pdf.no": "否",
        "pdf.screen.title": "篩選摘要 — {trial}",
        "pdf.screen.tiers": "各分級候選人數",
        "pdf.tier": "分級",
        "pdf.patients": "病人數",
        "pdf.tier.high": "可能符合",
        "pdf.tier.review": "待確認",
        "pdf.tier.excluded": "排除",
        "pdf.screen.by_practitioner": "各主治醫師的名單候選人",
        "pdf.practitioner": "主治醫師",
        "pdf.screen.open": "名單候選人的待確認事項",
        "pdf.label": "名稱",
        "pdf.to_ask": "待詢問",
        "pdf.screen.footer": "病人名單僅以加密方式寄給院內名單收件人。",
        "pdf.screen.footer.cells": " 1–{hi} 的格子顯示為「<{t}」。",
    },
}


def t(lang: str, key: str, **values: Any) -> str:
    """The text for ``key`` in ``lang`` (English when the language has no entry), formatted with ``values``."""
    text = T.get(norm_lang(lang), T["en"]).get(key) or T["en"][key]
    return text.format(**values) if values else text

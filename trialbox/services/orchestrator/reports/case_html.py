"""The CASE eligibility sheet (``scenarios/case.py``): one patient, one ruleset, every criterion with its evidence.

Plain HTML with inline CSS, no script and no external request, so it opens from a mail attachment, prints on A4 and
passes the console's sandboxed preview. The fixed wording is written here in each language, never by a model; every
quote and every chart-derived string is escaped. The sheet is PHI (it carries chart text).
"""

from __future__ import annotations

from html import escape
from typing import Any

TITLE = {
    "en": "Eligibility sheet: {ruleset} v{version}",
    "ja": "適格性シート：{ruleset} v{version}",
    "zh-TW": "適格性檢核表：{ruleset} v{version}",
}
NOTICE = {
    "en": "This sheet is a reading aid for the study team. It answers each criterion only from the chart text that "
    "was uploaded and from the hospital data the box holds. “Unknown” means the chart did not say, not that the "
    "patient is ineligible. The investigator decides eligibility.",
    "ja": "このシートは治験チームの確認を助ける資料です。アップロードされたカルテの文章と、"
    "この装置が保有する院内データからのみ各基準に回答しています。「不明」はカルテに記載がなかったことを意味し、"
    "不適格を意味しません。適格性の判断は治験責任医師が行います。",
    "zh-TW": "本表是協助研究團隊閱讀的資料。每項條件只依據上傳的病歷文字與本機保有的院內資料回答。"
    "「不明」表示病歷未提及，不代表不符合條件。是否適格由試驗主持人判斷。",
}
HEADLINE = {
    "en": "{met} met, {not_met} not met, {unknown} unknown, {human} for a human of {total}",
    "ja": "{total}項目中 該当{met} 非該当{not_met} 不明{unknown} 要確認{human}",
    "zh-TW": "共{total}項：符合{met}、不符合{not_met}、不明{unknown}、需人工{human}",
}
VERDICT = {
    "en": {"pass": "met", "fail": "not met", "unknown": "unknown", "pending_human": "needs a human"},
    "ja": {"pass": "該当", "fail": "非該当", "unknown": "不明", "pending_human": "要確認（人）"},
    "zh-TW": {"pass": "符合", "fail": "不符合", "unknown": "不明", "pending_human": "需人工確認"},
}
KIND = {
    "en": {"inclusion": "inclusion", "exclusion": "exclusion"},
    "ja": {"inclusion": "選択基準", "exclusion": "除外基準"},
    "zh-TW": {"inclusion": "納入條件", "exclusion": "排除條件"},
}
SOURCE = {
    "en": {"lake": "hospital data", "chart": "uploaded chart", "human": "study team"},
    "ja": {"lake": "院内データ", "chart": "アップロードしたカルテ", "human": "治験チーム"},
    "zh-TW": {"lake": "院內資料", "chart": "上傳病歷", "human": "研究團隊"},
}
HINT = {
    "en": {
        "structured": "Give the chart number so the box can check the hospital data, or attach the lab or "
        "diagnosis page.",
        "note": "Attach the clinic note or discharge summary that describes this, with its date.",
        "human": "To be asked or checked by the study team at the visit.",
    },
    "ja": {
        "structured": "カルテ番号を指定して院内データを照合するか、検査結果や診断の記載ページを添付してください。",
        "note": "この内容が記載された外来記録または退院サマリー（日付入り）を添付してください。",
        "human": "治験チームが来院時に確認する項目です。",
    },
    "zh-TW": {
        "structured": "提供病歷號以便比對院內資料，或附上檢驗結果或診斷的頁面。",
        "note": "請附上記載此內容的門診紀錄或出院摘要（含日期）。",
        "human": "由研究團隊於訪視時詢問或確認。",
    },
}
COLS = {
    "en": ("Criterion", "Type", "Result", "Evidence (verbatim, dated)", "Source", "What would resolve it"),
    "ja": ("基準", "区分", "結果", "根拠（原文引用・日付）", "出典", "確認に必要なもの"),
    "zh-TW": ("條件", "類型", "結果", "依據（原文引述、日期）", "來源", "如何補足"),
}
META = {
    "en": {
        "date": "Checked on",
        "by": "Requested by",
        "subject": "Patient",
        "pid": "pseudonym {pid}",
        "in_lake": "in the hospital data (snapshot {snapshot}); structured criteria from the database",
        "not_in_lake": "{note}",
        "charts": "Chart files",
        "undated": "{n} of {total} excerpts carry no date in the text and were given the upload date.",
        "judge": "Note criteria judged by {model}{verifier}; {calls} model calls; {disagreements} answers set to "
        "unknown because the two models disagreed.",
        "pair": " with {verifier} as the second model (both must agree)",
        "nojudge": "No language model is configured: note criteria could not be judged.",
        "chart_only": "The chart number was not given or not found, so structured criteria were also answered from the "
        "chart text and should be checked against the record.",
        "footer": "TrialBox · job {job_id} · the chart and this sheet stay on the box and are covered by its retention "
        "rule · recipients: {to}",
    },
    "ja": {
        "date": "確認日",
        "by": "依頼者",
        "subject": "患者",
        "pid": "仮名 {pid}",
        "in_lake": "院内データに存在（スナップショット {snapshot}）；構造化基準はデータベースから判定",
        "not_in_lake": "{note}",
        "charts": "カルテファイル",
        "undated": "{total}件中{n}件の抜粋には本文に日付がなく、アップロード日を付与しました。",
        "judge": "記述基準は {model}{verifier} が判定；モデル呼び出し {calls} 回；"
        "2モデルの不一致により不明とした回答 {disagreements} 件。",
        "pair": "（第2モデル {verifier}、両者一致が必要）",
        "nojudge": "言語モデルが設定されていないため、記述基準は判定できませんでした。",
        "chart_only": "カルテ番号が未指定または未登録のため、構造化基準もカルテの文章から判定しました。"
        "原本との照合が必要です。",
        "footer": "TrialBox · ジョブ {job_id} · カルテと本シートは装置内に保管され、保持規則の対象です · 宛先: {to}",
    },
    "zh-TW": {
        "date": "檢核日期",
        "by": "申請者",
        "subject": "病人",
        "pid": "假名 {pid}",
        "in_lake": "存在於院內資料（快照 {snapshot}）；結構化條件以資料庫判定",
        "not_in_lake": "{note}",
        "charts": "病歷檔案",
        "undated": "{total}段摘錄中有{n}段文字內無日期，已以上傳日期標示。",
        "judge": "病歷文字條件由 {model}{verifier} 判定；模型呼叫 {calls} 次；"
        "因兩模型不一致而列為不明者 {disagreements} 項。",
        "pair": "（第二模型 {verifier}，須兩者一致）",
        "nojudge": "未設定語言模型，病歷文字條件無法判定。",
        "chart_only": "未提供或查無病歷號，結構化條件亦以病歷文字判定，須與原始紀錄核對。",
        "footer": "TrialBox · 工作 {job_id} · 病歷與本表留存於本機並受保存規則約束 · 收件者: {to}",
    },
}
_CSS = """
body{font-family:'Noto Sans TC','Noto Sans JP','Noto Sans','Helvetica Neue',Arial,sans-serif;color:#1c2024;margin:0;
padding:20px;line-height:1.45;font-size:14px}
h1{font-size:22px;margin:0 0 4px}
.notice{border-left:5px solid #0d5c63;background:#eef5f6;padding:10px 12px;margin:12px 0}
.head{font-size:16px;font-weight:600;margin:10px 0}
.meta{color:#4a545e;font-size:13px;margin:0 0 4px}
table{border-collapse:collapse;width:100%;margin-top:12px}
th,td{border:1px solid #d6dadf;padding:6px 8px;vertical-align:top;text-align:left}
th{background:#f2f4f6;font-size:12px}
.v-pass{color:#1f6b31;font-weight:600}.v-fail{color:#9a3326;font-weight:600}.v-unknown{color:#8a6300;font-weight:600}
.v-pending_human{color:#4a545e;font-weight:600}
blockquote{margin:0;padding:0 0 0 8px;border-left:3px solid #c5cbd1;color:#1c2024}
.d{color:#4a545e;font-size:12px}
footer{margin-top:18px;color:#4a545e;font-size:12px;border-top:1px solid #d6dadf;padding-top:8px}
@media print{body{padding:0}}
"""


def _row(r: dict[str, Any], lang: str) -> str:
    verdict = str(r["verdict"])
    ev = ""
    if r.get("quote"):
        ev = f"<blockquote>{escape(str(r['quote']))}</blockquote>"
        if r.get("quote_date"):
            ev += f'<div class="d">{escape(str(r["quote_date"]))}</div>'
    elif r.get("refs"):
        ev = f'<div class="d">{escape(", ".join(str(x) for x in r["refs"]))}</div>'
    if r.get("reason") and verdict in ("unknown",):
        ev += f'<div class="d">{escape(str(r["reason"]))}</div>'
    return (
        f'<tr data-id="{escape(str(r["id"]))}" data-verdict="{escape(verdict)}">'
        f"<td><strong>{escape(str(r['id']))}</strong><br>{escape(str(r['text']))}</td>"
        f"<td>{escape(KIND[lang].get(str(r['kind']), str(r['kind'])))}</td>"
        f'<td class="v-{escape(verdict)}">{escape(VERDICT[lang].get(verdict, verdict))}</td>'
        f"<td>{ev or '–'}</td>"
        f"<td>{escape(SOURCE[lang].get(str(r['source']), str(r['source'])))}</td>"
        f"<td>{escape(str(r.get('resolve') or ''))}</td></tr>"
    )


def sheet(rec: dict[str, Any]) -> bytes:
    lang = str(rec.get("lang") or "en")
    m = META[lang]
    subj = rec["subject"]
    if subj.get("in_lake"):
        subject_line = m["in_lake"].format(snapshot=subj.get("snapshot"))
    else:
        subject_line = m["not_in_lake"].format(note=subj.get("note") or "")
    pid_part = m["pid"].format(pid=subj["pid"]) + " · " if subj.get("pid") else ""
    j = rec["judge"]
    if j.get("model"):
        pair = m["pair"].format(verifier=j["verifier"]) if j.get("verifier") else ""
        judge_line = m["judge"].format(
            model=j["model"], verifier=pair, calls=j.get("calls", 0), disagreements=j.get("disagreements", 0)
        )
    else:
        judge_line = m["nojudge"]
    charts = "; ".join(
        f"{escape(str(c['filename']))} ({c['excerpts']} excerpts, {c['earliest']} – {c['latest']}, sha256 "
        f"{str(c['sha256'])[:12]}…)"
        for c in rec["charts"]
    )
    rows = "".join(_row(r, lang) for r in rec["criteria"])
    head = HEADLINE[lang].format(**rec["counts"])
    parts = [
        f'<!doctype html><html lang="{escape(lang)}"><head><meta charset="utf-8">'
        f"<title>{escape(TITLE[lang].format(ruleset=rec['ruleset'], version=rec['version']))}</title>"
        f"<style>{_CSS}</style></head><body>",
        f"<h1>{escape(TITLE[lang].format(ruleset=rec['ruleset'], version=rec['version']))}</h1>",
        f'<p class="meta">{escape(m["date"])}: {escape(str(rec["index_date"]))} · {escape(m["by"])}: '
        f"{escape(str(rec['requested_by']))}</p>",
        f'<p class="notice" role="note" data-testid="notice"><strong>{escape(NOTICE[lang])}</strong></p>',
        f'<p class="head" data-testid="headline">{escape(head)}</p>',
        f'<p class="meta">{escape(m["subject"])}: {escape(pid_part)}{escape(subject_line)}</p>',
        f'<p class="meta">{escape(m["charts"])}: {charts}</p>',
    ]
    if rec.get("undated_excerpts"):
        parts.append(
            f'<p class="meta">{escape(m["undated"].format(n=rec["undated_excerpts"], total=rec["excerpts"]))}</p>'
        )
    if not subj.get("in_lake"):
        parts.append(f'<p class="meta">{escape(m["chart_only"])}</p>')
    parts.append(f'<p class="meta">{escape(judge_line)}</p>')
    parts.append(
        "<table><thead><tr>" + "".join(f"<th>{escape(c)}</th>" for c in COLS[lang]) + "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    parts.append(
        f"<footer>{escape(m['footer'].format(job_id=rec['job_id'], to=', '.join(rec.get('recipients') or [])))}"
        "</footer></body></html>"
    )
    return "".join(parts).encode("utf-8")


def summary_md(rec: dict[str, Any], to: list[str]) -> str:
    """The requester's mail body: counts only (aggregate), never a quote."""
    c = rec["counts"]
    lang = str(rec.get("lang") or "en")
    lines = [
        f"CASE check for **{rec['ruleset']} v{rec['version']}** on {rec['index_date']}: {HEADLINE[lang].format(**c)}.",
        "",
        f"- chart files: {len(rec['charts'])}; excerpts: {rec['excerpts']}"
        + (f" ({rec['undated_excerpts']} undated, given the upload date)" if rec.get("undated_excerpts") else ""),
        "- structured criteria: "
        + (
            "from the hospital data"
            if rec["subject"].get("in_lake")
            else f"from the chart ({rec['subject'].get('note')})"
        ),
        f"- the eligibility sheet (patient text) went to: {', '.join(to)}",
        "",
        NOTICE["en"],
    ]
    return "\n".join(lines)

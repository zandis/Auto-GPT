"""Consent explainer pages (``scenarios/consent.py``): the patient page per language and the reviewer's sheet.

Plain HTML with inline CSS, no script and no external request, so a page opens from a mail attachment, prints on A4 and
passes the console's sandboxed preview. Every model-written string is escaped. The fixed wording (the "not the consent
form" notice, headings, DRAFT banner) is written here in each language, never by a model.
"""

from __future__ import annotations

from html import escape
from typing import Any

DISCLAIMER = {
    "en": "This guide is a reading aid. It is not the consent form, it is not a signature, and it does not replace "
    "talking with the study team. Only the official consent form counts: if anything here differs from it, the "
    "consent form is correct.",
    "ja": "この説明書は理解を助けるための資料です。同意説明文書そのものではなく、"
    "署名でもなく、治験スタッフとの話し合いの代わりにもなりません。"
    "正式な同意説明文書だけが有効です。内容に違いがある場合は、同意説明文書が正しいものとします。",
    "zh-TW": "本說明是協助閱讀的資料，不是受試者同意書，也不是簽署文件，"
    "不能取代與研究團隊的討論。只有正式的受試者同意書才有效；"
    "若本說明與同意書有任何不同，以同意書為準。",
}
TITLE = {
    "en": "Study {study}: a plain-language guide to the consent form",
    "ja": "治験 {study}：同意説明文書のやさしい説明",
    "zh-TW": "研究 {study}：受試者同意書淺白說明",
}
DRAFT = {
    "en": "DRAFT for the study team's review. Do not give to patients.",
    "ja": "下書き（治験スタッフ確認用）。患者さんに渡さないでください。",
    "zh-TW": "草稿（供研究團隊審閱）。請勿交給病人。",
}
RELEASED = {
    "en": "Reviewed and released by {by} on {at}.",
    "ja": "{by} が確認し、{at} に公開しました。",
    "zh-TW": "已由 {by} 於 {at} 審閱並發布。",
}
QUIZ = {
    "en": ("Check your understanding", "The study team will go through these questions with you."),
    "ja": ("理解の確認", "治験スタッフが一緒にこれらの質問を確認します。"),
    "zh-TW": ("確認您的理解", "研究團隊會和您一起討論這些問題。"),
}
ASK = {
    "en": ("Your questions for the study team", "Write down anything you want to ask before you decide."),
    "ja": ("治験スタッフへの質問", "決める前に聞きたいことを書き留めておきましょう。"),
    "zh-TW": ("想問研究團隊的問題", "在決定之前，請寫下您想詢問的事情。"),
}
SOURCE = {"en": "consent form", "ja": "同意説明文書", "zh-TW": "同意書"}
SECTION_TITLES: dict[str, dict[str, str]] = {
    "purpose": {"en": "Why is this study being done?", "ja": "この治験の目的", "zh-TW": "為什麼要做這項研究？"},
    "procedures": {"en": "What will happen?", "ja": "参加すると何をするか", "zh-TW": "參加後會做什麼？"},
    "duration": {"en": "How long will it take?", "ja": "期間", "zh-TW": "需要多久？"},
    "risks": {"en": "Possible risks and discomforts", "ja": "考えられる危険や不快なこと", "zh-TW": "可能的風險與不適"},
    "benefits": {"en": "Possible benefits", "ja": "考えられる利益", "zh-TW": "可能的好處"},
    "alternatives": {"en": "Other choices", "ja": "ほかの選択肢", "zh-TW": "其他選擇"},
    "obligations": {"en": "What you will need to do", "ja": "参加する方にお願いすること", "zh-TW": "您需要配合的事項"},
    "rights": {"en": "Your choice and your rights", "ja": "参加は自由です", "zh-TW": "您的選擇與權利"},
    "privacy": {"en": "Your information", "ja": "個人情報の保護", "zh-TW": "您的資料保護"},
    "costs": {"en": "Costs, payments and injury", "ja": "費用・謝礼・健康被害", "zh-TW": "費用、補助與傷害補償"},
    "contacts": {"en": "Who to contact", "ja": "連絡先", "zh-TW": "聯絡方式"},
}
SECTION_ORDER = list(SECTION_TITLES)
STATUS_LABEL = {"ok": "verified", "held": "held back", "unverified": "not verified", None: "–"}

_CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","Noto Sans JP",sans-serif;max-width:46rem;
margin:0 auto;padding:1.25rem;line-height:1.65;color:#1b1f24;background:#fff;font-size:17px}
h1{font-size:1.5rem;line-height:1.3;margin:.5rem 0 1rem}h2{font-size:1.15rem;margin:1.6rem 0 .4rem;
border-bottom:2px solid #1d5fb4;padding-bottom:.2rem}
.notice{border:2px solid #1d5fb4;background:#eef4fc;border-radius:8px;padding:.8rem 1rem;margin:1rem 0}
.draft{background:#fff3cd;border:2px dashed #a15c00;color:#5c3500;padding:.6rem 1rem;border-radius:8px;
font-weight:700;margin:.5rem 0}
ul{padding-left:1.2rem}li{margin:.35rem 0}.ref{color:#5b6570;font-size:.8em;white-space:nowrap}
ol.quiz li{margin:.6rem 0}.lines{border-bottom:1px solid #9aa3ad;height:2rem}
footer{margin-top:2rem;color:#5b6570;font-size:.8rem;border-top:1px solid #d0d7de;padding-top:.6rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{border:1px solid #d0d7de;padding:.35rem .45rem;
vertical-align:top;text-align:left}th{background:#f3f5f7}.wide{max-width:none}
.b{display:inline-block;border-radius:4px;padding:0 .35rem;font-size:.75rem;font-weight:700}
.b-ok{background:#dcf2e3;color:#14532d}.b-held{background:#fde2e1;color:#7f1d1d}
.b-unverified{background:#fff3cd;color:#5c3500}.b-removed{background:#e5e7eb;color:#374151}
.muted{color:#5b6570}.q{font-style:italic;color:#374151}.bt{color:#5b6570;font-size:.8rem}
@media print{.draft{border-style:solid}body{font-size:12pt}}
@media (prefers-color-scheme:dark){body{background:#111418;color:#e6e9ed}.notice{background:#14243a}
th{background:#1c2128}.draft{background:#3a2a05;color:#ffd98a}.q{color:#c9d1d9}}
"""


def _text(x: dict[str, Any], lang: str) -> dict[str, Any]:
    t: dict[str, Any] = x["texts"].get(lang) or {}
    return t


def patient(rec: dict[str, Any], lang: str, view: dict[str, Any], release: dict[str, Any] | None) -> bytes:
    """The patient page in ``lang``: DRAFT until a reviewer releases it."""
    study = escape(rec["study"])
    title = TITLE[lang].format(study=rec["study"])
    out = [
        f'<!doctype html><html lang="{"zh-Hant-TW" if lang == "zh-TW" else lang}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>",
    ]
    if release is None:
        out.append(f'<p class="draft" role="note" data-testid="draft">{escape(DRAFT[lang])}</p>')
    out.append(f"<h1>{escape(title)}</h1>")
    out.append(
        f'<p class="notice" role="note" data-testid="disclaimer"><strong>{escape(DISCLAIMER[lang])}</strong></p>'
    )
    by_section: dict[str, list[dict[str, Any]]] = {}
    for it in view["items"]:
        by_section.setdefault(it["section"], []).append(it)
    for sec in SECTION_ORDER:
        rows = by_section.get(sec)
        if not rows:
            continue
        out.append(f"<h2>{escape(SECTION_TITLES[sec][lang])}</h2><ul>")
        for it in rows:
            ref = f' <span class="ref">({escape(SOURCE[lang])} {escape(it["para"])})</span>' if it["para"] else ""
            out.append(f'<li data-id="{escape(it["id"])}">{escape(_text(it, lang).get("text", ""))}{ref}</li>')
        out.append("</ul>")
    if view["questions"]:
        head, help_ = QUIZ[lang]
        out.append(f'<h2>{escape(head)}</h2><p class="muted">{escape(help_)}</p><ol class="quiz">')
        for q in view["questions"]:
            out.append(f'<li data-id="{escape(q["id"])}">{escape(_text(q, lang).get("question", ""))}</li>')
        out.append("</ol>")
    head, help_ = ASK[lang]
    out.append(f'<h2>{escape(head)}</h2><p class="muted">{escape(help_)}</p>')
    out.append('<div class="lines"></div>' * 4)
    stamp = RELEASED[lang].format(by=release["by"], at=release["at"][:10]) if release else DRAFT[lang]
    out.append(
        f"<footer>{escape(stamp)}<br>TrialBox {escape(rec['site'])} · {study} · "
        f"{escape(rec['icf']['filename'])} sha256 {escape(rec['icf']['sha256'][:12])} · "
        f"job {escape(release['job_id'] if release else rec['job_id'])}</footer></body></html>"
    )
    return "\n".join(out).encode("utf-8")


def _badge(status: str | None, removed: bool = False) -> str:
    if removed:
        return '<span class="b b-removed">removed</span>'
    return f'<span class="b b-{escape(status or "unverified")}">{escape(STATUS_LABEL.get(status, str(status)))}</span>'


def _cell(x: dict[str, Any], lang: str, field: str) -> str:
    t = x["texts"].get(lang)
    if t is None:
        return '<td class="muted">–</td>'
    body = t.get(field) if field != "qa" else f"{t.get('question', '')} — {t.get('answer', '')}"
    parts = [f'<div lang="{escape(lang)}">{escape(str(body or ""))}</div>']
    if not x["removed"]:
        parts.append(_badge(t.get("status")))
    if t.get("problem"):
        parts.append(f'<div class="bt">{escape(t["problem"])}</div>')
    if t.get("back_translation") and lang != "en":
        parts.append(f'<div class="bt">↩ {escape(t["back_translation"])}</div>')
    if t.get("long_sentences"):
        parts.append(f'<div class="bt">long sentences: {int(t["long_sentences"])}</div>')
    return f"<td>{''.join(parts)}</td>"


def review(rec: dict[str, Any]) -> bytes:
    """The reviewer's sheet: every statement in every language next to its consent-form quote and check results."""
    from orchestrator.scenarios.consent import counts

    c = counts(rec)
    langs = rec["languages"]
    study = escape(rec["study"])
    verifier = rec["models"].get("verifier")
    out = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>Consent explainer review · {study}</title><style>{_CSS}body{{max-width:80rem}}</style></head><body>",
        f'<p class="draft" role="note">{escape(DRAFT["en"])}</p>',
        f"<h1>Consent explainer review · {study}</h1>",
        f'<p class="notice" role="note"><strong>{escape(DISCLAIMER["en"])}</strong> Releasing it is a check that the '
        "statements match the consent form; it is not an electronic signature and not part of the consent record.</p>",
        "<table><tbody>",
        f"<tr><th>Consent form</th><td>{escape(rec['icf']['filename'])} · sha256 {escape(rec['icf']['sha256'][:16])}"
        f" · {rec['icf']['paragraphs']} paragraphs · language {escape(rec['source_language'])}</td></tr>",
        f"<tr><th>Models</th><td>draft and translation: {escape(str(rec['models']['draft']))}; second-model check: "
        + (escape(str(verifier)) if verifier else "<strong>not configured</strong> (check every statement yourself)")
        + "</td></tr>",
        f'<tr><th>Result</th><td data-testid="counts">{c["items"]} statements, {c["questions"]} questions · '
        f"removed by the grounding check: {c['removed']} · held back: {c['held']} · verified: {c['ok']} · "
        f"not verified: {c['unverified']}</td></tr>",
    ]
    if rec["missing_sections"]:
        out.append(f"<tr><th>Not covered</th><td>{escape(', '.join(rec['missing_sections']))}</td></tr>")
    for issue in rec["issues"]:
        out.append(f"<tr><th>Issue</th><td>{escape(issue)}</td></tr>")
    out.append("</tbody></table>")
    out.append(
        "<h2>How to release</h2><p>Compare each statement with its quote. Then send "
        f"<code>RELEASE {escape(rec['job_id'])}</code> as the subject of a mail to the box, or press "
        "<b>Release</b> on the job page in the console. Add <code>drop=I03,Q2</code> to leave items out, or "
        "<code>keep=I07</code> to include an item the second model held back. Items removed by the grounding check "
        "cannot be kept: fix the wording by running CONSENT again.</p>"
    )
    head = "".join(f'<th scope="col">{escape(lang)}</th>' for lang in langs)
    out.append(
        f'<h2>Statements</h2><table data-testid="items"><thead><tr><th scope="col">Id</th>'
        f'<th scope="col">Section</th>{head}<th scope="col">Consent-form quote</th></tr></thead><tbody>'
    )
    for it in rec["items"]:
        out.append(
            f'<tr id="{escape(it["id"])}"><td>{escape(it["id"])}'
            + ("<br>" + _badge(None, removed=True) if it["removed"] else "")
            + f"</td><td>{escape(it['section'])}</td>"
            + "".join(_cell(it, lang, "text") for lang in langs)
            + f'<td class="q">{escape(it["quote"])}<div class="bt">{escape(it["para"])}'
            + (f" · {escape(it['removed'])}" if it["removed"] else "")
            + "</div></td></tr>"
        )
    out.append("</tbody></table>")
    out.append(
        f'<h2>Teach-back questions</h2><table data-testid="questions"><thead><tr><th scope="col">Id</th>{head}'
        '<th scope="col">Consent-form quote</th></tr></thead><tbody>'
    )
    for q in rec["questions"]:
        out.append(
            f'<tr id="{escape(q["id"])}"><td>{escape(q["id"])}'
            + ("<br>" + _badge(None, removed=True) if q["removed"] else "")
            + "</td>"
            + "".join(_cell(q, lang, "qa") for lang in langs)
            + f'<td class="q">{escape(q["quote"])}<div class="bt">{escape(q["para"])}'
            + (f" · {escape(q['removed'])}" if q["removed"] else "")
            + "</div></td></tr>"
        )
    out.append("</tbody></table>")
    out.append(
        f"<footer>TrialBox {escape(rec['site'])} · {study} · requested by {escape(rec['requested_by'])} · "
        f"{escape(rec['created'])} · job {escape(rec['job_id'])}</footer></body></html>"
    )
    return "\n".join(out).encode("utf-8")

"""The sponsor and CRO dashboard (D-449): one self-contained HTML page from the sites' verified feeds.

The page holds only what the feeds hold (aggregates, rounded at the site). Every feed is shown with its signature state;
an unverified feed is shown only when the caller says so (the sample page), and then marked. Labels in en, ja, zh-TW.
No external script; one Google Fonts stylesheet with system fallbacks.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Trial opportunity board",
        "lede": "Recruiting ClinicalTrials.gov studies, counted against each site's own patients overnight. "
        "Only rounded totals leave the hospital.",
        "trials": "Recruiting trials tracked",
        "ready": "Trials with eligible patients",
        "sites": "Sites reporting",
        "updated": "Last refresh",
        "cond": "Condition",
        "phase": "Phase",
        "site": "Site",
        "min": "Minimum eligible",
        "all": "All",
        "trial": "Trial",
        "eligible": "Eligible now",
        "per_month": "New / month",
        "band": "12-month enrolment",
        "target": "Target",
        "criteria": "Criteria counted",
        "excl": "Top exclusions",
        "none": "No trial matches these filters.",
        "verified": "signed by site",
        "unverified": "not verified",
        "synthetic": "Sample data. Trials are real and recruiting today; patient counts are synthetic.",
        "rounding": "Counts rounded to the nearest {t}; fewer than {t} shown as <{t}. Automatic compile of the "
        "registry criteria, not reviewed by the site.",
        "lang": "Language",
    },
    "ja": {
        "title": "治験機会ボード",
        "lede": "募集中の ClinicalTrials.gov 試験を、各施設の患者データで毎晩集計。"
        "病院の外に出るのは丸めた件数だけです。",
        "trials": "追跡中の募集試験",
        "ready": "適格患者がいる試験",
        "sites": "報告施設",
        "updated": "最終更新",
        "cond": "疾患",
        "phase": "相",
        "site": "施設",
        "min": "適格数の下限",
        "all": "すべて",
        "trial": "試験",
        "eligible": "現在の適格数",
        "per_month": "月あたり新規",
        "band": "12か月の登録見込み",
        "target": "目標症例数",
        "criteria": "集計できた基準",
        "excl": "主な除外理由",
        "none": "条件に合う試験はありません。",
        "verified": "施設署名あり",
        "unverified": "未検証",
        "synthetic": "サンプルデータ。試験は本日募集中の実在試験、患者数は合成データです。",
        "rounding": "件数は {t} 単位で丸め、{t} 未満は <{t} と表示。"
        "登録情報の基準を自動変換したもので、施設の確認前です。",
        "lang": "言語",
    },
    "zh-TW": {
        "title": "臨床試驗機會看板",
        "lede": "每晚以各院自己的病人資料，計算 ClinicalTrials.gov 上正在收案的試驗。只有四捨五入後的總數會離開醫院。",
        "trials": "追蹤中的收案試驗",
        "ready": "有合格病人的試驗",
        "sites": "回報院所",
        "updated": "最近更新",
        "cond": "疾病",
        "phase": "期別",
        "site": "院所",
        "min": "最少合格人數",
        "all": "全部",
        "trial": "試驗",
        "eligible": "目前合格",
        "per_month": "每月新增",
        "band": "12 個月收案預估",
        "target": "目標人數",
        "criteria": "可計算條件",
        "excl": "主要排除條件",
        "none": "沒有符合篩選的試驗。",
        "verified": "院所已簽章",
        "unverified": "未驗證",
        "synthetic": "範例資料。試驗為今日實際收案中的試驗；病人數為合成資料。",
        "rounding": "人數以 {t} 為單位四捨五入，少於 {t} 顯示為 <{t}。條件由登錄資料自動轉換，院所尚未審閱。",
        "lang": "語言",
    },
}

_CSS = (_HERE / "dashboard.css").read_text(encoding="utf-8")

_JS = (_HERE / "dashboard.js").read_text(encoding="utf-8")


def _rows(feeds: Sequence[tuple[Mapping[str, Any], bool]]) -> list[dict[str, Any]]:
    out = []
    for feed, _ok in feeds:
        for r in feed.get("rows") or []:
            out.append({**r, "site": feed.get("site_label") or feed.get("site_id")})
    return out


def render(feeds: Sequence[tuple[Mapping[str, Any], bool]], *, lang: str = "en", standalone: bool = True) -> str:
    """The page for ``feeds``, each with whether its signature verified. ``standalone=False`` leaves out the doctype
    and ``<html>`` wrapper (for a host that adds its own)."""
    if lang not in LABELS:
        raise ValueError(f"unknown language {lang!r}")
    threshold = max((int(f.get("threshold") or 10) for f, _ in feeds), default=10)
    synthetic = any(bool(f.get("synthetic")) for f, _ in feeds)
    updated = max((str(f.get("generated_at") or "") for f, _ in feeds), default="")[:16].replace("T", " ")
    data = {
        "lang": lang,
        "labels": LABELS,
        "threshold": threshold,
        "updated": updated + (" UTC" if updated else ""),
        "feeds": [{"site": f.get("site_label") or f.get("site_id"), "verified": ok} for f, ok in feeds],
        "rows": _rows(feeds),
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    lab = LABELS[lang]
    e = html.escape
    filters = "".join(
        f'<label for="f-{k}"><span data-l="{lbl}">{e(lab[lbl])}</span><select id="f-{k}"></select></label>'
        for k, lbl in (("cond", "cond"), ("phase", "phase"), ("site", "site"))
    )
    heads = "".join(
        f'<th data-l="{k}">{e(lab[k])}</th>'
        for k in ("trial", "site", "eligible", "per_month", "band", "target", "criteria", "excl")
    )
    tiles = "".join(
        f'<div class="tile"><span data-l="{k}">{e(lab[k])}</span>'
        f'<b id="k-{k}"{' class="date"' if k == "updated" else ""}>–</b></div>'
        for k in ("trials", "ready", "sites", "updated")
    )
    body = f"""<title>Trial Opportunity Board</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{_CSS}</style>
<div class="wrap">
<header><div><h1 data-l="title">{e(lab["title"])}</h1><p class="lede" data-l="lede">{e(lab["lede"])}</p></div>
<label for="f-lang" class="sub"><span data-l="lang">{e(lab["lang"])}</span>
<select id="f-lang"><option value="en">English</option><option value="ja">日本語</option>
<option value="zh-TW">繁體中文</option></select></label></header>
{'<div class="banner" data-l="synthetic">' + e(lab["synthetic"]) + "</div>" if synthetic else ""}
<div class="tiles">{tiles}</div>
<div class="sites" id="sites"></div>
<div class="filters">{filters}<label for="f-min"><span data-l="min">{e(lab["min"])}</span>
<input id="f-min" type="number" min="0" step="10" value="0"></label></div>
<div class="scroller"><table><thead><tr>{heads}</tr></thead><tbody id="tbody"></tbody></table></div>
<p class="foot" id="foot"></p>
</div>
<script type="application/json" id="tb-data">{blob}</script>
<script>{_JS}</script>
"""
    if not standalone:
        return body
    return (
        f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"</head><body>\n{body}</body></html>\n"
    )

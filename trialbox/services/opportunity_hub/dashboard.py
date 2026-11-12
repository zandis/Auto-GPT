"""The sponsor and CRO dashboard (D-467): one self-contained HTML page from the sites' feeds.

Every feed is checked against the feed schema (:func:`tb_common.opportunity.validate`) before anything of it reaches
the page; a feed that fails is refused, whatever its signature. Each feed is shown with its state from
:func:`tb_common.opportunity.status` (verified against the site key register, out of date, or not verified). The
page's script escapes every value it inserts. Labels in en, ja, zh-TW. No external script; one Google Fonts
stylesheet with system fallbacks.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tb_common import opportunity as opp

_HERE = Path(__file__).resolve().parent

STATES = (opp.VERIFIED, opp.OUT_OF_DATE, opp.UNVERIFIED)

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Trial opportunity board",
        "lede": "Recruiting ClinicalTrials.gov studies, counted against each site's own patients once a period. "
        "Only rounded totals leave the hospital.",
        "trials": "Recruiting trials listed",
        "ready": "Trials with counts",
        "sites": "Sites reporting",
        "updated": "Period",
        "cond": "Condition",
        "phase": "Phase",
        "site": "Site",
        "min": "Minimum count",
        "all": "All",
        "trial": "Trial",
        "eligible": "May meet the criteria",
        "per_month": "New / month",
        "band": "12-month enrolment",
        "target": "Target",
        "criteria": "Criteria counted",
        "excl": "Criteria not matched most often",
        "none": "No trial matches these filters.",
        "verified": "signed by site (registered key)",
        "out_of_date": "signed, period over: out of date",
        "unverified": "NOT VERIFIED",
        "unverified_banner": "Test page: it shows feeds that were not verified against the site key register.",
        "withheld": "trials not listed (fewer than {t})",
        "w.none": "none",
        "w.some": "some",
        "r.not_compiled": "registry criteria could not be compiled",
        "r.no_countable_criteria": "no criterion could be counted",
        "r.count_failed": "not counted this period",
        "synthetic": "Sample data. The trials are synthetic registry records; patient counts are synthetic.",
        "rounding": "Counts rounded to the nearest {t}; trials with fewer than {t} are not listed. Rates and bands "
        "come from rounded counts only. Automatic compile of the registry criteria, not reviewed by the site.",
        "lang": "Language",
    },
    "ja": {
        "title": "治験機会ボード",
        "lede": "募集中の ClinicalTrials.gov 試験を、各施設の患者データで期間ごとに集計。"
        "病院の外に出るのは丸めた件数だけです。",
        "trials": "掲載中の募集試験",
        "ready": "件数のある試験",
        "sites": "報告施設",
        "updated": "期間",
        "cond": "疾患",
        "phase": "相",
        "site": "施設",
        "min": "件数の下限",
        "all": "すべて",
        "trial": "試験",
        "eligible": "条件に合う可能性",
        "per_month": "月あたり新規",
        "band": "12か月の登録見込み",
        "target": "目標症例数",
        "criteria": "集計できた基準",
        "excl": "合致しないことが多い基準",
        "none": "条件に合う試験はありません。",
        "verified": "施設署名あり（登録済みの鍵）",
        "out_of_date": "署名あり・期間終了（古いデータ）",
        "unverified": "未検証",
        "unverified_banner": "テスト用ページ：施設鍵の登録簿で検証されていないフィードを含みます。",
        "withheld": "掲載しない試験（{t} 未満）",
        "w.none": "なし",
        "w.some": "あり",
        "r.not_compiled": "登録情報の基準を変換できませんでした",
        "r.no_countable_criteria": "集計できる基準がありません",
        "r.count_failed": "今期は集計していません",
        "synthetic": "サンプルデータ。試験は合成の登録情報、患者数は合成データです。",
        "rounding": "件数は {t} 単位で丸め、{t} 未満の試験は掲載しません。率と見込みは丸めた件数だけから算出。"
        "登録情報の基準を自動変換したもので、施設の確認前です。",
        "lang": "言語",
    },
    "zh-TW": {
        "title": "臨床試驗機會看板",
        "lede": "每期以各院自己的病人資料，計算 ClinicalTrials.gov 上正在收案的試驗。只有四捨五入後的總數會離開醫院。",
        "trials": "列出的收案試驗",
        "ready": "有人數的試驗",
        "sites": "回報院所",
        "updated": "期間",
        "cond": "疾病",
        "phase": "期別",
        "site": "院所",
        "min": "最少人數",
        "all": "全部",
        "trial": "試驗",
        "eligible": "可能符合條件",
        "per_month": "每月新增",
        "band": "12 個月收案預估",
        "target": "目標人數",
        "criteria": "可計算條件",
        "excl": "最常未符合的條件",
        "none": "沒有符合篩選的試驗。",
        "verified": "院所已簽章（已登錄金鑰）",
        "out_of_date": "已簽章・期間已過（資料過期）",
        "unverified": "未驗證",
        "unverified_banner": "測試頁：含有未經院所金鑰登錄簿驗證的資料。",
        "withheld": "未列出的試驗（少於 {t}）",
        "w.none": "無",
        "w.some": "有",
        "r.not_compiled": "登錄條件無法轉換",
        "r.no_countable_criteria": "沒有可計算的條件",
        "r.count_failed": "本期未計算",
        "synthetic": "範例資料。試驗為合成的登錄資料；病人數為合成資料。",
        "rounding": "人數以 {t} 為單位四捨五入，少於 {t} 的試驗不列出。比率與預估只由四捨五入後的人數計算。"
        "條件由登錄資料自動轉換，院所尚未審閱。",
        "lang": "語言",
    },
}

_CSS = (_HERE / "dashboard.css").read_text(encoding="utf-8")

_JS = (_HERE / "dashboard.js").read_text(encoding="utf-8")


def _rows(feeds: Sequence[tuple[Mapping[str, Any], str]]) -> list[dict[str, Any]]:
    out = []
    for feed, _state in feeds:
        for r in feed["rows"]:
            out.append({**r, "site": feed["site_label"]})
    return out


def render(feeds: Sequence[tuple[Mapping[str, Any], str]], *, lang: str = "en", standalone: bool = True) -> str:
    """The page for ``feeds``, each with its state (:data:`STATES`). Every feed must pass the schema first
    (:class:`tb_common.opportunity.FeedRefused` otherwise). ``standalone=False`` leaves out the doctype and
    ``<html>`` wrapper (for a host that adds its own)."""
    if lang not in LABELS:
        raise ValueError(f"unknown language {lang!r}")
    for feed, state in feeds:
        opp.validate(feed)
        if state not in STATES:
            raise ValueError(f"unknown feed state {state!r}")
    threshold = max((int(f["threshold"]) for f, _ in feeds), default=opp.DEFAULT_THRESHOLD)
    synthetic = any(bool(f["synthetic"]) for f, _ in feeds)
    unverified = any(s == opp.UNVERIFIED for _, s in feeds)
    data = {
        "lang": lang,
        "labels": LABELS,
        "threshold": threshold,
        "feeds": [
            {"site": f["site_label"], "state": s, "period": f["period"], "withheld": f["withheld_rows"]}
            for f, s in feeds
        ],
        "rows": _rows(feeds),
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
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
    banners = ""
    if unverified:
        banners += '<div class="banner bad" data-l="unverified_banner">' + e(lab["unverified_banner"]) + "</div>"
    if synthetic:
        banners += '<div class="banner" data-l="synthetic">' + e(lab["synthetic"]) + "</div>"
    body = f"""<title>Trial Opportunity Board</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{_CSS}</style>
<div class="wrap">
<header><div><h1 data-l="title">{e(lab["title"])}</h1><p class="lede" data-l="lede">{e(lab["lede"])}</p></div>
<label for="f-lang" class="sub"><span data-l="lang">{e(lab["lang"])}</span>
<select id="f-lang"><option value="en">English</option><option value="ja">日本語</option>
<option value="zh-TW">繁體中文</option></select></label></header>
{banners}
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

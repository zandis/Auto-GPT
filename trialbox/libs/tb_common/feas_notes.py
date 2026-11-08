"""The feasibility notes as catalogue keys (TB-PLAN-03 step 4, D-119).

``FeasibilityResult.notes`` stays the English record (the contract, the XLSX, the audit); ``note_keys`` carries the
same lines as ``{key, args}`` so the console and the PDF say them in the reader's language. Before D-119 a Japanese
page showed the English sentences (Fable review 2026-11-08, finding 6).
"""

from __future__ import annotations

from typing import Any

NOTES: dict[str, dict[str, str]] = {
    "feas.note.cells": {
        "en": "Counts are distinct patients eligible at one or more of {n} month-ends ({first} … {last}); cells 1–{t1} "
        "are shown as '<{t}' and all other counts are rounded to the nearest {t}, so that no small cell can be "
        "derived from the others.",
        "ja": "件数は {n} 回の月末（{first} … {last}）のうち1回以上で適格だった患者の実人数です。1〜{t1} の件数は"
        "「<{t}」と表示し、その他の件数は {t} 単位に丸めています（小さな件数を他の値から逆算できないようにするため）。",
        "zh-TW": "計數為 {n} 個月底（{first} … {last}）中至少一次符合條件的不重複病人數；1–{t1} 顯示為「<{t}」，"
        "其他計數皆四捨五入至 {t} 的倍數，避免由其他數字推算出小計數。",
    },
    "feas.note.unknown": {
        "en": "Unknown inclusion values (no data in the window) do not count as eligible; unknown exclusions do not "
        "exclude (variant '{variant}' counts unknown inclusions as met).",
        "ja": "期間内に値のない選択基準は「適格」に数えません。値のない除外基準では除外しません"
        "（「{variant}」の試算では値のない選択基準を満たすものとして数えます）。",
        "zh-TW": "期間內無數值的納入條件不算符合；無數值的排除條件不排除"
        "（「{variant}」試算將無數值的納入條件視為符合）。",
    },
    "feas.note.latest": {
        "en": "Eligible at the latest month-end: {n}; mean new eligible per month (last 12 months): {lam}.",
        "ja": "直近の月末時点の適格者：{n}。1か月あたりの新規適格者の平均（直近12か月）：{lam}。",
        "zh-TW": "最近月底符合條件：{n}；每月新增符合條件平均（近12個月）：{lam}。",
    },
    "feas.note.washout": {
        "en": "Monthly new-eligible counts use a {m}-month wash-out at the start of the lookback.",
        "ja": "月ごとの新規適格者数は、調査期間の最初の {m} か月をウォッシュアウト期間として除いています。",
        "zh-TW": "每月新增符合條件數在回溯期開頭使用 {m} 個月的清除期。",
    },
    "feas.note.dropped": {
        "en": "{id}: {n} patients dropped with no value at any month-end.",
        "ja": "{id}：どの月末にも値がなく、{n} 人を除いています。",
        "zh-TW": "{id}：{n} 位病人在所有月底皆無數值而未計入。",
    },
    "feas.note.kept": {
        "en": "{id}: {n} patients not excluded only because no value was recorded.",
        "ja": "{id}：値の記録がないため除外していない患者が {n} 人います。",
        "zh-TW": "{id}：{n} 位病人僅因無紀錄數值而未被排除。",
    },
    "feas.note.not_applied": {
        "en": "Not applied in counts (note/human criteria, checked at screening): {ids}.",
        "ja": "集計に使っていない基準（記録の文章・担当者が判断する基準。スクリーニング時に確認）：{ids}。",
        "zh-TW": "未用於計數的條件（依病歷文字或由人員判斷，於篩選時確認）：{ids}。",
    },
}


def render(key: str, args: dict[str, Any] | None = None, lang: str = "en") -> str:
    by = NOTES.get(key)
    if by is None:
        return ""
    text = by.get(lang) or by.get(lang.split("-", maxsplit=1)[0]) or by["en"]
    try:
        return text.format(**{k: v for k, v in (args or {}).items()})
    except (KeyError, IndexError, ValueError):
        return by["en"].format_map({k: v for k, v in (args or {}).items()}) if lang == "en" else ""


def notes_for(result: Any, lang: str = "en") -> list[str]:
    """The result's notes in ``lang``: from ``note_keys`` when it has them, else the English ``notes`` (an older
    result) for English and nothing for another language."""
    keys = getattr(result, "note_keys", None)
    if keys is None and isinstance(result, dict):
        keys = result.get("note_keys")
    if keys:
        out = []
        for k in keys:
            key = k.get("key") if isinstance(k, dict) else k.key
            args = k.get("args") if isinstance(k, dict) else k.args
            line = render(str(key or ""), args or {}, lang)
            if line:
                out.append(line)
        return out
    notes = getattr(result, "notes", None) if not isinstance(result, dict) else result.get("notes")
    return list(notes or []) if lang == "en" else []


__all__ = ["NOTES", "notes_for", "render"]

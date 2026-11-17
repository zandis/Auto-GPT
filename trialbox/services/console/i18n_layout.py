"""Strings of T-684 (D-361), the clinical layout fixes: the second skip link, the folded study procedure and the
one-line serious-AE banners of the week page. Merged last into
``console.i18n`` (en, ja, zh-TW); every language has every key."""

from __future__ import annotations

EN: dict[str, str] = {
    "skip.worklist": "Skip to the patient list",
    "steps.fold": "Step {n} of {of}: {name}",
    "fold.show": "show",
}

JA: dict[str, str] = {
    "skip.worklist": "患者リストへスキップ",
    "steps.fold": "手順 {n}/{of}：{name}",
    "fold.show": "表示",
}

ZH: dict[str, str] = {
    "skip.worklist": "跳到病人清單",
    "steps.fold": "步驟 {n}/{of}：{name}",
    "fold.show": "顯示",
}

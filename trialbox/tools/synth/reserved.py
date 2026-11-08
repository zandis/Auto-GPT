"""Identifiers the synthetic hospital must never produce (TB-DS-21 §6): real service numbers, issued insurer-number
prefixes and the names of well-known real people. Checked by ``tools.synth_hospital``; in gold mode the generator
redraws a name that matches."""

from __future__ import annotations

import re

RESERVED: dict[str, list[str]] = {
    "phone": [r"^(110|112|113|118|119|165|911|999|0800\d*|0120\d*|0570\d*)$"],
    "insurer": [r"^(01|02|03|04|06|07|31|32|33|34|63|67|72|73|74|75)\d{6}$"],  # issued 法別番号 + 6 digits
    "name": [
        r"^(安倍|岸田|石破|菅)　?(晋三|文雄|茂|義偉)$",
        r"^(賴清德|蔡英文|馬英九|陳水扁|李登輝|柯文哲|侯友宜)$",
        r"^(Boris Johnson|Keir Starmer|Rishi Sunak|Theresa May)$",
    ],
}
_COMPILED = {k: [re.compile(p) for p in v] for k, v in RESERVED.items()}


def is_reserved(kind: str, value: str) -> bool:
    return any(p.search(value) for p in _COMPILED.get(kind, []))

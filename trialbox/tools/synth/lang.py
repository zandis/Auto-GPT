"""Note language adapter for the synthetic hospital (TB-DS-21 §5): one interface over the zh-TW, JA and EN templates.

The zh-TW adapter with ``alt_dates=False`` returns exactly what ``tools.synth.notes`` returns, so the default
generator path (and the committed fixtures) is unchanged. ``alt_dates=True`` writes 10 % of note dates in the local
alternative form: 和暦 (令和/平成) in Japanese, the ROC year (民國) in zh-TW. Alternative-form draws use their own RNG
so they never shift the main stream.
"""

from __future__ import annotations

import random
from datetime import date
from types import ModuleType

from tools.synth import notes as ZH
from tools.synth import notes_en as EN
from tools.synth import notes_ja as JA

LANGS = ("zh-TW", "ja", "en")
ALT_DATE_RATE = 0.10
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def wareki(d: date) -> str:
    """Japanese era date, e.g. 令和8年3月5日 (元年 for the first year)."""
    if d >= date(2019, 5, 1):
        era, y = "令和", d.year - 2018
    elif d >= date(1989, 1, 8):
        era, y = "平成", d.year - 1988
    else:
        era, y = "昭和", d.year - 1925
    return f"{era}{'元' if y == 1 else y}年{d.month}月{d.day}日"


def roc_year(d: date) -> str:
    return f"民國{d.year - 1911}年{d.month}月{d.day}日"


class Lang:
    def __init__(self, code: str, alt_dates: bool = False, rng: random.Random | None = None) -> None:
        if code not in LANGS:
            raise ValueError(f"unknown note language {code!r}")
        self.code = code
        self.mod: ModuleType = {"zh-TW": ZH, "ja": JA, "en": EN}[code]
        self.alt_dates = alt_dates
        self.rng = rng or random.Random(0)
        self.stop = ". " if code == "en" else "。"
        self.JOINTS: list[str] = self.mod.JOINTS
        self.NEEDLES: list[tuple[str, str]] = self.mod.NEEDLES
        self.ECOG = str(self.mod.ECOG_SENTENCE)
        self.CXR_CLEAR = str(self.mod.CXR_CLEAR)
        self.LUNG_MASS = str(self.mod.LUNG_MASS)

    # dates -------------------------------------------------------------------------------------------------------
    def fmt_date(self, d: date) -> str:
        alt = self.alt_dates and self.rng.random() < ALT_DATE_RATE
        if self.code == "ja":
            return wareki(d) if alt else f"{d.year}年{d.month}月{d.day}日"
        if self.code == "zh-TW":
            return roc_year(d) if alt else ZH.roc(d)
        return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"

    # filler: same draw shape in every language (20 sentences, rng.sample) --------------------------------------
    def filler(self, rng: random.Random, n: int) -> str:
        pool: list[str] = self.mod.FILLER
        return "".join(rng.sample(pool, k=min(n, len(pool))))

    # finding sentences -------------------------------------------------------------------------------------------
    def flare(self, d: date, joint: str) -> str:
        if self.code == "zh-TW":
            return ZH.flare_sentence(d, joint, self.fmt_date(d) if self.alt_dates else None)
        return str(self.mod.flare_sentence(self.fmt_date(d), joint))

    def single_flare(self, d: date) -> str:
        if self.code == "zh-TW":
            return ZH.single_flare_sentence(d, self.fmt_date(d) if self.alt_dates else None)
        return str(self.mod.single_flare_sentence(self.fmt_date(d)))

    def no_flare(self) -> str:
        return str(self.mod.no_flare_sentence())

    def current_flare(self) -> str:
        return str(self.mod.current_flare_sentence())

    def no_current_flare(self) -> str:
        return str(self.mod.no_current_flare_sentence())

    def ra_assessment(self, tjc: int, sjc: int, ptga: int) -> str:
        return str(self.mod.ra_assessment_sentence(tjc, sjc, ptga))

    def response(self, delta: float, good: bool) -> str:
        return str(self.mod.response_sentence(delta, good))

    def injection(self, willing: bool) -> str:
        return str(self.mod.injection_willing_sentence(willing))


# PHI sentence templates per language: (template, phi types in order). ``{x}`` marks a span; the generator fills
# and records each span (TB-DS-21 §5 "written into notes the way they appear in real text").
PHI_TEMPLATES: dict[str, dict[str, str]] = {
    "zh-TW": {
        "name": "記錄者：{name}醫師。",
        "family": "家屬{name}來電詢問病情。",
        "date": "記錄日期：{date}。",
        "chart": "病歷號{chart}。",
        "phone": "聯絡電話{phone}。",
        "address": "住址：{address}。",
        "insurer": "健保卡號{insurer}。",
        "hospital": "由{hospital}轉介。",
    },
    "ja": {
        "name": "記載医：{name}。",
        "family": "家族の{name}さんより電話あり。",
        "date": "記載日：{date}。",
        "chart": "カルテ番号{chart}。",
        "phone": "連絡先{phone}。",
        "address": "住所：{address}。",
        "insurer": "保険者番号{insurer}。",
        "hospital": "{hospital}より紹介。",
    },
    "en": {
        "name": "Seen by Dr {name}. ",
        "family": "Daughter {name} phoned about the results. ",
        "date": "Dictated {date}. ",
        "chart": "Chart no. {chart}. ",
        "phone": "Contact {phone}. ",
        "address": "Address: {address}. ",
        "insurer": "Insurance no. {insurer}. ",
        "hospital": "Referred by {hospital}. ",
    },
}

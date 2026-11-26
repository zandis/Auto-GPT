"""MATCH-ARCH section 6, item 2: the metrics of ``note_prep``, proved on notes whose answer is known by construction.

A generator builds notes in English, Japanese and Chinese from phrase banks. Each sentence's span, section, cues, dates
and numbers are known from how it was built, never read back from ``note_prep``. The bars are the item's:

* sentence / section F1 >= 0.95 (a segment is right when start, end and section all match);
* cue precision >= 0.95, with near-miss phrases in the mix (``no longer``, ``non-small cell``, ``未満``, ``無法``,
  ``排除標準``) and neutral words that hold a cue's letters (``Parkinson``, ``nocturia``, ``母集団``);
* the date interval contains the day written >= 0.95 (a full date must be that day exactly), relative dates included;
* wareki: every era, every form, the era's first and last day, the impossible dates: 100 %.

The gold is synthetic and the phrase banks are ours, so the figures say the tables and splitter do what they were
written to do on this kind of text; they are not a measure on a hospital's notes (set D and the CGMH night are).
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from adapter.note_prep import prepare
from tb_common.dates import ERAS

pytestmark = pytest.mark.nodb

NEG, FAM, OTHER = ("negation", "absent"), ("experiencer", "family"), ("experiencer", "other")
HIST, PLAN, HYP, UNC = ("temporality", "historical"), ("temporality", "planned"), ("temporality", "hypothetical"), (
    "uncertainty",
    "uncertain",
)  # fmt: skip

# language -> (header text, section) ; the header forms the tables know
HEADERS = {
    "en": [("Chief complaint:", "chief_complaint"), ("CC:", "chief_complaint"), ("PMH:", "history"),
           ("History of present illness:", "history"), ("Medications:", "medication"), ("Meds:", "medication"),
           ("Family history:", "family_history"), ("Allergies:", "allergy"), ("Assessment/Plan:", "assessment_plan"),
           ("A/P:", "assessment_plan"), ("Physical exam:", "other"), ("Social history:", "other")],
    "ja": [("【主訴】", "chief_complaint"), ("主訴:", "chief_complaint"), ("既往歴：", "history"),
           ("【現病歴】", "history"), ("内服薬:", "medication"), ("【家族歴】", "family_history"),
           ("アレルギー:", "allergy"), ("評価・計画:", "assessment_plan"), ("身体所見:", "other")],
    "zh": [("主訴：", "chief_complaint"), ("病史：", "history"), ("用藥：", "medication"), ("家族史：", "family_history"),
           ("過敏史：", "allergy"), ("診斷與處置：", "assessment_plan"), ("理學檢查：", "other")],
}  # fmt: skip
SYM = {"en": ["cough", "fever", "chest pain", "nausea", "dizziness", "headache", "nocturia"],
       "ja": ["咳", "発熱", "胸痛", "嘔気", "めまい", "頭痛"],
       "zh": ["咳嗽", "發燒", "胸痛", "噁心", "頭暈", "頭痛"]}  # fmt: skip
DX = {"en": ["hypertension", "diabetes", "Parkinson disease", "asthma", "nonspecific colitis"],
      "ja": ["糖尿病", "高血圧", "気管支喘息", "狭心症"],
      "zh": ["高血壓", "糖尿病", "氣喘", "心絞痛"]}  # fmt: skip
DRUG = {
    "en": ["aspirin", "metformin", "noradrenaline"],
    "ja": ["アスピリン", "メトホルミン"],
    "zh": ["阿斯匹靈", "二甲雙胍"],
}

# (template, cues); {sym} {dx} {drug} fill from the banks. "{d}", "{rel}" and "{q}" are the date and number slots.
TEMPLATES: dict[str, list[tuple[str, set[tuple[str, str]]]]] = {
    "en": [
        ("Patient denies {sym}.", {NEG}), ("No {sym} was reported.", {NEG}), ("Screen for {dx} was negative.", {NEG}),
        ("Mother had {dx}.", {FAM}), ("Father denies {dx}.", {FAM, NEG}), ("History of {dx}.", {HIST}),
        ("Suspected {dx}.", {UNC}), ("Plan to start {drug} next week.", {PLAN}), ("Return if {sym} worsens.", {HYP}),
        ("Possible {dx}, cannot be excluded.", {UNC}), ("Wife reports {sym}.", {OTHER}), ("Resolved {sym}.", {HIST}),
        ("Patient has {dx} and takes {drug}.", set()), ("No longer taking {drug}.", set()),
        ("Non-small cell lung cancer, stage 2.", set()), ("Seen by Dr. Lee for {dx}.", set()),
        ("Weight approx. 60 kg.", set()), ("Dose not to exceed 10 mg.", set()), ("Known {dx}, mayo clinic follow-up.", set()),
    ],
    "ja": [
        ("{sym}なし。", {NEG}), ("{dx}を認めず。", {NEG}), ("{dx}の既往あり。", {HIST}), ("母が{dx}。", {FAM}),
        ("父親に{dx}の家族歴。", {FAM}), ("{dx}の疑い。", {UNC}), ("次回受診時に{drug}を開始予定。", {PLAN}),
        ("{sym}が増悪する場合は再診。", {HYP}), ("配偶者が{sym}を訴える。", {OTHER}), ("{dx}は寛解。", {HIST}),
        ("{dx}で{drug}を内服中。", set()), ("体重55kg未満は対象外。", set()), ("母集団解析の結果を確認。", set()),
        ("非常に良好。", set()), ("無理なく歩行可能。", set()), ("{dx}ないし{sym}。", set()),
    ],
    "zh": [
        ("無{sym}。", {NEG}), ("否認{sym}。", {NEG}), ("{dx}陰性。", {NEG}), ("母親有{dx}。", {FAM}), ("曾患{dx}。", {HIST}),
        ("疑似{dx}。", {UNC}), ("預計下週開始{drug}。", {PLAN}), ("如果{sym}加重請回診。", {HYP}), ("無法排除{dx}。", {UNC}),
        ("配偶表示{sym}。", {OTHER}), ("病人有{dx},服用{drug}。", set()), ("未滿18歲不適用。", set()),
        ("排除標準請參閱附件。", set()), ("無法行走。", set()),
    ],
}  # fmt: skip
STOP = {"en": ".", "ja": "。", "zh": "。"}


def full_width(s: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if c.isdigit() else c for c in s)


# ---------------------------------------------------------------------------------------------- dates written
def era_name(t: date) -> tuple[str, int]:
    for name, (base, first, last) in ERAS.items():
        if first <= t and (last is None or t <= last):
            return name, t.year - base
    raise AssertionError(t)


def write_date(rng: random.Random, lang: str, t: date) -> tuple[str, str]:
    """``(text, kind)``: the date t as a note writes it; kind ``day`` means exactly t, else an interval holding t."""
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][t.month - 1]
    full = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December"][t.month - 1]  # fmt: skip
    name, n = era_name(t)
    y = "元" if n == 1 and rng.random() < 0.5 else str(n)
    letter = {"令和": "R", "平成": "H", "昭和": "S", "大正": "T"}[name]
    table: dict[str, list[tuple[str, str]]] = {
        "en": [(f"{t:%Y-%m-%d}", "day"), (f"{t.year}/{t.month}/{t.day}", "day"), (f"{mon} {t.day}, {t.year}", "day"),
               (f"{t.day} {full} {t.year}", "day"), (f"{full} {t.year}", "month"), (f"in {t.year}", "year")],
        "ja": [(f"{t.year}年{t.month}月{t.day}日", "day"), (f"{t:%Y.%m.%d}", "day"), (f"{name}{y}年{t.month}月{t.day}日", "day"),
               (f"{name}{y}年{t.month}月", "month"), (f"{name}{y}年", "year"), (f"{letter}{n:02d}.{t:%m.%d}", "day"),
               (f"{t.year}年{t.month}月", "month"), (full_width(f"{t.year}年{t.month}月{t.day}日"), "day")],
        "zh": [(f"民國{t.year - 1911}年{t.month}月{t.day}日", "day"), (f"民國{t.year - 1911}年{t.month}月", "month"),
               (f"{t.year}年{t.month}月", "month"), (f"民國{t.year - 1911}年", "year")]
        + ([(f"{t.year - 1911}/{t.month:02d}/{t.day:02d}", "day"), (f"{t.year - 1911}年{t.month}月{t.day}日", "day"),
            (f"{t.year - 1911}年{t.month}月", "month")] if t.year >= 2011 else []),  # a bare two-digit year is no ROC date
    }  # fmt: skip
    return rng.choice(table[lang])


def write_relative(rng: random.Random, lang: str, nd: date) -> tuple[str, date]:
    """``(phrase, the day it stands for)``: a day X before the note, said to the nearest day, week, month or year."""
    x = rng.randint(1, 1500)
    if x < 14:
        n, unit = x, "day"
    elif x < 60:
        n, unit = round(x / 7), "week"
    elif x < 700:
        n, unit = round(x / 30.44), "month"
    else:
        n, unit = round(x / 365.25), "year"
    word = {"en": {"day": "day", "week": "week", "month": "month", "year": "year"}}
    if lang == "en":
        return f"{n} {word['en'][unit]}{'s' if n != 1 else ''} ago", nd - timedelta(days=x)
    if lang == "ja":
        return f"{n}{ {'day': '日', 'week': '週間', 'month': 'か月', 'year': '年'}[unit] }前", nd - timedelta(days=x)
    return f"{n}{ {'day': '天', 'week': '週', 'month': '個月', 'year': '年'}[unit] }前", nd - timedelta(days=x)


# ---------------------------------------------------------------------------------------------- the notes
class Gold:
    def __init__(self) -> None:
        self.text = ""
        self.sentences: list[dict[str, Any]] = []

    def add(self, s: str) -> tuple[int, int]:
        a = len(self.text)
        self.text += s
        return a, len(self.text)


def build(rng: random.Random, lang: str) -> tuple[str, str, list[dict[str, Any]]]:
    """``(note, note_date, gold sentences)``; a gold sentence has start, end, section, cues, dates, numbers."""
    nd = date(2020, 1, 1) + timedelta(days=rng.randint(0, 2400))
    g = Gold()
    stop = STOP[lang]
    blocks: list[tuple[str, str | None]] = [("unlabelled", None)] if rng.random() < 0.3 else []
    blocks += [(sec, h) for h, sec in rng.sample(HEADERS[lang], rng.randint(3, 6))]
    for section, header in blocks:
        inline = header is not None and rng.random() < 0.4
        if header and not inline:
            g.add(header + "\n")
        elif header:
            g.add(header + " ")
        bullets = rng.random() < 0.5
        count = rng.randint(1, 4)
        for i in range(count):
            slots: dict[str, str] = {
                "sym": rng.choice(SYM[lang]),
                "dx": rng.choice(DX[lang]),
                "drug": rng.choice(DRUG[lang]),
            }
            dates: list[tuple[str, str]] = []
            numbers: list[tuple[float, str]] = []
            roll = rng.random()
            if roll < 0.2:  # a sentence with a written date
                t = date(1950, 1, 1) + timedelta(days=rng.randint(0, (date(2026, 7, 1) - date(1950, 1, 1)).days))
                text, kind = write_date(rng, lang, t)
                body = {"en": f"Seen on {text}{stop}", "ja": f"{text}に受診{stop}", "zh": f"{text}入院{stop}"}[lang]
                cues: set[tuple[str, str]] = set()
                dates.append((t.isoformat(), kind))
            elif roll < 0.3:  # a relative date
                phrase, t = write_relative(rng, lang, nd)
                body = {"en": f"Started {phrase}{stop}", "ja": f"{phrase}に開始{stop}", "zh": f"{phrase}開始{stop}"}[
                    lang
                ]
                cues = set()
                dates.append((t.isoformat(), "relative"))
            elif roll < 0.45:  # a number with a unit
                v = rng.choice([45, 120, 7.5, 0.9, 500, 38])
                unit, code = rng.choice(
                    [("U/L", "U/L"), ("mg/dL", "mg/dL"), ("mmol/L", "mmol/L"), ("mg", "mg"), ("mg/day", "mg/d")]
                )
                txt = f"{v} {unit}" if rng.random() < 0.7 else full_width(f"{v}") + unit
                body = {"en": f"Result {txt}{stop}", "ja": f"結果 {txt}{stop}", "zh": f"結果 {txt}{stop}"}[lang]
                cues = set()
                numbers.append((float(v), code))
            else:
                tpl, cues = rng.choice(TEMPLATES[lang])
                body = tpl.format(**slots)
                if "approx. 60 kg" in body:
                    numbers.append((60.0, "kg"))
                elif "10 mg" in body:
                    numbers.append((10.0, "mg"))
                elif "55kg" in body:
                    numbers.append((55.0, "kg"))
            if bullets and not (inline and i == 0):
                g.add("- " if lang == "en" else "・")
            a, b = g.add(body)
            g.sentences.append(
                {"start": a, "end": b, "section": section, "cues": cues, "dates": dates, "numbers": numbers}
            )
            g.add("\n" if bullets or i == count - 1 else (" " if lang == "en" else ""))
        if not g.text.endswith("\n"):
            g.add("\n")
    return g.text, nd.isoformat(), g.sentences


def corpus(n: int = 400) -> Iterator[tuple[str, str, str, list[dict[str, Any]]]]:
    rng = random.Random(20261127)
    for k in range(n):
        lang = ("en", "ja", "zh")[k % 3]
        text, nd, gold = build(rng, lang)
        yield lang, text, nd, gold


def f1(pred: set[Any], gold: set[Any]) -> float:
    tp = len(pred & gold)
    return 0.0 if not tp else 2 * tp / (len(pred) + len(gold))


# ---------------------------------------------------------------------------------------------- the metrics
def test_sentence_and_section_f1() -> None:
    pred_all: set[Any] = set()
    gold_all: set[Any] = set()
    pred_s: set[Any] = set()
    gold_s: set[Any] = set()
    for k, (_lang, text, nd, gold) in enumerate(corpus()):
        segs = prepare(f"n{k}", text, nd)
        pred_all |= {(k, s.start, s.end, s.section) for s in segs}
        gold_all |= {(k, g["start"], g["end"], g["section"]) for g in gold}
        pred_s |= {(k, s.start, s.end) for s in segs}
        gold_s |= {(k, g["start"], g["end"]) for g in gold}
    assert f1(pred_s, gold_s) >= 0.95, f1(pred_s, gold_s)
    assert f1(pred_all, gold_all) >= 0.95, (f1(pred_all, gold_all), sorted(gold_all - pred_all)[:5])


def test_cue_precision_and_recall() -> None:
    tp = fp = fn = 0
    misses: list[Any] = []
    for k, (_lang, text, nd, gold) in enumerate(corpus()):
        by_span = {(g["start"], g["end"]): g for g in gold}
        for s in prepare(f"n{k}", text, nd):
            g = by_span.get((s.start, s.end))
            if g is None:
                continue
            pred = {(c.kind, c.value) for c in s.cues}
            tp += len(pred & g["cues"])
            fp += len(pred - g["cues"])
            fn += len(g["cues"] - pred)
            if pred != g["cues"] and len(misses) < 8:
                misses.append((s.text, sorted(pred), sorted(g["cues"])))
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    assert precision >= 0.95, (precision, misses)
    assert recall >= 0.95, (recall, misses)


def test_date_interval_holds_the_day_written() -> None:
    total = held = 0
    wrong: list[Any] = []
    for k, (_lang, text, nd, gold) in enumerate(corpus(600)):
        by_span = {(g["start"], g["end"]): g for g in gold}
        for s in prepare(f"n{k}", text, nd):
            g = by_span.get((s.start, s.end))
            if g is None or not g["dates"]:
                continue
            for truth, kind in g["dates"]:
                total += 1
                ok = any(d.lo <= truth <= d.hi for d in s.dates)
                if kind == "day":
                    ok = ok and any(d.lo == d.hi == truth for d in s.dates)
                held += ok
                if not ok and len(wrong) < 8:
                    wrong.append((s.text, truth, kind, [(d.lo, d.hi) for d in s.dates]))
    assert total > 100
    assert held / total >= 0.95, (held / total, wrong)


def test_numbers_and_units_are_exact() -> None:
    total = held = extra = 0
    for k, (_lang, text, nd, gold) in enumerate(corpus()):
        by_span = {(g["start"], g["end"]): g for g in gold}
        for s in prepare(f"n{k}", text, nd):
            g = by_span.get((s.start, s.end))
            if g is None:
                continue
            pred = {(q.value, q.ucum) for q in s.numbers}
            total += len(g["numbers"])
            held += len(pred & set(g["numbers"]))
            extra += len(pred - set(g["numbers"]))
    assert total > 50 and held == total and extra == 0, (total, held, extra)


def test_nothing_is_dropped_only_headers_and_marks_stay_outside_the_segments() -> None:
    for k, (lang, text, nd, _gold) in enumerate(corpus()):
        rest = list(text)
        for s in prepare(f"n{k}", text, nd):
            rest[s.start : s.end] = " " * (s.end - s.start)
        left = "".join(rest)
        for header, _section in HEADERS[lang]:
            left = left.replace(header, " ")
        assert not any(ch.isalnum() for ch in left), (k, left)


# ---------------------------------------------------------------------------------------------- wareki, 100 %
def era_cases() -> Iterator[tuple[str, int, date, date | None, date]]:
    for name, (base, first, last) in ERAS.items():
        last = last or date(2100, 12, 31)
        for t in (first, last, first + timedelta(days=(last - first).days // 2)):
            yield name, base, first, last, t


def test_wareki_full_dates_every_era_every_form() -> None:
    letters = {"令和": "R", "平成": "H", "昭和": "S", "大正": "T"}
    n = 0
    for name, base, _first, _last, t in era_cases():
        y = t.year - base
        forms = [f"{name}{y}年{t.month}月{t.day}日", f"{name}{y}/{t.month}/{t.day}", f"{name}{y}.{t.month}.{t.day}",
                 full_width(f"{name}{y}年{t.month}月{t.day}日"), f"{name} {y} 年 {t.month} 月 {t.day} 日"]  # fmt: skip
        if y == 1:
            forms.append(f"{name}元年{t.month}月{t.day}日")
        if name in letters:
            forms.append(f"{letters[name]}{y:02d}.{t.month:02d}.{t.day:02d}")
        for form in forms:
            seg = prepare("w", f"Seen {form}.")[0]
            got = [(d.lo, d.hi) for d in seg.dates]
            assert got == [(t.isoformat(), t.isoformat())], (form, got)
            n += 1
    assert n >= 30


def test_wareki_partial_dates_are_the_era_clipped_interval() -> None:
    for name, base, first, last, t in era_cases():
        last = last or date(2100, 12, 31)
        y = t.year - base
        lo = max(date(t.year, 1, 1), first)
        hi = min(date(t.year, 12, 31), last)
        seg = prepare("w", f"{name}{y}年に開始。")[0]
        assert [(d.lo, d.hi, d.kind) for d in seg.dates] == [(lo.isoformat(), hi.isoformat(), "year")], name
        m_lo = max(date(t.year, t.month, 1), first)
        m_hi = min(date(t.year + (t.month == 12), t.month % 12 + 1, 1) - timedelta(days=1), last)
        seg = prepare("w", f"{name}{y}年{t.month}月に開始。")[0]
        assert [(d.lo, d.hi, d.kind) for d in seg.dates] == [(m_lo.isoformat(), m_hi.isoformat(), "month")], name


@pytest.mark.parametrize(
    "text",
    [
        "平成31年5月1日に受診。",  # 平成 ended on 2019-04-30
        "令和1年4月30日に受診。",  # 令和 began on 2019-05-01
        "平成31年5月に受診。",
        "昭和64年1月8日に受診。",  # 昭和 ended on 1989-01-07
        "令和6年2月30日に受診。",  # a day the calendar lacks
        "令和6年13月1日に受診。",
        "令和0年1月1日に受診。",
        "R06.13.01 seen.",
        "AR06.01.10 is an order code",  # a letter after a word is no era
        "2026-02-30 seen.",
        "20260724 order number",  # a run of eight digits is no date
    ],
)
def test_wareki_and_other_impossible_dates_give_nothing(text: str) -> None:
    assert prepare("w", text)[0].dates == ()

"""The note accuracy set per language and stratum, its runner and its scorer (NEW-LLM-6; deep review 2026-11-12,
LLM-006 and LLM-009).

The measured note accuracy rested on one template study in Japanese and the 54-case canary. This set measures the
product's ``judge`` prompt and parser on what that left out, per language (ja, zh-TW, en):

* ``plain``: the condition stated, or stated absent, among routine sentences;
* ``long``: one note longer than half the excerpt budget, cut around its decisive sentence by the product's own
  excerpt builder (:func:`matching.excerpts.build`, ``[…]`` where sentences were left out);
* ``negation``: a negated list holding the condition ("no asthma, COPD or interstitial lung disease"), or one of other
  conditions beside a stated one;
* ``family``: a relative's condition alone (gold ``unknown``: nothing is said of the patient), or beside the patient's;
* ``era``: an event dated in 和暦 (ja) or 民國 (zh-TW), inside or outside the criterion's window;
* ``window``: the same with Western dates;
* ``lab``: a value written in a note against the criterion's threshold, the threshold itself included.

Criteria and note questions are in English, as the compiler writes them (LLM-015); notes are in the site's language.
Every case is a canary case (``services/orchestrator/canary``) with ``kind`` (inclusion or exclusion), ``type``,
``stratum`` and, when decided, ``evidence`` (the decisive sentence, quoted by a right answer). The set is generated
from a seed and pinned by ``eval/accuracy/MANIFEST.json``; it is not committed. Synthetic text written for TrialBox;
no patient data.

    python -m tools.accuracy_set generate cases.jsonl [--seed N] [--manifest eval/accuracy/MANIFEST.json]
    python -m tools.accuracy_set run cases.jsonl answers.json      # both models, through this box's gateway
    python -m tools.accuracy_set score cases.jsonl answers.json [--out report.json]

Only a run through the gateway counts (the build-vs-reuse review): ``run`` builds the clients as the orchestrator
does (``TB_GATEWAY_URL`` ...), with the gateway's swap when the two models share one GPU. The report gives, per model
and for the pair (decided only when both agree), accuracy with a Wilson interval per language and stratum, wrong and
missed exclusions with an exact one-sided 95 % upper bound, a ten-bin confidence table per language with its
expected calibration error (LLM-009), and the error and unknown rates at candidate confidence floors.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import random
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

#: the seed of the measured set (eval/accuracy/MANIFEST.json)
SEED = 20261114
#: gold exclusions, and decided gold non-exclusions, at least, per language
PER_CLASS = 200
LANGS = ("ja", "zh-TW", "en")
#: candidate confidence floors the report gives the error and unknown rates at
FLOORS = (0.5, 0.6, 0.7, 0.8, 0.9)
#: a long note holds at least this many tokens: more than the whole excerpt budget (2,500), so the builder cuts it
LONG_TOKENS = 3000
BASE_INDEX = date(2026, 11, 1)
FIELDS = ("criterion_text", "note_question", "index_date", "excerpts")

NOTE_TYPES = {
    "ja": ("経過記録", "外来記録", "退院時要約"),
    "zh-TW": ("病程紀錄", "門診紀錄", "出院摘要"),
    "en": ("progress", "outpatient", "discharge summary"),
}
FILLER = {
    "en": (
        "Seen in clinic for routine review.", "Blood pressure 128/76 mmHg, pulse 72.", "Weight stable at 64 kg.",
        "Sleeping well and appetite good.", "Walks 30 minutes most days.", "Influenza vaccine given today.",
        "Reports mild seasonal rhinitis.", "Chest clear on auscultation.", "Abdomen soft and non-tender.",
        "No new medication since last visit.", "Lives with spouse; independent in daily activities.",
        "Non-smoker; drinks alcohol occasionally.", "Dental check-up booked next month.",
        "Advised to keep up regular exercise.", "Skin intact, no rash.", "Temperature 36.6 C.",
        "Follow-up in three months.", "Discussed diet and salt intake.", "Hearing and vision unchanged.",
        "Knee pain improved with physiotherapy.", "Bowel habit regular.", "Urine dipstick unremarkable.",
        "Mood stable, no concerns raised.", "Medication list reconciled with the pharmacy.",
    ),
    "ja": (
        "定期受診のため来院。", "血圧128/76mmHg、脈拍72回/分。", "体重は64kgで変化なし。", "睡眠良好で食欲もある。",
        "ほぼ毎日30分程度歩いている。", "本日インフルエンザワクチンを接種した。", "季節性の鼻炎症状が軽度ある。",
        "胸部聴診で異常なし。", "腹部は平坦軟で圧痛なし。", "前回受診以降、新たな処方はない。",
        "配偶者と同居し、日常生活は自立している。", "喫煙歴なし、飲酒は機会飲酒。", "来月に歯科検診の予定あり。",
        "運動を続けるよう指導した。", "皮膚に発疹なし。", "体温36.6度。", "3か月後に再診予定。",
        "減塩について説明した。", "聴力と視力に変化なし。", "膝の痛みはリハビリで改善している。", "排便は規則的。",
        "尿検査に異常なし。", "気分は安定しており、特に訴えなし。", "薬局と服薬内容を確認した。",
    ),
    "zh-TW": (
        "因定期追蹤返診。", "血壓128/76mmHg，脈搏每分鐘72次。", "體重64公斤，無明顯變化。", "睡眠良好，食慾正常。",
        "幾乎每天步行約30分鐘。", "今日施打流感疫苗。", "有輕微季節性鼻炎症狀。", "胸部聽診無異常。",
        "腹部柔軟無壓痛。", "上次門診後無新增藥物。", "與配偶同住，日常生活可自理。", "不抽菸，偶爾飲酒。",
        "下個月安排牙科檢查。", "鼓勵持續規律運動。", "皮膚完整，無皮疹。", "體溫36.6度。", "三個月後回診。",
        "說明低鹽飲食。", "聽力與視力無變化。", "膝痛經復健後改善。", "排便規律。", "尿液檢查無異常。",
        "情緒穩定，無特別不適。", "已與藥局核對用藥。",
    ),
}  # fmt: skip
OTHERS = {
    "ja": ("喘息", "COPD", "胃潰瘍", "緑内障", "甲状腺機能低下症", "骨粗鬆症"),
    "zh-TW": ("氣喘", "慢性阻塞性肺病", "胃潰瘍", "青光眼", "甲狀腺功能低下", "骨質疏鬆症"),
    "en": ("asthma", "COPD", "peptic ulcer", "glaucoma", "hypothyroidism", "osteoporosis"),
}
RELATIVES = {
    "ja": ("母", "父", "姉", "兄"),
    "zh-TW": ("母親", "父親", "姊姊", "哥哥"),
    "en": ("mother", "father", "sister", "brother"),
}
NEG_LIST = {
    "ja": ("既往歴：{a}、{b}、{t}はいずれもなし。", "既往歴：{a}、{b}はいずれもなし。"),
    "zh-TW": ("過去病史：無{a}、{b}或{t}。", "過去病史：無{a}或{b}。"),
    "en": ("Past history: no {a}, {b} or {t}.", "Past history: no {a} or {b}."),
}
FAMILY = {"ja": "家族歴：{r}が{t}。", "zh-TW": "家族史：{r}患有{t}。", "en": "Family history: {r} had {t}."}


@dataclass(frozen=True)
class Dx:
    """A condition stated present or absent: ``name``, ``pos`` and ``neg`` sentences per language."""

    id: str
    kind: str
    text: str
    question: str
    name: Mapping[str, str]
    pos: Mapping[str, tuple[str, ...]]
    neg: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Dated:
    """An event inside ``window`` days before the index date, or outside it: one sentence per language with ``{d}``."""

    id: str
    kind: str
    text: str
    question: str
    window: int
    event: Mapping[str, str]


@dataclass(frozen=True)
class Lab:
    """A value against ``threshold`` (``op`` is ``>=`` or ``<``): one sentence per language with ``{v}``."""

    id: str
    kind: str
    text: str
    question: str
    op: str
    threshold: float
    step: float
    line: Mapping[str, str]


DX = (
    Dx(
        "ild",
        "exclusion",
        "History of interstitial lung disease",
        "Does the patient have a history of interstitial lung disease?",
        {"ja": "間質性肺炎", "zh-TW": "間質性肺病", "en": "interstitial lung disease"},
        {
            "ja": (
                "胸部CTで両下肺に網状影を認め、間質性肺炎と診断されている。",
                "間質性肺炎に対しピルフェニドン内服中。",
            ),
            "zh-TW": ("胸部電腦斷層顯示兩側下肺網狀陰影，診斷為間質性肺病。", "間質性肺病，目前服用pirfenidone治療。"),
            "en": (
                "Chest CT shows bilateral basal reticulation consistent with interstitial lung disease.",
                "Known interstitial lung disease, on pirfenidone.",
            ),
        },
        {
            "ja": (
                "胸部CTで間質影は認めず、間質性肺炎は否定的。",
                "呼吸器内科で精査し、間質性肺炎はないと判断された。",
            ),
            "zh-TW": ("胸部電腦斷層未見間質性變化，排除間質性肺病。", "經胸腔內科評估，無間質性肺病。"),
            "en": (
                "Chest CT without interstitial change; interstitial lung disease excluded.",
                "Reviewed by respiratory medicine: no interstitial lung disease.",
            ),
        },
    ),
    Dx(
        "hf",
        "exclusion",
        "Heart failure, NYHA class III or IV",
        "Does the patient have heart failure of NYHA class III or IV?",
        {"ja": "心不全", "zh-TW": "心臟衰竭", "en": "heart failure"},
        {
            "ja": ("慢性心不全でNYHA III度、軽い労作で息切れあり。", "心不全増悪で入院歴あり、現在NYHA IV度。"),
            "zh-TW": ("慢性心臟衰竭，NYHA第三級，輕度活動即喘。", "心臟衰竭惡化曾住院，目前NYHA第四級。"),
            "en": (
                "Chronic heart failure, NYHA class III, breathless on minimal exertion.",
                "Heart failure with recent admission, now NYHA class IV.",
            ),
        },
        {
            "ja": ("心エコーでEF 62%、心不全の所見なし。", "息切れや浮腫はなく、心不全は認めない。"),
            "zh-TW": ("心臟超音波EF 62%，無心臟衰竭跡象。", "無喘或水腫，無心臟衰竭。"),
            "en": ("Echo EF 62% with no sign of heart failure.", "No dyspnoea or oedema; no heart failure."),
        },
    ),
    Dx(
        "hbv",
        "exclusion",
        "Chronic hepatitis B infection",
        "Does the patient have chronic hepatitis B infection?",
        {"ja": "B型肝炎", "zh-TW": "B型肝炎", "en": "hepatitis B"},
        {
            "ja": ("HBs抗原陽性、慢性B型肝炎で核酸アナログ内服中。", "慢性B型肝炎として消化器内科に通院している。"),
            "zh-TW": ("HBsAg陽性，慢性B型肝炎，服用抗病毒藥物。", "慢性B型肝炎，定期於腸胃科追蹤。"),
            "en": (
                "HBsAg positive; chronic hepatitis B on entecavir.",
                "Chronic hepatitis B followed by gastroenterology.",
            ),
        },
        {
            "ja": ("HBs抗原陰性、B型肝炎の感染はない。", "肝炎ウイルス検査は陰性で、B型肝炎は否定された。"),
            "zh-TW": ("HBsAg陰性，無B型肝炎感染。", "肝炎病毒檢驗陰性，排除B型肝炎。"),
            "en": (
                "HBsAg negative; no hepatitis B infection.",
                "Viral hepatitis screen negative, hepatitis B excluded.",
            ),
        },
    ),
    Dx(
        "epi",
        "exclusion",
        "History of epilepsy",
        "Does the patient have a history of epilepsy?",
        {"ja": "てんかん", "zh-TW": "癲癇", "en": "epilepsy"},
        {
            "ja": ("てんかんの既往があり、レベチラセタム内服中。", "小児期よりてんかん発作を繰り返している。"),
            "zh-TW": ("有癲癇病史，服用levetiracetam。", "自幼即有癲癇反覆發作。"),
            "en": ("History of epilepsy, on levetiracetam.", "Recurrent epileptic seizures since childhood."),
        },
        {
            "ja": ("けいれん発作の既往はなく、てんかんはない。", "脳波は正常で、てんかんは否定的。"),
            "zh-TW": ("無抽搐病史，無癲癇。", "腦波正常，排除癲癇。"),
            "en": ("No seizures ever; no epilepsy.", "EEG normal, epilepsy excluded."),
        },
    ),
    Dx(
        "t2dm",
        "inclusion",
        "Type 2 diabetes mellitus",
        "Does the patient have type 2 diabetes?",
        {"ja": "2型糖尿病", "zh-TW": "第二型糖尿病", "en": "type 2 diabetes"},
        {
            "ja": ("2型糖尿病でメトホルミン内服中。", "2型糖尿病として当院糖尿病内科に通院している。"),
            "zh-TW": ("第二型糖尿病，服用metformin。", "第二型糖尿病，於本院新陳代謝科追蹤。"),
            "en": ("Type 2 diabetes on metformin.", "Type 2 diabetes, followed in the diabetes clinic."),
        },
        {
            "ja": ("糖尿病の既往はなく、空腹時血糖も正常。", "糖負荷試験は正常型で、糖尿病は否定された。"),
            "zh-TW": ("無糖尿病病史，空腹血糖正常。", "葡萄糖耐受試驗正常，排除糖尿病。"),
            "en": (
                "No history of diabetes; fasting glucose normal.",
                "Glucose tolerance test normal, diabetes excluded.",
            ),
        },
    ),
    Dx(
        "ad",
        "inclusion",
        "Clinical diagnosis of Alzheimer's disease",
        "Does the patient have a diagnosis of Alzheimer's disease?",
        {"ja": "アルツハイマー型認知症", "zh-TW": "阿茲海默症", "en": "Alzheimer's disease"},
        {
            "ja": (
                "アルツハイマー型認知症と診断され、ドネペジル内服中。",
                "アミロイドPET陽性で、アルツハイマー型認知症と診断された。",
            ),
            "zh-TW": ("診斷為阿茲海默症，服用donepezil。", "類澱粉蛋白正子造影陽性，診斷為阿茲海默症。"),
            "en": (
                "Diagnosed with Alzheimer's disease, on donepezil.",
                "Amyloid PET positive; Alzheimer's disease diagnosed.",
            ),
        },
        {
            "ja": ("認知機能は正常で、認知症は認めない。", "神経内科で評価し、アルツハイマー型認知症は否定された。"),
            "zh-TW": ("認知功能正常，無失智症。", "經神經科評估，排除阿茲海默症。"),
            "en": ("Cognition normal; no dementia.", "Assessed by neurology, Alzheimer's disease excluded."),
        },
    ),
    Dx(
        "ra",
        "inclusion",
        "Rheumatoid arthritis",
        "Does the patient have rheumatoid arthritis?",
        {"ja": "関節リウマチ", "zh-TW": "類風濕性關節炎", "en": "rheumatoid arthritis"},
        {
            "ja": ("関節リウマチでメトトレキサート内服中。", "抗CCP抗体陽性の関節リウマチとして通院中。"),
            "zh-TW": ("類風濕性關節炎，服用methotrexate。", "抗CCP抗體陽性之類風濕性關節炎，持續追蹤。"),
            "en": ("Rheumatoid arthritis on methotrexate.", "Anti-CCP positive rheumatoid arthritis under follow-up."),
        },
        {
            "ja": ("関節腫脹なく、関節リウマチは否定的。", "リウマトイド因子陰性で、関節リウマチはない。"),
            "zh-TW": ("無關節腫脹，排除類風濕性關節炎。", "類風濕因子陰性，無類風濕性關節炎。"),
            "en": (
                "No synovitis; rheumatoid arthritis excluded.",
                "Rheumatoid factor negative, no rheumatoid arthritis.",
            ),
        },
    ),
)
DATED = (
    Dated(
        "stroke",
        "exclusion",
        "Stroke within the past 6 months",
        "Has the patient had a stroke within the 6 months before the index date?",
        183,
        {
            "ja": "{d}に脳梗塞を発症し入院加療、以後再発なし。",
            "zh-TW": "{d}發生腦梗塞住院治療，此後無復發。",
            "en": "Admitted with ischaemic stroke on {d}, with no further events since.",
        },
    ),
    Dated(
        "malig",
        "exclusion",
        "Malignancy diagnosed within the past 5 years",
        "Has the patient been diagnosed with a malignancy within the 5 years before the index date?",
        1826,
        {
            "ja": "{d}に大腸癌と診断され手術施行、以後再発なし。",
            "zh-TW": "{d}診斷大腸癌並接受手術，此後無復發。",
            "en": "Colon cancer diagnosed on {d} and resected, with no recurrence since.",
        },
    ),
    Dated(
        "mi",
        "exclusion",
        "Myocardial infarction within the past 12 months",
        "Has the patient had a myocardial infarction within the 12 months before the index date?",
        365,
        {
            "ja": "{d}に急性心筋梗塞でPCI施行、以後胸痛なし。",
            "zh-TW": "{d}因急性心肌梗塞接受心導管治療，此後無胸痛。",
            "en": "Acute myocardial infarction treated with PCI on {d}, with no chest pain since.",
        },
    ),
    Dated(
        "gout",
        "inclusion",
        "Gout flare within the past 12 months",
        "Has the patient had a gout flare within the 12 months before the index date?",
        365,
        {
            "ja": "{d}に右母趾の痛風発作があり、以後発作なし。",
            "zh-TW": "{d}右腳大拇趾痛風發作，此後未再發作。",
            "en": "Gout flare of the right big toe on {d}, with no flare since.",
        },
    ),
)
LABS = (
    Lab(
        "egfr",
        "exclusion",
        "eGFR below 30 mL/min/1.73m2",
        "Is the patient's eGFR below 30 mL/min/1.73m2?",
        "<",
        30,
        1,
        {
            "ja": "採血でeGFRは{v} mL/min/1.73m2であった。",
            "zh-TW": "抽血檢查eGFR為{v} mL/min/1.73m2。",
            "en": "Bloods: eGFR {v} mL/min/1.73m2.",
        },
    ),
    Lab(
        "alt",
        "exclusion",
        "ALT 120 U/L or higher",
        "Is the patient's ALT 120 U/L or higher?",
        ">=",
        120,
        1,
        {"ja": "肝機能はALT {v} U/Lであった。", "zh-TW": "肝功能檢查ALT {v} U/L。", "en": "Liver panel: ALT {v} U/L."},
    ),
    Lab(
        "hba1c",
        "inclusion",
        "HbA1c 7.0% or higher",
        "Is the patient's HbA1c 7.0% or higher?",
        ">=",
        7.0,
        0.1,
        {"ja": "HbA1cは{v}%であった。", "zh-TW": "糖化血色素HbA1c為{v}%。", "en": "HbA1c {v}%."},
    ),
    Lab(
        "urate",
        "inclusion",
        "Serum urate 8.0 mg/dL or higher",
        "Is the patient's serum urate 8.0 mg/dL or higher?",
        ">=",
        8.0,
        0.1,
        {"ja": "血清尿酸値は{v} mg/dLであった。", "zh-TW": "血清尿酸值{v} mg/dL。", "en": "Serum urate {v} mg/dL."},
    ),
)


# ------------------------------------------------------------------------------------------------- dates
_ERAS = ((date(2019, 5, 1), "令和", 2018), (date(1989, 1, 8), "平成", 1988))


def wareki(d: date) -> str:
    """``d`` in the Japanese era calendar (令和 from 2019-05-01, 平成 before; the first year is 元年)."""
    for start, name, offset in _ERAS:
        if d >= start:
            y = d.year - offset
            return f"{name}{'元' if y == 1 else y}年{d.month}月{d.day}日"
    raise ValueError(f"no era for {d}")


def minguo(d: date) -> str:
    """``d`` in the Republic of China calendar (民國 year = Western year − 1911)."""
    return f"民國{d.year - 1911}年{d.month}月{d.day}日"


def western(d: date, lang: str) -> str:
    return f"{d.day} {d.strftime('%B')} {d.year}" if lang == "en" else f"{d.year}年{d.month}月{d.day}日"


# ------------------------------------------------------------------------------------------------- the set
def _join(sents: Iterable[str], lang: str) -> str:
    return (" " if lang == "en" else "").join(sents)


def _short(rng: random.Random, lang: str, decisive: list[str], day: date) -> list[dict[str, Any]]:
    """One note: routine sentences around the decisive ones; sometimes an older routine note beside it."""
    sents = rng.sample(FILLER[lang], rng.randint(1, 3))
    for s in decisive:
        sents.insert(rng.randint(0, len(sents)), s)
    notes = [{"date": day.isoformat(), "note_type": rng.choice(NOTE_TYPES[lang]), "text": _join(sents, lang)}]
    if rng.random() < 0.3:
        old = day - timedelta(days=rng.randint(30, 200))
        notes.append(
            {
                "date": old.isoformat(),
                "note_type": rng.choice(NOTE_TYPES[lang]),
                "text": _join(rng.sample(FILLER[lang], 2), lang),
            }
        )
    return notes


def _long(rng: random.Random, lang: str, decisive: str, day: date) -> tuple[list[dict[str, Any]], int, int]:
    """One note of more than :data:`LONG_TOKENS` tokens with ``decisive`` in its middle, as the product's excerpt
    builder shows it: the excerpts, how many notes it left out, and the note's tokens."""
    from matching.excerpts import DEFAULT_TOKENS, Note, build, note_tokens

    sents: list[str] = []
    base = note_tokens("")
    total = base
    while total < LONG_TOKENS:  # each sentence's own cost and its line end
        s = rng.choice(FILLER[lang])
        sents.append(s)
        total += _cost(s) - base + 1
    sents.insert(len(sents) // 2 + rng.randint(-5, 5), decisive)
    text = "\n".join(sents)
    got = build([Note("d1", day, rng.choice(NOTE_TYPES[lang]), text)], {"d1": [decisive]}, DEFAULT_TOKENS)
    shown = [{k: e[k] for k in ("date", "note_type", "text")} for e in got.shown]
    return shown, got.left_out, note_tokens(text)


@functools.lru_cache(maxsize=256)
def _cost(sentence: str) -> int:
    from matching.excerpts import note_tokens

    return note_tokens(sentence)


def _lab_value(rng: random.Random, lab: Lab, met: bool, boundary: bool) -> float | int:
    k = rng.randint(1, 15)
    if lab.op == ">=":
        v = lab.threshold if (met and boundary) else lab.threshold + (k if met else -k) * lab.step
    else:
        v = lab.threshold if (not met and boundary) else lab.threshold + (-k if met else k) * lab.step
    return round(v, 1) if isinstance(lab.step, float) else int(v)


def _fmt(v: float | int) -> str:
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def _cells(lang: str) -> list[tuple[Any, str, str]]:
    """(criterion, stratum, expected) of one round."""
    out: list[tuple[Any, str, str]] = []
    for dx in DX:
        for st in ("plain", "negation", "long"):
            out += [(dx, st, "pass"), (dx, st, "fail")]
        out += [(dx, "family", "pass"), (dx, "family", "fail"), (dx, "family", "unknown")]
    for ev in DATED:
        for st in ("window", "long") + (("era",) if lang != "en" else ()):
            out += [(ev, st, "pass"), (ev, st, "fail")]
    for lab in LABS:
        for st in ("lab", "long"):
            out += [(lab, st, "pass"), (lab, st, "fail")]
    return out


def _case(rng: random.Random, lang: str, crit: Any, stratum: str, expected: str, rnd: int) -> dict[str, Any]:
    index = BASE_INDEX + timedelta(days=rng.randint(-60, 60))
    day = index - timedelta(days=rng.randint(1, 30))
    extra: dict[str, Any] = {}
    evidence: str | None
    decisive: list[str]
    if isinstance(crit, Dx):
        pos, neg = rng.choice(crit.pos[lang]), rng.choice(crit.neg[lang])
        a, b = rng.sample(OTHERS[lang], 2)
        if stratum == "negation":
            if expected == "fail":
                evidence = NEG_LIST[lang][0].format(a=a, b=b, t=crit.name[lang])
                decisive = [evidence]
            else:
                evidence, decisive = pos, [NEG_LIST[lang][1].format(a=a, b=b), pos]
        elif stratum == "family":
            fam = FAMILY[lang].format(r=rng.choice(RELATIVES[lang]), t=crit.name[lang])
            evidence = {"pass": pos, "fail": neg, "unknown": None}[expected]
            decisive = [fam] + ([evidence] if evidence else [])
        else:
            evidence = pos if expected == "pass" else neg
            decisive = [evidence]
    elif isinstance(crit, Dated):
        inside = expected == "pass"
        back = rng.randint(40, crit.window - 15) if inside else rng.randint(crit.window + 15, 2 * crit.window + 15)
        event = index - timedelta(days=back)
        if stratum == "era":
            shown = wareki(event) if lang == "ja" else minguo(event)
        else:
            shown = western(event, lang)
        evidence = crit.event[lang].format(d=shown)
        decisive = [evidence]
        extra = {"event_date": event.isoformat(), "window_days": crit.window}
    else:
        v = _lab_value(rng, crit, expected == "pass", stratum == "lab" and rnd % 3 == 0)
        evidence = crit.line[lang].format(v=_fmt(v))
        decisive = [evidence]
        extra = {"value": v, "threshold": crit.threshold, "op": crit.op}
    if stratum == "long":
        assert evidence is not None
        excerpts, left_out, tokens = _long(rng, lang, evidence, day)
        extra |= {"left_out": left_out, "note_tokens": tokens}
    else:
        excerpts = _short(rng, lang, decisive, day)
    case = {
        "id": f"{lang}:{crit.id}:{stratum}:{expected}:{rnd}",
        "language": lang,
        "criterion_text": crit.text,
        "note_question": crit.question,
        "index_date": index.isoformat(),
        "excerpts": excerpts,
        "expected": expected,
        "kind": crit.kind,
        "type": crit.id,
        "stratum": stratum,
    }
    if evidence is not None:
        case["evidence"] = evidence
    return case | extra


def generate(seed: int = SEED, per_class: int = PER_CLASS) -> list[dict[str, Any]]:
    """The set: per language, rounds of every (criterion, stratum, gold answer) cell until it holds ``per_class``
    gold exclusions and ``per_class`` decided gold non-exclusions. The same for the same seed."""
    rng = random.Random(seed)
    out: list[dict[str, Any]] = []
    for lang in LANGS:
        mine: list[dict[str, Any]] = []
        rnd = 0
        while not _enough(mine, per_class):
            mine += [_case(rng, lang, crit, st, exp, rnd) for crit, st, exp in _cells(lang)]
            rnd += 1
        out += mine
    return out


def _enough(cases: list[dict[str, Any]], per_class: int) -> bool:
    ex = sum(1 for c in cases if gold_excludes(c))
    kept = sum(1 for c in cases if not gold_excludes(c) and c["expected"] != "unknown")
    return ex >= per_class and kept >= per_class


def set_hash(cases: list[dict[str, Any]]) -> str:
    text = "\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in cases)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def counts(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in cases:
        row = out.setdefault(c["language"], {"cases": 0, "gold_exclusions": 0, "gold_non_exclusions": 0, "unknown": 0})
        row["cases"] += 1
        if c["expected"] == "unknown":
            row["unknown"] += 1
        row["gold_exclusions" if gold_excludes(c) else "gold_non_exclusions"] += 1
    return out


# ------------------------------------------------------------------------------------------------- answers
def quote_in(quote: str | None, text: str) -> bool:
    from tb_common.quotes import quote_in as _quote_in

    return bool(quote) and _quote_in(str(quote), text)


def answer_of(data: dict[str, Any], excerpts: list[dict[str, Any]]) -> dict[str, Any]:
    """A model's answer through the product's parser (:func:`orchestrator.scenarios.evaluate.postprocess`): the
    verdict, its confidence and the reason code."""
    from orchestrator.scenarios.evaluate import postprocess

    r = postprocess(data, excerpts)
    return {"verdict": r.predicate, "confidence": float(r.confidence), "reason": str(r.reason or "")}


def run_model(client: Any, cases: list[dict[str, Any]], prompt: str = "judge") -> dict[str, dict[str, Any]]:
    """Each case asked as the canary asks it (:func:`orchestrator.selftest.check_model`), keeping the confidence; a
    refused call is an ``error``."""
    from orchestrator.selftest import clip
    from tb_common.llm import LlmError

    out: dict[str, dict[str, Any]] = {}
    for c in cases:
        try:
            res = client.chat_json(prompt, {k: c[k] for k in FIELDS}, job_id="accuracy")
        except LlmError as exc:
            out[c["id"]] = {"error": clip(str(exc))}
            continue
        out[c["id"]] = answer_of(res.data, c["excerpts"])
    return out


# ------------------------------------------------------------------------------------------------- the scorer
def gold_excludes(c: Mapping[str, Any]) -> bool:
    """Whether the gold answer makes the patient ineligible: an exclusion met, or an inclusion not met."""
    return excludes(str(c["kind"]), str(c["expected"]))


def excludes(kind: str, verdict: str) -> bool:
    return verdict == ("pass" if kind == "exclusion" else "fail")


def exact_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """The exact (Clopper–Pearson) one-sided upper ``1 − alpha`` bound of a rate seen ``k`` times in ``n``."""
    if n <= 0 or k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _binom_cdf(k, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def _binom_cdf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return sum(
        math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
        for i in range(k + 1)
    )


def _wilson(x: int, n: int) -> tuple[float, float]:
    from deliverables.analytics import wilson

    lo, hi = wilson(x, n)
    return round(lo, 4), round(hi, 4)


def _cell(rows: list[tuple[dict[str, Any], dict[str, Any] | None]]) -> dict[str, Any]:
    n = len(rows)
    ok = [a for _, a in rows if a is not None and "verdict" in a]
    correct = sum(1 for c, a in rows if a is not None and a.get("verdict") == c["expected"])
    gold_ex = [(c, a) for c, a in rows if gold_excludes(c)]
    gold_kept = [(c, a) for c, a in rows if not gold_excludes(c)]
    wrong = sum(1 for c, a in gold_kept if a is not None and excludes(c["kind"], str(a.get("verdict"))))
    missed = sum(1 for c, a in gold_ex if a is None or not excludes(c["kind"], str(a.get("verdict"))))
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else None,
        "accuracy_ci95": _wilson(correct, n),
        "errors": n - len(ok),
        "unknown": sum(1 for a in ok if a["verdict"] == "unknown"),
        "exclusions": len(gold_ex),
        "missed_exclusions": missed,
        "non_exclusions": len(gold_kept),
        "wrong_exclusions": wrong,
        "wrong_exclusion_upper95": round(exact_upper(wrong, len(gold_kept)), 6),
    }


def _grouped(cases: list[dict[str, Any]], answers: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [(c, answers.get(c["id"])) for c in cases]
    by: dict[str, dict[str, Any]] = {}
    for lang in sorted({c["language"] for c in cases}):
        mine = [r for r in rows if r[0]["language"] == lang]
        cell = {st: _cell([r for r in mine if r[0]["stratum"] == st]) for st in sorted({r[0]["stratum"] for r in mine})}
        by[lang] = cell | {"all": _cell(mine)}
    return {"all": _cell(rows), "by": by}


def _calibration(rows: list[tuple[dict[str, Any], dict[str, Any] | None]]) -> dict[str, Any]:
    """Ten confidence bins of the decided answers: how many, their mean confidence, how many were right."""
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(10)]
    for c, a in rows:
        if a is None or a.get("verdict") not in ("pass", "fail"):
            continue
        conf = min(max(float(a.get("confidence", 0.0)), 0.0), 1.0)
        bins[min(int(conf * 10), 9)].append((conf, a["verdict"] == c["expected"]))
    total = sum(len(b) for b in bins)
    out, ece = [], 0.0
    for i, b in enumerate(bins):
        mean = sum(x for x, _ in b) / len(b) if b else None
        right = sum(1 for _, r in b if r) / len(b) if b else None
        if mean is not None and right is not None:
            ece += len(b) / total * abs(right - mean)
        out.append({"lo": i / 10, "hi": (i + 1) / 10, "n": len(b), "confidence": mean, "accuracy": right})
    return {"bins": out, "decided": total, "ece": round(ece, 4) if total else None}


def _floors(rows: list[tuple[dict[str, Any], dict[str, Any] | None]]) -> list[dict[str, Any]]:
    """At each floor an answer less sure than it is unknown: how many are decided, how many of those are wrong, the
    wrong exclusions among them, and the unknown rate."""
    n = len(rows)
    out = []
    for floor in FLOORS:
        dec = [
            (c, a)
            for c, a in rows
            if a is not None and a.get("verdict") in ("pass", "fail") and float(a.get("confidence", 0.0)) >= floor
        ]
        out.append(
            {
                "floor": floor,
                "decided": len(dec),
                "wrong": sum(1 for c, a in dec if a["verdict"] != c["expected"]),
                "wrong_exclusions": sum(
                    1 for c, a in dec if not gold_excludes(c) and excludes(c["kind"], a["verdict"])
                ),
                "unknown_rate": round(1 - len(dec) / n, 4) if n else None,
            }
        )
    return out


def _model(cases: list[dict[str, Any]], answers: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    rep = _grouped(cases, answers)
    rep["calibration"], rep["floors"] = {}, {}
    for lang in sorted({c["language"] for c in cases}):
        rows = [(c, answers.get(c["id"])) for c in cases if c["language"] == lang]
        rep["calibration"][lang] = _calibration(rows)
        rep["floors"][lang] = _floors(rows)
    return rep


def pair_answers(
    judge: Mapping[str, dict[str, Any]], verifier: Mapping[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """The pair decides only when both models give the same decided answer; else it is unknown (D-478). A case
    either model could not answer is an error of the pair."""
    out: dict[str, dict[str, Any]] = {}
    for cid in set(judge) | set(verifier):
        a, b = judge.get(cid), verifier.get(cid)
        if a is None or b is None or "verdict" not in a or "verdict" not in b:
            out[cid] = {"error": "a model did not answer"}
        elif a["verdict"] == b["verdict"] and a["verdict"] in ("pass", "fail"):
            out[cid] = {"verdict": a["verdict"], "confidence": min(a["confidence"], b["confidence"])}
        else:
            out[cid] = {"verdict": "unknown", "confidence": 0.0}
    return out


def score(cases: list[dict[str, Any]], answers: Mapping[str, Mapping[str, dict[str, Any]]]) -> dict[str, Any]:
    """The report: per model (``answers``: role → case id → answer) and, with a judge and a verifier, for the pair."""
    rep: dict[str, Any] = {"cases": len(cases), "counts": counts(cases), "set": set_hash(cases)}
    rep["models"] = {role: _model(cases, ans) for role, ans in answers.items()}
    if "judge" in answers and "verifier" in answers:
        rep["pair"] = _grouped(cases, pair_answers(answers["judge"], answers["verifier"]))
    return rep


# ------------------------------------------------------------------------------------------------- the command
def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _gateway_clients() -> tuple[Any, Any, Callable[[str], None] | None]:
    """The judge and the verifier as the orchestrator builds them (through this box's gateway), and the gateway's
    swap when the two share one GPU (as ``tools.canary`` does)."""
    from orchestrator.app import verifier_client
    from orchestrator.twophase import GatewaySwap
    from tb_common.audit import AuditLog
    from tb_common.config import get_config
    from tb_common.llm import LlmClient

    cfg = get_config()
    audit = AuditLog(cfg.env.audit_path, cfg.env.tz)
    gs = GatewaySwap.from_env()
    return LlmClient.from_config(audit), verifier_client(audit), (gs.use if gs is not None else None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.accuracy_set", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("out", type=Path)
    g.add_argument("--seed", type=int, default=SEED)
    g.add_argument("--manifest", type=Path, default=None)
    r = sub.add_parser("run")
    r.add_argument("cases", type=Path)
    r.add_argument("out", type=Path)
    s = sub.add_parser("score")
    s.add_argument("cases", type=Path)
    s.add_argument("answers", type=Path)
    s.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        cases = generate(a.seed)
        a.out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")
        man = {"seed": a.seed, "per_class": PER_CLASS, "sha256": set_hash(cases), "counts": counts(cases)}
        if a.manifest:
            a.manifest.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(man, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "run":
        cases = _read(a.cases)
        judge, verifier, swap = _gateway_clients()
        out: dict[str, Any] = {}
        for role, endpoint, client in (("judge", "serving", judge), ("verifier", "verifier", verifier)):
            if client is None:
                continue
            if swap is not None:
                swap(endpoint)
            out[role] = run_model(client, cases)
        a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    rep = score(_read(a.cases), json.loads(a.answers.read_text("utf-8")))
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

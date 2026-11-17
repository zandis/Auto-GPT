# ruff: noqa: E501
# mypy: ignore-errors
# (a measurement tool, D-1037: never imported by the product; Presidio is not a dependency of the box)
"""A second opinion on the note masker (D-1037): Presidio (MIT) against ``tb_common.phi_guard``
(each result names the note masking version it measured).

    uv venv .pv && uv pip install --python .pv/bin/python presidio-analyzer pyyaml \\
        en_core_web_lg@https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl \\
        zh_core_web_sm@https://github.com/explosion/spacy-models/releases/download/zh_core_web_sm-3.8.0/zh_core_web_sm-3.8.0-py3-none-any.whl
    .pv/bin/python tools/phi_second_opinion.py [--out eval/phi_second_opinion/results.json]

Offline (the two spaCy models are local once installed). Presidio runs its English recognisers (spaCy
``en_core_web_lg`` names and places, phones, e-mail, dates) and four of this tool's own for Taiwan charts: a Han
name (spaCy ``zh_core_web_sm`` on each run of Han characters), the national ID's shape, a Taiwan phone and a Taiwan
address in Han or English form, plus a labelled chart number. None of them reads phi_guard's code.

Three sets, all synthetic or public:

* ``tw-en``: English Taiwan charts made here (seeded; every person fictional; IDs with a wrong check digit, so none
  is a real person's; chart numbers from 3, never a real range): English narrative, Han and romanised names,
  Taiwan IDs, phones and addresses, DOB in Western and ROC forms, and decoys (eponyms, drugs, departments).
* ``phi_synth-en``: the 40 English notes of ``eval/phi_synth`` (labelled; their facility, age and visit dates are
  not what the note masker masks, so only names, IDs, phones, addresses, DOB and e-mail are scored).
* ``sigir-en`` and ``sigir-mixed``: the 53 public-domain SIGIR notes of ``eval/criterion_ml`` in English and in the
  code-mixed form (no identifier planted): every span flagged is a candidate false positive.

A planted identifier is ``found`` when the flagged spans cover all of its non-space characters, ``partial`` when
some, ``missed`` when none. A decoy flagged is a false hit."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "libs"), str(ROOT / "services"), str(ROOT)]

# ------------------------------------------------------------------------------------------------ the tw-en set
SURNAMES = [("陳", "Chen"), ("林", "Lin"), ("黃", "Huang"), ("張", "Chang"), ("李", "Lee"), ("王", "Wang"),
            ("吳", "Wu"), ("劉", "Liu"), ("蔡", "Tsai"), ("楊", "Yang"), ("許", "Hsu"), ("鄭", "Cheng"),
            ("謝", "Hsieh"), ("郭", "Kuo"), ("洪", "Hung"), ("曾", "Tseng"), ("邱", "Chiu"), ("廖", "Liao")]  # fmt: skip
GIVEN = [("美玲", "Mei-Ling"), ("志明", "Chih-Ming"), ("雅婷", "Ya-Ting"), ("建宏", "Chien-Hung"),
         ("淑芬", "Shu-Fen"), ("俊傑", "Chun-Chieh"), ("怡君", "Yi-Chun"), ("家豪", "Chia-Hao"),
         ("宗翰", "Tsung-Han"), ("佩珊", "Pei-Shan"), ("冠宇", "Kuan-Yu"), ("惠敏", "Hui-Min")]  # fmt: skip
CITIES = [("臺北市", "大安區", "Taipei City", "Da'an Dist."), ("新北市", "板橋區", "New Taipei City", "Banqiao Dist."),
          ("桃園市", "龜山區", "Taoyuan City", "Guishan Dist."), ("臺中市", "西屯區", "Taichung City", "Xitun Dist."),
          ("高雄市", "苓雅區", "Kaohsiung City", "Lingya Dist.")]  # fmt: skip
ROADS = [
    ("信義路", "Xinyi Rd."),
    ("中山路", "Zhongshan Rd."),
    ("文化一路", "Wenhua 1st Rd."),
    ("民生路", "Minsheng Rd."),
]
SECTIONS = [("", ""), ("二段", "Sec. 2, "), ("四段", "Sec. 4, ")]
LETTER = "ABCDEFGHJKLMNPQRSTUVXYWZIO"  # the ID's letter order (A=10 ... O=35)
DECOYS = ["Parkinson", "Hashimoto", "Cushing", "Glasgow", "Foley", "Norvasc", "脈優", "心臟內科", "Bell's palsy"]


def _bad_id(rng: random.Random) -> str:
    """A Taiwan national ID's shape with a WRONG check digit: never a real person's number."""
    letter = rng.choice(LETTER[:24])
    body = [rng.choice("12")] + [str(rng.randint(0, 9)) for _ in range(7)]
    n = LETTER.index(letter) + 10
    s = n // 10 + (n % 10) * 9 + sum(int(d) * w for d, w in zip(body, range(8, 0, -1), strict=True))
    good = (10 - s % 10) % 10
    return letter + "".join(body) + str((good + rng.randint(1, 9)) % 10)


def _person(rng: random.Random) -> tuple[str, str, str, str]:
    (sh, sl), (gh, gl) = rng.choice(SURNAMES), rng.choice(GIVEN)
    return sh + gh, f"{sl} {gl}", f"{sl.upper()}, {gl.upper()}", sl


def _phone(rng: random.Random) -> str:
    m = f"09{rng.randint(10, 89)}"
    return rng.choice([f"{m}-{rng.randint(100, 999)}-{rng.randint(100, 999)}",
                       f"+886-{m[1:]}-{rng.randint(100, 999)}-{rng.randint(100, 999)}",
                       f"(02){rng.randint(2000, 2999)}-{rng.randint(1000, 9999)}",
                       f"0{rng.randint(2, 8)}-{rng.randint(2000, 2999)}-{rng.randint(1000, 9999)}"])  # fmt: skip


def _address(rng: random.Random) -> str:
    (ch, dh, ce, de), (rh, re_), (sh, se) = rng.choice(CITIES), rng.choice(ROADS), rng.choice(SECTIONS)
    no, fl = rng.randint(1, 399), rng.randint(2, 15)
    return rng.choice([f"{ch}{dh}{rh}{sh}{no}號{fl}樓", f"{fl}F., No. {no}, {se}{re_}, {de}, {ce}"])


def tw_en(n: int = 60, seed: int = 1037) -> list[dict]:
    rng = random.Random(seed)
    notes = []
    for i in range(n):
        han, latin, upper, sur = _person(rng)
        rel_han, rel_latin, _, _ = _person(rng)
        doc_han, doc_latin, _, _ = _person(rng)
        y, mo, d = rng.randint(1935, 1975), rng.randint(1, 12), rng.randint(1, 28)
        dob = rng.choice([f"{y}/{mo:02d}/{d:02d}", f"{y - 1911}/{mo:02d}/{d:02d}", f"民國{y - 1911}年{mo}月{d}日"])
        roc = " (ROC)" if re.fullmatch(r"\d{2}/\d{2}/\d{2}", dob) else ""
        pid, mrn, phone, addr = _bad_id(rng), f"3{rng.randint(0, 9999999):07d}", _phone(rng), _address(rng)
        who = rng.choice([f"Patient: {upper}", f"Patient: {latin}", f"Name: {han} ({latin})", f"姓名: {han}"])
        rel = rng.choice(["daughter", "son", "wife", "husband"])
        decoys = rng.sample(DECOYS, 3)
        bed = f"{rng.randint(5, 12)}{rng.choice('ABC')}-{rng.randint(1, 40):02d}"
        lines = [
            "ADMISSION NOTE",
            who,
            f"Chart No.: {mrn}   ID: {pid}   DOB: {dob}{roc}",
            f"Address: {addr}   Tel: {phone}",
            f"CC: dyspnea on exertion for 3 days. Hx of {decoys[0]} disease and HTN, on {decoys[1]} 5 mg qd.",
            f"PI: This {2024 - y} y/o patient, {sur} family, was brought by {rel} {rel_han} ({rel_latin}). "
            f"Seen at {decoys[2]} OPD by Dr. {doc_latin}; consulted {doc_han} 醫師.",
            f"Bed {bed}. Plan: f/u in 2 wks; contact {rel_latin} at {phone} if needed.",
        ]
        text = "\n".join(lines)
        phi = [(x, t) for x, t in [
            (upper if who.startswith("Patient: " + upper) else latin if "Patient: " in who else han, "name_latin" if "Patient: " in who else "name_han"),
            (mrn, "mrn"), (pid, "id"), (dob, "dob"), (addr, "address"), (phone, "phone"),
            (rel_han, "name_han"), (rel_latin, "name_latin"), (doc_latin, "name_latin"), (doc_han, "name_han"),
        ]]  # fmt: skip
        if who.startswith("Name: "):
            phi.append((latin, "name_latin"))
        notes.append({"i": i, "text": text, "phi": [{"span": s, "type": t} for s, t in phi], "decoys": decoys})
    return notes


# ------------------------------------------------------------------------------------------------ the other sets
SYNTH_TYPES = {"PERSON": "name_latin", "ID": "id", "PHONE": "phone", "ADDRESS": "address", "EMAIL": "email"}


def phi_synth_en() -> list[dict]:
    out = []
    for line in (ROOT / "eval" / "phi_synth" / "notes.jsonl").read_text(encoding="utf-8").splitlines():
        n = json.loads(line)
        if n["lang"] != "en":
            continue
        phi = [{"span": p["span"], "type": SYNTH_TYPES[p["type"]]} for p in n["phi"] if p["type"] in SYNTH_TYPES]
        # a date is scored only as a date of birth (the masker keeps the dates of care)
        for p in n["phi"]:
            if p["type"] == "DATE" and re.search(r"(DOB|born|birth)\W{0,3}" + re.escape(p["span"]), n["text"], re.I):
                phi.append({"span": p["span"], "type": "dob"})
        out.append({"i": n["i"], "text": n["text"], "phi": phi, "decoys": n["decoys"]})
    return out


def sigir(lang: str) -> list[dict]:
    notes = json.loads((ROOT / "eval" / "criterion_ml" / f"notes_{lang}.json").read_text(encoding="utf-8"))
    return [{"i": k, "text": " ".join(v), "phi": [], "decoys": []} for k, v in sorted(notes.items())]


# ------------------------------------------------------------------------------------------------ the detectors
GUARD_KIND = {"name": "name", "phone": "phone", "mrn": "mrn", "id": "id", "dob": "dob", "address": "address",
              "email": "email", "bed": "bed", "room": "room"}  # fmt: skip


def phi_guard_spans(text: str) -> list[tuple[str, int, int]]:
    from tb_common import phi_guard

    return [(GUARD_KIND[k], s, e) for k, s, e in phi_guard.note_spans(text)]


PRESIDIO_KIND = {"PERSON": "name", "PHONE_NUMBER": "phone", "TW_PHONE": "phone", "EMAIL_ADDRESS": "email",
                 "TW_ID": "id", "US_SSN": "id", "US_DRIVER_LICENSE": "id", "US_PASSPORT": "id", "US_BANK_NUMBER": "id",
                 "MEDICAL_LICENSE": "id", "TW_MRN": "mrn", "TW_ADDRESS": "address", "LOCATION": "address",
                 "DATE_TIME": "date", "NRP": "group", "IP_ADDRESS": "id", "URL": "url", "CREDIT_CARD": "id",
                 "IBAN_CODE": "id", "CRYPTO": "id", "UK_NHS": "id", "HAN_PERSON": "name"}  # fmt: skip


def presidio_engine():
    import spacy
    from presidio_analyzer import AnalyzerEngine, EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import PhoneRecognizer

    nlp = NlpEngineProvider(nlp_configuration={"nlp_engine_name": "spacy",
                            "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}]}).create_engine()  # fmt: skip
    engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    zh = spacy.load("zh_core_web_sm")

    class HanPerson(EntityRecognizer):
        def load(self):
            pass

        def analyze(self, text, entities, nlp_artifacts=None):
            out = []
            for m in re.finditer(r"[一-鿿]{2,}", text):
                for ent in zh(m.group()).ents:
                    if ent.label_ == "PERSON":
                        out.append(
                            RecognizerResult("HAN_PERSON", m.start() + ent.start_char, m.start() + ent.end_char, 0.7)
                        )
            return out

    engine.registry.add_recognizer(HanPerson(supported_entities=["HAN_PERSON"], supported_language="en"))
    engine.registry.add_recognizer(PhoneRecognizer(supported_regions=("TW", "US", "UK", "DE", "FR", "JP")))
    pats = {
        "TW_ID": [Pattern("tw id", r"\b[A-Z][12]\d{8}\b", 0.6)],
        "TW_PHONE": [Pattern("tw phone", r"(?:\+886[- ]?9\d{2}[- ]?\d{3}[- ]?\d{3}|\b09\d{2}-?\d{3}-?\d{3}\b|\(0\d\)\s?\d{3,4}-?\d{4}|\b0\d-\d{3,4}-\d{4}\b)", 0.6)],
        "TW_ADDRESS": [Pattern("han address", r"[一-鿿]{1,4}[縣市][一-鿿]{1,4}[區鄉鎮市][一-鿿0-9]{1,8}?(?:路|街|大道)(?:[一二三四五六七八九十]段)?(?:\d+巷)?(?:\d+弄)?\d+號(?:\d+樓)?", 0.7),
                       Pattern("en tw address", r"(?:\d+F\.,\s*)?No\.\s*\d+,\s*(?:Sec\.\s*\d+,\s*)?[A-Z][\w' ]+(?:Rd|St|Ave|Blvd)\.,\s*[A-Z][\w' ]+Dist\.,\s*[A-Z][\w ]+City", 0.7)],
        "TW_MRN": [Pattern("labelled chart number", r"(?:\bMRN|\bChart No\.?|病歷號)\s*[:：#]?\s*[A-Z0-9-]{5,12}", 0.6)],
    }  # fmt: skip
    for ent, p in pats.items():
        engine.registry.add_recognizer(PatternRecognizer(supported_entity=ent, patterns=p, supported_language="en"))
    return engine


def presidio_spans(engine, text: str) -> list[tuple[str, int, int]]:
    res = engine.analyze(text=text, language="en", score_threshold=0.35)
    return [(PRESIDIO_KIND.get(r.entity_type, r.entity_type.lower()), r.start, r.end) for r in res]


# ------------------------------------------------------------------------------------------------ scoring
def _cover(text: str, spans: list[tuple[str, int, int]]) -> list[bool]:
    c = [False] * len(text)
    for _, s, e in spans:
        for j in range(s, e):
            c[j] = True
    return c


def _status(text: str, cov: list[bool], start: int, end: int) -> str:
    idx = [j for j in range(start, end) if not text[j].isspace()]
    hit = sum(cov[j] for j in idx)
    return "found" if hit == len(idx) else "partial" if hit else "missed"


def _locate(text: str, span: str, used: set[int]) -> int:
    pos = text.find(span)
    while pos in used:
        pos = text.find(span, pos + 1)
    used.add(pos)
    return pos


def shape(text: str) -> str:
    """A span's shape, never its value (the results are committed and scanned): A/a for letters, 9 for digits, 漢 for
    a Han character, かカ for kana; punctuation and spaces kept. A word the masker must not touch (a decoy, an
    abbreviation, a department) is kept as written when it is a whole word of :data:`KEEP`."""
    if text in KEEP:
        return text
    out = []
    for ch in text:
        out.append("9" if ch.isdigit() else "A" if "A" <= ch <= "Z" else "a" if "a" <= ch <= "z"
                   else "漢" if "\u4e00" <= ch <= "\u9fff" else "か" if "\u3040" <= ch <= "\u30ff" else ch)  # fmt: skip
    return "".join(out)


KEEP = set(DECOYS) | {"HTN", "OPD", "ROC", "MRN", "ER", "CT", "WBC", "HPF", "Hb", "BAL", "EKG", "CBC", "PMH", "PE",
                      "CXR", "SG", "mIU", "Cardiology", "Pulmonology", "Neurology", "Augmentin", "Apixaban"}  # fmt: skip


def score(name: str, notes: list[dict], engine) -> dict:
    planted: dict[str, Counter] = defaultdict(Counter)
    only: dict[str, list[dict]] = {"presidio_only": [], "phi_guard_only": []}
    decoy_hits: Counter = Counter()
    extra: dict[str, list[dict]] = {"presidio_only": [], "phi_guard_only": []}
    for n in notes:
        t = n["text"]
        g, p = phi_guard_spans(t), presidio_spans(engine, t)
        gc, pc = _cover(t, g), _cover(t, p)
        used: set[int] = set()
        inside = [False] * len(t)
        for ph in n["phi"]:
            s = _locate(t, ph["span"], used)
            if s < 0:
                continue
            e = s + len(ph["span"])
            for j in range(s, e):
                inside[j] = True
            a, b = _status(t, gc, s, e), _status(t, pc, s, e)
            planted[ph["type"]][f"phi_guard_{a}"] += 1
            planted[ph["type"]][f"presidio_{b}"] += 1
            if a != "found" and b == "found":
                only["presidio_only"].append(
                    {"note": n["i"], "type": ph["type"], "shape": shape(ph["span"]), "phi_guard": a}
                )
            if b != "found" and a == "found":
                only["phi_guard_only"].append(
                    {"note": n["i"], "type": ph["type"], "shape": shape(ph["span"]), "presidio": b}
                )
        for dcy in n["decoys"]:
            for m in re.finditer(re.escape(dcy), t):
                decoy_hits[f"phi_guard:{dcy}"] += any(gc[m.start() : m.end()])
                decoy_hits[f"presidio:{dcy}"] += any(pc[m.start() : m.end()])
        # spans one flagged outside every planted identifier and the other did not touch
        for who, mine, other in (("presidio_only", p, gc), ("phi_guard_only", g, pc)):
            for kind, s, e in mine:
                if not any(inside[s:e]) and not any(other[s:e]):
                    extra[who].append({"note": n["i"], "kind": kind, "shape": shape(t[s:e])})
    from tb_common.phi_guard import NOTE_MASK_VERSION

    return {
        "set": name,
        "note_mask_version": NOTE_MASK_VERSION,
        "notes": len(notes),
        "planted": {k: dict(sorted(v.items())) for k, v in sorted(planted.items())},
        "planted_differences": only,
        "decoy_hits": {k: v for k, v in sorted(decoy_hits.items()) if v},
        "unplanted_differences": {
            k: Counter((x["kind"], x["shape"]) for x in v).most_common() for k, v in extra.items()
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "phi_second_opinion" / "results.json")
    a = ap.parse_args()
    engine = presidio_engine()
    sets = [
        ("tw-en", tw_en()),
        ("phi_synth-en", phi_synth_en()),
        ("sigir-en", sigir("en")),
        ("sigir-mixed", sigir("mixed")),
    ]
    results = [score(name, notes, engine) for name, notes in sets]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in results:
        print(r["set"], r["notes"], json.dumps(r["planted"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

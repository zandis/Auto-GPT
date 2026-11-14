"""Deterministic synthetic hospital: HIS-like source tables + ground truth for note criteria and retrieval.

Every patient is fictional. Per-patient "states" are drawn independently per criterion so that every
structured criterion of the GZQO and RA-BIO rulesets has true / false / (where nullable) null cases, and every note
criterion has yes / no / unknown narratives. Numeric values are kept away from rule thresholds (margins below) so
CQL (decimal) and SQL (double) evaluation cannot disagree through rounding.
"""

from __future__ import annotations

import math
import operator
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import yaml

from tools.synth import names_en, names_ja
from tools.synth import notes as N
from tools.synth.catalog import (
    AD_DRUGS,
    AD_DX,
    AD_PRACTITIONERS,
    BIOLOGICS,
    DRUGS,
    DX,
    LABS,
    PRACTITIONERS,
    PROCS,
    RAJAK_DRUGS,
    RAJAK_DX,
)
from tools.synth.lang import PHI_TEMPLATES, Lang
from tools.synth.reserved import is_reserved

Row = dict[str, Any]
STYLES = ("TW", "JP", "EN")  # EN: the TW table layout with English identities and notes (D-743)


@dataclass(frozen=True)
class Find:
    """A note sentence that answers one ruleset criterion (a finding slot, TB-DS-21 §5.1)."""

    text: str
    criterion: str
    value: str


@dataclass(frozen=True)
class Phi:
    """A sentence carrying PHI spans: (type, start, end) relative to ``text``."""

    text: str
    spans: tuple[tuple[str, int, int], ...]


Part = str | Find | Phi


def tw_id_valid(id_no: str) -> bool:
    """True when a Taiwanese national-ID-shaped string has a valid check digit (so it could be a real one)."""
    codes = "ABCDEFGHJKLMNPQRSTUVXYWZIO"  # A=10 ... in issuing order
    if len(id_no) != 10 or id_no[0] not in codes or not id_no[1:].isdigit():
        return False
    n = codes.index(id_no[0]) + 10
    digits = [n // 10, n % 10] + [int(c) for c in id_no[1:]]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
    return sum(d * w for d, w in zip(digits, weights, strict=True)) % 10 == 0


# every planted-state rate lives in one file (TB-DS-21 §3.1), so a check can read the numbers the generator used
RATES: dict[str, dict[str, dict[str, float]]] = yaml.safe_load(
    (Path(__file__).with_name("rates.yaml")).read_text(encoding="utf-8")
)


def rate(archetype: str, attribute: str) -> dict[str, float]:
    """The planted-state weights for ``attribute`` of ``archetype`` patients (``rates.yaml``)."""
    return {str(k): float(v) for k, v in RATES[archetype][attribute].items()}


# thresholds used by the rulesets, per value kind, and the margin kept from each
THRESHOLDS = {
    "bmi": ([24.0, 25.0, 27.0, 30.0], 0.15),
    "urate": ([6.0, 6.8, 7.0], 0.15),
    "egfr": ([30.0, 45.0, 60.0], 1.5),
    "hba1c": ([10.0], 0.2),
    "alt": ([120.0], 5.0),
    "sbp": ([160.0], 2.0),
    "das28": ([2.6, 3.2, 5.1], 0.08),
}


def far(kind: str, value: float) -> bool:
    ths, margin = THRESHOLDS[kind]
    return all(abs(value - t) >= margin for t in ths)


def egfr_ckd_epi_2021(scr: float, age: float, female: bool) -> float:
    kappa = 0.7 if female else 0.9
    alpha = -0.241 if female else -0.302
    ratio = scr / kappa
    val = 142 * min(ratio, 1.0) ** alpha * max(ratio, 1.0) ** -1.200 * 0.9938**age
    return float(val * 1.012 if female else val)


def das28(tjc: int, sjc: int, ptga: float, esr: float | None, crp_mg_l: float | None) -> float:
    base = 0.56 * math.sqrt(tjc) + 0.28 * math.sqrt(sjc) + 0.014 * ptga
    if esr is not None:
        return base + 0.70 * math.log(esr)
    assert crp_mg_l is not None
    return base + 0.36 * math.log(crp_mg_l + 1) + 0.96


@dataclass
class SiteData:
    site_id: str
    ref_date: date
    tables: dict[str, list[Row]]
    note_truth: dict[str, dict[str, str]] = field(default_factory=dict)  # mrn -> criterion -> yes/no/unknown
    human_truth: dict[str, dict[str, str]] = field(default_factory=dict)
    needles: list[Row] = field(default_factory=list)
    states: dict[str, dict[str, str]] = field(default_factory=dict)  # mrn -> planted state per attribute
    seeded_changes: list[Row] = field(default_factory=list)


TABLES = [
    "patient",
    "practitioner",
    "encounter",
    "appointment",
    "diagnosis",
    "lab",
    "vital",
    "medication",
    "procedure",
    "report",
    "note",
    "claim",
    "registry",
]


class Generator:
    def __init__(
        self,
        seed: int,
        site_id: str,
        ref_date: date,
        n: int,
        mrn_prefix: str,
        *,
        style: str = "TW",
        lang_mix: dict[str, float] | None = None,
        gold: bool = False,
        index_offset: int = 0,
        counter_base: int = 0,
        plant_needles: bool = True,
        practitioners: bool = True,
        mix: str = "mix",
    ) -> None:
        """``style``/``lang_mix``/``gold`` default to the original generator (TW records, zh-TW notes, no gold), which
        keeps ``tools/make_fixtures.py`` byte-identical. ``gold=True`` plants PHI spans, alternative date forms and
        safe identifiers and records ``gold_notes`` (TB-DS-21 §5). ``index_offset``/``counter_base`` let
        ``tools.synth_hospital`` write one site in chunks. ``mix`` names the patient mix in ``rates.yaml`` ``site``:
        ``mix`` (the default, unchanged), ``mix_jp_ad`` (the Japanese memory-clinic site of scenario J1, T-503) or
        ``mix_tw_ra`` (the Taiwanese rheumatology site of scenarios T1 to T3, T-504)."""
        if style not in STYLES:
            raise ValueError(f"unknown record style {style!r}")
        self.rng = random.Random(seed)
        # separate streams: language, date form and PHI draws never shift the main stream
        self.lrng = random.Random(f"{seed}:lang")
        self.prng = random.Random(f"{seed}:phi")
        self.style = style
        self.gold = gold
        self.index_offset = index_offset
        self.with_practitioners = practitioners
        self.mix = mix
        self.lang_mix = dict(lang_mix or {"zh-TW": 1.0})
        self.langs = {code: Lang(code, alt_dates=gold, rng=self.lrng) for code in self.lang_mix}
        self.primary_lang = max(self.lang_mix, key=lambda k: self.lang_mix[k])
        self.L = self.langs[self.primary_lang]
        self.note_lang: dict[str, str] = {}  # mrn -> note language
        self.gold_notes: list[Row] = []
        self.site_id = site_id
        self.ref = ref_date
        self.snapshot = ref_date - timedelta(days=1)
        self.n = n
        self.prefix = mrn_prefix
        self.t: dict[str, list[Row]] = {k: [] for k in TABLES}
        self.counters: dict[str, int] = {}
        self.counter_base = counter_base
        self.data = SiteData(site_id, ref_date, self.t)
        self.needle_queue = list(self.L.NEEDLES) if plant_needles else []

    # ---------------------------------------------------------------- helpers
    def nid(self, kind: str) -> str:
        self.counters[kind] = self.counters.get(kind, self.counter_base) + 1
        return f"{kind.upper()}{self.prefix}{self.counters[kind]:07d}"

    def days_ago(self, lo: int, hi: int) -> date:
        """A date between lo and hi days before the snapshot (inclusive)."""
        return self.snapshot - timedelta(days=self.rng.randint(lo, hi))

    def dt(self, d: date) -> str:
        t = time(self.rng.randint(8, 16), self.rng.choice([0, 10, 20, 30, 40, 50]))
        return datetime.combine(d, t).strftime("%Y-%m-%d %H:%M:%S")

    def pick(self, weights: dict[str, float]) -> str:
        keys = list(weights)
        return self.rng.choices(keys, weights=[weights[k] for k in keys])[0]

    def state(self, mrn: str, key: str, value: str) -> str:
        self.data.states.setdefault(mrn, {})[key] = value
        return value

    def encounter(self, mrn: str, d: date, dept: str, staff: str | None = None, typ: str = "OPD") -> str:
        enc = self.nid("e")
        staff = staff or self.staff_for(dept)
        self.t["encounter"].append(
            {
                "enc_no": enc,
                "mrn": mrn,
                "visit_datetime": self.dt(d),
                "dept_code": dept,
                "staff_id": staff,
                "enc_type": typ,
            }
        )
        return enc

    def staff_for(self, dept: str) -> str:
        cands = [p for p, _, dp in PRACTITIONERS + AD_PRACTITIONERS if dp == dept]  # AD depts: only the ad mix
        return self.rng.choice(cands) if cands else PRACTITIONERS[0][0]

    def dx(self, mrn: str, key: str, d: date, dept: str = "FM", enc: str | None = None, status: str = "A") -> None:
        enc = enc or self.encounter(mrn, d, dept)
        code, _ = DX[key] if key in DX else {**AD_DX, **RAJAK_DX}[key]  # archetype codes (T-503, T-504)
        self.t["diagnosis"].append(
            {
                "diag_no": self.nid("d"),
                "enc_no": enc,
                "mrn": mrn,
                "icd10": code,
                "diag_date": d.isoformat(),
                "recorded_date": d.isoformat(),
                "status": status,
            }
        )

    def lab(self, mrn: str, code: str, value: str | float, d: date) -> None:
        name, unit = LABS[code]
        if isinstance(value, float):
            value = f"{value:.2f}".rstrip("0").rstrip(".") if code not in ("HT", "WT") else f"{value:.1f}"
        self.t["lab"].append(
            {
                "lab_no": self.nid("l"),
                "mrn": mrn,
                "local_code": code,
                "item_name": name,
                "result_value": str(value),
                "unit": unit,
                "sample_datetime": self.dt(d),
            }
        )

    def vital(
        self,
        mrn: str,
        d: date,
        height: float | None = None,
        weight: float | None = None,
        sbp: float | None = None,
        dbp: float | None = None,
    ) -> None:
        def fmt(v: float | None) -> str:
            return "" if v is None else f"{v:.1f}".rstrip("0").rstrip(".")

        self.t["vital"].append(
            {
                "vital_no": self.nid("v"),
                "mrn": mrn,
                "measure_datetime": self.dt(d),
                "height_cm": fmt(height),
                "weight_kg": fmt(weight),
                "sbp": fmt(sbp),
                "dbp": fmt(dbp),
            }
        )

    def rx(self, mrn: str, key: str, start: date, end: date, dept: str = "FM", status: str = "active") -> None:
        drug = DRUGS[key] if key in DRUGS else {**AD_DRUGS, **RAJAK_DRUGS}[key]
        self.t["medication"].append(
            {
                "rx_no": self.nid("m"),
                "mrn": mrn,
                "nhi_drug_code": drug.nhi_code,
                "atc": drug.atc,
                "drug_name": drug.name,
                "order_date": start.isoformat(),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily_dose": drug.dose,
                "dose_unit": drug.unit,
                "status": status,
                "dept_code": dept,
            }
        )

    def rx_course(self, mrn: str, key: str, start: date, total_days: int, gap: int = 0, dept: str = "FM") -> None:
        """Consecutive 28-day refills from ``start`` covering ``total_days`` with ``gap`` days between refills."""
        d = start
        remaining = total_days
        while remaining > 0:
            length = min(28, remaining)
            end = d + timedelta(days=length - 1)
            if end > self.snapshot:
                end = self.snapshot
            if d > self.snapshot:
                break
            self.rx(mrn, key, d, end, dept)
            remaining -= length
            d = end + timedelta(days=1 + gap)

    def note(self, mrn: str, d: date, dept: str, body: list[Part], note_type: str = "progress") -> str:
        lang = self.L
        enc = self.encounter(mrn, d, dept)
        parts: list[Part] = [lang.filler(self.rng, self.rng.randint(4, 9))]
        parts.extend(body)
        parts.append(lang.filler(self.rng, self.rng.randint(5, 11)))
        if self.needle_queue and self.rng.random() < 0.06 and lang.code == self.primary_lang:
            sentence, query = self.needle_queue.pop(0)
            parts.insert(self.rng.randint(1, len(parts)), sentence + lang.stop)
            note_no = self.nid("n")
            self.data.needles.append({"mrn": mrn, "query": query, "fragment": sentence, "note_no": note_no})
        else:
            note_no = self.nid("n")
        self.t["note"].append(
            {
                "note_no": note_no,
                "mrn": mrn,
                "enc_no": enc,
                "note_datetime": self.dt(d),
                "note_type": note_type,
                "text": self.assemble(note_no, mrn, d, parts),
            }
        )
        return note_no

    def assemble(self, note_no: str, mrn: str, d: date, parts: list[Part]) -> str:
        """Join the note parts; in gold mode also plant PHI and record findings and spans (code points, end excl.)."""
        if not self.gold:
            return "".join(p if isinstance(p, str) else p.text for p in parts)
        phi = self.phi_sentences(mrn, d)
        for chunk in phi:
            parts.insert(self.prng.randint(0, len(parts)), chunk)
        text: list[str] = []
        findings: list[Row] = []
        spans: list[Row] = []
        pos = 0
        for p in parts:
            t = p if isinstance(p, str) else p.text
            if isinstance(p, Find):
                findings.append({"criterion": p.criterion, "value": p.value, "start": pos, "end": pos + len(t)})
            elif isinstance(p, Phi):
                spans.extend({"type": k, "start": pos + a, "end": pos + b} for k, a, b in p.spans)
            text.append(t)
            pos += len(t)
        self.gold_notes.append(
            {"note_no": note_no, "mrn": mrn, "lang": self.L.code, "findings": findings, "phi": spans}
        )
        return "".join(text)

    def phi_sentences(self, mrn: str, d: date) -> list[Phi]:
        """PHI written the way it appears in real notes (signature, family call, referral), rates in ``rates.yaml``."""
        rates = RATES["phi"]
        r = self.prng
        if r.random() >= float(rates["note_rate"]["carries"]):
            return []
        row = self.patient_row(mrn)
        tpl = PHI_TEMPLATES[self.L.code]
        out: list[Phi] = []
        for kind, p in rates["types"].items():
            if r.random() >= float(p):
                continue
            if kind == "name":
                key = r.choice(["name", "family"])
                value = row["name"] if key == "family" else self.fake_person_name(r)
            else:
                key = kind
                getters: dict[str, Callable[[], str]] = {
                    "date": lambda: self.L.fmt_date(d),
                    "chart": lambda: mrn,
                    "phone": lambda: str(row["phone"]),
                    "address": lambda: self.fake_address(r),
                    "insurer": lambda: str(row["id_no"]),
                    "hospital": lambda: self.fake_hospital(r),
                }
                value = getters[kind]()
            before, after = tpl[key].split("{" + key.replace("family", "name") + "}")
            out.append(Phi(before + value + after, ((kind, len(before), len(before) + len(value)),)))
        return out

    def patient_row(self, mrn: str) -> Row:
        return next(r for r in reversed(self.t["patient"]) if r["mrn"] == mrn)

    def fake_person_name(self, r: random.Random, sex: str | None = None) -> str:
        name = self._person_name(r, sex)
        while self.gold and is_reserved("name", name):
            name = self._person_name(self.prng, sex)
        return name

    def _person_name(self, r: random.Random, sex: str | None = None) -> str:
        sex = sex or r.choice("MF")
        if self.L.code == "ja" or (self.style == "JP" and self.L.code != "en"):
            fam = r.choice(names_ja.FAMILY)[0]
            giv = r.choice(names_ja.GIVEN_M if sex == "M" else names_ja.GIVEN_F)[0]
            return f"{fam}　{giv}"
        if self.L.code == "en":
            return f"{r.choice(names_en.GIVEN_M if sex == 'M' else names_en.GIVEN_F)} {r.choice(names_en.FAMILY)}"
        return N.fake_name(r)

    def fake_address(self, r: random.Random) -> str:
        if self.L.code == "en":
            return f"{r.randint(1, 199)} {r.choice(names_en.STREETS)}, {r.choice(names_en.CITIES)}"
        if self.L.code == "ja":
            return f"{r.choice(names_ja.CITIES)}{r.choice(names_ja.TOWNS)}{r.randint(1, 9)}丁目{r.randint(1, 30)}番"
        return (
            f"{r.choice(['虛擬市', '範例市', '測試市'])}{r.choice(['中正路', '民生路', '和平路'])}{r.randint(1, 300)}號"
        )

    def fake_hospital(self, r: random.Random) -> str:
        if self.L.code == "en":
            return r.choice(names_en.HOSPITALS)
        if self.L.code == "ja":
            return r.choice(names_ja.HOSPITALS)
        return r.choice(["杏林綜合醫院", "青山診所", "晨光紀念醫院"])

    def appointment(self, mrn: str, days_ahead: int, dept: str, staff: str | None = None, status: str = "B") -> None:
        d = self.ref + timedelta(days=days_ahead)
        self.t["appointment"].append(
            {
                "appt_no": self.nid("a"),
                "mrn": mrn,
                "appt_datetime": self.dt(d),
                "duration_min": self.rng.choice([10, 15, 20, 30]),
                "staff_id": staff or self.staff_for(dept),
                "dept_code": dept,
                "status": status,
            }
        )

    # ---------------------------------------------------------------- patients
    def patient(self, i: int, sex: str, age: int) -> str:
        mrn = f"{self.prefix}{i:07d}"
        bdate = self.snapshot - timedelta(days=int(age * 365.25) + self.rng.randint(15, 340))
        if bdate.month == 2 and bdate.day == 29:
            bdate = bdate.replace(day=28)
        if len(self.langs) > 1:
            codes = list(self.lang_mix)
            self.L = self.langs[self.lrng.choices(codes, weights=[self.lang_mix[c] for c in codes])[0]]
        self.note_lang[mrn] = self.L.code
        if self.style == "JP":
            name, id_no, phone = self.jp_identity(sex)
        elif self.style == "EN":
            name, id_no, phone = self.en_identity(sex)
        else:
            letter = self.rng.choice("ABCDEFGHJKLMNPQRSTUVXYWZIO")
            name = N.fake_name(self.rng) if self.L.code != "en" else self.fake_person_name(self.rng, sex)
            id_no = f"{letter}{1 if sex == 'M' else 2}{self.rng.randint(10_000_000, 99_999_999)}"
            phone = f"09{self.rng.randint(10_000_000, 99_999_999)}"
            if self.gold and tw_id_valid(id_no):  # never a number that could be issued to a real person
                id_no = id_no[:-1] + str((int(id_no[-1]) + 1) % 10)
        while self.gold and is_reserved("name", name):  # never a well-known real person's name
            name = self.fake_person_name(self.prng, sex)
        self.t["patient"].append(
            {
                "mrn": mrn,
                "name": name,
                "id_no": id_no,
                "birth_date": bdate.isoformat(),
                "sex": sex,
                "death_date": "",
                "phone": phone,
            }
        )
        if self.rng.random() < 0.65:
            self.t["registry"].append(
                {
                    "mrn": mrn,
                    "consent_contact": "Y" if self.rng.random() < 0.8 else "N",
                    "consent_date": self.days_ago(30, 900).isoformat(),
                }
            )
        return mrn

    def en_identity(self, sex: str) -> tuple[str, str, str]:
        """English name, an identifier of no country (``SYN`` and seven digits: not a national number's form) and a
        phone number of 555-0100 to 555-0199, the range kept for fiction (D-743)."""
        name = self.fake_person_name(self.rng, sex)
        return name, f"SYN{self.rng.randint(1_000_000, 9_999_999)}", f"555-01{self.rng.randint(0, 99):02d}"

    def jp_identity(self, sex: str) -> tuple[str, str, str]:
        """Japanese name (kanji), insurer number and phone. Insurer numbers use 法別番号 00, which is never issued."""
        if self.L.code == "en":
            name = self.fake_person_name(self.rng, sex)
        else:
            fam = self.rng.choice(names_ja.FAMILY)[0]
            giv = self.rng.choice(names_ja.GIVEN_M if sex == "M" else names_ja.GIVEN_F)[0]
            name = f"{fam}　{giv}"
        insurer = f"00{self.rng.randint(100_000, 999_999)}"
        phone = f"0{self.rng.choice([70, 80, 90])}-{self.rng.randint(1000, 9999)}-{self.rng.randint(1000, 9999)}"
        return name, insurer, phone

    def age_of(self, mrn: str) -> float:
        row = next(r for r in reversed(self.t["patient"]) if r["mrn"] == mrn)
        b = date.fromisoformat(row["birth_date"])
        return (self.ref - b).days / 365.25

    def anthropometrics(self, mrn: str, sex: str, state: str) -> None:
        if state == "missing":
            return
        h = self.rng.gauss(170 if sex == "M" else 158, 6)
        bands = {
            "<24": (19.0, 23.8),
            "24-25": (24.2, 24.8),
            "25-27": (25.2, 26.8),
            "27-30": (27.2, 29.8),
            ">30": (30.2, 39.0),
            "stale": (26.0, 33.0),
            "no_height": (27.5, 33.0),
        }
        lo, hi = bands[state]
        for _ in range(200):
            bmi = self.rng.uniform(lo, hi)
            w = round(bmi * (round(h, 1) / 100) ** 2, 1)
            real = w / (round(h, 1) / 100) ** 2
            if lo <= real <= hi and far("bmi", real):
                break
        if state == "stale":
            self.vital(mrn, self.days_ago(400, 700), height=round(h, 1), weight=w)
            return
        d = self.days_ago(5, 300)
        if state != "no_height":
            hd = d - timedelta(days=self.rng.randint(0, 50))
            if hd == d:
                self.vital(mrn, d, height=round(h, 1), weight=w)
            else:
                self.vital(mrn, hd, height=round(h, 1))
                self.vital(mrn, d, weight=w)
        else:
            self.vital(mrn, self.days_ago(420, 600), height=round(h, 1))
            self.vital(mrn, d, weight=w)
        if self.rng.random() < 0.5:  # older weight, must not be "latest"
            self.vital(
                mrn,
                d - timedelta(days=self.rng.randint(60, 200)),
                weight=round(w * self.rng.uniform(0.9, 1.1), 1),
            )

    def series(
        self,
        mrn: str,
        code: str,
        state: str,
        kind: str,
        good: tuple[float, float],
        bad: tuple[float, float],
        window: int,
    ) -> None:
        """Plant a lab series whose latest value inside ``window`` days is in ``good``/``bad`` (or absent)."""
        put: Any = self.lab
        if code == "SBP":

            def put(m: str, _c: str, v: float, d: date) -> None:
                self.vital(m, d, sbp=round(v), dbp=self.rng.randint(58, 98))

        if state == "missing":
            return
        if state == "stale":
            put(mrn, code, self.rng.uniform(*bad), self.days_ago(window + 20, window + 300))
            return
        rng_ = good if state == "good" else bad
        for _ in range(100):
            v = round(self.rng.uniform(*rng_), 2 if code != "SBP" else 0)
            if far(kind, v):
                break
        latest = self.days_ago(3, window - 5)
        put(mrn, code, v, latest)
        for _ in range(self.rng.randint(0, 2)):  # earlier, not latest; may be either side
            other = round(self.rng.uniform(min(good[0], bad[0]), max(good[1], bad[1])), 2 if code != "SBP" else 0)
            put(mrn, code, other, latest - timedelta(days=self.rng.randint(15, 400)))

    def creatinine(self, mrn: str, sex: str, state: str) -> None:
        if state == "missing":
            return
        age = self.age_of(mrn)
        female = sex == "F"
        for _ in range(500):
            scr = round(self.rng.uniform(0.5, 1.6) if state == "normal" else self.rng.uniform(2.2, 5.0), 2)
            e = egfr_ckd_epi_2021(scr, age, female)
            if far("egfr", e) and ((state == "normal" and e > 30) or (state == "low" and e < 30)):
                break
        self.lab(mrn, "CRE", scr, self.days_ago(5, 330))

    # ---------------------------------------------------------------- archetypes
    def gout_patient(self, i: int) -> None:
        g = self.state
        sex = "M" if self.rng.random() < 0.85 else "F"
        age = self.rng.randint(15, 17) if self.rng.random() < 0.04 else self.rng.randint(25, 82)
        mrn = self.patient(i, sex, age)
        g(mrn, "archetype", "gout")
        dept_main = self.rng.choice(["RHEU", "RHEU", "META", "FM"])
        if g(mrn, "gout_dx", self.pick(rate("gout", "gout_dx"))) == "coded":
            onset = self.days_ago(200, 4500)
            self.dx(mrn, self.rng.choice(["gout", "gout_foot", "gout_chronic"]), onset, dept_main)
            for _ in range(self.rng.randint(0, 3)):
                self.dx(mrn, "gout", self.days_ago(10, 700), dept_main)
        # visits to RHEU/META in the last 12 months (GZQO-INC-09: >= 1)
        visits = g(mrn, "rheu_meta_visits", self.pick(rate("gout", "rheu_meta_visits")))
        for _ in range({"0": 0, "1": 1, "3+": self.rng.randint(3, 6)}[visits]):
            self.encounter(mrn, self.days_ago(5, 350), self.rng.choice(["RHEU", "META"]))
        if visits == "0":
            self.encounter(mrn, self.days_ago(380, 900), "RHEU")
            self.encounter(mrn, self.days_ago(10, 300), "FM")
        self.anthropometrics(
            mrn,
            sex,
            g(
                mrn,
                "bmi",
                self.pick(rate("gout", "bmi")),
            ),
        )
        self.series(
            mrn,
            "UA",
            g(mrn, "urate", self.pick(rate("gout", "urate"))),
            "urate",
            (7.0, 11.5),
            (3.5, 6.6),
            365,
        )
        self.creatinine(mrn, sex, g(mrn, "creatinine", self.pick(rate("gout", "creatinine"))))
        self.series(
            mrn,
            "HBA1C",
            g(mrn, "hba1c", self.pick(rate("gout", "hba1c"))),
            "hba1c",
            (5.0, 9.6),
            (10.3, 13.5),
            180,
        )
        self.series(
            mrn,
            "ALT",
            g(mrn, "alt", self.pick(rate("gout", "alt"))),
            "alt",
            (8, 95),
            (130, 420),
            180,
        )
        self.series(
            mrn,
            "SBP",
            g(mrn, "sbp", self.pick(rate("gout", "sbp"))),
            "sbp",
            (100, 156),
            (163, 195),
            90,
        )
        # urate-lowering therapy (GZQO-INC-06: continuous >= 90 d within [-180, 0], gaps <= 30)
        ult = g(
            mrn,
            "ult",
            self.pick(rate("gout", "ult")),
        )
        drug = self.rng.choice(["allopurinol", "febuxostat", "benzbromarone"])
        if ult == "long":
            self.rx_course(mrn, drug, self.days_ago(200, 400), 500, 0, dept_main)
        elif ult == "short":
            self.rx_course(mrn, drug, self.days_ago(40, 70), 60, 0, dept_main)
        elif ult == "gappy_ok":
            self.rx_course(mrn, drug, self.days_ago(170, 175), 175, self.rng.randint(5, 25), dept_main)
        elif ult == "gappy_bad":
            self.rx(mrn, drug, self.days_ago(178, 178), self.days_ago(130, 130), dept_main)
            self.rx(mrn, drug, self.days_ago(80, 80), self.days_ago(30, 30), dept_main)
        elif ult == "old":
            self.rx_course(mrn, drug, self.days_ago(500, 700), 150, 0, dept_main)
        if self.rng.random() < 0.5:
            self.rx(mrn, "colchicine", self.days_ago(20, 300), self.days_ago(0, 15), dept_main)
        self.common_exclusions(mrn, sex, age)
        # notes: flares (INC-05), current flare (EXC-11), injection willingness (INC-07, human)
        flare = g(mrn, "flare_12m", self.pick(rate("gout", "flare_12m")))
        truth = self.data.note_truth.setdefault(mrn, {})
        if flare == "two_plus":
            for _ in range(self.rng.randint(2, 3)):
                fd = self.days_ago(20, 330)
                self.note(
                    mrn,
                    fd + timedelta(days=self.rng.randint(1, 10)),
                    dept_main,
                    [Find(self.L.flare(fd, self.rng.choice(self.L.JOINTS)), "GZQO-INC-05", "yes")],
                )
            truth["GZQO-INC-05"] = "yes"
        elif flare == "single":
            fd = self.days_ago(30, 300)
            self.note(mrn, self.days_ago(5, 25), dept_main, [Find(self.L.single_flare(fd), "GZQO-INC-05", "no")])
            truth["GZQO-INC-05"] = "no"
        elif flare == "none":
            self.note(mrn, self.days_ago(5, 80), dept_main, [Find(self.L.no_flare(), "GZQO-INC-05", "no")])
            truth["GZQO-INC-05"] = "no"
        else:
            self.note(mrn, self.days_ago(5, 200), dept_main, [])
            truth["GZQO-INC-05"] = "unknown"
        cur = g(mrn, "current_flare", self.pick(rate("gout", "current_flare")))
        if cur == "current":
            self.note(mrn, self.days_ago(1, 10), dept_main, [Find(self.L.current_flare(), "GZQO-EXC-11", "yes")])
            truth["GZQO-EXC-11"] = "yes"
        elif cur == "none":
            self.note(mrn, self.days_ago(1, 12), dept_main, [Find(self.L.no_current_flare(), "GZQO-EXC-11", "no")])
            truth["GZQO-EXC-11"] = "no"
        else:
            truth["GZQO-EXC-11"] = "unknown"
        inj = self.pick(rate("gout", "injection"))
        if inj != "no_info":
            sentence = Find(self.L.injection(inj == "willing"), "GZQO-INC-07", inj)
            self.note(mrn, self.days_ago(5, 90), dept_main, [sentence])
        self.data.human_truth.setdefault(mrn, {})["GZQO-INC-07"] = inj
        self.appointments(mrn, dept_main, screen=True)

    def common_exclusions(self, mrn: str, sex: str, age: int) -> None:
        g = self.state
        if g(mrn, "t1dm", self.pick(rate("gout", "t1dm"))) == "yes":
            self.dx(mrn, "t1dm", self.days_ago(300, 4000), "META")
        elif self.rng.random() < 0.25:
            self.dx(mrn, "t2dm", self.days_ago(100, 3000), "META")
            self.rx_course(mrn, "metformin", self.days_ago(100, 300), 200, 0, "META")
        if g(mrn, "pancreatitis", self.pick(rate("gout", "pancreatitis"))) != "no":
            key = "pancreatitis_acute" if self.data.states[mrn]["pancreatitis"] == "acute" else "pancreatitis_chronic"
            self.dx(mrn, key, self.days_ago(100, 3000), "FM")
        if g(mrn, "mtc_men2", self.pick(rate("gout", "mtc_men2"))) != "no":
            self.dx(mrn, "mtc" if self.data.states[mrn]["mtc_men2"] == "mtc" else "men2", self.days_ago(200, 3000))
        glp = g(mrn, "glp1", self.pick(rate("gout", "glp1")))
        if glp != "no":
            d = self.days_ago(5, 80) if glp == "recent" else self.days_ago(100, 400)
            self.rx(
                mrn,
                self.rng.choice(["semaglutide", "liraglutide", "dulaglutide", "tirzepatide"]),
                d,
                d + timedelta(days=27),
                "META",
            )
        if g(mrn, "bariatric", self.pick(rate("gout", "bariatric"))) == "yes":
            code, name = PROCS[self.rng.choice(["bariatric_sleeve", "bariatric_bypass"])]
            self.t["procedure"].append(
                {
                    "proc_no": self.nid("p"),
                    "mrn": mrn,
                    "order_code": code,
                    "proc_name": name,
                    "proc_date": self.days_ago(200, 3000).isoformat(),
                }
            )
        mal = g(mrn, "malignancy", self.pick(rate("gout", "malignancy")))
        if mal == "recent":
            self.dx(mrn, self.rng.choice(["breast_ca", "colon_ca", "lung_ca"]), self.days_ago(30, 1700), "ONC")
        elif mal == "old":
            self.dx(mrn, self.rng.choice(["breast_ca", "colon_ca"]), self.days_ago(1900, 3500), "ONC")
        elif mal == "skin":
            self.dx(mrn, "skin_bcc", self.days_ago(30, 1000), "FM")
        if sex == "F" and 18 <= age <= 45:
            preg = g(mrn, "pregnancy", self.pick(rate("gout", "pregnancy")))
            if preg == "dx":
                self.dx(mrn, "pregnancy", self.days_ago(10, 200), "FM")
            elif preg == "hcg_pos":
                self.lab(mrn, "HCGU", "POS", self.days_ago(2, 25))
            elif preg == "hcg_neg":
                self.lab(mrn, "HCGU", "NEG", self.days_ago(2, 25))
        cv = g(mrn, "mi_stroke", self.pick(rate("gout", "mi_stroke")))
        if cv != "no":
            d = self.days_ago(5, 80) if cv == "recent" else self.days_ago(120, 1500)
            self.dx(mrn, self.rng.choice(["ami", "stroke"]), d, "CARD")
        for key in ("htn", "hld", "ckd3", "oa_knee", "gerd"):
            if self.rng.random() < 0.2:
                self.dx(mrn, key, self.days_ago(30, 2000), self.rng.choice(["FM", "CARD", "NEPH", "ORTH"]))

    def appointments(self, mrn: str, dept: str, screen: bool) -> None:
        r = self.rng.random()
        if dept in ("RHEU", "META") and screen:
            if r < 0.35:
                self.appointment(mrn, self.rng.randint(0, 13), dept)
            elif r < 0.7:
                self.appointment(mrn, self.rng.randint(14, 175), dept)
            elif r < 0.75:
                self.appointment(mrn, self.rng.randint(1, 13), dept, status="C")
        elif r < 0.4:
            self.appointment(mrn, self.rng.randint(0, 175), dept)

    def ra_patient(self, i: int) -> None:
        g = self.state
        sex = "F" if self.rng.random() < 0.75 else "M"
        age = self.rng.randint(14, 17) if self.rng.random() < 0.03 else self.rng.randint(25, 80)
        mrn = self.patient(i, sex, age)
        g(mrn, "archetype", "ra")
        dx_state = g(mrn, "ra_dx", self.pick(rate("ra", "ra_dx")))
        if dx_state == "long":
            self.dx(mrn, self.rng.choice(["ra_seropos", "ra_other"]), self.days_ago(200, 4000), "RHEU")
        elif dx_state == "recent":
            self.dx(mrn, "ra_other", self.days_ago(10, 150), "RHEU")
        for _ in range(self.rng.randint(1, 4)):
            enc_d = self.days_ago(5, 360)
            if dx_state == "long":
                self.dx(mrn, "ra_other", enc_d, "RHEU")
            else:
                self.encounter(mrn, enc_d, "RHEU")
        for drug_state_key, drugs in (
            ("mtx", ["methotrexate"]),
            ("csdmard2", ["hydroxychloroquine", "sulfasalazine", "leflunomide"]),
        ):
            st = g(mrn, drug_state_key, self.pick(rate("ra", drug_state_key)))
            drug = self.rng.choice(drugs)
            if st == "long":
                self.rx_course(mrn, drug, self.days_ago(250, 700), self.rng.randint(200, 600), 0, "RHEU")
            elif st == "short":
                self.rx_course(mrn, drug, self.days_ago(100, 400), 120, 0, "RHEU")
            elif st == "gappy_bad":
                start = self.days_ago(500, 600)
                self.rx_course(mrn, drug, start, 100, 0, "RHEU")
                self.rx_course(mrn, drug, start + timedelta(days=160), 100, 0, "RHEU")
        if self.rng.random() < 0.4:
            self.rx_course(mrn, "prednisolone", self.days_ago(60, 200), 120, 0, "RHEU")
        # DAS28 assessments: recent window [-90,0] (INC-04, REN) and earlier window [-180,-30] (INC-05)
        recent = g(
            mrn,
            "das28_recent",
            self.pick(rate("ra", "das28_recent")),
        )
        use_esr = self.rng.random() < 0.7
        g(mrn, "das28_marker", "esr" if use_esr else "crp")
        self.das28_assessment(mrn, recent, self.days_ago(3, 80), use_esr)
        earlier = g(mrn, "das28_earlier", self.pick(rate("ra", "das28_earlier")))
        self.das28_assessment(mrn, earlier, self.days_ago(100, 175), use_esr)
        self.ra_safety(mrn, sex, age)
        self.ra_claims(mrn)
        # documentation items
        if g(mrn, "doc_hbsag", self.pick(rate("ra", "doc_hbsag"))) == "yes":
            self.lab(mrn, "HBSAG", self.data.states[mrn].get("hbv_result", "NEG"), self.days_ago(10, 340))
        if g(mrn, "doc_ahbc", self.pick(rate("ra", "doc_ahbc"))) == "yes":
            self.lab(mrn, "AHBC", self.rng.choice(["NEG", "NEG", "POS"]), self.days_ago(10, 340))
        tbdoc = g(mrn, "doc_tb", self.pick(rate("ra", "doc_tb")))
        if tbdoc == "cxr":
            self.report(mrn, self.days_ago(10, 170), self.L.CXR_CLEAR)
        elif tbdoc == "igra" and "igra_done" not in self.data.states[mrn]:
            self.lab(mrn, "IGRA", "NEG", self.days_ago(10, 170))
        # note: response to biologic (REN-02)
        resp = g(mrn, "response", self.pick(rate("ra", "response")))
        truth = self.data.note_truth.setdefault(mrn, {})
        if resp == "good":
            self.note(
                mrn,
                self.days_ago(3, 80),
                "RHEU",
                [Find(self.L.response(self.rng.uniform(1.3, 2.8), True), "RA-BIO-REN-02", "yes")],
            )
            truth["RA-BIO-REN-02"] = "yes"
        elif resp == "poor":
            self.note(
                mrn,
                self.days_ago(3, 80),
                "RHEU",
                [Find(self.L.response(self.rng.uniform(0.1, 0.9), False), "RA-BIO-REN-02", "no")],
            )
            truth["RA-BIO-REN-02"] = "no"
        else:
            self.note(mrn, self.days_ago(3, 200), "RHEU", [])
            truth["RA-BIO-REN-02"] = "unknown"
        r = self.rng.random()
        if r < 0.6:
            self.appointment(mrn, self.rng.randint(0, 13), "RHEU", self.rng.choice(["P12345", "P23456"]))
        elif r < 0.85:
            self.appointment(mrn, self.rng.randint(14, 120), "RHEU")

    def das28_assessment(self, mrn: str, state: str, d: date, use_esr: bool) -> None:
        if state == "none":
            return
        bands = {
            "high": (5.25, 7.5),
            "moderate": (3.35, 4.95),
            "low": (1.5, 3.05),
            "missing_component": (3.5, 6.0),
        }
        lo, hi = bands[state]
        for _ in range(2000):
            tjc, sjc = self.rng.randint(0, 22), self.rng.randint(0, 16)
            ptga = self.rng.randint(5, 95)
            esr = round(self.rng.uniform(4, 95), 0) if use_esr else None
            crp = round(self.rng.uniform(0.05, 6.0), 2) if not use_esr else None  # mg/dL in HIS
            val = das28(tjc, sjc, ptga, esr, None if crp is None else crp * 10)
            if lo <= val <= hi and far("das28", val):
                break
        self.lab(mrn, "TJC28", str(tjc), d)
        self.lab(mrn, "SJC28", str(sjc), d)
        if state != "missing_component":
            self.lab(mrn, "PTGA", str(ptga), d)
        if use_esr:
            self.lab(mrn, "ESR", str(int(esr or 0)), d)
        else:
            self.lab(mrn, "CRP", float(crp or 0), d)
        self.note(mrn, d, "RHEU", [self.L.ra_assessment(tjc, sjc, ptga)])

    def report(self, mrn: str, d: date, conclusion: str) -> None:
        self.t["report"].append(
            {
                "rpt_no": self.nid("r"),
                "mrn": mrn,
                "exam_code": "RAD-CXR",
                "exam_name": "Chest X-ray PA",
                "exam_date": d.isoformat(),
                "conclusion": conclusion,
            }
        )

    def ra_safety(self, mrn: str, sex: str, age: int) -> None:
        g = self.state
        tb = g(
            mrn,
            "tb",
            self.pick(rate("ra", "tb")),
        )
        if tb == "active":
            self.dx(mrn, "tb_pulm", self.days_ago(10, 300), "FM")
        elif tb.startswith("igra_pos"):
            self.lab(mrn, "IGRA", "POS", self.days_ago(20, 150))
            self.data.states[mrn]["igra_done"] = "1"
            if tb == "igra_pos_treated":
                self.rx_course(mrn, "isoniazid", self.days_ago(15, 120), 270, 0, "FM")
        elif tb == "igra_neg":
            self.lab(mrn, "IGRA", "NEG", self.days_ago(20, 300))
            self.data.states[mrn]["igra_done"] = "1"
        hbv = g(mrn, "hbv", self.pick(rate("ra", "hbv")))
        if hbv.startswith("pos"):
            self.data.states[mrn]["hbv_result"] = "POS"
            self.lab(mrn, "HBSAG", "POS", self.days_ago(30, 300))
            self.dx(mrn, "hbv_chronic", self.days_ago(100, 2000), "FM")
            if hbv == "pos_av":
                self.rx_course(mrn, "entecavir", self.days_ago(60, 85), 120, 0, "FM")
        elif hbv == "neg":
            self.lab(mrn, "HBSAG", "NEG", self.days_ago(30, 300))
        mal = g(mrn, "malignancy", self.pick(rate("ra", "malignancy")))
        if mal == "recent":
            self.dx(mrn, "breast_ca", self.days_ago(60, 1500), "ONC")
        elif mal == "old":
            self.dx(mrn, "colon_ca", self.days_ago(1900, 3000), "ONC")
        if sex == "F" and 18 <= age <= 45 and g(mrn, "pregnancy", self.pick(rate("ra", "pregnancy"))) == "dx":
            self.dx(mrn, "pregnancy", self.days_ago(10, 200), "FM")
        inf = g(mrn, "infection", self.pick(rate("ra", "infection")))
        if inf != "no":
            d = {
                "recent": self.days_ago(3, 25),
                "mid": self.days_ago(40, 170),
                "old": self.days_ago(200, 900),
            }[inf]
            self.dx(mrn, self.rng.choice(["sepsis", "pneumonia"]), d, "FM")
        if g(mrn, "hf", self.pick(rate("ra", "hf"))) == "yes":
            self.dx(mrn, "hf", self.days_ago(60, 2000), "CARD")

    def ra_claims(self, mrn: str) -> None:
        g = self.state
        st = g(
            mrn,
            "approval",
            self.pick(rate("ra", "approval")),
        )
        bio = DRUGS[self.rng.choice(BIOLOGICS)]
        if st == "none":
            return
        if st in ("active_far", "renewal_due", "expired"):
            if st == "active_far":
                end = self.ref + timedelta(days=self.rng.randint(60, 150))
            elif st == "renewal_due":
                end = self.ref + timedelta(days=self.rng.randint(3, 40))
            else:
                end = self.ref - timedelta(days=self.rng.randint(20, 200))
            start = end - timedelta(days=180)
            created = start - timedelta(days=self.rng.randint(10, 25))
            self.t["claim"].append(
                {
                    "claim_no": self.nid("c"),
                    "mrn": mrn,
                    "created_date": created.isoformat(),
                    "product_code": bio.nhi_code,
                    "apply_type": "1",
                    "outcome": "approved",
                    "approval_start": start.isoformat(),
                    "approval_end": end.isoformat(),
                }
            )
            self.rx_course(mrn, bio.key, max(start, self.days_ago(170, 175)), 170, 0, "RHEU")
        else:
            created = self.days_ago(5, 80)
            self.t["claim"].append(
                {
                    "claim_no": self.nid("c"),
                    "mrn": mrn,
                    "created_date": created.isoformat(),
                    "product_code": bio.nhi_code,
                    "apply_type": "1",
                    "outcome": "pending" if st == "pending_recent" else "denied",
                    "approval_start": "",
                    "approval_end": "",
                }
            )

    def onc_patient(self, i: int) -> None:
        sex = self.rng.choice("MF")
        mrn = self.patient(i, sex, self.rng.randint(45, 82))
        self.state(mrn, "archetype", "onc")
        self.dx(mrn, "nsclc_egfr", self.days_ago(30, 400), "ONC")
        egfr = self.state(mrn, "egfr_mut", self.pick(rate("onc", "egfr_mut")))
        self.lab(mrn, "EGFRT", "POS" if egfr == "pos" else "NEG", self.days_ago(20, 380))
        self.report(mrn, self.days_ago(5, 60), self.L.LUNG_MASS)
        self.anthropometrics(mrn, sex, self.rng.choice(["<24", "24-25", "25-27"]))
        self.series(mrn, "ALT", "good", "alt", (8, 95), (130, 420), 180)
        self.creatinine(mrn, sex, "normal")
        if self.state(mrn, "osi", "on" if self.rng.random() < 0.5 else "none") == "on":  # renewal-type patient
            self.rx_course(mrn, "osimertinib", self.days_ago(30, 200), 90, 0, "ONC")
        self.note(mrn, self.days_ago(3, 40), "ONC", [Find(self.L.ECOG, "ONC-OSI-INC-04", "yes")])
        self.appointment(mrn, self.rng.randint(0, 20), "ONC")

    def ad_patient(self, i: int) -> None:
        """Early Alzheimer's disease / MCI at the memory clinic (scenario J1, T-503): see ``tools.synth.ad``."""
        from tools.synth.ad import ad_patient

        ad_patient(self, i)

    def rajak_patient(self, i: int) -> None:
        """Rheumatoid arthritis at the rheumatology clinic, screened for a JAK-inhibitor trial (scenario T2, T-504):
        see ``tools.synth.rajak``."""
        from tools.synth.rajak import rajak_patient

        rajak_patient(self, i)

    def general_patient(self, i: int) -> None:
        sex = self.rng.choice("MF")
        age = self.rng.randint(18, 90) if self.rng.random() > 0.05 else self.rng.randint(5, 17)
        mrn = self.patient(i, sex, age)
        self.state(mrn, "archetype", "general")
        dept = self.rng.choice(["FM", "FM", "CARD", "NEPH", "ORTH", "META"])
        for _ in range(self.rng.randint(1, 5)):
            self.encounter(mrn, self.days_ago(5, 1000), dept)
        for key in ("htn", "hld", "t2dm", "ckd3", "oa_knee", "lbp", "gerd", "osteoporosis", "obesity"):
            if self.rng.random() < 0.18:
                self.dx(mrn, key, self.days_ago(20, 3000), dept)
        if self.rng.random() < 0.06:
            self.dx(mrn, "gout", self.days_ago(100, 3000), dept)
            self.series(mrn, "UA", self.rng.choice(["good", "bad", "missing"]), "urate", (7.0, 10.0), (3.5, 6.6), 365)
        if self.rng.random() < 0.6:
            self.anthropometrics(mrn, sex, self.rng.choice(["<24", "24-25", "25-27", "27-30", ">30", "missing"]))
        if self.rng.random() < 0.5:
            self.creatinine(mrn, sex, self.rng.choice(["normal", "normal", "low"]))
        if self.rng.random() < 0.4:
            self.series(mrn, "HBA1C", self.rng.choice(["good", "bad"]), "hba1c", (5.0, 9.6), (10.3, 13.0), 180)
        if self.rng.random() < 0.4:
            self.series(mrn, "SBP", self.rng.choice(["good", "good", "bad"]), "sbp", (100, 156), (163, 195), 90)
        if self.rng.random() < 0.3:
            self.rx_course(
                mrn,
                self.rng.choice(["amlodipine", "atorvastatin", "metformin"]),
                self.days_ago(50, 400),
                self.rng.randint(60, 360),
                0,
                dept,
            )
        if self.rng.random() < 0.08:
            self.dx(mrn, self.rng.choice(["ami", "stroke"]), self.days_ago(5, 2000), "CARD")
        if self.rng.random() < 0.5:
            self.note(mrn, self.days_ago(5, 400), dept, [])
        self.appointments(mrn, dept, screen=False)

    # ---------------------------------------------------------------- driver
    def run(self) -> SiteData:
        for k, (pid, name, dept) in enumerate(PRACTITIONERS if self.with_practitioners else []):
            if self.style == "JP":
                name = (
                    f"{names_ja.FAMILY[k % len(names_ja.FAMILY)][0]}　{names_ja.GIVEN_M[k % len(names_ja.GIVEN_M)][0]}"
                )
            elif self.style == "EN":
                name = f"{names_en.GIVEN_M[k % len(names_en.GIVEN_M)]} {names_en.FAMILY[k % len(names_en.FAMILY)]}"
            self.t["practitioner"].append({"staff_id": pid, "name": name, "dept_code": dept})
        mix = list(rate("site", self.mix).items())
        if self.with_practitioners and any(k == "ad" for k, _ in mix):  # the memory clinic's doctors (T-503)
            for k, (pid, name, dept) in enumerate(AD_PRACTITIONERS, start=len(PRACTITIONERS)):
                if self.style == "JP":
                    fam = names_ja.FAMILY[(3 * k + 1) % len(names_ja.FAMILY)][0]
                    name = f"{fam}　{names_ja.GIVEN_F[k % len(names_ja.GIVEN_F)][0]}"
                elif self.style == "EN":
                    fam_en = names_en.FAMILY[(3 * k + 1) % len(names_en.FAMILY)]
                    name = f"{names_en.GIVEN_F[k % len(names_en.GIVEN_F)]} {fam_en}"
                self.t["practitioner"].append({"staff_id": pid, "name": name, "dept_code": dept})
        kinds = [k for k, w in mix for _ in range(round(w * self.n))]
        while len(kinds) < self.n:
            kinds.append("general")
        self.rng.shuffle(kinds)
        for i, kind in enumerate(kinds[: self.n], start=1 + self.index_offset):
            getattr(self, f"{kind}_patient")(i)
        # guarantee all 20 retrieval needles are planted
        while self.needle_queue:
            sentence, query = self.needle_queue.pop(0)
            row = self.rng.choice([r for r in self.t["patient"]])
            note_no = self.nid("n")
            d = self.days_ago(5, 300)
            enc = self.encounter(row["mrn"], d, "FM")
            self.L = self.langs[self.primary_lang]
            text = self.L.filler(self.rng, 2) + sentence + self.L.stop + self.L.filler(self.rng, 3)
            if self.gold:
                self.gold_notes.append(
                    {"note_no": note_no, "mrn": row["mrn"], "lang": self.L.code, "findings": [], "phi": []}
                )
            self.t["note"].append(
                {
                    "note_no": note_no,
                    "mrn": row["mrn"],
                    "enc_no": enc,
                    "note_datetime": self.dt(d),
                    "note_type": "progress",
                    "text": text,
                }
            )
            self.data.needles.append({"mrn": row["mrn"], "query": query, "fragment": sentence, "note_no": note_no})
        for name in TABLES:
            key = {"patient": "mrn", "practitioner": "staff_id", "registry": "mrn"}.get(name)
            if key is None:
                first = next(iter(self.t[name][0])) if self.t[name] else None
                if first:
                    self.t[name].sort(key=operator.itemgetter(first))
        return self.data


def generate(
    seed: int = 42,
    site_id: str = "DEMO-A",
    ref_date: date = date(2026, 10, 5),
    n: int = 600,
    mrn_prefix: str = "1",
) -> SiteData:
    return Generator(seed, site_id, ref_date, n, mrn_prefix).run()

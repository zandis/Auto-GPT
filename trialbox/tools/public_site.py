"""Public-data sites: real public clinical text as the patient notes of a test hospital, in the box's ingest format.

The synthetic hospital (``tools.synth_hospital``) has made-up notes. This tool builds a hospital whose notes are real
clinical text that is free to use, so the whole platform (ingest, de-identification, feasibility, the list, the
judge, mail, exports, the screens) can be driven on text a clinician wrote:

* **EN site** - the 53 SIGIR 2016 patient descriptions shipped with TrialGPT (``eval/criterion_ml/notes_en.json``;
  NCBI, US-government work, public domain, see ``eval/criterion_ml/LICENSE.NCBI``). Real case summaries written for
  the SIGIR trial-matching collection.
* **JA site** - NTCIR-16 Real-MedNLP MedTxt (CC BY 4.0, Sociocom NAIST): Japanese case reports (MedTxt-CR) and
  radiology reports (MedTxt-RR) written by clinicians. Fetched at run time into ``.cache/medtxt`` (``python -c
  "import tools.medtxt_eval as m; m.fetch()"``), never committed.

What is real and what is not is written next to the CSVs (``PROVENANCE.md``) and returned by :func:`build`:

* **real**: every note text, verbatim (one patient per source document);
* **derived from the text** by the fixed rules in this file: age and sex where the text states them (``"A 58-year-old
  woman"``, ``"６４歳男性"``; ``"60歳代"`` becomes 65 and is counted as approximate), and diagnoses the text names
  without a negation, a family-history or a suspicion cue (a small EN/JA dictionary to ICD-10, ``DX``); a fact the
  text does not state is left out, never guessed;
* **placed, not from the source**: chart numbers, the one outpatient visit each note is attached to (a date in the
  300 days before the snapshot), the birth date's month (1 July of the derived birth year), the clinic staff table,
  and next-visit appointments for every third patient (the sources have no dates or schedules; the box needs them to
  run the clinic-day mail). No names, ID numbers, phone numbers, labs, medicines or contact consents are made up.

    python -m tools.public_site --out /tmp/tb-public/hospital      # writes the CSVs and PROVENANCE.md
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REF = date(2026, 11, 1)
SIGIR = ROOT / "eval" / "criterion_ml" / "notes_en.json"
PI_STAFF = "P12345"
STAFF = [  # the clinic staff table is configuration, not patient data (placed)
    ("P12345", "Investigator (public-data site)", "MED"),
    ("P23456", "Clinic doctor (public-data site)", "MED"),
]

# (ICD-10, English patterns, Japanese patterns). Order matters only for reporting; every match is kept.
DX: list[tuple[str, str, list[str], list[str]]] = [
    ("I10", "hypertension", [r"\bhypertensi(on|ve)\b", r"\bHTN\b"], ["高血圧"]),
    ("E10.9", "type 1 diabetes", [r"\btype 1 diabetes\b", r"\bT1DM\b"], ["1型糖尿病"]),
    ("E11.9", "type 2 diabetes", [r"\b(type 2 )?diabet(es|ic)\b(?! insipidus)", r"\bT2DM\b"], ["2型糖尿病", "糖尿病"]),
    ("E66.9", "obesity", [r"\bobes(e|ity)\b"], ["肥満"]),
    (
        "E78.5",
        "hyperlipidaemia",
        [r"\bhyper(cholesterol|lipid)aemia\b", r"\bhyper(cholesterol|lipid)emia\b"],
        ["脂質異常症", "高脂血症"],
    ),
    ("I50.9", "heart failure", [r"\bheart failure\b", r"\bCHF\b"], ["心不全"]),
    ("I21.9", "myocardial infarction", [r"\bmyocardial infarction\b"], ["心筋梗塞"]),
    ("I48.9", "atrial fibrillation", [r"\batrial fibrillation\b"], ["心房細動"]),
    ("I63.9", "cerebral infarction", [r"\b(ischemic )?stroke\b", r"\bcerebral infarction\b"], ["脳梗塞"]),
    ("J45.9", "asthma", [r"\basthma\b"], ["喘息"]),
    ("J44.9", "COPD", [r"\bCOPD\b", r"\bchronic obstructive pulmonary\b"], ["慢性閉塞性肺疾患", "COPD"]),
    (
        "J84.9",
        "interstitial lung disease",
        [r"\binterstitial (lung disease|pneumonia)\b"],
        ["間質性肺炎", "間質性肺疾患"],
    ),
    ("J18.9", "pneumonia", [r"\bpneumonia\b"], ["肺炎"]),
    ("A15.9", "tuberculosis", [r"\btuberculosis\b"], ["結核"]),
    ("B18.1", "chronic hepatitis B", [r"\bhepatitis B\b"], ["B型肝炎", "Ｂ型肝炎"]),
    ("B18.2", "chronic hepatitis C", [r"\bhepatitis C\b"], ["C型肝炎", "Ｃ型肝炎"]),
    ("K85.90", "pancreatitis", [r"\bpancreatitis\b"], ["膵炎"]),
    ("N18.9", "chronic kidney disease", [r"\bchronic kidney disease\b", r"\bCKD\b"], ["慢性腎臓病", "慢性腎不全"]),
    ("M06.9", "rheumatoid arthritis", [r"\brheumatoid arthritis\b"], ["関節リウマチ"]),
    ("M10.9", "gout", [r"\bgout\b"], ["痛風"]),
    (
        "C34.90",
        "lung cancer",
        [r"\b(lung|bronchogenic) (cancer|carcinoma|adenocarcinoma)\b"],
        ["肺癌", "肺腺癌", "肺扁平上皮癌", "肺小細胞癌"],
    ),
    ("C16.9", "gastric cancer", [r"\b(gastric|stomach) (cancer|carcinoma|adenocarcinoma)\b"], ["胃癌"]),
    (
        "C18.9",
        "colorectal cancer",
        [r"\b(colon|colorectal|rectal) (cancer|carcinoma|adenocarcinoma)\b"],
        ["大腸癌", "結腸癌", "直腸癌"],
    ),
    ("C50.9", "breast cancer", [r"\bbreast (cancer|carcinoma)\b"], ["乳癌"]),
    ("C22.0", "hepatocellular carcinoma", [r"\bhepatocellular carcinoma\b", r"\bHCC\b"], ["肝細胞癌"]),
    ("C25.9", "pancreatic cancer", [r"\bpancreatic (cancer|carcinoma|adenocarcinoma)\b"], ["膵癌", "膵臓癌"]),
    ("C61", "prostate cancer", [r"\bprostate (cancer|carcinoma)\b"], ["前立腺癌"]),
    (
        "C80.1",
        "malignancy, other site",
        [r"\b(metastatic )?(carcinoma|malignancy|lymphoma|sarcoma)\b"],
        ["癌", "悪性腫瘍", "リンパ腫", "肉腫"],
    ),
    ("Z33.1", "pregnancy", [r"\bpregnan(t|cy)\b(?! test)", r"\bgravida\b"], ["妊娠"]),
]
_CANCER_SPECIFIC = {code for code, *_ in DX if code.startswith("C") and code != "C80.1"}

# a cue in the same sentence that turns a mention into "not a diagnosis of this patient"
EN_NEG = re.compile(
    r"\b(no|denies|denied|without|negative for|free of|rule out|r/o|ruled out|suspect(ed)?|possible|family history|"
    r"mother|father|sister|brother|daughter|son)\b",
    re.I,
)
JA_NEG_AFTER = re.compile(
    r"^[^。、,，]{0,12}?(なし|無し|ない|認めず|認めない|認められない|否定|陰性|疑|の可能性|は除外|とした場合|であれば|の場合)"
)
JA_LITERATURE = re.compile(r"(報告がある|報告されて|報告も|報告例|文献|とされる|といわれ|に対する感度)")
JA_FAMILY = re.compile(r"(家族歴|父|母|兄|弟|姉|妹|祖父|祖母)")


@dataclass
class Derived:
    source: str  # "SIGIR" or "MedTxt-CR" / "MedTxt-RR"
    doc: str
    lang: str
    text: str
    age: int | None = None
    age_approx: bool = False
    sex: str | None = None
    dx: list[tuple[str, str, str]] = field(default_factory=list)  # (icd10, label, evidence sentence)


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def derive_en(text: str) -> tuple[int | None, bool, str | None]:
    m = re.search(r"\b(\d{1,3})[- ](year|yr)s?[- ]old\b", text, re.I) or re.search(
        r"\b(\d{1,3}) ?(yo|y/o)\b", text, re.I
    )
    age = int(m.group(1)) if m else None
    if age is None and re.search(r"\b\d{1,2}[- ](month|week|day)s?[- ]old\b", text, re.I):
        age = 0
    sex = None
    sm = re.search(r"\b(woman|female|girl|lady|mother|man|male|boy|gentleman)\b", text, re.I)
    if sm:
        sex = "F" if sm.group(1).lower() in ("woman", "female", "girl", "lady", "mother") else "M"
    return age, False, sex


def derive_ja(text: str) -> tuple[int | None, bool, str | None]:
    t = _nfkc(text)
    approx = False
    age = None
    m = re.search(r"(\d{1,3})\s*歳代", t)
    if m:
        age, approx = int(m.group(1)) + 5, True
    else:
        m = re.search(r"(\d{1,3})\s*歳", t)
        if m:
            age = int(m.group(1))
        elif re.search(r"(\d{1,2})\s*(か月|ヶ月|カ月)\s*(男|女)", t):
            age = 0
    sex = None
    sm = re.search(r"(男性|男児|女性|女児|歳\s*男|歳\s*女|歳代\s*男|歳代\s*女)", t)
    if sm:
        sex = "M" if "男" in sm.group(1) else "F"
    return age, approx, sex


def _sentences(text: str, lang: str) -> list[str]:
    if lang == "ja":
        return [s for s in re.split(r"(?<=[。])|(?<=\.)(?!\d)", _nfkc(text)) if s.strip()]
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def derive_dx(text: str, lang: str) -> list[tuple[str, str, str]]:
    found: dict[str, tuple[str, str, str]] = {}
    for sent in _sentences(text, lang):
        if lang == "ja" and JA_LITERATURE.search(sent):
            continue
        for code, label, en_pats, ja_pats in DX:
            if code in found:
                continue
            if lang == "ja":
                for p in ja_pats:
                    p = _nfkc(p)
                    for m in re.finditer(re.escape(p), sent):
                        after = sent[m.end() :]
                        if JA_NEG_AFTER.search(after) or JA_FAMILY.search(sent[: m.start()]):
                            continue
                        found[code] = (code, label, sent.strip()[:200])
                        break
                    if code in found:
                        break
            else:
                for p in en_pats:
                    hit = re.search(p, sent, re.I)
                    if hit and not EN_NEG.search(sent[: hit.start()]):
                        found[code] = (code, label, sent.strip()[:200])
                        break
    # "1型糖尿病" also matches "糖尿病"; type 1 wins. A named cancer makes the generic one redundant.
    if "E10.9" in found:
        found.pop("E11.9", None)
    if found.keys() & _CANCER_SPECIFIC:
        found.pop("C80.1", None)
    return list(found.values())


def sigir_docs() -> list[Derived]:
    notes: dict[str, list[str]] = json.loads(SIGIR.read_text(encoding="utf-8"))
    out = []
    for doc, sents in notes.items():
        text = " ".join(s.strip() for s in sents)
        age, approx, sex = derive_en(text)
        out.append(Derived("SIGIR", doc, "en", text, age, approx, sex, derive_dx(text, "en")))
    return out


def medtxt_docs() -> list[Derived]:
    from tools import medtxt_eval

    _items, notes = medtxt_eval.dataset()
    out = []
    for doc, sents in notes["ja"].items():
        text = "".join(sents) if isinstance(sents, list) else str(sents)
        src = "MedTxt-CR" if doc.startswith("CR:") else "MedTxt-RR"
        age, approx, sex = derive_ja(text)
        out.append(Derived(src, doc, "ja", text, age, approx, sex, derive_dx(text, "ja")))
    return out


def _write(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def build(out: Path, ref: date = REF, sites: tuple[str, ...] = ("en", "ja")) -> dict[str, Any]:
    """Write the landing CSVs and ``PROVENANCE.md`` into ``out``; return the counts and the per-patient derivations."""
    docs: list[Derived] = []
    if "en" in sites:
        docs += sigir_docs()
    if "ja" in sites:
        docs += medtxt_docs()
    if not docs:
        raise SystemExit("no public data found (SIGIR notes missing, or MedTxt not fetched)")
    out.mkdir(parents=True, exist_ok=True)
    pats, encs, notes, dxs, appts = [], [], [], [], []
    patients: list[dict[str, Any]] = []
    for i, d in enumerate(docs, 1):
        mrn = f"{70000000 + i}"
        visit = datetime.combine(ref - timedelta(days=7 + (i * 37) % 300), datetime.min.time()).replace(hour=10)
        birth = ""
        if d.age is not None:
            birth = date(visit.year - d.age - (1 if visit.month < 7 else 0), 7, 1).isoformat()
        pats.append([mrn, "", "", birth, d.sex or "", "", ""])
        enc = f"E{70000000 + i}"
        encs.append([enc, mrn, visit.strftime("%Y-%m-%d %H:%M:%S"), "MED", PI_STAFF if i % 2 else "P23456", "OPD"])
        ntype = "radiology" if d.source == "MedTxt-RR" else "consult"
        notes.append(
            [f"N{70000000 + i}", mrn, enc, (visit + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), ntype, d.text]
        )
        for j, (code, _label, _ev) in enumerate(d.dx, 1):
            dx_day = visit.date().isoformat()
            dxs.append([f"D{70000000 + i}{j:02d}", enc, mrn, code, dx_day, dx_day, "A"])
        if i % 3 == 0:  # placed: a next visit with the investigator in the coming two weeks (weekday, 09:00-11:30)
            day = ref + timedelta(days=1 + (i % 14))
            while day.weekday() >= 5:
                day += timedelta(days=1)
            at = datetime.combine(day, datetime.min.time()).replace(hour=9 + (i % 3), minute=30 * (i % 2))
            appts.append([f"A{70000000 + i}", mrn, at.strftime("%Y-%m-%d %H:%M:%S"), 15, PI_STAFF, "MED", "B"])
        patients.append(
            {
                "mrn": mrn,
                "source": d.source,
                "doc": d.doc,
                "lang": d.lang,
                "age": d.age,
                "age_approx": d.age_approx,
                "sex": d.sex,
                "dx": [{"icd10": c, "label": lab, "evidence": ev} for c, lab, ev in d.dx],
            }
        )
    _write(out / "patient.csv", ["mrn", "name", "id_no", "birth_date", "sex", "death_date", "phone"], pats)
    _write(out / "encounter.csv", ["enc_no", "mrn", "visit_datetime", "dept_code", "staff_id", "enc_type"], encs)
    _write(out / "note.csv", ["note_no", "mrn", "enc_no", "note_datetime", "note_type", "text"], notes)
    _write(out / "diagnosis.csv", ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status"], dxs)
    _write(
        out / "appointment.csv",
        ["appt_no", "mrn", "appt_datetime", "duration_min", "staff_id", "dept_code", "status"],
        appts,
    )
    _write(out / "practitioner.csv", ["staff_id", "name", "dept_code"], [list(s) for s in STAFF])
    summary = summarise(patients, len(appts))
    (out / "derivation.json").write_text(
        json.dumps({"summary": summary, "patients": patients}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "PROVENANCE.md").write_text(provenance_md(summary), encoding="utf-8")
    return {"summary": summary, "patients": patients, "dir": str(out)}


def summarise(patients: list[dict[str, Any]], appointments: int) -> dict[str, Any]:
    by_src = Counter(p["source"] for p in patients)
    dx = Counter(d["icd10"] + " " + d["label"] for p in patients for d in p["dx"])
    return {
        "patients": len(patients),
        "by_source": dict(by_src),
        "age_stated": sum(p["age"] is not None and not p["age_approx"] for p in patients),
        "age_approx": sum(bool(p["age_approx"]) for p in patients),
        "age_missing": sum(p["age"] is None for p in patients),
        "sex_stated": sum(p["sex"] is not None for p in patients),
        "with_dx": sum(bool(p["dx"]) for p in patients),
        "dx_rows": sum(len(p["dx"]) for p in patients),
        "dx_counts": dict(dx.most_common()),
        "appointments_placed": appointments,
    }


def provenance_md(s: dict[str, Any]) -> str:
    src = ", ".join(f"{k} {v}" for k, v in s["by_source"].items())
    dx = "\n".join(f"| {k} | {v} |" for k, v in s["dx_counts"].items())
    rows = [
        (
            "Note text (every word)",
            "**Real.** SIGIR 2016 patient descriptions (NCBI TrialGPT release, public domain); NTCIR-16 Real-MedNLP "
            "MedTxt-CR case reports and MedTxt-RR radiology reports (CC BY 4.0, Sociocom NAIST)",
        ),
        (
            "Age",
            f"**Derived** from the text where stated ({s['age_stated']} exact, {s['age_approx']} from a decade such "
            f"as 60歳代 -> 65, {s['age_missing']} not stated -> no birth date)",
        ),
        ("Sex", f"**Derived** from the text where stated ({s['sex_stated']} of {s['patients']})"),
        (
            "Diagnoses",
            "**Derived** by a fixed EN/JA dictionary to ICD-10, skipping negated, family-history and suspected "
            f"mentions ({s['dx_rows']} rows on {s['with_dx']} patients); rule-based, so it can miss or over-read",
        ),
        (
            f"Chart number, visit date, birth month, clinic staff, {s['appointments_placed']} next-visit appointments",
            "**Placed** (not in the sources; the box needs them to run)",
        ),
        (
            "Names, ID numbers, phones, labs, medicines, contact consent",
            "**None** (the sources do not give them; nothing is made up)",
        ),
    ]
    table = "\n".join(f"| {a} | {b} |" for a, b in rows)
    return (
        "# Public-data site: what is real and what is derived\n\n"
        f"Built by `tools/public_site.py`. {s['patients']} patients, one per source document ({src}).\n\n"
        f"| What | Where it comes from |\n| --- | --- |\n{table}\n\n"
        f"## Derived diagnoses\n\n| ICD-10 | Patients |\n| --- | --- |\n{dx}\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=Path("/tmp/tb-public/hospital"))
    ap.add_argument("--sites", default="en,ja")
    a = ap.parse_args(argv)
    res = build(a.out, sites=tuple(a.sites.split(",")))
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

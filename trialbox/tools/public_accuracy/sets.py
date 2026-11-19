"""One reader per public set: the source files in ``.cache/public_accuracy/<set>`` -> a :class:`Bundle`.

A bundle holds what a site would screen and what only the scorer may see:

* ``patients``: one note each (the text verbatim; age and sex where the text or the source's structured fields state
  them, never guessed);
* ``trials``: one protocol each (title, inclusion and exclusion lines as published; the age and sex lines a site's
  protocol carries are written from ClinicalTrials.gov's structured fields where the set's text lacks them, and are
  marked ``placed`` in the bundle);
* ``pairs`` (patient x trial labels) and ``criteria`` (patient x criterion labels): the gold. The site builder writes
  them outside the site folder; the box never reads them.

Readers take the cache folder and a seeded sample size, so a first run, a dry run and a unit test read the same code.
They take the answer key's version too (``key``, :mod:`.key`, D-1104): ``v1`` reads as launch P1b did, ``v2`` (the
default) with the P1b review's corrections B2 and B3; the old version stays readable, never overwritten.
"""

from __future__ import annotations

import csv
import html
import io
import json
import random
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.public_accuracy import key as keys
from tools.public_accuracy import sources as src

SEED = 20261114

# ---------------------------------------------------------------- the bundle


@dataclass
class Patient:
    key: str  # source id, unique in the bundle ("trec2021:12", "sigir:sigir-20141")
    lang: str  # en | ja | zh-Hant | zh-Hans
    text: str
    age: int | None = None
    sex: str | None = None  # F | M
    sentences: list[str] = field(default_factory=list)  # numbered sentences when the gold cites them (SIGIR)
    notes: list[str] = field(default_factory=list)  # provenance remarks ("converted", "templated from fields")
    # the age as the text states it, with its unit ((6, "month") for a 6-month-old): the birth date is the visit minus
    # it (B1); None when the text states none (then ``age`` in years, when a structured field gives it)
    age_stated: tuple[int, str] | None = None


@dataclass
class Trial:
    key: str  # source id (NCT id, TFDA protocol number, jRCT id)
    lang: str
    title: str
    inclusion: list[str]
    exclusion: list[str]
    placed: list[str] = field(default_factory=list)  # lines written from structured fields, not the source's text
    # inclusion lines the benchmark itself wrote that no gold row judges (JMED's "20歳以上"): the scorer counts the
    # patients they exclude on their own row (S3, S4), as it does the placed lines
    written: list[str] = field(default_factory=list)
    pair_key: str = ""  # the same trial in another language (zh-Hant TFDA <-> its NCT record)
    notes: list[str] = field(default_factory=list)


@dataclass
class Pair:
    patient: str
    trial: str
    label: str  # eligible | excluded | would_consider | not_refer
    stratum: str = ""


@dataclass
class CriterionGold:
    patient: str
    trial: str
    kind: str  # inclusion | exclusion
    text: str
    label: str  # the source's own word (TrialGPT: included / not included / excluded / not excluded / ...)
    evidence: list[int] = field(default_factory=list)  # sentence ids of the deciding text
    stratum: str = ""


@dataclass
class Bundle:
    set: str
    patients: dict[str, Patient] = field(default_factory=dict)
    trials: dict[str, Trial] = field(default_factory=dict)
    pairs: list[Pair] = field(default_factory=list)
    criteria: list[CriterionGold] = field(default_factory=list)
    compile_gold: dict[str, Any] = field(default_factory=dict)  # trial key -> per-line expected features (Chia)
    provenance: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, Any]:
        return {
            "patients": len(self.patients),
            "trials": len(self.trials),
            "pairs": dict(Counter(p.label for p in self.pairs)),
            "criteria": len(self.criteria),
            "compile_gold": len(self.compile_gold),
        }


# ---------------------------------------------------------------- shared helpers
_BULLET = re.compile(r"^\s*(?:[•●◦○・\-*]|\(?\d{1,3}[.)、]|[（(]\d{1,3}[）)]|[a-z][.)])\s*")


_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_HEADING = re.compile(
    r"((主要)?(納入|排除|選択|除外|纳入)(條件|条件|條件如下|基準|標準|标准)[^。\n]{0,20}?[:：]?"
    r"|(inclusion|exclusion) criteria\s*[:：]?)",
    re.I,
)


def _heading(p: str) -> bool:
    """A section heading ("Inclusion criteria:", "納入條件", "主要排除條件：..."), not a criterion."""
    return bool(_HEADING.fullmatch(p.strip().rstrip(":："))) or bool(_HEADING.fullmatch(p.strip()))


def criteria_lines(block: str) -> list[str]:
    """An eligibility block -> one line per criterion: NCBI's blank-line split, else bullets or numbered lines; the
    heading lines ("Inclusion criteria:", "納入條件") and fragments under five characters are dropped."""
    text = html.unescape(block).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\\([<>*_\[\]~=])", r"\1", text)  # ClinicalTrials.gov's markdown escapes ("\<=2")
    rows = [r for r in text.split("\n") if r.strip()]
    if sum(1 for r in rows if _BULLET.match(r)) >= 2:  # bullets or numbers: one item each, wrapped lines joined
        parts: list[str] = []
        for r in rows:
            if _heading(r.strip()):
                parts.append("")  # a heading ends the item before it; it is not a criterion
            elif _BULLET.match(r) or not parts or not parts[-1]:
                parts.append(r)
            else:
                parts[-1] += " " + r.strip()
    else:
        parts = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(parts) <= 1:
            parts = rows
    out = []
    for p in parts:
        p = " ".join(_BULLET.sub("", p.strip()).split())
        if len(p) < (2 if _CJK.search(p) else 5) or _heading(p):
            continue
        out.append(p)
    return out


def age_years(text: str | None) -> float | None:
    """ClinicalTrials.gov's ``"18 Years"`` / ``"6 Months"`` -> years; None for N/A or nothing."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(year|month|week|day)", str(text or ""), re.I)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    return round(n / {"year": 1, "month": 12, "week": 52, "day": 365}[unit], 2)


def age_limit(text: str | None) -> tuple[float, str] | None:
    """ClinicalTrials.gov's ``"18 Years"`` / ``"2 Months"`` -> (number, unit), the unit as written; None for N/A."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(year|month|week|day)", str(text or ""), re.I)
    return (float(m.group(1)), m.group(2).lower()) if m else None


_AGE_WORDS = re.compile(r"\b(age[ds]?|years?[- ]old|years? of age|months?[- ]old|old)\b|歳|岁|歲", re.I)
_AGE_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|y\b|months?|weeks?|days?|歳|岁|歲)?", re.I)


def stated_age_bounds(lines: Iterable[str]) -> set[float]:
    """The age bounds (in years) the protocol's own lines state: a number on a line that speaks of age, in the unit
    beside it (years when none)."""
    out: set[float] = set()
    for ln in lines:
        if not _AGE_WORDS.search(ln):
            continue
        for m in _AGE_NUM.finditer(ln):
            unit = (m.group(2) or "year").lower()
            div = {"m": 12, "w": 52, "d": 365}.get(unit[:1], 1) if unit[:1] in "mwd" else 1
            out.add(round(float(m.group(1)) / div, 2))
    return out


def placed_lines(
    min_age: str | None, max_age: str | None, sex: str | None, stated: Iterable[str] = (), key: str = keys.CURRENT
) -> tuple[list[str], list[str]]:
    """(inclusion lines, notes) a site's protocol carries for the structured age and sex limits.

    B2 (P1b review, key v2): the limit keeps its unit ("2 Months" is "Aged 2 months or older", never "0.17 years"),
    and a bound the protocol's own lines (``stated``) already give is not written again (11 rulesets carried one
    twice). Key ``v1`` writes them as launch P1b had them: in years, whatever the protocol states."""
    inc, notes, skipped = [], [], []
    if keys.check(key) == "v1":
        lo, hi = age_years(min_age), age_years(max_age)
        if lo is not None:
            inc.append(f"Aged {lo:g} years or older")
        if hi is not None:
            inc.append(f"Age <= {hi:g} years")
        if (sex or "").upper() in ("FEMALE", "MALE"):
            inc.append(f"{sex.capitalize()} participants only")  # type: ignore[union-attr]
        if inc:
            notes.append("age/sex lines written from ClinicalTrials.gov's structured eligibility fields")
        return inc, notes
    have = stated_age_bounds(stated)

    def phrase(lim: tuple[float, str]) -> str:
        n, unit = lim
        return f"{n:g} {unit}{'' if n == 1 else 's'}"

    for lim, line in ((age_limit(min_age), "Aged {} or older"), (age_limit(max_age), "Age <= {}")):
        if lim is None:
            continue
        if age_years(f"{lim[0]:g} {lim[1]}") in have:
            skipped.append(line.format(phrase(lim)))
            continue
        inc.append(line.format(phrase(lim)))
    if (sex or "").upper() in ("FEMALE", "MALE"):
        inc.append(f"{sex.capitalize()} participants only")  # type: ignore[union-attr]
    if inc:
        notes.append("age/sex lines written from ClinicalTrials.gov's structured eligibility fields")
    if skipped:
        notes.append("an age line from the structured fields left out: the protocol's own text states that bound")
    return inc, notes


def derive_age_sex(text: str) -> tuple[int | None, str | None]:
    """Age and sex where an English note states them (the rules of ``tools.public_site.derive_en``)."""
    from tools.public_site import derive_en

    age, _approx, sex = derive_en(text)
    return age, sex


def stated_age(text: str) -> tuple[int, str] | None:
    """The age an English note states, with its unit (``tools.public_site.stated_age_en``)."""
    from tools.public_site import stated_age_en

    return stated_age_en(text)


def _read_cached(cache: Path, source_id: str) -> bytes:
    p = src.path_of(source_id, cache)
    if not p.exists():
        raise SystemExit(f"{p} missing: run `python -m tools.public_accuracy fetch --only {src.BY_ID[source_id].set}`")
    return p.read_bytes()


def stream_lines(cache: Path, source_id: str) -> Iterator[str]:
    """A large corpus line by line: the kept file when there is one, else streamed and checked against its pin at the
    end (a mismatch raises after the last line: the caller's selection is then discarded, never kept)."""
    import hashlib

    s = src.BY_ID[source_id]
    local = src.path_of(source_id, cache)
    if local.exists():
        with local.open(encoding="utf-8") as fh:
            yield from fh
        return
    h = hashlib.sha256()
    with src.https_open(s.url, timeout=900) as resp:
        buf = b""
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            h.update(chunk)
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                yield ln.decode("utf-8")
        if buf:
            yield buf.decode("utf-8")
    if h.hexdigest() != s.sha256:
        raise ValueError(f"{s.url}: streamed sha256 {h.hexdigest()} is not the pinned {s.sha256}")


# ---------------------------------------------------------------- TREC Clinical Trials
TREC_LABEL = {"2": "eligible", "1": "excluded"}


def _xml_root(xml_text: str) -> ET.Element:
    """The root element of an outside XML file, refusing a document type or an entity declaration before anything is
    parsed: without them no entity can be declared (so none expands or loads), and the TREC topics files have
    neither. defusedxml is not a dependency of this package, so the refusal is done here."""
    for decl in ("<!DOCTYPE", "<!ENTITY"):
        if decl in xml_text:
            raise ValueError(f"an XML file with {decl} is refused (no document type or entity is read)")
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start",))
    parser.feed(xml_text)
    parser.close()
    for event in parser.read_events():
        if len(event) == 2 and isinstance(event[1], ET.Element):
            return event[1]
    raise ValueError("an XML file without an element")


def trec_topics(xml_text: str, year: str) -> dict[str, Patient]:
    """2021/2022: one free-text note per topic. 2023: questionnaire fields, written as ``field: value`` lines (the
    patient's chart is then a structured summary, marked so)."""
    root = _xml_root(xml_text)
    out = {}
    for t in root.iter("topic"):
        key = f"trec{year}:{t.get('number')}"
        fields = [(f.get("name") or "", (f.text or "").strip()) for f in t.iter("field")]
        if fields:
            text = "\n".join(f"{k}: {v}" for k, v in fields if v)
            age, sex = None, None
            for k, v in fields:
                if k.lower() == "age" and v.strip().isdigit():
                    age = int(v)
                if k.lower() in ("sex", "gender"):
                    sex = "F" if v.lower().startswith("f") else "M" if v.lower().startswith("m") else None
            out[key] = Patient(
                key,
                "en",
                text,
                age,
                sex,
                notes=[f"TREC {year} questionnaire ({t.get('template')}): fields written as lines"],
            )
        else:
            text = " ".join((t.text or "").split())
            age, sex = derive_age_sex(text)
            out[key] = Patient(key, "en", text, age, sex, age_stated=stated_age(text))
    return out


def trec_qrels(text: str, year: str) -> list[Pair]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] in TREC_LABEL:
            out.append(Pair(f"trec{year}:{parts[0]}", parts[2], TREC_LABEL[parts[3]], stratum=f"trec{year}"))
    return out


def trec_sample(pairs: list[Pair], n_pairs: int, per_patient_min: int = 2, seed: int = SEED) -> list[Pair]:
    """A balanced sample that bounds the protocols to compile: trials judged for several patients first (each trial is
    one protocol compiled and approved on the box), then every patient's own pairs until each has
    ``per_patient_min`` eligible and as many excluded (where the qrels have them), then the rest at random, eligible
    and excluded alternating, until ``n_pairs``."""
    rng = random.Random(seed)
    by_trial: dict[str, list[Pair]] = defaultdict(list)
    for p in pairs:
        by_trial[p.trial].append(p)
    chosen: list[Pair] = []
    seen: set[tuple[str, str]] = set()

    def take(p: Pair) -> None:
        if (p.patient, p.trial) not in seen and len(chosen) < n_pairs:
            seen.add((p.patient, p.trial))
            chosen.append(p)

    shared = sorted((t for t, ps in by_trial.items() if len(ps) > 1), key=lambda t: (-len(by_trial[t]), t))
    for t in shared:
        if len(chosen) >= n_pairs // 2:
            break
        for p in by_trial[t]:
            take(p)
    by_pat: dict[tuple[str, str], list[Pair]] = defaultdict(list)
    for p in pairs:
        by_pat[(p.patient, p.label)].append(p)
    for ps in by_pat.values():
        rng.shuffle(ps)
    have = Counter((p.patient, p.label) for p in chosen)
    patients = sorted({p.patient for p in pairs})
    total = Counter(p.label for p in chosen)

    def give(pat: str, labs: tuple[str, ...]) -> None:
        for lab in sorted(labs, key=lambda x: total[x]):  # the label the sample has fewer of first
            nxt = next((p for p in by_pat.get((pat, lab), []) if (p.patient, p.trial) not in seen), None)
            if nxt is not None and len(chosen) < n_pairs:
                take(nxt)
                have[(pat, lab)] += 1
                total[lab] += 1
                return

    for r in range(per_patient_min):  # every patient covered before any patient gets its next pair
        for pat in patients:
            if have[(pat, "eligible")] + have[(pat, "excluded")] <= 2 * r:
                give(pat, ("eligible", "excluded"))
        for pat in patients:
            for lab in ("eligible", "excluded"):
                if have[(pat, lab)] <= r:
                    give(pat, (lab,))
    rest = {
        lab: [p for p in pairs if p.label == lab and (p.patient, p.trial) not in seen] for lab in TREC_LABEL.values()
    }
    for v in rest.values():
        rng.shuffle(v)
    i = 0
    while len(chosen) < n_pairs and any(rest.values()):
        lab = ("eligible", "excluded")[i % 2]
        if rest[lab]:
            take(rest[lab].pop())
        i += 1
    return chosen


def ncbi_trials(lines: Iterable[str], want: set[str]) -> dict[str, dict[str, Any]]:
    """The NCBI TrialGPT corpus records of ``want`` (title and the two criteria blocks)."""
    out: dict[str, dict[str, Any]] = {}
    for line in lines:
        if not line.strip():
            continue
        d = json.loads(line)
        if d["_id"] in want and d["_id"] not in out:
            m = d.get("metadata") or {}
            out[d["_id"]] = {
                "title": d.get("title") or m.get("brief_title") or "",
                "inclusion": m.get("inclusion_criteria", ""),
                "exclusion": m.get("exclusion_criteria", ""),
            }
    return out


def ctgov_fields(ncts: Iterable[str], cache: Path, *, get: Any = None) -> dict[str, dict[str, Any]]:
    """ClinicalTrials.gov's eligibility module and title per NCT id (current version), 50 a request, kept in
    ``.cache/public_accuracy/ctgov/fields.json`` with ``LIVE.json``: ``minimumAge``, ``maximumAge``, ``sex``,
    ``eligibilityCriteria``, ``briefTitle``."""
    import urllib.parse

    d = src.set_dir("ctgov", cache)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "fields.json"
    have: dict[str, dict[str, Any]] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    todo = sorted(set(ncts) - set(have))
    rows = []
    for i in range(0, len(todo), 50):
        ids = todo[i : i + 50]
        q = urllib.parse.urlencode(
            {
                "filter.ids": ",".join(ids),
                "pageSize": 50,
                "fields": "NCTId,BriefTitle,EligibilityModule,OrgStudyId,SecondaryIdInfo",
            }
        )
        url = f"https://clinicaltrials.gov/api/v2/studies?{q}"
        data = (get or src.polite_get)(url)
        rows.append(src.live_record(cache, "ctgov", url, data))
        for s in json.loads(data).get("studies", []):
            have.update(_ctgov_row(s))
        f.write_text(json.dumps(have, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if rows:
        src.record(cache, "ctgov", rows, "LIVE.json")
    return {k: have[k] for k in ncts if k in have}


def _ctgov_row(study: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ps = study.get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    el = ps.get("eligibilityModule") or {}
    nct = ident.get("nctId")
    return (
        {
            nct: {
                "title": ident.get("briefTitle") or "",
                "criteria": el.get("eligibilityCriteria") or "",
                "minimumAge": el.get("minimumAge"),
                "maximumAge": el.get("maximumAge"),
                "sex": el.get("sex"),
                "orgStudyId": (ident.get("orgStudyIdInfo") or {}).get("id"),
                "secondaryIds": [x.get("id") for x in ident.get("secondaryIdInfos") or []],
            }
        }
        if nct
        else {}
    )


def split_ctgov_criteria(text: str) -> tuple[list[str], list[str]]:
    """ClinicalTrials.gov's one ``eligibilityCriteria`` text -> (inclusion lines, exclusion lines)."""
    m = re.search(r"exclusion criteria\s*:?", text, re.I)
    inc, exc = (text[: m.start()], text[m.end() :]) if m else (text, "")
    inc = re.sub(r"^\s*inclusion criteria\s*:?", "", inc, flags=re.I)
    return criteria_lines(inc), criteria_lines(exc)


def read_trec(
    cache: Path,
    years: tuple[str, ...] = ("2021", "2022"),
    n_pairs: int = 60,
    live: bool = True,
    get: Any = None,
    key: str = keys.CURRENT,
) -> Bundle:
    """TREC CT: the sampled pairs, their patients, and their trials' criteria (2021/2022 from NCBI's corpus, the
    snapshot the assessors judged; 2023 from ClinicalTrials.gov's current record, marked so). Age and sex lines from
    ClinicalTrials.gov's structured fields (``live``)."""
    b = Bundle("trec")
    pairs: list[Pair] = []
    for y in years:
        b.patients.update(trec_topics(_read_cached(cache, f"topics{y}.xml").decode("utf-8"), y))
        pairs += trec_qrels(_read_cached(cache, f"qrels{y}.txt").decode("utf-8"), y)
    b.pairs = trec_sample(pairs, n_pairs)
    want = {p.trial for p in b.pairs}
    texts: dict[str, dict[str, Any]] = {}
    for y in years:
        if y in ("2021", "2022"):
            texts.update(ncbi_trials(stream_lines(cache, f"trec_{y}_corpus.jsonl"), want - set(texts)))
    fields = ctgov_fields(want, cache, get=get) if live else {}
    for nct in sorted(want):
        f = fields.get(nct, {})
        t = texts.get(nct)
        notes = []
        if t is None:  # 2023 (or a trial NCBI's corpus lacks): the current record
            inc, exc = split_ctgov_criteria(str(f.get("criteria") or ""))
            title = str(f.get("title") or "")
            notes.append("criteria from ClinicalTrials.gov's current record, not the judged snapshot")
        else:
            inc, exc, title = criteria_lines(t["inclusion"]), criteria_lines(t["exclusion"]), t["title"]
        placed, pn = placed_lines(f.get("minimumAge"), f.get("maximumAge"), f.get("sex"), [*inc, *exc], key)
        b.trials[nct] = Trial(nct, "en", title, inc, exc, placed, notes=notes + pn)
    b.patients = {k: v for k, v in b.patients.items() if k in {p.patient for p in b.pairs}}
    b.pairs = [
        p for p in b.pairs if b.trials.get(p.trial) and (b.trials[p.trial].inclusion or b.trials[p.trial].exclusion)
    ]
    b.provenance.append(f"TREC CT {', '.join(years)}: {len(b.pairs)} pairs sampled (seed {SEED})")
    return b


# ---------------------------------------------------------------- SIGIR 2016 + TrialGPT criterion labels
SIGIR_LABEL = {"2": "eligible", "1": "would_consider", "0": "not_refer"}
CRITERION_ML = src.ROOT / "eval" / "criterion_ml"


def sentences_en(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", " ".join(text.split())) if s.strip()]


def read_sigir(
    cache: Path,
    n_pairs: int = 60,
    labels: tuple[str, ...] = ("2", "1", "0"),
    live: bool = True,
    get: Any = None,
    key: str = keys.CURRENT,
) -> Bundle:
    """SIGIR 2016 (NCBI copy: 58 patients, 3,835 judgements): all three labels kept apart ("would consider" is its own
    stratum, never merged into eligible), the trials from NCBI's SIGIR corpus, and the 1,015 TrialGPT physician
    criterion labels with their evidence sentence ids (``eval/criterion_ml/annotations.jsonl``, committed, public
    domain notice) where the patient and trial are in the sample. The patient's sentences are TrialGPT's numbering,
    so an evidence id names the same sentence in the box's note."""
    b = Bundle("sigir")
    notes_en: dict[str, list[str]] = json.loads((CRITERION_ML / "notes_en.json").read_text(encoding="utf-8"))
    for line in _read_cached(cache, "sigir_queries.jsonl").decode("utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            sents = notes_en.get(q["_id"]) or sentences_en(q["text"])
            text = " ".join(s.strip() for s in sents)
            age, sex = derive_age_sex(text)
            b.patients[q["_id"]] = Patient(
                q["_id"], "en", text, age, sex, sentences=list(sents), age_stated=stated_age(text)
            )
    pairs = []
    for line in _read_cached(cache, "sigir_qrels_test.tsv").decode("utf-8").splitlines()[1:]:
        qid, nct, score = line.split("\t")
        if score in labels:
            pairs.append(Pair(qid, nct, SIGIR_LABEL[score], stratum="sigir-" + SIGIR_LABEL[score]))
    ann = [json.loads(x) for x in (CRITERION_ML / "annotations.jsonl").read_text(encoding="utf-8").splitlines() if x]
    annotated = {(a["patient_id"], a["trial_id"]) for a in ann}
    rng = random.Random(SEED)
    first = [p for p in pairs if (p.patient, p.trial) in annotated]
    rest = [p for p in pairs if (p.patient, p.trial) not in annotated]
    rng.shuffle(rest)
    by_lab: dict[str, list[Pair]] = defaultdict(list)
    for p in rest:
        by_lab[p.label].append(p)
    chosen = first[: max(1, n_pairs // 2)]
    i = 0
    while len(chosen) < n_pairs and any(by_lab.values()):
        lab = [SIGIR_LABEL[x] for x in labels][i % len(labels)]
        if by_lab[lab]:
            chosen.append(by_lab[lab].pop())
        i += 1
    b.pairs = chosen
    want = {p.trial for p in chosen}
    corpus = ncbi_trials(_read_cached(cache, "sigir_corpus.jsonl").decode("utf-8").splitlines(), want)
    fields = ctgov_fields(want, cache, get=get) if live else {}
    for nct in sorted(want):
        t = corpus.get(nct)
        if t is None:
            continue
        f = fields.get(nct, {})
        inc, exc = criteria_lines(t["inclusion"]), criteria_lines(t["exclusion"])
        placed, pn = placed_lines(f.get("minimumAge"), f.get("maximumAge"), f.get("sex"), [*inc, *exc], key)
        b.trials[nct] = Trial(nct, "en", t["title"], inc, exc, placed, notes=pn)
    b.pairs = [p for p in chosen if p.trial in b.trials and p.patient in b.patients]
    keep = {(p.patient, p.trial) for p in b.pairs}
    b.criteria = [
        CriterionGold(
            a["patient_id"],
            a["trial_id"],
            a["criterion_type"],
            a["criterion_text"],
            a["expert_eligibility"],
            list(a.get("expert_sentences") or []),
            "sigir-criterion",
        )
        for a in ann
        if (a["patient_id"], a["trial_id"]) in keep
    ]
    b.patients = {k: v for k, v in b.patients.items() if k in {p.patient for p in b.pairs}}
    b.provenance.append(f"SIGIR 2016 (NCBI copy): {len(b.pairs)} pairs, {len(b.criteria)} physician criterion labels")
    return b


# ---------------------------------------------------------------- Taiwan FDA trial list (zh-Hant)
TFDA_COLS = ("臨床試驗計畫書編號", "臨床試驗計畫中文名稱", "納入條件", "排除條件", "資料更新時間", "適應症中文")
_TFDA_EXC_HEAD = re.compile(r"(主要)?排除(條件|標準|准則)[^\n]{0,30}?[:：]|^\s*排除(條件|標準)", re.M)
_CJK_DAMAGE = re.compile(r"[一-鿿]\?|\?[一-鿿]")


@dataclass
class TfdaRow:
    protocol: str
    title: str
    inclusion: list[str]
    exclusion: list[str]
    indication: str
    issues: list[str]


def tfda_clean(inc: str, exc: str) -> tuple[str, str, list[str]]:
    """Undo the export's quirks: HTML entities decoded; a block copied into both columns split at its own exclusion
    heading (or, when it has none, the exclusion left empty and the trial flagged). Returns (inclusion, exclusion,
    issues)."""
    issues = []
    i, e = html.unescape(inc or ""), html.unescape(exc or "")
    if i != (inc or "") or e != (exc or ""):
        issues.append("html_entities")
    if _CJK_DAMAGE.search(i + e):
        issues.append("lost_characters")  # '?' in place of a character the export could not encode
    if i.strip() and i.strip() == e.strip():
        issues.append("duplicated_block")
        m = _TFDA_EXC_HEAD.search(i)
        if m:
            i, e = i[: m.start()], i[m.end() :]
        else:
            e = ""
            issues.append("unsplittable")
    return i, e, issues


def read_tfda_rows(cache: Path) -> list[TfdaRow]:
    """The newest row of every protocol number (the export repeats a trial once per update), cleaned."""
    data = _read_cached(cache, "tfda_205_csv.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv") and not n.startswith("__MACOSX"))
        text = z.read(name).decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(text))
    newest: dict[str, dict[str, str]] = {}
    for r in rows:
        pn = (r.get("臨床試驗計畫書編號") or "").strip()
        if pn and (pn not in newest or (r.get("資料更新時間") or "") >= (newest[pn].get("資料更新時間") or "")):
            newest[pn] = r
    out = []
    for pn, r in sorted(newest.items()):
        i, e, issues = tfda_clean(r.get("納入條件") or "", r.get("排除條件") or "")
        out.append(
            TfdaRow(
                pn,
                (r.get("臨床試驗計畫中文名稱") or "").strip(),
                criteria_lines(i),
                criteria_lines(e),
                (r.get("適應症中文") or "").strip(),
                issues,
            )
        )
    return out


def _norm_id(s: str) -> str:
    return re.sub(r"[\s_\-/()]", "", unicodedata.normalize("NFKC", s or "")).upper()


def ctgov_by_protocol(protocol: str, cache: Path, *, get: Any = None) -> str | None:
    """The NCT id whose sponsor protocol number (org study id or a secondary id) is ``protocol``, or None. One
    ClinicalTrials.gov request, kept in ``ctgov/by_protocol.json``."""
    import urllib.parse

    d = src.set_dir("ctgov", cache)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "by_protocol.json"
    have: dict[str, str | None] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if protocol in have:
        return have[protocol]
    term = f'AREA[OrgStudyId]"{protocol}" OR AREA[SecondaryId]"{protocol}"'
    q = urllib.parse.urlencode(
        {"query.term": term, "pageSize": 5, "fields": "NCTId,BriefTitle,EligibilityModule,OrgStudyId,SecondaryIdInfo"}
    )
    url = f"https://clinicaltrials.gov/api/v2/studies?{q}"
    data = (get or src.polite_get)(url)
    src.record(cache, "ctgov", [src.live_record(cache, "ctgov", url, data)], "LIVE.json")
    hit = None
    fields_f = d / "fields.json"
    fields: dict[str, Any] = json.loads(fields_f.read_text(encoding="utf-8")) if fields_f.exists() else {}
    for s in json.loads(data).get("studies", []):
        row = _ctgov_row(s)
        for nct, r in row.items():
            ids = [r.get("orgStudyId") or "", *(r.get("secondaryIds") or [])]
            if any(_norm_id(x) == _norm_id(protocol) for x in ids) and hit is None:
                hit = nct
                fields.update(row)
    have[protocol] = hit
    f.write_text(json.dumps(have, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    fields_f.write_text(json.dumps(fields, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return hit


def read_tfda(cache: Path, n_trials: int = 10, lookups: int | None = None, get: Any = None) -> Bundle:
    """Taiwan FDA trials with zh-Hant criteria, cleaned, each paired with its ClinicalTrials.gov English record by the
    sponsor's protocol number. A seeded draw of splittable trials is looked up one by one (at most ``lookups``) until
    ``n_trials`` pairs are found; each pair is two trials (``<key>``/zh-Hant and its NCT id/en) with ``pair_key``
    naming the other. Patients: none (a compile-agreement set)."""
    b = Bundle("tfda")
    rows = read_tfda_rows(cache)
    issues = Counter(x for r in rows for x in r.issues)
    usable = [r for r in rows if r.inclusion and "unsplittable" not in r.issues]
    rng = random.Random(SEED)
    rng.shuffle(usable)
    tried = matched = 0
    for r in usable:
        if matched >= n_trials or (lookups is not None and tried >= lookups):
            break
        tried += 1
        nct = ctgov_by_protocol(r.protocol, src.CACHE if cache is None else cache, get=get)
        if nct is None:
            continue
        f = json.loads((src.set_dir("ctgov", cache) / "fields.json").read_text(encoding="utf-8")).get(nct, {})
        inc_en, exc_en = split_ctgov_criteria(str(f.get("criteria") or ""))
        if not inc_en:
            continue
        matched += 1
        zh_key = f"TFDA:{r.protocol}"
        notes = [f"cleaned: {', '.join(r.issues)}"] if r.issues else []
        b.trials[zh_key] = Trial(zh_key, "zh-Hant", r.title, r.inclusion, r.exclusion, pair_key=nct, notes=notes)
        b.trials[nct] = Trial(
            nct,
            "en",
            str(f.get("title") or ""),
            inc_en,
            exc_en,
            pair_key=zh_key,
            notes=["ClinicalTrials.gov current record, matched by the sponsor's protocol number"],
        )
    b.provenance.append(
        f"TFDA 205: {len(rows)} protocols, {len(usable)} with splittable criteria; quirks {dict(issues)}; "
        f"{tried} looked up on ClinicalTrials.gov, {matched} matched"
    )
    return b


# ---------------------------------------------------------------- jRCT (ja) with an NCT id
JRCT_ID = re.compile(r"jRCT[a-z]?\s?\d{7,10}")


def jrct_ids_from_ctgov(cache: Path, n: int, get: Any = None) -> list[tuple[str, str]]:
    """(jRCT id, NCT id) pairs from ClinicalTrials.gov records that name a jRCT secondary id (one request)."""
    import urllib.parse

    q = urllib.parse.urlencode(
        {"query.term": "AREA[SecondaryIdDomain]jRCT", "pageSize": 1000, "fields": "NCTId,SecondaryIdInfo"}
    )
    url = f"https://clinicaltrials.gov/api/v2/studies?{q}"
    data = (get or src.polite_get)(url)
    src.record(cache, "ctgov", [src.live_record(cache, "ctgov", url, data)], "LIVE.json")
    out = []
    for s in json.loads(data).get("studies", []):
        ident = (s.get("protocolSection") or {}).get("identificationModule") or {}
        for x in ident.get("secondaryIdInfos") or []:
            m = JRCT_ID.search(f"{x.get('id', '')} {x.get('domain', '')}")
            if m:
                out.append((m.group(0).replace(" ", ""), str(ident.get("nctId") or "")))
                break
    rng = random.Random(SEED)
    rng.shuffle(out)
    return out[:n]


def jrct_criteria(page: str) -> tuple[list[str], list[str], str, list[str]]:
    """(inclusion, exclusion, title, NCT ids) from one jRCT record page: the Japanese cell after the label
    "主たる選択基準" / "主たる除外基準"."""

    def cell(label: str) -> str:
        m = re.search(label + r".*?</th>\s*<td[^>]*>(.*?)</td>", page, re.S)
        return html.unescape(re.sub(r"<br\s*/?>", "\n", m.group(1))) if m else ""

    title = re.search(r"<title>(.*?)</title>", page, re.S)
    inc, exc = cell("主たる選択基準"), cell("主たる除外基準")

    def lines(t: str) -> list[str]:
        return criteria_lines(re.sub(r"<[^>]+>", "", t))

    return lines(inc), lines(exc), (title.group(1).strip() if title else ""), sorted(set(re.findall(r"NCT\d{8}", page)))


def read_jrct(cache: Path, n: int = 10, get: Any = None) -> Bundle:
    """jRCT records that carry an NCT id, fetched one by one (single records under PDL 1.0; no crawling), each paired
    with its ClinicalTrials.gov English record."""
    b = Bundle("jrct")
    d = src.set_dir("jrct", cache)
    d.mkdir(parents=True, exist_ok=True)
    pairs = jrct_ids_from_ctgov(cache, n, get=get)
    fields = ctgov_fields([nct for _, nct in pairs], cache, get=get)
    rows = []
    for jid, nct in pairs:
        f = d / f"{jid}.html"
        if not f.exists():
            url = f"https://jrct.mhlw.go.jp/latest-detail/{jid}"
            try:
                data = (get or src.polite_get)(url)
            except OSError as err:  # a record the registry does not serve now (HTTP 500 on 2026-11-15): left out, said
                b.provenance.append(f"jRCT {jid}: not fetched ({str(err)[:80]}); left out")
                continue
            f.write_bytes(data)
            rows.append(src.live_record(cache, "jrct", url, data))
        inc, exc, title, ncts = jrct_criteria(f.read_text(encoding="utf-8", errors="replace"))
        en_inc, en_exc = split_ctgov_criteria(str(fields.get(nct, {}).get("criteria") or ""))
        if not inc or not en_inc:
            continue
        key = f"jRCT:{jid}"
        b.trials[key] = Trial(
            key,
            "ja",
            title,
            inc,
            exc,
            pair_key=nct,
            notes=[] if nct in ncts else ["the jRCT page does not name this NCT id"],
        )
        b.trials[nct] = Trial(nct, "en", str(fields.get(nct, {}).get("title") or ""), en_inc, en_exc, pair_key=key)
    if rows:
        src.record(cache, "jrct", rows, "LIVE.json")
    b.provenance.append(f"jRCT: {len(pairs)} records with an NCT id looked up, {len(b.trials) // 2} paired")
    return b


# ---------------------------------------------------------------- Chia (criteria compile gold)
CHIA_FEATURES = {
    "Condition": "condition",
    "Drug": "drug",
    "Procedure": "procedure",
    "Measurement": "measurement",
    "Value": "value",
    "Temporal": "temporal",
    "Negation": "negation",
    "Person": "person",
    "Observation": "observation",
}


def chia_line_features(txt: str, ann: str) -> list[dict[str, Any]]:
    """Per line of a Chia ``_inc.txt``/``_exc.txt``: the line and the entity kinds annotated inside it."""
    spans = []
    for row in ann.splitlines():
        if row.startswith("T"):
            parts = row.split("\t")
            if len(parts) >= 2:
                head = parts[1].split(" ")
                kind = head[0]
                nums = [int(x) for x in re.findall(r"\d+", " ".join(head[1:]))]
                if nums:
                    spans.append((kind, nums[0], nums[-1]))
    out, pos = [], 0
    for line in txt.split("\n"):
        start, end = pos, pos + len(line)
        pos = end + 1
        if len(line.strip()) < 5:
            continue
        kinds = sorted({CHIA_FEATURES[k] for k, s, e in spans if k in CHIA_FEATURES and s >= start and e <= end + 1})
        out.append({"text": line.strip(), "features": kinds})
    return out


def read_chia(cache: Path, n_trials: int = 10) -> Bundle:
    """Chia (1,000 Phase IV trials): each trial's inclusion and exclusion text as a protocol, and per line the entity
    kinds the annotators marked (condition, drug, measurement with a value, temporal, negation ...) as compile gold."""
    b = Bundle("chia")
    with zipfile.ZipFile(io.BytesIO(_read_cached(cache, "chia_without_scope.zip"))) as z:
        names = set(z.namelist())
        ncts = sorted({n.split("_")[0] for n in names if n.endswith("_inc.txt")})
        rng = random.Random(SEED)
        rng.shuffle(ncts)
        for nct in ncts[:n_trials]:
            lines: dict[str, list[dict[str, Any]]] = {}
            for kind in ("inc", "exc"):
                t, a = f"{nct}_{kind}.txt", f"{nct}_{kind}.ann"
                if t in names:
                    lines[kind] = chia_line_features(
                        z.read(t).decode("utf-8"), z.read(a).decode("utf-8") if a in names else ""
                    )
            inc = [x["text"] for x in lines.get("inc", [])]
            exc = [x["text"] for x in lines.get("exc", [])]
            if inc:
                b.trials[nct] = Trial(nct, "en", nct, inc, exc)
                b.compile_gold[nct] = lines
    b.provenance.append(f"Chia: {len(b.trials)} trials of {len(ncts)} (seed {SEED})")
    return b


# ---------------------------------------------------------------- TCGA-Reports (cancer type as gold)
# TCGA project -> the criterion a trial for it would write (ten common types; a report of another type is "excluded")
TCGA_CRITERIA = {
    "TCGA-BRCA": "Histologically confirmed invasive breast carcinoma",
    "TCGA-LUAD": "Histologically confirmed adenocarcinoma of the lung",
    "TCGA-LUSC": "Histologically confirmed squamous cell carcinoma of the lung",
    "TCGA-KIRC": "Histologically confirmed clear cell renal cell carcinoma",
    "TCGA-COAD": "Histologically confirmed adenocarcinoma of the colon",
    "TCGA-PRAD": "Histologically confirmed adenocarcinoma of the prostate",
    "TCGA-THCA": "Histologically confirmed papillary or follicular thyroid carcinoma",
    "TCGA-UCEC": "Histologically confirmed endometrial carcinoma",
    "TCGA-HNSC": "Histologically confirmed squamous cell carcinoma of the head and neck",
    "TCGA-LIHC": "Histologically confirmed hepatocellular carcinoma",
}


def gdc_projects(barcodes: list[str], cache: Path, get: Any = None) -> dict[str, str]:
    """TCGA case barcode -> project id, from the GDC cases API (open access), 100 a request, kept in
    ``tcga/projects.json``."""
    import urllib.parse

    d = src.set_dir("tcga", cache)
    f = d / "projects.json"
    have: dict[str, str] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    todo = sorted(set(barcodes) - set(have))
    rows = []
    for i in range(0, len(todo), 100):
        ids = todo[i : i + 100]
        filt = {"op": "in", "content": {"field": "submitter_id", "value": ids}}
        q = urllib.parse.urlencode(
            {
                "filters": json.dumps(filt),
                "fields": "submitter_id,project.project_id",
                "size": len(ids),
                "format": "json",
            }
        )
        url = f"https://api.gdc.cancer.gov/cases?{q}"
        data = (get or src.polite_get)(url)
        rows.append(src.live_record(cache, "gdc", url, data))
        for h in json.loads(data)["data"]["hits"]:
            have[h["submitter_id"]] = h["project"]["project_id"]
        f.write_text(json.dumps(have, indent=1, sort_keys=True), encoding="utf-8")
    if rows:
        src.record(cache, "tcga", rows, "LIVE.json")
    return have


def read_tcga(cache: Path, n_reports: int = 20, get: Any = None) -> Bundle:
    """TCGA pathology reports (OCR'd, real clinician text) as charts; one trial per cancer type in
    :data:`TCGA_CRITERIA`; gold: a report of that type is eligible on its trial's criterion and excluded on the other
    nine (criterion level). The sample is drawn evenly over the ten types."""
    b = Bundle("tcga")
    with zipfile.ZipFile(io.BytesIO(_read_cached(cache, "tcga_reports.csv.zip"))) as z:
        text = z.read("TCGA_Reports.csv").decode("utf-8")
    reports = {r["patient_filename"]: r["text"] for r in csv.DictReader(io.StringIO(text))}
    by_case = {fn.split(".")[0]: fn for fn in reports}
    rng = random.Random(SEED)
    cases = sorted(by_case)
    rng.shuffle(cases)
    projects = gdc_projects(cases[: max(4 * n_reports, 100)], cache, get=get)
    per: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        if projects.get(c) in TCGA_CRITERIA:
            per[projects[c]].append(c)
    quota = max(1, n_reports // len(TCGA_CRITERIA))
    chosen = [c for proj in sorted(per) for c in per[proj][:quota]][:n_reports]
    for proj, crit in TCGA_CRITERIA.items():
        b.trials[proj] = Trial(
            proj,
            "en",
            f"Public test protocol: {proj}",
            [crit],
            [],
            # a note criterion only: SCREEN takes a ruleset of note criteria alone since D-788 (train 20), so the
            # age line once placed for it is gone (TCGA reports carry no age to check it against)
            notes=["a test protocol written for the TCGA set, not a real trial; note criterion only"],
        )
    for c in chosen:
        b.patients[c] = Patient(c, "en", " ".join(reports[by_case[c]].split()), notes=["OCR'd pathology report"])
        for proj, crit in TCGA_CRITERIA.items():
            lab = "included" if projects[c] == proj else "not included"
            b.criteria.append(CriterionGold(c, proj, "inclusion", crit, lab, stratum="tcga-" + lab.replace(" ", "-")))
            b.pairs.append(Pair(c, proj, "eligible" if lab == "included" else "excluded", stratum="tcga"))
    b.provenance.append(f"TCGA-Reports: {len(chosen)} reports over {len(per)} types (GDC project as gold)")
    return b


# ---------------------------------------------------------------- JMED-Personas (ja, synthetic, structured truth)
JMED_CRITERIA = {"JMED-DM": ("糖尿病", "糖尿病の既往がある患者"), "JMED-HT": ("高血圧", "高血圧症の既往がある患者")}
JMED_NOTE_FIELDS = (
    "ペルソナ_医学的背景",
    "ペルソナ_受診に至った経過",
    "ペルソナ_診察・検査所見",
    "ペルソナ_治療・服薬上の課題",
    "ペルソナ_生活背景・支援状況",
)


def jmed_note(r: dict[str, Any]) -> str:
    """The chart of a JMED-Personas patient: its narrative persona fields, as the box reads them."""
    return "\n".join(str(r.get(k) or "") for k in JMED_NOTE_FIELDS)


# D-1104: a risk, a tendency or a borderline state is not the condition. In launch P1b's notes "糖尿病のリスクは低い",
# "境界型糖尿病", "高血圧リスク" and "高血圧傾向" were read as the patient having it (4 of the labels the note changes)
JMED_HEDGE_AFTER = re.compile(r"^\s*の?\s*(リスク|傾向|予備群)")
JMED_HEDGE_BEFORE = re.compile(r"(境界型|境界域)\s*$")


def jmed_stratum(note: str, word: str) -> str:
    """B3 (P1b review): the truth of a JMED criterion from the chart the box reads (the persona fields), not from the
    structured 主病名 / 既往歴 / 現病歴, which the note need not state while it states a comorbidity they lack (3 of the
    7 "wrong exclusions" of P1b were right by the note). ``own``: a sentence says the patient has it (not negated,
    not a relative's, not a risk, a tendency or a borderline state); ``family-only``: only a relative's; ``none``."""
    from tools.public_site import JA_FAMILY, JA_NEG_AFTER, _nfkc

    w = _nfkc(word)
    own = family = False
    for sent in re.split(r"(?<=[。\n])", _nfkc(note)):
        for m in re.finditer(re.escape(w), sent):
            if JA_FAMILY.search(sent[: m.start()]):
                family = True
            elif not (
                JA_NEG_AFTER.search(sent[m.end() :])
                or JMED_HEDGE_AFTER.search(sent[m.end() :])
                or JMED_HEDGE_BEFORE.search(sent[: m.start()])
            ):
                own = True
    return "own" if own else "family-only" if family else "none"


def jmed_coded_stratum(r: dict[str, Any], word: str) -> str:
    """The stratum of a JMED criterion by the structured fields: ``own`` when the condition is in 主病名 / 既往歴 /
    現病歴, ``family-only`` when it is only in 家族歴, else ``none``. The sampling frame of every key version, and the
    truth of key v1 (launch P1b)."""
    own = " ".join(str(r.get(k) or "") for k in ("主病名", "既往歴", "現病歴"))
    fam = str(r.get("家族歴") or "")
    return "own" if word in own else "family-only" if word in fam else "none"


def read_jmed(cache: Path, n: int = 40, key: str = keys.CURRENT) -> Bundle:
    """JMED-Personas (synthetic Japanese patients, CC BY 4.0): the narrative fields as the chart; two exclusion
    criteria (diabetes, hypertension in the history). The patients are sampled per stratum of the structured fields
    (:func:`jmed_coded_stratum`) in every key version, so v1 and v2 judge the same patients. Key v2: the truth from
    the same chart the box reads (B3, :func:`jmed_stratum`): excluded when the note says the patient has the
    condition, not when it is only a relative's (the family-history stratum); where the structured fields say
    otherwise it is counted in the provenance, never used as the truth. Key v1 (launch P1b): the truth from the
    structured fields."""
    import pyarrow.parquet as pq

    keys.check(key)
    b = Bundle("jmed")
    t = pq.read_table(io.BytesIO(_read_cached(cache, "jmed_personas_01.parquet")), use_threads=False).to_pylist()
    rng = random.Random(SEED)
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in t:
        for tid, (word, _crit) in JMED_CRITERIA.items():
            strata[f"{tid}:{jmed_coded_stratum(r, word)}"].append(r)
    for v in strata.values():
        rng.shuffle(v)
    chosen: dict[str, dict[str, Any]] = {}
    per = max(1, n // (3 * len(JMED_CRITERIA)))
    for k in sorted(strata):
        for r in strata[k][:per]:
            chosen[str(r["患者ID"])] = r
    for tid, (_word, crit) in JMED_CRITERIA.items():
        b.trials[tid] = Trial(
            tid,
            "ja",
            f"公開データ試験 {tid}",
            ["20歳以上"],
            [crit],
            written=["20歳以上"],
            notes=["a test protocol written for the JMED set, not a real trial"],
        )
    differ = 0
    for pid, r in chosen.items():
        text = jmed_note(r)
        age = int(r["年齢"]) if str(r.get("年齢") or "").isdigit() else None
        sex = {"男性": "M", "女性": "F"}.get(str(r.get("性別")))
        b.patients[pid] = Patient(pid, "ja", text, age, sex, notes=["synthetic patient (JMED-Personas)"])
        for tid, (word, crit) in JMED_CRITERIA.items():
            coded = jmed_coded_stratum(r, word)
            stratum = coded if key == "v1" else jmed_stratum(text, word)
            differ += (stratum == "own") != (coded == "own")
            b.criteria.append(
                CriterionGold(
                    pid,
                    tid,
                    "exclusion",
                    crit,
                    "excluded" if stratum == "own" else "not excluded",
                    stratum=f"jmed-{stratum}",
                )
            )
    b.provenance.append(f"JMED-Personas shard 01: {len(chosen)} patients, strata {sorted(strata)}")
    if key != "v1":
        b.provenance.append(
            f"JMED truth from the chart the box reads (B3): {differ} patient x criterion labels differ from the "
            "structured 主病名/既往歴/現病歴 (the patients sampled by those fields' strata, as key v1)"
        )
    return b


# ---------------------------------------------------------------- notes without criterion gold (charts only)
def read_notes_only(cache: Path, name: str, n: int = 20, get: Any = None) -> Bundle:
    """Sets that give real-shaped notes but no criterion gold yet (ACI-Bench, MACCROBAT, OpenTWBench vignettes, PMC
    Chinese case reports): charts only. Their gold is a clinician's to write (lane A2), per stratum."""
    b = Bundle(name)
    rng = random.Random(SEED)
    if name == "aci":
        with zipfile.ZipFile(io.BytesIO(_read_cached(cache, "aci_bench_2023.zip"))) as z:
            rows = list(csv.DictReader(io.StringIO(z.read("aci-bench-corpus/challenge_data/train.csv").decode())))
        for r in rows[:n]:
            b.patients[f"aci:{r['encounter_id']}"] = Patient(
                f"aci:{r['encounter_id']}", "en", r["note"], notes=["role-played visit note (ACI-Bench)"]
            )
    elif name == "maccrobat":
        with zipfile.ZipFile(io.BytesIO(_read_cached(cache, "maccrobat2020.zip"))) as z:
            txt = sorted(x for x in z.namelist() if x.endswith(".txt"))
            for x in txt[:n]:
                pid = "maccrobat:" + Path(x).stem
                b.patients[pid] = Patient(pid, "en", z.read(x).decode("utf-8"), notes=["PMC case report"])
    elif name == "opentw":
        import pyarrow.parquet as pq

        rows = pq.read_table(io.BytesIO(_read_cached(cache, "opentw_medicine.parquet")), use_threads=False).to_pylist()
        vign = [r for r in rows if VIGNETTE.search(str(r.get("question") or ""))]
        rng.shuffle(vign)
        for r in vign[:n]:
            pid = f"opentw:{r['paper_id']}:{r['q_no']}"
            b.patients[pid] = Patient(
                pid, "zh-Hant", str(r["question"]), notes=["exam vignette (one or two sentences)"]
            )
    elif name == "pmc_zh":
        for pmcid, text in pmc_zh_cases(cache, n, get=get).items():
            b.patients[f"pmc:{pmcid}"] = Patient(
                f"pmc:{pmcid}",
                "zh-Hans",
                text,
                notes=[
                    "Simplified Chinese as published; NOT converted (no OpenCC in this environment); needs "
                    "Taiwanese clinician review; not a Taiwanese chart"
                ],
            )
    else:
        raise SystemExit(f"unknown notes-only set {name}")
    b.provenance.append(f"{name}: {len(b.patients)} charts, no criterion gold")
    return b


VIGNETTE = re.compile(r"\d+\s*歲\s*(?:的)?\s*(?:男|女)|(?:男|女)性?[,，、]?\s*\d+\s*歲")
PMC_QUERY = "chinese[la] AND cc by license[filter] AND case report[ti]"  # 314 articles on 2026-11-14


def pmc_zh_cases(cache: Path, n: int, get: Any = None) -> dict[str, str]:
    """Chinese-language PMC case reports under CC BY: the ids from E-utilities (one search), then each article's XML
    one by one; an article whose own licence is not CC BY is skipped. The case text is the article body's paragraphs."""
    import urllib.parse

    d = src.set_dir("pmc_zh", cache)
    d.mkdir(parents=True, exist_ok=True)
    g = get or src.polite_get
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(
        {"db": "pmc", "term": PMC_QUERY, "retmax": 4 * n, "retmode": "json"}
    )
    data = g(url)
    rows = [src.live_record(cache, "pmc", url, data)]
    ids = json.loads(data)["esearchresult"]["idlist"]
    out: dict[str, str] = {}
    for pmc in ids:
        if len(out) >= n:
            break
        f = d / f"PMC{pmc}.xml"
        if not f.exists():
            u = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmc}"
            x = g(u)
            f.write_bytes(x)
            rows.append(src.live_record(cache, "pmc", u, x))
        xml = f.read_text(encoding="utf-8", errors="replace")
        lic = re.search(r"creativecommons\.org/licenses/([a-z\-]+)/", xml)
        if not lic or lic.group(1) != "by":  # the search filter says CC BY; the article's own licence decides
            f.unlink()
            continue
        body = re.search(r"<body>(.*?)</body>", xml, re.S)
        paras = re.findall(r"<p[^>]*>(.*?)</p>", body.group(1) if body else "", re.S)
        text = "\n".join(html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in paras)
        if len(re.findall(r"[一-鿿]", text)) > 200:
            out[f"PMC{pmc}"] = text
    src.record(cache, "pmc_zh", rows, "LIVE.json")
    return out


def medtxt_count(cache_medtxt: Path) -> dict[str, int]:
    """Reports per MedTxt file in ``.cache/medtxt`` (the 100 vs 148 question)."""
    out = {}
    for f in sorted(cache_medtxt.rglob("*.xml")):
        out[str(f.relative_to(cache_medtxt))] = len(re.findall(r"<article id=", f.read_text(encoding="utf-8")))
    return out


READERS = {"trec", "trec2023", "sigir", "tfda", "jrct", "chia", "tcga", "jmed", "aci", "maccrobat", "opentw", "pmc_zh"}


def read(
    name: str, cache: Path = src.CACHE, size: int = 20, live: bool = True, get: Any = None, key: str = keys.CURRENT
) -> Bundle:
    """The bundle of set ``name`` at sample ``size`` (pairs for TREC/SIGIR, trials for TFDA/jRCT/Chia, reports or
    patients for the others), as answer key ``key`` has it (:mod:`.key`; the sets B2 and B3 do not touch read the
    same in every version)."""
    keys.check(key)
    if name == "trec":
        return read_trec(cache, ("2021", "2022"), size, live=live, get=get, key=key)
    if name == "trec2023":
        return read_trec(cache, ("2023",), size, live=live, get=get, key=key)
    if name == "sigir":
        return read_sigir(cache, size, live=live, get=get, key=key)
    if name == "tfda":
        return read_tfda(cache, size, lookups=6 * size, get=get)
    if name == "jrct":
        return read_jrct(cache, size, get=get)
    if name == "chia":
        return read_chia(cache, size)
    if name == "tcga":
        return read_tcga(cache, size, get=get)
    if name == "jmed":
        return read_jmed(cache, size, key)
    if name in ("aci", "maccrobat", "opentw", "pmc_zh"):
        return read_notes_only(cache, name, size, get=get)
    raise SystemExit(f"unknown set {name}: one of {', '.join(sorted(READERS))}")

"""The synthetic hospital (TB-DS-21): JP-, TW- and EN-style sites, notes in JA / zh-TW / EN, gold files and checks.

Builds on ``tools.synth.generator`` (same landing tables, so the ingest, rulesets and tests read it unchanged) and
adds: one or more sites per run, each in Japanese or Taiwanese record style; a note-language mix per site; planted
PHI spans and finding offsets in ``gold/notes.jsonl``; chunked, streaming output (10,000 patients per chunk, so the
500,000-patient ``full`` profile runs in flat memory); and the checks of TB-DS-21 §6.

    python -m tools.synth_hospital --profile ci --out /tmp/synth                 # 5,000 patients, 1 JP + 1 TW site
    python -m tools.synth_hospital --profile full --out /var/tmp/synth           # 500,000 patients (not run in CI)
    python -m tools.synth_hospital --sites jp-a:JP:5000 --lang-mix JP=ja:1.0 --out /tmp/jp
    python -m tools.synth_hospital --profile jp-ad --out /tmp/jp-ad                # the Japanese memory clinic (T-503)
    python -m tools.synth_hospital --profile tw-ra --out /tmp/tw-ra                # Taiwanese rheumatology site (T-504)

Every patient is fictional. Synthea is optional and off: this build has no Synthea mapping (TB-DS-21 §4); the
``--synthea`` flag only reports that.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from tools.synth.generator import RATES, TABLES, Generator, SiteData, tw_id_valid
from tools.synth.reserved import is_reserved

ROOT = Path(__file__).resolve().parents[2]
CHUNK = 10_000
COUNTER_STRIDE = 10_000_000  # per-chunk id counter base: ids stay unique while a chunk has < 10 M rows of a kind

PROFILES: dict[str, dict[str, Any]] = {
    "ci": {"sites": "jp-a:JP:2500,tw-a:TW:2500", "tolerance": 0.05},
    "full": {"sites": "jp-head:JP:300000,tw-a:TW:200000", "tolerance": 0.02},
    # the demo's site in one language (DEMO-JA, TB_DEMO_SITE_LANG): the ci hospital's size and two campuses, both
    # Japanese-style (records and notes in Japanese and English) or both Taiwanese-style (zh-TW and English)
    "ci-ja": {"sites": "jp-a:JP:2500,jp-b:JP:2500", "tolerance": 0.05},
    "ci-zh-TW": {"sites": "tw-a:TW:2500,tw-b:TW:2500", "tolerance": 0.05},
    # D-743: English sites (the TW table layout, English identities, every note English) for D-502's en runs
    "ci-en": {"sites": "en-a:EN:2500,en-b:EN:2500", "tolerance": 0.05},
    # scenario J1 (T-503): one Japanese site with a memory clinic (``ad`` patients), notes in Japanese and English
    # only, for the trial AD-MAB and the registry NEUR-COH. ``site:style:patients:mix`` names the rates.yaml mix.
    "jp-ad": {
        "sites": "jp-ad:JP:2500:mix_jp_ad",
        "tolerance": 0.05,
        "studies": ["AD-MAB", "NEUR-COH", "GZQO", "RA-BIO"],
    },
    # scenarios T1 to T3 (T-504): one Taiwanese site with a rheumatology clinic screening for the JAK-inhibitor trial
    # RA-JAK (``rajak`` patients), gout patients for GZQO and GOUT-COH, RA patients for RA-COH; zh-TW and English notes
    "tw-ra": {
        "sites": "tw-ra:TW:1500:mix_tw_ra",
        "tolerance": 0.05,
        "studies": ["RA-JAK", "GZQO", "RA-COH", "RA-BIO"],
    },
}
DEFAULT_LANG_MIX = {"JP": {"ja": 0.9, "en": 0.1}, "TW": {"zh-TW": 0.9, "en": 0.1}, "EN": {"en": 1.0}}
EN_ID = re.compile(r"SYN\d{7}")  # D-743: an English site's identifier, the form of no country's number
EN_PHONE = re.compile(r"555-01\d\d")  # D-743: 555-0100 to 555-0199, the range kept for fiction
DEFAULT_STUDIES = ["GOUT-COH", "GZQO", "ONC-OSI", "RA-BIO", "RA-COH"]

# TB-DS-21 §5.1: the note criteria the generator has a finding slot for (criterion -> slot names)
SLOTS: dict[str, list[str]] = {
    "GZQO-INC-05": ["flare_history", "flare_single"],
    "GZQO-EXC-11": ["flare_current"],
    "GZQO-INC-07": ["injection_willing"],
    "RA-BIO-REN-02": ["biologic_response"],
    "ONC-OSI-INC-04": ["ecog"],
}
# the ``ad`` archetype's slots (T-503); required only on a site whose mix holds ``ad``
AD_SLOTS: dict[str, list[str]] = {
    "AD-MAB-INC-03": ["mmse"],
    "AD-MAB-INC-04": ["cdr"],
    "AD-MAB-INC-05": ["amyloid_pet", "amyloid_csf"],
    "AD-MAB-EXC-02": ["mri_microbleeds"],
}
SLOTS.update(AD_SLOTS)
# the ``rajak`` archetype's slots (T-504): the notes half of the two mixed criteria, required only where the mix has it
RAJAK_SLOTS: dict[str, list[str]] = {
    "RA-JAK-EXC-06": ["herpes_zoster"],
    "RA-JAK-EXC-07": ["venous_thromboembolism"],
}
SLOTS.update(RAJAK_SLOTS)


@dataclass
class SiteSpec:
    site_id: str
    style: str
    n: int
    prefix: str
    seed: int
    lang_mix: dict[str, float]
    mix: str = "mix"  # the patient mix in rates.yaml ``site`` (``mix_jp_ad``: the memory-clinic site, T-503)

    @property
    def has_ad(self) -> bool:
        return "ad" in RATES["site"][self.mix]

    @property
    def has_rajak(self) -> bool:
        return "rajak" in RATES["site"][self.mix]


@dataclass
class SiteResult:
    spec: SiteSpec
    out: Path
    counts: Counter[str] = field(default_factory=Counter)
    rate_counts: dict[tuple[str, str], Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    human_counts: Counter[str] = field(default_factory=Counter)
    langs: Counter[str] = field(default_factory=Counter)
    phi_notes: int = 0
    phi_spans: int = 0
    findings: Counter[str] = field(default_factory=Counter)
    offset_errors: list[str] = field(default_factory=list)
    reserved_hits: list[str] = field(default_factory=list)
    seconds: float = 0.0


# ------------------------------------------------------------------------------------------------ parsing
def parse_sites(text: str, seed: int, lang_mix: dict[str, dict[str, float]]) -> list[SiteSpec]:
    out = []
    for k, part in enumerate(p for p in text.split(",") if p.strip()):
        site_id, style, n, *rest = part.strip().split(":")
        style = style.upper()
        if style not in DEFAULT_LANG_MIX:
            raise SystemExit(f"--sites: style must be one of {', '.join(DEFAULT_LANG_MIX)}, got {style!r}")
        if style == "EN" and any(w > 0 for code, w in lang_mix.get(style, {}).items() if code != "en"):
            raise SystemExit(f"--sites: {site_id} is an English site, whose notes are English only (D-743)")
        mix = rest[0] if rest else "mix"
        if mix not in RATES["site"]:
            raise SystemExit(f"--sites: unknown patient mix {mix!r} (rates.yaml site: {', '.join(RATES['site'])})")
        prefix = rest[1] if len(rest) > 1 else str(k + 2)
        spec = SiteSpec(site_id.upper(), style, int(n), prefix, seed + 1000 * k, lang_mix.get(style, {}), mix)
        if spec.has_ad and "zh-TW" in spec.lang_mix:
            raise SystemExit(f"--sites: {site_id} has Alzheimer's patients, whose notes are Japanese or English only")
        out.append(spec)
    return out


def parse_lang_mix(items: list[str] | None) -> dict[str, dict[str, float]]:
    mix = {k: dict(v) for k, v in DEFAULT_LANG_MIX.items()}
    for item in items or []:
        style, rest = item.split("=", 1)
        weights = {lang: float(w) for lang, w in (x.split(":") for x in rest.split(","))}
        mix[style.upper()] = weights
    return mix


# ------------------------------------------------------------------------------------------------ writing
class StreamWriter:
    """Appends one site's tables and truth files chunk by chunk (TB-DS-21 §4 "chunks of 10,000 patients")."""

    def __init__(self, out: Path) -> None:
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        (out / "gold").mkdir(exist_ok=True)
        self.csv: dict[str, tuple[TextIO, csv.DictWriter[str] | None]] = {}
        self.json_maps: dict[str, tuple[TextIO, list[bool]]] = {}
        for name in ("note_truth", "human_truth", "states"):
            fh = (out / f"{name}.json").open("w", encoding="utf-8")
            fh.write("{")
            self.json_maps[name] = (fh, [True])
        self.gold = (out / "gold" / "notes.jsonl").open("w", encoding="utf-8")
        self.needles: list[dict[str, Any]] = []
        self.counts: Counter[str] = Counter()

    def table(self, name: str, rows: list[dict[str, Any]]) -> None:
        if name not in self.csv:
            self.csv[name] = ((self.out / f"{name}.csv").open("w", newline="", encoding="utf-8"), None)
        fh, w = self.csv[name]
        if rows and w is None:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            self.csv[name] = (fh, w)
        if w is not None:
            w.writerows(rows)
        self.counts[name] += len(rows)

    def json_map(self, name: str, obj: dict[str, Any]) -> None:
        fh, first = self.json_maps[name]
        for key in sorted(obj):
            fh.write(
                ("\n" if first[0] else ",\n")
                + json.dumps(key)
                + ": "
                + json.dumps(obj[key], ensure_ascii=False, sort_keys=True)
            )
            first[0] = False

    def close(self, meta: dict[str, Any]) -> None:
        for fh, _w in self.csv.values():
            fh.close()
        for name in TABLES:  # a table with no rows still gets a (header-less) file, as make_fixtures writes
            if name not in self.csv:
                (self.out / f"{name}.csv").write_text("", encoding="utf-8")
        for fh, _ in self.json_maps.values():
            fh.write("\n}")
            fh.close()
        self.gold.close()
        (self.out / "needles.json").write_text(
            json.dumps(self.needles, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        meta["counts"] = dict(sorted(self.counts.items()))
        (self.out / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )


def roundtrip_notes(rows: list[dict[str, Any]]) -> dict[str, str]:
    """note_no -> text after a CSV write and read, so offsets are checked against the text as written."""
    if not rows:
        return {}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    buf.seek(0)
    return {r["note_no"]: r["text"] for r in csv.DictReader(buf)}


def generate_site(spec: SiteSpec, ref_date: date, out: Path, chunk: int = CHUNK) -> SiteResult:
    t0 = time.monotonic()
    res = SiteResult(spec, out)
    wr = StreamWriter(out)
    done = 0
    k = 0
    while done < spec.n:
        size = min(chunk, spec.n - done)
        g = Generator(
            spec.seed + k,
            spec.site_id,
            ref_date,
            size,
            spec.prefix,
            style=spec.style,
            lang_mix=spec.lang_mix,
            gold=True,
            index_offset=done,
            counter_base=k * COUNTER_STRIDE,
            plant_needles=(k == 0),
            practitioners=(k == 0),
            mix=spec.mix,
        )
        data = g.run()
        collect(res, g, data)
        written = roundtrip_notes(data.tables["note"])
        for gn in g.gold_notes:
            text = written.get(gn["note_no"])
            if text is None:
                res.offset_errors.append(f"{gn['note_no']}: gold line without a note")
                continue
            for f in gn["findings"]:
                if not (0 <= f["start"] < f["end"] <= len(text)):
                    res.offset_errors.append(f"{gn['note_no']}: finding {f['criterion']} out of range")
            for p in gn["phi"]:
                if not (0 <= p["start"] < p["end"] <= len(text)):
                    res.offset_errors.append(f"{gn['note_no']}: phi {p['type']} out of range")
            wr.gold.write(json.dumps(gn, ensure_ascii=False, sort_keys=True) + "\n")
        check_gold_text(res, g, written)
        for name in TABLES:
            wr.table(name, data.tables[name])
        wr.json_map("note_truth", data.note_truth)
        wr.json_map("human_truth", data.human_truth)
        wr.json_map("states", data.states)
        wr.needles.extend(data.needles)
        done += size
        k += 1
    res.counts = wr.counts
    meta = {
        "site_id": spec.site_id,
        "style": spec.style,
        "lang_mix": spec.lang_mix,
        "ref_date": ref_date.isoformat(),
        "seed": spec.seed,
        "mix": spec.mix,
        "chunks": k,
        "generator": "tools.synth_hospital (TB-DS-21)",
    }
    wr.close(meta)
    res.seconds = time.monotonic() - t0
    return res


def check_gold_text(res: SiteResult, g: Generator, written: dict[str, str]) -> None:
    """Re-find every planted span: a finding is the slot's sentence, a PHI span is the value it was built from."""
    phi_values: dict[str, set[str]] = defaultdict(set)
    for row in g.t["patient"]:
        phi_values["chart"].add(row["mrn"])
        phi_values["phone"].add(row["phone"])
        phi_values["insurer"].add(row["id_no"])
    for gn in g.gold_notes:
        text = written.get(gn["note_no"], "")
        for f in gn["findings"]:
            span = text[f["start"] : f["end"]]
            if not span or span[-1] not in "。. ":
                res.offset_errors.append(f"{gn['note_no']}: finding {f['criterion']} not a whole sentence: {span!r}")
        for p in gn["phi"]:
            span = text[p["start"] : p["end"]]
            if p["type"] in phi_values and span not in phi_values[p["type"]]:
                res.offset_errors.append(f"{gn['note_no']}: phi {p['type']} {span!r} not the planted value")
            if p["type"] == "chart" and span != gn["mrn"]:
                res.offset_errors.append(f"{gn['note_no']}: chart span is not this patient's chart number")


def collect(res: SiteResult, g: Generator, data: SiteData) -> None:
    for st in data.states.values():
        arch = st.get("archetype", "")
        for attr, value in st.items():
            res.rate_counts[(arch, attr)][value] += 1
    for ht in data.human_truth.values():
        for crit, v in ht.items():
            res.human_counts[v] += 1
            if crit == "GZQO-INC-07":  # the injection rate lives in human_truth, not states
                res.rate_counts[("gout", "injection")][v] += 1
    for lang in g.note_lang.values():
        res.langs[lang] += 1
    for gn in g.gold_notes:
        if gn["phi"]:
            res.phi_notes += 1
            res.phi_spans += len(gn["phi"])
        for f in gn["findings"]:
            res.findings[f"{f['criterion']}={f['value']}"] += 1
    for row in data.tables["patient"]:
        for kind, value in (("phone", row["phone"]), ("insurer", row["id_no"]), ("name", row["name"])):
            if is_reserved(kind, value):
                res.reserved_hits.append(f"{row['mrn']}: {kind} {value}")
        if g.style == "TW" and tw_id_valid(row["id_no"]):
            res.reserved_hits.append(f"{row['mrn']}: national ID with a valid check digit")
        if g.style == "EN" and not (EN_ID.fullmatch(row["id_no"]) and EN_PHONE.fullmatch(row["phone"])):
            res.reserved_hits.append(f"{row['mrn']}: English site identifier or phone not of the fictional form")


# ------------------------------------------------------------------------------------------------ checks
def rate_check(results: list[SiteResult], tolerance: float) -> tuple[list[dict[str, Any]], list[str]]:
    """Observed share of each planted state vs its rates.yaml weight, pooled over sites (same rates everywhere).

    A cell is checked when it holds enough patients that 3 binomial standard deviations fit inside the tolerance;
    smaller cells are listed as skipped (they are checked on the full profile)."""
    pooled: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for r in results:
        for key, c in r.rate_counts.items():
            pooled[key].update(c)
    rows, failures = [], []
    for arch, attrs in RATES.items():
        if arch in ("site", "phi"):
            continue
        for attr, weights in attrs.items():
            obs = pooled.get((arch, attr), Counter())
            n = sum(obs.values())
            total = sum(float(w) for w in weights.values())
            extra = set(obs) - {str(k) for k in weights}
            for state, w in weights.items():
                p = float(w) / total
                need = math.ceil(9 * p * (1 - p) / tolerance**2) if 0 < p < 1 else 1
                row = {"archetype": arch, "attribute": attr, "state": str(state), "expected": round(p, 4), "n": n}
                if n == 0 or extra:
                    row["status"] = "not observed" if n == 0 else f"skipped (states outside rates: {sorted(extra)})"
                elif n < need:
                    row["status"] = f"skipped (n<{need})"
                    row["observed"] = round(obs[str(state)] / n, 4)
                else:
                    o = obs[str(state)] / n
                    row["observed"] = round(o, 4)
                    row["status"] = "ok" if abs(o - p) <= tolerance else "FAIL"
                    if row["status"] == "FAIL":
                        failures.append(f"{arch}.{attr}={state}: observed {o:.3f}, expected {p:.3f} (n={n})")
                rows.append(row)
    return rows, failures


def note_criteria(studies: list[str]) -> dict[str, str]:
    out = {}
    for rs in studies:
        for f in sorted((ROOT / "rulesets" / rs / "ir").glob("*.json")):
            crit = json.loads(f.read_text(encoding="utf-8"))
            if crit.get("class") == "note":
                out[crit["id"]] = rs
    return out


def slot_check(studies: list[str]) -> list[str]:
    return [
        f"{cid} ({rs}) has no finding slot in TB-DS-21 §5.1"
        for cid, rs in note_criteria(studies).items()
        if cid not in SLOTS
    ]


def manifest(out: Path) -> dict[str, str]:
    """sha256 of every file under ``out`` (the determinism check compares two of these)."""
    return {
        str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "manifest.json" and p.name != "summary.json"
    }


@dataclass
class RunResult:
    out: Path
    sites: list[SiteResult]
    rates: list[dict[str, Any]]
    failures: list[str]
    seconds: float
    summary: dict[str, Any]

    @property
    def passed(self) -> bool:
        return not self.failures


def run(
    out: Path,
    *,
    profile: str = "ci",
    sites: str | None = None,
    lang_mix: dict[str, dict[str, float]] | None = None,
    studies: list[str] | None = None,
    ref_date: date = date(2026, 11, 1),
    seed: int = 42,
    chunk: int = CHUNK,
) -> RunResult:
    prof = PROFILES[profile]
    specs = parse_sites(sites or prof["sites"], seed, lang_mix or DEFAULT_LANG_MIX)
    studies = studies or prof.get("studies") or DEFAULT_STUDIES
    t0 = time.monotonic()
    results = [generate_site(s, ref_date, out / s.site_id.lower(), chunk) for s in specs]
    rates, failures = rate_check(results, prof["tolerance"])
    failures += slot_check(studies)
    for r in results:
        failures += [f"{r.spec.site_id}: {e}" for e in r.offset_errors[:20]]
        failures += [f"{r.spec.site_id}: reserved {e}" for e in r.reserved_hits[:20]]
        if r.human_counts and not {"willing", "unwilling", "no_info"} <= set(r.human_counts):
            failures.append(f"{r.spec.site_id}: GZQO-INC-07 lacks a willing/unwilling/no_info case")
        for crit in SLOTS:
            if crit == "ONC-OSI-INC-04" or (crit in AD_SLOTS and not r.spec.has_ad):
                continue
            if crit in RAJAK_SLOTS and not r.spec.has_rajak:
                continue
            if not any(k.startswith(crit + "=") for k in r.findings):
                failures.append(f"{r.spec.site_id}: no planted finding for {crit}")
    seconds = time.monotonic() - t0
    files = {}
    for r in results:
        files.update({f"{r.out.name}/{k}": v for k, v in manifest(r.out).items()})
    (out / "manifest.json").write_text(json.dumps(files, indent=1, sort_keys=True), encoding="utf-8")
    summary = {
        "profile": profile,
        "seed": seed,
        "ref_date": ref_date.isoformat(),
        "studies": studies,
        "seconds": round(seconds, 1),
        "tolerance_points": prof["tolerance"] * 100,
        "sites": [
            {
                "site_id": r.spec.site_id,
                "dir": r.out.name,
                "style": r.spec.style,
                "patients": r.counts["patient"],
                "notes": r.counts["note"],
                "note_languages": dict(r.langs),
                "notes_with_phi": r.phi_notes,
                "phi_spans": r.phi_spans,
                "findings": dict(sorted(r.findings.items())),
                "seconds": round(r.seconds, 1),
            }
            for r in results
        ],
        "rate_cells": {
            "ok": sum(1 for x in rates if x["status"] == "ok"),
            "fail": sum(1 for x in rates if x["status"] == "FAIL"),
            "skipped": sum(1 for x in rates if x["status"] not in ("ok", "FAIL")),
        },
        "failures": failures,
        "digest": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "rates_check.json").write_text(json.dumps(rates, ensure_ascii=False, indent=1), encoding="utf-8")
    return RunResult(out, results, rates, failures, seconds, summary)

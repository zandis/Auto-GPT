"""The first real-model public accuracy run: its sample, the model calls it implies, and the hours and US$ from them.

Every figure is derived here from the data in ``.cache/public_accuracy`` and from constants with a named source; a
figure with no source is ``None`` and printed "not known". Sources:

* the sample: the set readers' own samplers on the full qrels (TREC: the protocols to compile follow from the pairs,
  since nearly every TREC 2021/2022 trial is judged for one patient only);
* criteria per protocol: counted on the sets (SIGIR corpus for the English trials, the TFDA export, Chia);
* model calls of a compile: low = one ``ir_extract`` call (what the stand-in run served); high = that plus one
  ``concept_map`` call per eligibility line (the rule of ``tools/g_probes.estimate_rows`` for G-8);
* model calls of a screened pair: high = judge and verifier on every line (each line a note criterion); the real share
  of note criteria that reach the judge after the structured filters is NOT known: the stand-in compiler makes almost
  every line a ``human`` criterion (measured: 0 judge calls), and the only real-model compile on record (G-8,
  NCT02629159, 2026-11-14, superseded, before B14) made 8 of 10 criteria note or mixed;
* rates: the main SCREEN at 16 calls in flight, 4.502 calls/s (mean of ja 4.391 and zh-TW 4.613, run
  ``20261113T044219Z-2b9eec74``), and one call at a time, 0.403 calls/s (``tools.complete_run.SINGLE_CALL_CPS``), both
  measured on lane G's own serving and in-process box, which predates the shipped serving setup (superseded); the
  installed box's rate is not measured;
* box time per protocol outside the models: measured on the in-process box of the stand-in run (this machine), not on
  an installed box;
* price: US$2.74 an hour spot (``tools.complete_run.PRICE_PER_HOUR``), plus the VM start and the pair canary.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tools.public_accuracy import sets
from tools.public_accuracy import sources as src

SCREEN_CPS_16 = round((4.391 + 4.613) / 2, 3)  # main SCREEN calls/s at 16 in flight, run 20261113T044219Z-2b9eec74
NOTE_SHARE_G8 = 8 / 10  # G-8 NCT02629159: 7 note + 1 mixed of 10 (superseded, pre-B14): a hint, not a measurement


@dataclass
class Row:
    set: str
    sample: str
    lang: str
    patients: int
    protocols: int
    pairs: int  # patient x protocol answers the scorer reads
    lines_per_protocol: float
    compile_calls_low: int
    compile_calls_high: int
    screen_calls_high: int
    gold: str


def _median(xs: list[int]) -> float:
    return float(statistics.median(xs)) if xs else 0.0


def rows(cache: Path = src.CACHE) -> list[Row]:
    out: list[Row] = []
    q = (src.path_of("sigir_qrels_test.tsv", cache)).read_text(encoding="utf-8").splitlines()[1:]
    want = {x.split("\t")[1] for x in q}
    corpus = sets.ncbi_trials(src.path_of("sigir_corpus.jsonl", cache).read_text(encoding="utf-8").splitlines(), want)
    en_lines = _median(
        [len(sets.criteria_lines(t["inclusion"])) + len(sets.criteria_lines(t["exclusion"])) for t in corpus.values()]
    )

    def screened(
        name: str, sample: str, lang: str, patients: int, protocols: int, pairs: int, lines: float, gold: str
    ) -> Row:
        return Row(
            name,
            sample,
            lang,
            patients,
            protocols,
            pairs,
            lines,
            protocols,
            int(protocols * (1 + lines)),
            int(pairs * 2 * lines),
            gold,
        )

    trec = []
    for y in ("2021", "2022"):
        trec += sets.trec_qrels(src.path_of(f"qrels{y}.txt", cache).read_text(encoding="utf-8"), y)
    for n in (3000, 1225):
        s = sets.trec_sample(trec, n)
        out.append(
            screened(
                "TREC CT 2021+2022",
                f"{n} pairs, balanced",
                "en",
                len({p.patient for p in s}),
                len({p.trial for p in s}),
                len(s),
                en_lines,
                "NIST assessor label per pair (eligible / excluded)",
            )
        )
    t23 = sets.trec_sample(
        sets.trec_qrels(src.path_of("qrels2023.txt", cache).read_text(encoding="utf-8"), "2023"), 500
    )
    out.append(
        screened(
            "TREC CT 2023",
            "500 pairs, balanced",
            "en",
            len({p.patient for p in t23}),
            len({p.trial for p in t23}),
            len(t23),
            en_lines,
            "NIST label per pair; questionnaire patients; criteria from today's CT.gov record",
        )
    )
    out.append(
        screened(
            "SIGIR 2016, all labels",
            "3,835 pairs (421 / 681 / 2,733)",
            "en",
            len({x.split("\t")[0] for x in q}),
            len(want),
            len(q),
            en_lines,
            "assessor 0/1/2; 'would consider' apart",
        )
    )
    ann = (sets.CRITERION_ML / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
    import json

    a = [json.loads(x) for x in ann if x]
    out.append(
        screened(
            "SIGIR, physician criterion labels",
            "1,015 criteria",
            "en",
            len({x["patient_id"] for x in a}),
            len({x["trial_id"] for x in a}),
            len({(x["patient_id"], x["trial_id"]) for x in a}),
            en_lines,
            "physician label per criterion + evidence sentence ids",
        )
    )
    tf = [r for r in sets.read_tfda_rows(cache) if r.inclusion and "unsplittable" not in r.issues]
    tf_lines = _median([len(r.inclusion) + len(r.exclusion) for r in tf])
    out.append(
        Row(
            "Taiwan FDA (zh-Hant) + CT.gov (en)",
            "100 trials, two languages each",
            "zh-Hant+en",
            0,
            200,
            0,
            tf_lines,
            200,
            int(100 * (1 + tf_lines) + 100 * (1 + en_lines)),
            0,
            "the same trial compiled twice: class / age / count agreement",
        )
    )
    out.append(
        Row(
            "jRCT (ja) + CT.gov (en)",
            "50 trials, two languages each",
            "ja+en",
            0,
            100,
            0,
            en_lines,
            100,
            int(100 * (1 + en_lines)),
            0,
            "as TFDA",
        )
    )
    chia = sets.read_chia(cache, 100)
    ch_lines = _median([len(t.inclusion) + len(t.exclusion) for t in chia.trials.values()])
    out.append(
        Row(
            "Chia",
            "100 trials",
            "en",
            0,
            100,
            0,
            ch_lines,
            100,
            int(100 * (1 + ch_lines)),
            0,
            "annotated entity kinds per line (structured vs not)",
        )
    )
    out.append(
        screened(
            "TCGA-Reports",
            "500 reports x 10 cancer-type criteria",
            "en",
            500,
            10,
            5000,
            1.0,
            "TCGA project of the case (GDC)",
        )
    )
    out.append(
        screened(
            "JMED-Personas",
            "300 patients x 2 criteria",
            "ja",
            300,
            2,
            600,
            2.0,
            "structured fields (own history vs family history only)",
        )
    )
    return out


def hours(r: Row, box_s_per_protocol: float | None) -> dict[str, Any]:
    """Hours on the card: compile calls one at a time (0.403/s), screen calls at 16 in flight (4.502/s), plus the box's
    own time per protocol when one was measured. Low = compile low and no screen call (the stand-in's case); high =
    the high bounds."""
    from tools.complete_run import SINGLE_CALL_CPS

    box = (r.protocols * box_s_per_protocol) if box_s_per_protocol is not None else 0.0
    lo = (r.compile_calls_low / SINGLE_CALL_CPS + box) / 3600
    hi = (r.compile_calls_high / SINGLE_CALL_CPS + r.screen_calls_high / SCREEN_CPS_16 + box) / 3600
    return {"hours_low": round(lo, 2), "hours_high": round(hi, 2)}


def table(cache: Path = src.CACHE, box_s_per_protocol: float | None = None) -> dict[str, Any]:
    from tools.complete_run import BOOT_HOURS, CANARY_SECONDS, PRICE_PER_HOUR, SINGLE_CALL_CPS

    out = []
    for r in rows(cache):
        out.append({**asdict(r), **hours(r, box_s_per_protocol)})
    fixed = BOOT_HOURS + CANARY_SECONDS / 3600
    return {
        "rows": out,
        "fixed_hours": round(fixed, 2),
        "price_per_hour": PRICE_PER_HOUR,
        "rates": {"single_call_cps": SINGLE_CALL_CPS, "screen_cps_16": SCREEN_CPS_16},
        "box_s_per_protocol": box_s_per_protocol,
        "note_share_hint": NOTE_SHARE_G8,
    }

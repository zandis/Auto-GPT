"""The scorer: the box's answers (``answers.json`` of :mod:`.box`, or the same shape collected from an installed box)
joined to the gold (``gold/`` of :mod:`.site`) by ids only, after the run.

Pair level (TREC, SIGIR, TCGA): a pair is the gold label of one patient for one trial and the box's answer for that
patient in that trial's SCREEN. The box's answer is one of

* ``excluded``  the patient's tier is ``excluded`` (some criterion blocked, the pair agreeing where a model decided);
* ``listed``    on the candidate list and no criterion left open;
* ``open``      on the list with a criterion left to a person or not answered (``pending_human``, ``unknown``,
  ``not evaluated``);
* ``unanswered`` the patient is not in that trial's SCREEN (the screen failed, or scope missed the patient).

Reported per language and stratum: **eligible lost** (eligible, excluded), **excluded caught** (excluded,
excluded), **wrong exclusions** (of the box's exclusions, the share whose gold is eligible), **unanswered**, and the
open share. SIGIR's "would consider" and "would not refer" are their own strata and never enter eligible or excluded.

Criterion level (the TrialGPT physician labels, TCGA cancer type, JMED-Personas): the gold criterion is matched to the
compiled criterion by its text (the box numbers criteria in protocol order); the box's verdict ``fail`` is a block.
A block on a criterion the gold says is met or not applicable is a wrong exclusion; a block on one the gold says is not
met is a catch. With SIGIR's evidence sentence ids, the judge's quote is checked against the deciding sentences.

Compile level: the same trial in two languages (TFDA zh-Hant and its NCT record; jRCT ja and its NCT record):
criteria count, class split and the age limit, per pair and in all; Chia: per line, whether the compiler's class and
domain agree with the entity kinds the annotators marked.

Every rate carries an exact (Clopper-Pearson) 95 % interval. Nothing here reads a model.
"""

from __future__ import annotations

import difflib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

OPEN_VERDICTS = ("pending_human", "unknown", "not_evaluated", "not evaluated", "data_gap", "uncertain")


# ---------------------------------------------------------------- exact intervals
def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Bin(n, p), summed in log space."""
    if p <= 0:
        return 1.0
    if p >= 1:
        return 1.0 if k >= n else 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(
        1.0,
        sum(
            math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
            for i in range(k + 1)
        ),
    )


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact two-sided interval for k successes in n (bisection on the binomial tail; no SciPy)."""
    if n == 0:
        return (0.0, 1.0)

    def solve(f: Any) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _binom_cdf(k - 1, n, p) < alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: _binom_cdf(k, n, p) > alpha / 2)
    return (round(lower, 4), round(upper, 4))


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = clopper_pearson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": [lo, hi]}


# ---------------------------------------------------------------- joining
def load(built: Path, work: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    gold = built / "gold"
    ids = json.loads((gold / "ids.json").read_text(encoding="utf-8"))
    pairs = [json.loads(x) for x in (gold / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if x]
    crits = [json.loads(x) for x in (gold / "criteria.jsonl").read_text(encoding="utf-8").splitlines() if x]
    answers = json.loads((work / "answers.json").read_text(encoding="utf-8"))
    return ids, pairs, crits, answers


def pid_of(mrn: str, key: bytes | None = None) -> str:
    """The box's pseudonym of a chart number (the site key of the run)."""
    from tb_common.crypto import pid_for_mrn

    if key is None:
        from tools import feas_demo as fd

        key = fd.KEY
    return str(pid_for_mrn(key, mrn))


def answer_of(answers: dict[str, Any], ruleset: str, pid: str) -> tuple[str, dict[str, Any] | None]:
    a = answers.get(ruleset) or {}
    p = (a.get("patients") or {}).get(pid)
    if p is None:
        return "unanswered", None
    if p.get("tier") == "excluded":
        return "excluded", p
    if any(str(v.get("verdict")) in OPEN_VERDICTS for v in p.get("verdicts") or []):
        return "open", p
    return "listed", p


def criterion_says_excluded(crits: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(mrn, ruleset) of every pair whose own criterion labels exclude the patient: an inclusion "not included" or an
    exclusion "excluded" (the physicians' criterion-level reading)."""
    return {
        (str(c["mrn"]), str(c["ruleset"]))
        for c in crits
        if c.get("mrn") and c.get("ruleset") and (c.get("kind"), c.get("label")) in BLOCK_RIGHT
    }


def score_pairs(
    ids: dict[str, Any],
    pairs: list[dict[str, Any]],
    answers: dict[str, Any],
    key: bytes | None = None,
    crits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pair-level table per (language, stratum, gold label).

    S1 (P1b review): a pair whose label is ``eligible`` while its own criterion labels exclude the patient (an
    inclusion not met, an exclusion met) is a conflict inside the gold. Those pairs are counted on their own
    (``label_conflicts``), with what the box answered, and the box's exclusions of them are said apart from
    ``eligible_lost`` (2 of sigir's 4 "eligible lost" in P1b agreed with the physicians' criterion labels)."""
    lang_of = ids.get("lang") or {}
    cells: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    by_crit = criterion_says_excluded(crits or [])
    conflicts: dict[str, Counter[str]] = defaultdict(Counter)
    for g in pairs:
        if not g.get("mrn") or not g.get("ruleset"):
            continue
        got, _ = answer_of(answers, g["ruleset"], pid_of(g["mrn"], key))
        cells[(lang_of.get(g["ruleset"], "?"), g.get("stratum") or "", g["label"])][got] += 1
        if g["label"] == "eligible" and (str(g["mrn"]), str(g["ruleset"])) in by_crit:
            conflicts[lang_of.get(g["ruleset"], "?")][got] += 1
    rows = []
    for (lang, stratum, label), c in sorted(cells.items()):
        n = sum(c.values())
        rows.append(
            {
                "lang": lang,
                "stratum": stratum,
                "gold": label,
                "n": n,
                **{k: c[k] for k in ("excluded", "listed", "open", "unanswered")},
            }
        )
    summary = summarise(rows)
    for lang, c in conflicts.items():
        if lang in summary:
            summary[lang]["eligible_lost_where_the_criterion_labels_exclude"] = c["excluded"]
    return {
        "rows": rows,
        "summary": summary,
        "label_conflicts": {
            "what": "pairs labelled eligible whose own criterion labels exclude the patient (inclusion not included, "
            "or exclusion excluded): a conflict inside the gold, with the box's answer",
            "by_lang": {lang: {"pairs": sum(c.values()), **dict(c)} for lang, c in sorted(conflicts.items())},
            "pairs": sum(sum(c.values()) for c in conflicts.values()),
        },
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_lang[r["lang"]].append(r)
    for lang, rs in by_lang.items():
        el = [r for r in rs if r["gold"] == "eligible"]
        ex = [r for r in rs if r["gold"] == "excluded"]
        # over the pairs the box answered (2026-11-15, Gate C): an unanswered pair is not a pair the box kept, so it
        # never enters eligible lost or excluded caught; the unanswered share is its own line
        n_el, n_ex = sum(r["n"] - r["unanswered"] for r in el), sum(r["n"] - r["unanswered"] for r in ex)
        lost, caught = sum(r["excluded"] for r in el), sum(r["excluded"] for r in ex)
        boxed = lost + caught
        answered = [r for r in rs if r["gold"] in ("eligible", "excluded")]
        n_all = sum(r["n"] for r in answered)
        out[lang] = {
            "answered": n_el + n_ex,
            "eligible_lost": rate(lost, n_el),
            "excluded_caught": rate(caught, n_ex),
            "wrong_exclusions": rate(lost, boxed),
            "unanswered": rate(sum(r["unanswered"] for r in answered), n_all),
            "left_open": rate(sum(r["open"] for r in answered), n_all),
            "other_strata": {
                f"{r['stratum']}:{r['gold']}": {k: r[k] for k in ("n", "excluded", "listed", "open", "unanswered")}
                for r in rs
                if r["gold"] not in ("eligible", "excluded")
            },
        }
    return out


# ---------------------------------------------------------------- criterion level
def match_criterion(text: str, draft: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    """The compiled criterion whose text is the gold criterion's (exact, contained, or a ratio of at least 0.6)."""
    t = " ".join(str(text).split()).lower()
    best, score = None, 0.0
    for c in draft:
        if c.get("kind") and kind and c["kind"] != kind:
            continue
        cc = " ".join(str(c.get("text") or "").split()).lower()
        s = 1.0 if t == cc or (len(t) > 20 and (t in cc or cc in t)) else difflib.SequenceMatcher(None, t, cc).ratio()
        if s > score:
            best, score = c, s
    return best if score >= 0.6 else None


BLOCK_RIGHT = {("inclusion", "not included"), ("exclusion", "excluded")}
BLOCK_WRONG = {
    ("inclusion", "included"),
    ("exclusion", "not excluded"),
    ("inclusion", "not enough information"),
    ("exclusion", "not enough information"),
    ("inclusion", "not applicable"),
    ("exclusion", "not applicable"),
}


def evidence_hit(quote: str | None, sentences: list[str], evidence: list[int]) -> bool | None:
    """Whether the judge's quote lies in one of the gold's deciding sentences (None: no quote or no evidence ids)."""
    if not quote or not evidence or not sentences:
        return None
    q = " ".join(quote.split()).lower()[:120]
    for i in evidence:
        if 0 <= i < len(sentences):
            s = " ".join(sentences[i].split()).lower()
            if q[:60] in s or s[:60] in q:
                return True
    return False


def score_criteria(
    ids: dict[str, Any],
    crits: list[dict[str, Any]],
    answers: dict[str, Any],
    sentences: dict[str, list[str]] | None = None,
    key: bytes | None = None,
) -> dict[str, Any]:
    lang_of = ids.get("lang") or {}
    cells: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    evid: Counter[str] = Counter()
    for g in crits:
        rs, mrn = g.get("ruleset"), g.get("mrn")
        if not rs or not mrn:
            continue
        a = answers.get(rs) or {}
        c = match_criterion(g["text"], a.get("draft") or [], g["kind"])
        pid = pid_of(mrn, key)
        p = (a.get("patients") or {}).get(pid)
        if c is None:
            got = "not_compiled"
        elif p is None:
            got = "unanswered"
        else:
            v = next((x for x in p.get("verdicts") or [] if x.get("id") == c["id"]), None)
            verdict = str((v or {}).get("verdict") or "")
            # S2 (P1b review): a matched row with no verdict is "no verdict", never a "no block"
            got = (
                "no_verdict"
                if not verdict
                else "block"
                if verdict == "fail"
                else "open"
                if verdict in OPEN_VERDICTS
                else "no_block"
            )
            if v is not None and sentences is not None:
                hit = evidence_hit(v.get("quote"), sentences.get(g["patient"]) or [], g.get("evidence") or [])
                evid["no quote or no ids" if hit is None else "in a deciding sentence" if hit else "elsewhere"] += 1
        cells[(lang_of.get(rs, "?"), g.get("stratum") or "", g["kind"], g["label"])][got] += 1
    rows = []
    for (lang, stratum, kind, label), c in sorted(cells.items()):
        right = (kind, label) in BLOCK_RIGHT
        wrong = (kind, label) in BLOCK_WRONG
        rows.append(
            {
                "lang": lang,
                "stratum": stratum,
                "kind": kind,
                "gold": label,
                "n": sum(c.values()),
                **dict(c),
                "block_is": "catch" if right else "wrong exclusion" if wrong else "-",
            }
        )

    # over the criteria the box answered (2026-11-15, Gate C): a criterion not compiled or a patient unanswered is
    # counted on its own line, never as a "no block" in a rate's denominator
    def answered(r: dict[str, Any]) -> int:
        return sum(int(r.get(k, 0)) for k in ("block", "open", "no_block"))

    blocks_wrong = sum(int(r.get("block", 0)) for r in rows if r["block_is"] == "wrong exclusion")
    n_wrongable = sum(answered(r) for r in rows if r["block_is"] == "wrong exclusion")
    caught = sum(int(r.get("block", 0)) for r in rows if r["block_is"] == "catch")
    n_catchable = sum(answered(r) for r in rows if r["block_is"] == "catch")
    return {
        "answered": sum(answered(r) for r in rows),
        "unanswered": sum(int(r.get("unanswered", 0)) for r in rows),
        "rows": rows,
        "wrong_exclusion": rate(blocks_wrong, n_wrongable),
        "caught": rate(caught, n_catchable),
        "not_compiled": sum(r.get("not_compiled", 0) for r in rows),
        "no_verdict": sum(int(r.get("no_verdict", 0)) for r in rows),
        "evidence": dict(evid),
    }


# ---------------------------------------------------------------- lines the benchmark wrote (S3, S4)
def _fails(p: dict[str, Any], cid: Any) -> bool:
    return any(v.get("id") == cid and v.get("verdict") == "fail" for v in p.get("verdicts") or [])


def score_written(
    ids: dict[str, Any], written: dict[str, list[str]], answers: dict[str, Any], crits: list[dict[str, Any]]
) -> dict[str, Any]:
    """S3, S4 (P1b review): the lines the benchmark wrote into a protocol that no gold row judges (the placed age and
    sex lines; JMED's coded "20歳以上") are invisible at criterion level, yet the box excludes patients by them. Per
    line matched to its compiled criterion: the patients the box answered, those it blocked on that line, and of
    those the excluded ones; a line not compiled is said. Patients are counted once per protocol and in all."""
    lang_of = ids.get("lang") or {}
    judged = {(str(c.get("ruleset")), " ".join(str(c.get("text") or "").split()).lower()) for c in crits}
    rows: list[dict[str, Any]] = []
    excluded_by_written: set[tuple[str, str]] = set()
    for rs, lines in sorted(written.items()):
        a = answers.get(rs) or {}
        draft = a.get("draft") or []
        pats = a.get("patients") or {}
        for line in lines:
            if (rs, " ".join(line.split()).lower()) in judged:
                continue  # a gold row judges it: the criterion table has it
            c = match_criterion(line, draft, "inclusion")
            row: dict[str, Any] = {"ruleset": rs, "lang": lang_of.get(rs, "?"), "line": line}
            if c is None:
                rows.append({**row, "compiled": False})
                continue
            cid = c["id"]
            blocked = [pid for pid, p in pats.items() if _fails(p, cid)]
            excl = [pid for pid in blocked if (pats[pid] or {}).get("tier") == "excluded"]
            excluded_by_written |= {(rs, pid) for pid in excl}
            rows.append({**row, "compiled": True, "class": c.get("class"), "answered": len(pats),
                         "blocked": len(blocked), "excluded": len(excl)})  # fmt: skip
    by_lang: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_lang[r["lang"]]["lines"] += 1
        by_lang[r["lang"]]["blocked"] += int(r.get("blocked", 0))
        by_lang[r["lang"]]["excluded"] += int(r.get("excluded", 0))
        by_lang[r["lang"]]["not_compiled"] += 0 if r["compiled"] else 1
    return {
        "what": "patients the box excluded on a line the benchmark wrote (no gold row judges it): placed age and sex "
        "lines, JMED's coded age line",
        "rows": rows,
        "summary": {lang: dict(c) for lang, c in sorted(by_lang.items())},
        "patients_excluded": len(excluded_by_written),
    }


# ---------------------------------------------------------------- compile level
def class_split(draft: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(c.get("class")) for c in draft))


def _age(draft: list[dict[str, Any]]) -> list[Any]:
    return sorted(
        json.dumps((c.get("logic") or {}).get("age"), sort_keys=True)
        for c in draft
        if (c.get("logic") or {}).get("domain") == "demographic" and (c.get("logic") or {}).get("age")
    )


def score_compile_pairs(ids: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """The same trial in two languages: criteria counts, class split, age limits, per pair and summed."""
    rows = []
    done: set[str] = set()
    for rs, other in sorted((ids.get("pair_of") or {}).items()):
        if rs in done or ids["lang"].get(rs) == "en":
            continue
        done |= {rs, other}
        a, b = (answers.get(rs) or {}).get("draft") or [], (answers.get(other) or {}).get("draft") or []
        sa, sb = class_split(a), class_split(b)
        rows.append(
            {
                "local": rs,
                "lang": ids["lang"].get(rs),
                "en": other,
                "n_local": len(a),
                "n_en": len(b),
                "class_local": sa,
                "class_en": sb,
                "age_local": _age(a),
                "age_en": _age(b),
                "age_agree": _age(a) == _age(b),
                "structured_share_gap": round(
                    abs(sa.get("structured", 0) / (len(a) or 1) - sb.get("structured", 0) / (len(b) or 1)), 3
                ),
            }
        )
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_lang[str(r["lang"])].append(r)
    summary = {
        lang: {
            "pairs": len(rs),
            "both_compiled": sum(1 for r in rs if r["n_local"] and r["n_en"]),
            "age_agree": rate(sum(r["age_agree"] for r in rs), len(rs)),
            "mean_structured_share_gap": round(sum(r["structured_share_gap"] for r in rs) / len(rs), 3),
        }
        for lang, rs in by_lang.items()
    }
    return {"rows": rows, "summary": summary}


STRUCTURABLE = {"measurement", "value", "person"}


def score_chia(built: Path, answers: dict[str, Any]) -> dict[str, Any]:
    """Per Chia line matched to a compiled criterion: does the class agree with the annotation? A line with a
    measurement, a value or a person (age, sex) is structurable; one with only a condition, drug or procedure is a
    coded or note criterion. Reported as agreement of "structured" with "structurable"."""
    gold = json.loads((built / "gold" / "compile_gold.json").read_text(encoding="utf-8"))
    agree, n, unmatched = 0, 0, 0
    for rs, kinds in gold.items():
        draft = (answers.get(rs) or {}).get("draft") or []
        for kind, lines in kinds.items():
            for ln in lines:
                c = match_criterion(ln["text"], draft, "inclusion" if kind == "inc" else "exclusion")
                if c is None:
                    unmatched += 1
                    continue
                n += 1
                structurable = bool(set(ln["features"]) & STRUCTURABLE)
                agree += structurable == (c.get("class") in ("structured", "mixed"))
    return {"class_agreement": rate(agree, n), "unmatched_lines": unmatched}


def score(built: Path, work: Path, key: bytes | None = None) -> dict[str, Any]:
    ids, pairs, crits, answers = load(built, work)
    out: dict[str, Any] = {"set": ids.get("set"), "what": "joined by ids after the run; the gold was not in the box"}
    if pairs:
        out["pairs"] = score_pairs(ids, pairs, answers, key, crits)
    if crits:
        sents = None
        if ids.get("set") == "sigir":
            from tools.public_accuracy.sets import CRITERION_ML

            sents = json.loads((CRITERION_ML / "notes_en.json").read_text(encoding="utf-8"))
        out["criteria"] = score_criteria(ids, crits, answers, sents, key)
    wf = built / "gold" / "written.json"
    if wf.exists():  # S3, S4 (a set built before the file existed has no such row)
        written = json.loads(wf.read_text(encoding="utf-8"))
        if written:
            out["written_lines"] = score_written(ids, written, answers, crits)
    if ids.get("pair_of"):
        out["compile_pairs"] = score_compile_pairs(ids, answers)
    if (built / "gold" / "compile_gold.json").exists() and json.loads(
        (built / "gold" / "compile_gold.json").read_text(encoding="utf-8")
    ):
        out["chia"] = score_chia(built, answers)
    drafts = [c for a in answers.values() for c in a.get("draft") or []]
    out["compiled"] = {
        "protocols": len(answers),
        "criteria": len(drafts),
        "class_split": class_split(drafts),
        "screened": sum(1 for a in answers.values() if a.get("screen") == "done"),
    }
    # a set with gold rows the box answered none of has no figure (Gate C: "not scored, because"), never a 0 %
    why = not_scored_because(out)
    if why:
        out["not_scored_because"] = why
    return out


def not_scored_because(out: dict[str, Any]) -> str | None:
    """Why a scored folder has no figure, or None. Pair and criterion sets need answered rows; compile sets need
    compiled criteria."""
    if "pairs" in out or "criteria" in out:
        n = int((out.get("criteria") or {}).get("answered") or 0)
        n += sum(int(v.get("answered") or 0) for v in ((out.get("pairs") or {}).get("summary") or {}).values())
        if n == 0:
            return "the box answered none of the set's gold rows (no SCREEN finished for them)"
        return None
    if not (out.get("compiled") or {}).get("criteria"):
        return "the box compiled no criteria"
    return None

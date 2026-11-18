"""The ladder report (card 10A-3; plan 9's 9c-1 with review 15's B16-16 and review 17's 17-2): for a screening run,
which rung decided each patient-criterion cell, by criterion kind, note language and site, and the **decided share**
(cells the machine answered "met" or "not met", of all cells) that is printed beside every accuracy figure and every
bound, so that no bound can be met by answering "unknown" [review 17, section 3].

    python -m tools.public_accuracy.ladder RUN [RUN ...] [--json OUT]

``RUN`` is a stored set, as :mod:`.replay` reads it (a ``.tgz`` as the driver stores it, that folder extracted, or a
folder holding such sets). A tarball is unpacked by :func:`tools.public_accuracy.replay.safe_extract` into a new
empty folder outside the repository; nothing in it is run. It reads ``built/gold/ids.json`` and ``work/answers.json``
only, never the gold labels, and needs no model and no network.

A cell is one verdict of one patient on one criterion in a protocol's SCREEN. Its rung is read from the verdict's
``basis`` through :data:`RUNGS` (data, in the order of the ladder). A cell is **decided** when its verdict is
``pass`` or ``fail``; ``unknown`` and a cell waiting for a person are not. The criterion kinds are
``criterion_kinds.json`` beside this file: regular expressions over the criterion's text, multi-label, rough and for
proportions only. A cell counts under every kind its criterion carries.

The note language of a cell is the patient's (``ids.json`` ``patient_lang``, through the run's pseudonyms), else the
protocol's (``lang``); the site is the set's own (each public set is built as one site by :mod:`.site`), or
``ids.json`` ``site`` where a set names one per protocol. Every share carries the scorer's exact 95 % interval.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: the report's layout; keys are only ever added
SCHEMA_VERSION = 1
KINDS_FILE = Path(__file__).with_name("criterion_kinds.json")
DECIDED_VERDICTS = ("pass", "fail")

#: the ladder, bottom to top: (rung, what it is, the verdict bases that rung writes). A basis the table does not know
#: is reported as its own rung ``other:<basis>``, never folded into a known one. ``unknown`` holds every cell no rung
#: decided and no person was asked for (basis empty).
RUNGS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("rules", "coded data and rules (S1)", ("coded", "rules", "derived")),
    ("terminology", "terminology on text (S2)", ("terminology", "lexicon")),
    ("extractor", "rule extractor on text", ("extractor", "rule_extractor")),
    ("search", "meaning search (S2b)", ("search", "embedding")),
    ("judge", "judge with verifier (S3/S4)", ("pair", "notes", "judge", "verifier")),
    ("person", "waiting for a person", ("person", "human")),
    ("unknown", "no rung decided", ("",)),
)
_RUNG_OF = {b: r for r, _w, bases in RUNGS for b in bases}
RUNG_ORDER = [r for r, _w, _b in RUNGS]


@lru_cache(maxsize=1)
def kinds_table() -> tuple[tuple[str, str, str, tuple[re.Pattern[str], ...]], ...]:
    """(kind, label, answer_by, patterns) from ``criterion_kinds.json``."""
    data = json.loads(KINDS_FILE.read_text(encoding="utf-8"))
    return tuple(
        (k["kind"], k["label"], k["answer_by"], tuple(re.compile(p, re.IGNORECASE) for p in k["patterns"]))
        for k in data["kinds"]
    )


def kinds_of(text: str) -> list[str]:
    """The kinds a criterion's text carries, in the table's order; ``["none"]`` when it matches no kind."""
    found = [k for k, _l, _a, pats in kinds_table() if any(p.search(text or "") for p in pats)]
    return found or ["none"]


def rung_of(verdict: dict[str, Any]) -> str:
    v = str(verdict.get("verdict") or "")
    basis = str(verdict.get("basis") or "")
    if v == "pending_human" and not basis:
        return "person"
    if not basis and v in DECIDED_VERDICTS:
        return "other:none"
    return _RUNG_OF.get(basis, f"other:{basis}")


def is_decided(verdict: dict[str, Any]) -> bool:
    return str(verdict.get("verdict") or "") in DECIDED_VERDICTS


def share(k: int, n: int) -> dict[str, Any]:
    """``k`` of ``n`` with the scorer's exact (Clopper-Pearson) 95 % interval."""
    from tools.public_accuracy.score import rate

    return rate(k, n)


def _lang_of_patients(ids: dict[str, Any], work: Path | None, key: bytes | None) -> dict[str, str]:
    """pseudonym -> note language, through the run's own pseudonyms (``work/pidmap.json``) and the scorer's."""
    by_mrn = ids.get("patient_lang") or {}
    out: dict[str, str] = {}
    pm = work / "pidmap.json" if work is not None else None
    if pm is not None and pm.exists():
        for mrn, pid in json.loads(pm.read_text(encoding="utf-8")).items():
            if mrn in by_mrn:
                out[str(pid)] = str(by_mrn[mrn])
    if by_mrn:
        try:
            from tools.public_accuracy.score import pid_of

            for mrn, lang in by_mrn.items():
                out.setdefault(pid_of(mrn, key), str(lang))
        except Exception:  # noqa: BLE001 - no site key here: the protocol's language is the fallback
            pass
    return out


def _table() -> dict[str, Any]:
    return {"cells": 0, "decided": 0, "rungs": Counter()}


def _close(t: dict[str, Any]) -> dict[str, Any]:
    rungs = {r: t["rungs"][r] for r in RUNG_ORDER if t["rungs"].get(r)}
    rungs.update({r: n for r, n in sorted(t["rungs"].items()) if r not in RUNG_ORDER})
    return {"cells": t["cells"], "rungs": rungs, "decided": share(t["decided"], t["cells"])}


def ladder(ids: dict[str, Any], answers: dict[str, Any], *, work: Path | None = None,
           key: bytes | None = None, site: str | None = None) -> dict[str, Any]:  # fmt: skip
    """The ladder of one set: cells by rung, kind, note language and site, each with its decided share."""
    set_name = str(ids.get("set") or "?")
    lang_of_ruleset = ids.get("lang") or {}
    site_of_ruleset = ids.get("site") if isinstance(ids.get("site"), dict) else {}
    the_site = site or (ids.get("site") if isinstance(ids.get("site"), str) else None) or set_name
    lang_of_patient = _lang_of_patients(ids, work, key)
    text: dict[str, str] = {}
    crit_kinds: Counter[str] = Counter()
    multi = 0
    criteria = 0
    for a in answers.values():
        for c in a.get("draft") or []:
            cid = str(c.get("id"))
            if cid in text:
                continue
            text[cid] = str(c.get("text") or "")
            ks = kinds_of(text[cid])
            criteria += 1
            multi += int(len(ks) >= 2)
            for k in ks:
                crit_kinds[k] += 1
    total = _table()
    by_lang: dict[str, dict[str, Any]] = defaultdict(_table)
    by_site: dict[str, dict[str, Any]] = defaultdict(_table)
    by_kind: dict[str, dict[str, Any]] = defaultdict(_table)
    tiers: Counter[str] = Counter()
    for rs, a in answers.items():
        for pid, p in (a.get("patients") or {}).items():
            tiers[str(p.get("tier"))] += 1
            lang = lang_of_patient.get(str(pid)) or str(lang_of_ruleset.get(rs) or "?")
            st = str(site_of_ruleset.get(rs) or the_site)
            for v in p.get("verdicts") or []:
                rung, dec = rung_of(v), int(is_decided(v))
                ks = kinds_of(text.get(str(v.get("id")), ""))
                for t in (total, by_lang[lang], by_site[st], *(by_kind[k] for k in ks)):
                    t["cells"] += 1
                    t["decided"] += dec
                    t["rungs"][rung] += 1
    order = [k for k, _l, _a, _p in kinds_table()] + ["none"]
    labels = {k: (lab, ans) for k, lab, ans, _p in kinds_table()}
    kinds = {}
    for k in order:
        if not crit_kinds.get(k) and k not in by_kind:
            continue
        lab, ans = labels.get(k, ("matched no kind", "-"))
        kinds[k] = {"label": lab, "answer_by": ans, "criteria": share(crit_kinds.get(k, 0), criteria),
                    **_close(by_kind.get(k) or _table())}  # fmt: skip
    return {
        "schema_version": SCHEMA_VERSION,
        "set": set_name,
        "what": "patient-criterion cells by the rung that decided them; decided = verdict pass or fail",
        "rungs_known": [{"rung": r, "what": w, "bases": list(b)} for r, w, b in RUNGS],
        **_close(total),
        "tiers": dict(sorted(tiers.items())),
        "by_language": {k: _close(v) for k, v in sorted(by_lang.items())},
        "by_site": {k: _close(v) for k, v in sorted(by_site.items())},
        "criteria": criteria,
        "criteria_with_two_or_more_kinds": share(multi, criteria),
        "by_kind": kinds,
        "kinds_file": KINDS_FILE.name,
    }


def ladder_of_folder(built: Path, work: Path, key: bytes | None = None) -> dict[str, Any]:
    ids = json.loads((built / "gold" / "ids.json").read_text(encoding="utf-8"))
    if not (work / "answers.json").exists():
        return {"schema_version": SCHEMA_VERSION, "set": ids.get("set"),
                "not_scored_because": "no answers.json: the set did not run"}  # fmt: skip
    answers = json.loads((work / "answers.json").read_text(encoding="utf-8"))
    return ladder(ids, answers, work=work, key=key)


# ---------------------------------------------------------------- printing
def pct(d: dict[str, Any]) -> str:
    """The share to one decimal, from the counts (592 of 1,118 is 53.0 %, not the rounded rate's 52.9 %)."""
    if not d.get("n"):
        return "n/a"
    tenths = (2000 * d["k"] + d["n"]) // (2 * d["n"])  # half up, in integers
    return f"{tenths // 10}.{tenths % 10} %"


def decided_phrase(lad: dict[str, Any] | None) -> str:
    """'decided 138 of 895 (15.4 %, 95 % CI 13.1 to 17.9 %)', the words printed beside a figure or a bound."""
    if not lad or "decided" not in lad:
        return "decided: not known (no ladder)"
    d = lad["decided"]
    lo, hi = d["ci95"]
    return f"decided {d['k']} of {d['n']} ({pct(d)}, 95 % CI {100 * lo:.1f} to {100 * hi:.1f} %)"


def _rung_cols(rungs: dict[str, int], cols: list[str]) -> str:
    return "".join(f"{rungs.get(r, 0):>10}" for r in cols)


def render(ladders: dict[str, dict[str, Any]], indent: str = "") -> list[str]:
    """The rung table (one row per set, then per language and site) and the kind table per set."""
    lines: list[str] = []
    w = lines.append
    sets = {n: x for n, x in ladders.items() if x and "cells" in x}
    for n, x in ladders.items():
        if n not in sets:
            w(f"{indent}{n}: not scored: {(x or {}).get('not_scored_because', 'no ladder')}")
    if not sets:
        return lines
    seen = {r for x in sets.values() for t in (x, *x["by_language"].values(), *x["by_site"].values())
            for r in t["rungs"]}  # fmt: skip
    cols = [r for r in RUNG_ORDER if r in seen] + sorted(r for r in seen if r not in RUNG_ORDER)
    head = f"{indent}{'':<22}{'cells':>8}" + "".join(f"{r[:9]:>10}" for r in cols) + "  decided"
    w(f"{indent}Which rung decided each patient-criterion cell (decided: pass or fail; the rest is open)")
    w(head)

    def row(label: str, t: dict[str, Any]) -> None:
        w(f"{indent}{label:<22}{t['cells']:>8}{_rung_cols(t['rungs'], cols)}  {decided_phrase(t)}")

    for n, x in sets.items():
        row(n, x)
        for lang, t in x["by_language"].items():
            if len(x["by_language"]) > 1:
                row(f"  language {lang}", t)
        for st, t in x["by_site"].items():
            if len(x["by_site"]) > 1:
                row(f"  site {st}", t)
    langs: dict[str, dict[str, Any]] = {}
    for x in sets.values():
        for lang, t in x["by_language"].items():
            acc = langs.setdefault(lang, {"cells": 0, "decided": 0, "rungs": Counter()})
            acc["cells"] += t["cells"]
            acc["decided"] += t["decided"]["k"]
            acc["rungs"].update(t["rungs"])
    if len(sets) > 1:
        w(f"{indent}By note language, all sets:")
        for lang, t in sorted(langs.items()):
            row(f"  {lang}", _close(t))
        w(f"{indent}By site, all sets:")
        for n, x in sets.items():
            for st, t in x["by_site"].items():
                row(f"  {st}", t)
    for n, x in sets.items():
        m = x["criteria_with_two_or_more_kinds"]
        w(f"{indent}{n}: criteria by kind ({x['criteria']} criteria; {m['k']} ({pct(m)}) carry two or more kinds; "
          f"rough, for proportions only); cells by rung per kind")  # fmt: skip
        w(f"{indent}  {'kind':<20}{'criteria':>9}{'share':>8}{'cells':>7}" + "".join(f"{r[:9]:>10}" for r in cols)
          + "  decided")  # fmt: skip
        for k, t in x["by_kind"].items():
            c = t["criteria"]
            dec = f"{t['decided']['k']} of {t['cells']}" if t["cells"] else "no cells"
            w(f"{indent}  {k:<20}{c['k']:>9}{pct(c):>8}{t['cells']:>7}{_rung_cols(t['rungs'], cols)}  {dec}")
    return lines


# ---------------------------------------------------------------- command line
def main(argv: list[str] | None = None) -> int:
    from tools.public_accuracy import replay as rp

    ap = argparse.ArgumentParser(prog="python -m tools.public_accuracy.ladder", description=(__doc__ or "").strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("runs", nargs="+", type=Path, help="stored sets: .tgz, extracted folders, or a folder of them")
    ap.add_argument("--json", type=Path, help="write the ladders here (JSON)")
    a = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="tb-ladder-") as t:
            found = rp.collect(a.runs, Path(t))
            res = {n: ladder_of_folder(found[n] / "built", found[n] / "work") for n in sorted(found)}
    except (rp.Refused, OSError, ValueError) as exc:
        print(f"ladder: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write("\n".join(render(res)) + "\n")
    if a.json:
        a.json.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

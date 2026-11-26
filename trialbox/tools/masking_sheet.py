"""The masking sheet of rc1 (card F-3, ring 0 piece 25, rc1 checklist row 9): which identifier forms the masking at
egress (M3: the egress edge's one rule set) masks in each language, at what measured rate, and which it does not.

    python -m tools.masking_sheet --write    # run on this checkout, write results.json and the sheet's tables
    python -m tools.masking_sheet --render   # the sheet's tables from the committed results.json, no run
    python -m tools.masking_sheet --check    # the sheet's tables equal what results.json gives

The run reuses card V-5's harness (``tools.masking_leaks``: synthetic notes with one planted identifier each, its
leak rule and its scopes) and adds four small probe sets, each through the same entry point
(``tb_common.egress_edge.mask_text(text, site_mrn_regex())``, the rules of what leaves the box):

* V5-01's remainder: a kanji surname outside the masker's list directly before 様, 先生 or 殿;
* the J10C1 known gaps of ``eval/phi_synth/ja_guard_probes.json``;
* the plan 10 review's R22-23 probes, rebuilt here (the review did not commit its texts): names without a label and
  names behind an encoding (percent, HTML entities, a zero-width joiner, a decomposed macron, full-width figures);
* R22-21's log probes: a value that is not text in a log record's extras, through ``tb_common.logging.JsonFormatter``.

Every name and number is the harness's own invention (its pools and its seeded generators). The results and the
sheet hold only shapes: a value's digits written ``d``, its letters ``A``/``a``, its kanji ``漢``, its kana
``カ``/``か``.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools import masking_leaks as ml

ROOT = Path(__file__).resolve().parents[1]
SHEET_PATH = ROOT / "docs/validation/masking-sheet.md"
RESULTS_PATH = ROOT / "docs/validation/masking-sheet/results.json"
COMMAND = "PYTHONPATH=libs:services:. .venv/bin/python -m tools.masking_sheet --write"
SHEET_LANGS = ("en", "zh-TW", "ja")
KIND_ORDER = ("name", "national_id", "chart", "phone", "address", "email", "dob")
SCOPES = ("in", "free", "line_break")
ZWJ = "‍"

# ---------------------------------------------------------------------------------------------- shapes


def shape_char(c: str) -> str:
    """The class of one character of a value: digits ``d``, letters ``A``/``a``, kanji ``漢``, kana ``カ``/``か``
    (full-width forms in full-width), a combining mark ``◌``, a format character (a zero-width joiner) ``⟨zwj⟩``."""
    if c == "\n":
        return "⏎"
    if c == "\t":
        return "⇥"
    if "0" <= c <= "9":
        return "d"
    if "０" <= c <= "９":
        return "ｄ"
    if "A" <= c <= "Z":
        return "A"
    if "a" <= c <= "z":
        return "a"
    if "Ａ" <= c <= "Ｚ":
        return "Ａ"
    if "ａ" <= c <= "ｚ":
        return "ａ"
    if "ぁ" <= c <= "ゟ":
        return "か"
    if "゠" <= c <= "ヿ" and c not in "・ー":
        return "カ"
    cat = unicodedata.category(c)
    if cat == "Lo" and "㐀" <= c <= "鿿":
        return "漢"
    if cat == "Mn":
        return "◌"
    if cat == "Cf":
        return "⟨zwj⟩"
    if cat.startswith("L") or cat.startswith("N"):
        return "?"
    return c


def shape(surface: str, v: tuple[int, int] | None = None) -> str:
    """``surface`` with the value at ``v`` (all of it by default) written as its character classes; a label or an
    honorific around the value stays as it is."""
    a, b = v or (0, len(surface))
    return _keep(surface[:a]) + "".join(shape_char(c) for c in surface[a:b]) + _keep(surface[b:])


def _keep(s: str) -> str:
    return s.replace("\n", "⏎").replace("\t", "⇥")


def example(lang: str, form: str) -> str:
    """The example shape of one harness form: one value from the form's own generator, seeded by language and form."""
    for _kind, f, gen in ml.forms(lang):
        if f == form:
            it = gen(random.Random(f"{ml.SEED}:example:{lang}:{form}"))
            return shape(it.surface, it.v)
    raise KeyError(f"{lang} has no form {form!r}")


# ---------------------------------------------------------------------------------------------- reading a value


def readable(text: str, out: str, a: int, b: int, mask_char: str) -> int:
    """How many letters and digits of ``text[a:b]`` the masker's output ``out`` leaves readable (separators, marks
    and format characters are not counted)."""
    if len(out) != len(text):
        raise ml.PlantError("the masker changed the length; a value is read by place")
    return sum(1 for i in range(a, b) if unicodedata.category(text[i])[0] in "LN" and out[i] != mask_char)


# ---------------------------------------------------------------------------------------------- V5-01's remainder
#: the harness's kanji family names outside the masker's surname list, each with a harness given name
V5_01_NAMES = (("丸山", "陽子"), ("大塚", "翔太"), ("吉川", "美咲"), ("今井", "健一"))
V5_01_SUFFIXES = ("様", "先生", "殿")
V5_01_FRAMES = ("{}来院。", "本日{}来院。")  # at a line's start; after a word


def v5_01_probes() -> list[tuple[str, int, int]]:
    """``(text, start, end of the surname)``: each unlisted surname, with its given name, directly before each
    honorific, in each frame."""
    out = []
    for frame in V5_01_FRAMES:
        for suffix in V5_01_SUFFIXES:
            for fam, given in V5_01_NAMES:
                value = fam + given + suffix
                text = frame.format(value)
                a = text.index(value)
                out.append((text, a, a + len(fam)))
    return out


def v5_01_readable(mask: Callable[[str], str], mask_char: str) -> list[str]:
    """The V5-01 probes whose whole surname the masker leaves readable."""
    bad = []
    for text, a, b in v5_01_probes():
        if readable(text, mask(text), a, b, mask_char) == b - a:
            bad.append(text)
    return bad


# ---------------------------------------------------------------------------------------------- J10C1 known gaps
J10C1_ROWS = {
    "J10C1-01": ("free_name",),
    "J10C1-02": ("romaji_name",),
    "J10C1-03": ("line_break",),
    "J10C1-04": ("address",),
    "J10C1-05": ("pension", "passport"),
}
JA_PROBES = ROOT / "eval/phi_synth/ja_guard_probes.json"


def j10c1(eng: ml.Engines) -> dict[str, Any]:
    """J10C1-01 to -05: the known-gap lines with an identifier left readable; J10C1-06: the known over-masked
    ordinary lines the masker alters."""
    known = json.loads(JA_PROBES.read_text(encoding="utf-8"))["known_gaps"]
    gaps = known["missed"]
    out: dict[str, Any] = {}
    for row, kinds in J10C1_ROWS.items():
        n = missed = 0
        for p in gaps:
            if p["kind"] not in kinds:
                continue
            text, masked = str(p["text"]), eng.mask(str(p["text"]))
            n += 1
            for value in p["ids"]:
                a = text.index(value)
                if readable(text, masked, a, a + len(value), eng.mask_char):
                    missed += 1
                    break
        out[row] = {"kinds": list(kinds), "probes": n, "missed": missed}
    lines = [str(t) for t in known["overmasked"]]
    out["J10C1-06"] = {"kinds": ["overmasked"], "probes": len(lines), "altered": sum(eng.mask(t) != t for t in lines)}
    return out


# ---------------------------------------------------------------------------------------------- R22-23, rebuilt


def _entities(s: str) -> str:
    return "".join(f"&#{ord(c)};" for c in s)


def _zwj(s: str) -> str:
    return s[0] + ZWJ + s[1:]


def _macron(s: str) -> str:
    """The first O of a Hepburn name with a decomposed macron (Otsuka as O, U+0304, tsuka)."""
    i = s.index("O")
    return s[: i + 1] + "̄" + s[i + 1 :]


def _ja_name(r: random.Random) -> str:
    return r.choice(ml.JA_FAMILY)[0] + r.choice(ml.JA_GIVEN)[0]


def _zh_name(r: random.Random) -> str:
    return ml._zh_name(r, 3)[0]


def _en_name(r: random.Random) -> str:
    return f"{r.choice(ml.EN_FIRST)} {r.choice(ml.EN_LAST)}"


def _hepburn_o(r: random.Random) -> str:
    fam = r.choice([f[3] for f in ml.JA_FAMILY if f[3].startswith("O")])
    return f"{fam.upper()} {r.choice(ml.JA_GIVEN)[3]}"


#: language -> (category, frame with {} where the value goes, the value's generator); a frame is a clinical line
R22_23: dict[str, list[tuple[str, str, Callable[[random.Random], str]]]] = {
    "ja": [
        ("label", "氏名：{}。既往歴に糖尿病。", _ja_name),
        ("no_label", "患者は{}。既往歴に糖尿病。", _ja_name),
        ("percent", "氏名：{}。既往歴に糖尿病。", lambda r: quote(_ja_name(r))),
        ("entities", "氏名：{}。既往歴に糖尿病。", lambda r: _entities(_ja_name(r))),
        ("zero_width_joiner", "氏名：{}。既往歴に糖尿病。", lambda r: _zwj(_ja_name(r))),
        ("decomposed_macron", "氏名：{}。既往歴に糖尿病。", lambda r: _macron(_hepburn_o(r))),
        ("fullwidth_number", "番号：{}。既往歴に糖尿病。", lambda r: ml.fw(ml.my_number(r))),
        ("phone_zero_width_joiner", "電話：{}。既往歴に糖尿病。", lambda r: _zwj(ml._jp_phone(r, "mobile"))),
    ],
    "zh-TW": [
        ("label", "姓名：{}。既往有糖尿病。", _zh_name),
        ("no_label", "病人{}今日回診，既往有糖尿病。", _zh_name),
        ("percent", "姓名：{}。既往有糖尿病。", lambda r: quote(_zh_name(r))),
        ("entities", "姓名：{}。既往有糖尿病。", lambda r: _entities(_zh_name(r))),
        ("zero_width_joiner", "姓名：{}。既往有糖尿病。", lambda r: _zwj(_zh_name(r))),
        ("fullwidth_number", "身分證號：{}。既往有糖尿病。", lambda r: ml.fw(ml.tw_id(r))),
        ("phone_zero_width_joiner", "電話：{}。既往有糖尿病。", lambda r: _zwj(ml._tw_phone(r, "mobile_hyphen"))),
    ],
    "en": [
        ("label", "Name: {}. History of diabetes.", _en_name),
        ("no_label", "Patient {}, male, presents with chest pain.", _en_name),
        ("percent", "Name: {}. History of diabetes.", lambda r: quote(_en_name(r))),
        ("entities", "Name: {}. History of diabetes.", lambda r: _entities(_en_name(r))),
        ("zero_width_joiner", "Name: {}. History of diabetes.", lambda r: _zwj(_en_name(r))),
        ("fullwidth_number", "SSN {}. History of diabetes.", lambda r: ml.fw(ml.ssn(r))),
        ("phone_zero_width_joiner", "Phone: {}. History of diabetes.", lambda r: _zwj(ml._na_phone(r, "hyphen"))),
    ],
}
R22_23_PER = 3  # values per category


def r22_23(eng: ml.Engines) -> dict[str, Any]:
    """Per language and category: probes, missed (any letter or digit of the value readable after the masker) and
    the tripwire's misses."""
    out: dict[str, Any] = {}
    for lang in SHEET_LANGS:
        rng = random.Random(f"{ml.SEED}:r22-23:{lang}")
        cats: dict[str, Any] = {}
        for cat, frame, gen in R22_23[lang]:
            c = cats.setdefault(cat, {"probes": 0, "missed": 0, "tripwire_missed": 0, "example": ""})
            for _ in range(R22_23_PER):
                value = gen(rng)
                text = frame.replace("{}", value)
                a = text.index(value)
                c["probes"] += 1
                c["missed"] += readable(text, eng.mask(text), a, a + len(value), eng.mask_char) > 0
                c["tripwire_missed"] += not eng.tripwire(text)
                c["example"] = c["example"] or shape(text, (a, a + len(value)))
        out[lang] = {
            "probes": sum(c["probes"] for c in cats.values()),
            "missed": sum(c["missed"] for c in cats.values()),
            "categories": cats,
        }
    return out


# ---------------------------------------------------------------------------------------------- R22-21, logs


class _Row:
    """A record object whose text form holds identifiers (as a dataclass or ORM row would print)."""

    def __init__(self, name: str, phone: str) -> None:
        self.name, self.phone = name, phone

    def __str__(self) -> str:
        return f"Row(name={self.name!r}, phone={self.phone!r})"


#: the value types put in a log record's extras; ``text`` is the control
LOG_TYPES: dict[str, Callable[[str], Any]] = {
    "text": lambda v: v,
    "object": lambda v: _Row(v, "-"),
    "path": lambda v: Path("/var/lib/trialbox/export") / v / "note.txt",
    "exception": lambda v: ValueError(f"no consent for {v}"),
    "bytes": lambda v: v.encode("utf-8"),
}


def _log_values(r: random.Random) -> list[tuple[str, str]]:
    """``(language, value)``: a name with an honorific and a phone in each language, from the harness's generators."""
    f, g = r.choice(ml.JA_FAMILY), r.choice(ml.JA_GIVEN)
    return [
        ("ja", f[0] + g[0] + "さん"),
        ("ja", ml._jp_phone(r, "mobile")),
        ("zh-TW", ml._zh_name(r, 3)[0] + "先生"),
        ("zh-TW", ml._tw_phone(r, "mobile_hyphen")),
        ("en", "Mr. " + _en_name(r)),
        ("en", ml._na_phone(r, "hyphen")),
    ]


def _strings(x: Any) -> list[str]:
    if isinstance(x, dict):
        return [s for k, v in x.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    return [str(x)]


def r22_21() -> dict[str, Any]:
    """Per extras value type: probes and leaked (the identifier, or its UTF-8 escape for bytes, is in a field of the
    written line)."""
    from tb_common.logging import JsonFormatter

    fmt = JsonFormatter("masking-sheet")
    rng = random.Random(f"{ml.SEED}:r22-21")
    values = _log_values(rng)
    out: dict[str, Any] = {}
    for typ, make in LOG_TYPES.items():
        c = out.setdefault(typ, {"probes": 0, "leaked": 0})
        for _lang, v in values:
            rec = logging.LogRecord("probe", logging.INFO, __file__, 0, "probe", None, None)
            rec.payload = make(v)
            fields = _strings(json.loads(fmt.format(rec)))
            forms = (v, repr(v.encode("utf-8"))[2:-1])
            c["probes"] += 1
            c["leaked"] += any(f in s for s in fields for f in forms)
    return out


# ---------------------------------------------------------------------------------------------- the run


#: the files whose code the run measures: the masker, the harness and its base notes, the guard, the log formatter
MEASURED = (
    "libs/tb_common/phi_guard.py",
    "libs/tb_common/egress_edge.py",
    "libs/tb_common/logging.py",
    "services/guard/guard.py",
    "tools/masking_leaks.py",
    "tools/masking_sheet.py",
    "tools/synth/generator.py",
    "eval/phi_synth/ja_guard_probes.json",
)
BLOBS = (
    "libs/tb_common/phi_guard.py",
    "libs/tb_common/egress_edge.py",
    "tools/masking_leaks.py",
    "libs/tb_common/logging.py",
)
ENTRY_POINT = (
    "tb_common.egress_edge.mask_text(text, site_mrn_regex()), the one rule set of what leaves the box (D-1093)"
)


def _git(*args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def commit() -> dict[str, Any]:
    """The master commit the measured code is compared with (the merge base of HEAD and origin/master), and the
    measured files that differ from it in this checkout (a new tool of this card's differs: it is not on master yet)."""
    sha = _git("merge-base", "HEAD", "origin/master")
    differ = None
    if sha:
        names = _git("diff", "--name-only", sha, "--", *MEASURED)
        differ = sorted(Path(n).relative_to("trialbox").as_posix() for n in (names or "").splitlines() if n)
    return {"master": sha, "measured_files_differ": differ}


def blobs() -> dict[str, str | None]:
    """The git blob id of each file as it is on disk when the run reads it."""
    return {path: _git("hash-object", path) for path in BLOBS}


def _cell() -> dict[str, int]:
    return {"probes": 0, "masked": 0, "partly": 0, "leaked": 0, "tripwire_missed": 0}


def per_thousand(n: int, d: int) -> float:
    return round(1000 * n / d, 1) if d else 0.0


def summarise(leaks: dict[str, Any]) -> dict[str, Any]:
    """The harness's cells as one row per language and form, with its scopes, and the totals per language."""
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for lang in SHEET_LANGS:
        for kind, form, _gen in ml.forms(lang):
            if form not in ml.NOT_HELD:
                rows[(lang, kind, form)] = {"lang": lang, "kind": kind, "form": form, "example": example(lang, form)}
    for key, c in leaks["cells"].items():
        lang, kind, form, sc = key.split("|")
        cell = {
            "probes": c["planted"],
            "masked": c["planted"] - c["leaked"] - c["partly"],
            "partly": c["partly"],
            "leaked": c["leaked"],
            "tripwire_missed": c["tripwire_missed"],
        }
        cell["leaked_per_1000"] = per_thousand(cell["leaked"], cell["probes"])
        rows[(lang, kind, form)][sc] = cell
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    forms = sorted(rows.values(), key=lambda r: (SHEET_LANGS.index(r["lang"]), order[r["kind"]]))
    return {"forms": forms, "totals": totals(forms)}


def totals(forms: list[dict[str, Any]]) -> dict[str, Any]:
    """Per language, per scope, and per scope and kind: the sums of the form rows."""
    out: dict[str, Any] = {}
    for r in forms:
        for sc in SCOPES:
            if sc not in r:
                continue
            for key in (sc, f"{sc}|{r['kind']}"):
                t = out.setdefault(r["lang"], {}).setdefault(key, _cell())
                for f in t:
                    t[f] += r[sc][f]
    for lang in out.values():
        for t in lang.values():
            t["leaked_per_1000"] = per_thousand(t["leaked"], t["probes"])
    return out


def run(eng: ml.Engines) -> dict[str, Any]:
    leaks = ml.run(eng)
    sheet = summarise(leaks)
    not_held = []
    for k, c in leaks["not_held"].items():
        lang, _kind, form, sc = k.split("|")
        not_held.append({"lang": lang, "form": form, "scope": sc, "probes": c["planted"], "leaked": c["leaked"]})
    v5 = v5_01_readable(eng.mask, eng.mask_char)
    return {
        "card": "F-3",
        "rc1_row": 9,
        "commit": commit(),
        "blobs": blobs(),
        "site_mrn_regex": eng.mrn_regex,
        "date": date.today().isoformat(),
        "command": COMMAND,
        "entry_point": ENTRY_POINT,
        "harness": {
            "tool": "tools/masking_leaks.py",
            "seed": leaks["seed"],
            "per_form": ml.PER_FORM,
            "base_notes": leaks["base_notes"],
        },
        "forms": sheet["forms"],
        "totals": sheet["totals"],
        "not_held": not_held,
        "v5_01": {"probes": len(v5_01_probes()), "readable": len(v5), "readable_shapes": [shape(t) for t in v5]},
        "j10c1": j10c1(eng),
        "over_masking": [
            {"lang": k.split("|")[0], "kind": k.split("|")[1], "probes": c["planted"], "altered": c["altered"]}
            for k, c in leaks["over_masking"].items()
        ],
        "r22_23": r22_23(eng),
        "r22_21": r22_21(),
    }


# ---------------------------------------------------------------------------------------------- the sheet's tables
SCOPE_WORD = {"in": "in scope", "free": "free-standing", "line_break": "line break"}
#: a cell with fewer probes than this shows its count, not a rate
SMALL = 20


def rate(k: int, n: int) -> str:
    """A table's per-1,000 cell: the rate, or for a small cell the probe count (``6 probes``)."""
    return f"{n} probes" if n < SMALL else f"{per_thousand(k, n)}"


def frac(k: int, n: int, verb: str = "leaked") -> str:
    """``k of n leaked``, with the rate per 1,000 only when ``n`` is not small."""
    return f"{k} of {n} {verb}" + (f" ({per_thousand(k, n)} per 1,000)" if n >= SMALL else "")


def _of(c: dict[str, Any] | None) -> str:
    return f"{c['leaked']} of {c['probes']}" if c else "-"


def lang_table(res: dict[str, Any], lang: str) -> str:
    out = [
        "| Kind | Form | Example shape | Probes | Masked | Partly | Leaked | Masked per 1,000 | Leaked per 1,000 "
        "| Free-standing: leaked | Line break: leaked | Tripwire missed |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in res["forms"]:
        if r["lang"] != lang:
            continue
        c = r.get("in")
        if c:
            head = (
                f"{c['probes']} | {c['masked']} | {c['partly']} | {c['leaked']} | "
                f"{rate(c['masked'], c['probes'])} | {rate(c['leaked'], c['probes'])}"
            )
        else:
            head = "- | - | - | - | - | -"
        trip = str(c["tripwire_missed"]) if c else "-"
        out.append(
            f"| {r['kind']} | {r['form']} | `{r['example']}` | {head} | {_of(r.get('free'))} | "
            f"{_of(r.get('line_break'))} | {trip} |"
        )
    return "\n".join(out)


def pass_table(res: dict[str, Any], lang: str) -> str:
    """The forms of ``lang`` the masker lets pass, in whole or in part, within the ruling's scope."""
    out = [
        "| Kind | Form | Example shape | Leaked | Partly | Of | Leaked per 1,000 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for r in res["forms"]:
        c = r.get("in")
        if r["lang"] == lang and c and (c["leaked"] or c["partly"]):
            out.append(
                f"| {r['kind']} | {r['form']} | `{r['example']}` | {c['leaked']} | {c['partly']} | {c['probes']} | "
                f"{rate(c['leaked'], c['probes'])} |"
            )
    t = res["totals"][lang]
    out.append("")
    out.append(
        f"In scope, all forms: {frac(t['in']['leaked'], t['in']['probes'])}, {t['in']['partly']} partly masked. "
        f"Free-standing names: {_of(t.get('free'))} leaked. A value split by a line break: {_of(t.get('line_break'))} "
        f"leaked."
    )
    return "\n".join(out)


def summary_table(res: dict[str, Any]) -> str:
    out = [
        "| Language | Scope | Probes | Masked | Partly | Leaked | Masked per 1,000 | Leaked per 1,000 "
        "| Tripwire missed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for lang in SHEET_LANGS:
        rows = [(SCOPE_WORD[sc], res["totals"][lang].get(sc)) for sc in SCOPES]
        rows.append(("names in scope", res["totals"][lang]["in|name"]))
        for word, t in rows:
            if t:
                out.append(
                    f"| {lang} | {word} | {t['probes']} | {t['masked']} | {t['partly']} | {t['leaked']} | "
                    f"{rate(t['masked'], t['probes'])} | {rate(t['leaked'], t['probes'])} | "
                    f"{t['tripwire_missed']} |"
                )
    return "\n".join(out)


def _sum(res: dict[str, Any], keep: Callable[[dict[str, Any]], bool], sc: str = "in") -> dict[str, int]:
    """The sums of the ``sc`` cells of the form rows ``keep`` accepts."""
    out = _cell()
    for r in res["forms"]:
        if sc in r and keep(r):
            for f in out:
                out[f] += r[sc][f]
    return out


def measured(c: dict[str, int]) -> str:
    """A row's figure: ``0 of N leaked on this run`` when nothing leaked (no more is claimed), else the count."""
    if c["leaked"] == 0:
        return f"0 of {c['probes']} leaked on this run" + (f"; {c['partly']} partly masked" if c["partly"] else "")
    return frac(c["leaked"], c["probes"]) + (f"; {c['partly']} partly masked" if c["partly"] else "")


INSURANCE = ("ja", "insurance_symbol_no")


def _forms(*pairs: tuple[str, str]) -> Callable[[dict[str, Any]], bool]:
    return lambda r: (r["lang"], r["form"]) in pairs


def row_figures(res: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Each open masking row of the register (and the review's R22-21 and R22-23): what passes, and what this run
    measured of it."""
    t = res["totals"]

    def names(lang: str) -> str:
        return f"{lang} names in scope: {measured(t[lang]['in|name'])}"

    v5, jr, r23, r21 = res["v5_01"], res["j10c1"], res["r22_23"], res["r22_21"]
    over = [o for o in res["over_masking"] if o["kind"] == "date_compact8"]
    trip = _sum(res, lambda r: True)
    full_at = _sum(res, lambda r: r["form"] == "fullwidth_at")
    fw_phone = _forms(
        ("zh-TW", "tw_mobile_fullwidth"),
        ("ja", "jp_fullwidth"),
        ("zh-TW", "tw_landline_paren"),
        ("en", "tw_landline_paren"),
    )
    nt = [c for k, c in r21.items() if k != "text"]
    by = "; ".join(f"{lg} {r23[lg]['missed']} of {r23[lg]['probes']}" for lg in SHEET_LANGS)
    j = {
        row: f"{jr[row]['missed']} of {jr[row]['probes']} "
        + ("lines readable" if jr[row]["missed"] else "leaked on this run")
        for row in J10C1_ROWS
    }
    return {
        "V5-01": (
            "Japanese names in scope; what is left: a kanji surname outside the masker's list before 様, 先生 or 殿",
            f"{names('ja')}; the surname readable in {v5['readable']} of {v5['probes']} probes of the remainder",
        ),
        "V5-02": ("English names in scope", names("en")),
        "V5-03": ("Chinese names in scope", names("zh-TW")),
        "V5-04": ("The insurance card's 記号・番号 after its label", measured(_sum(res, _forms(INSURANCE)))),
        "V5-05": ("An e-mail with a full-width ＠ (three languages)", measured(full_at)),
        "V5-06": ("Full-width mobiles; landlines with the area code in brackets", measured(_sum(res, fw_phone))),
        "V5-07": ("A value split by a hard wrap (all forms)", measured(_sum(res, lambda r: True, "line_break"))),
        "V5-08": ("A compact ROC birth date before 出生", measured(_sum(res, _forms(("zh-TW", "born_roc_compact"))))),
        "V5-09": ("A US SSN (no label)", measured(_sum(res, _forms(("en", "us_ssn"))))),
        "V5-10": (
            "The gateway's tripwire on in-scope notes",
            f"the tripwire missed {frac(trip['tripwire_missed'], trip['probes'], 'notes')}",
        ),
        "V5-11": (
            "Over-masking: an 8-digit clinical date",
            frac(sum(o["altered"] for o in over), sum(o["probes"] for o in over), "altered"),
        ),
        "V5-12": (
            "The postcode of a masked full address",
            measured(_sum(res, _forms(("zh-TW", "tw_full"), ("ja", "jp_full"), ("en", "en_full")))),
        ),
        "V5-13": (
            "Free-standing names (no label, role, title or honorific)",
            measured(_sum(res, lambda r: r["kind"] == "name", "free")),
        ),
        "J10C1-01": ("A Japanese name with no label or honorific", j["J10C1-01"]),
        "J10C1-02": ("A romaji name without a label", j["J10C1-02"]),
        "J10C1-03": ("A name split by a line break after its label", j["J10C1-03"]),
        "J10C1-04": ("An address without 市", j["J10C1-04"]),
        "J10C1-05": ("A pension number and a passport number", j["J10C1-05"]),
        "J10C1-06": (
            "Over-masking: two ordinary Japanese lines",
            f"{jr['J10C1-06']['altered']} of {jr['J10C1-06']['probes']} lines altered",
        ),
        "R22-23": (
            "The review's: names without a label, and identifiers behind an encoding",
            f"{sum(r23[lg]['missed'] for lg in SHEET_LANGS)} of {sum(r23[lg]['probes'] for lg in SHEET_LANGS)} "
            f"rebuilt probes readable ({by})",
        ),
        "R22-21": (
            "The review's: log extras that are not text (the log formatter, not the note masker)",
            f"{frac(sum(c['leaked'] for c in nt), sum(c['probes'] for c in nt))}; text extras "
            f"{r21['text']['leaked']} of {r21['text']['probes']}",
        ),
    }


def rows_table(res: dict[str, Any]) -> str:
    out = ["| Row | What passes | Measured on this run |", "|---|---|---|"]
    for row, (what, fig) in row_figures(res).items():
        out.append(f"| {row} | {what} | {fig} |")
    return "\n".join(out)


def r22_23_table(res: dict[str, Any]) -> str:
    out = [
        "| Language | Category | Example shape | Probes | Readable after the masker | Tripwire missed |",
        "|---|---|---|---:|---:|---:|",
    ]
    for lang in SHEET_LANGS:
        for cat, c in res["r22_23"][lang]["categories"].items():
            cells = f"{c['probes']} | {c['missed']} | {c['tripwire_missed']}"
            out.append(f"| {lang} | {cat} | `{c['example']}` | {cells} |")
    return "\n".join(out)


def r22_21_table(res: dict[str, Any]) -> str:
    out = ["| Extras value type | Probes | Identifier written readable |", "|---|---:|---:|"]
    for typ, c in res["r22_21"].items():
        out.append(f"| {typ} | {c['probes']} | {c['leaked']} |")
    return "\n".join(out)


def run_line(res: dict[str, Any]) -> str:
    h, c = res["harness"], res["commit"]
    bn = ", ".join(f"{lg} {x['kept']}" for lg, x in h["base_notes"].items())
    differ = ", ".join(f"`{p}`" for p in c["measured_files_differ"]) or "none"
    bl = "; ".join(f"`{p}` `{b}`" for p, b in res["blobs"].items())
    return (
        f"The measured code equals master commit `{c['master']}` (the merge base with `origin/master`) except: "
        f"{differ}. Blobs as read: {bl}. Site chart-number pattern in effect: `{res['site_mrn_regex']}`. "
        f"Run {res['date']}, command `{res['command']}` (from `trialbox/`). Entry point: `{res['entry_point']}`. "
        f"Harness seed {h['seed']}, {h['per_form']} notes per form (three at each of seven places); base notes kept: "
        f"{bn}."
    )


def blocks(res: dict[str, Any]) -> dict[str, str]:
    out = {"run": run_line(res), "summary": summary_table(res)}
    for lang in SHEET_LANGS:
        out[f"forms-{lang}"] = lang_table(res, lang)
        out[f"pass-{lang}"] = pass_table(res, lang)
    out["rows"] = rows_table(res)
    out["r22-23"] = r22_23_table(res)
    out["r22-21"] = r22_21_table(res)
    return out


def block(name: str) -> re.Pattern[str]:
    """The generated block ``name`` of the sheet: its begin marker, its body, its end marker."""
    n = re.escape(name)
    return re.compile(rf"(<!-- masking-sheet:{n}:begin -->\n)(.*?)(\n<!-- masking-sheet:{n}:end -->)", re.S)


def render(page: str, bodies: dict[str, str]) -> str:
    for name, body in bodies.items():
        m = block(name).search(page)
        if m is None:
            raise SystemExit(f"the sheet has no generated block {name!r}")
        page = page[: m.start(2)] + body + page[m.end(2) :]
    return page


def load(path: Path = RESULTS_PATH) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def check(sheet: Path = SHEET_PATH, results: Path = RESULTS_PATH) -> list[str]:
    """The sheet's generated blocks that differ from what ``results.json`` gives (a missing block counts)."""
    page = sheet.read_text(encoding="utf-8")
    bad = []
    for name, body in blocks(load(results)).items():
        m = block(name).search(page)
        if not m or m.group(2) != body:
            bad.append(name)
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="run, write results.json and the sheet's tables")
    g.add_argument("--render", action="store_true", help="the sheet's tables from the committed results.json")
    g.add_argument("--check", action="store_true", help="the sheet's tables equal results.json")
    a = ap.parse_args(argv)
    if a.check:
        bad = check()
        print("masking-sheet: sheet and results.json agree" if not bad else f"masking-sheet: differ: {bad}")
        return 1 if bad else 0
    if a.write:
        res = run(ml.engines())
        if not res["commit"]["master"]:
            raise SystemExit("no merge base with origin/master: fetch master first; the results must name it")
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    SHEET_PATH.write_text(render(SHEET_PATH.read_text(encoding="utf-8"), blocks(load())), encoding="utf-8")
    print(f"masking-sheet: wrote {SHEET_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

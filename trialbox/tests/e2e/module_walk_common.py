"""H-29 (D-1103): what the four module walks share: their texts, acts, steps and findings, the browser's plan, the
findings page and the runs' logs.

Each module walk is a plan file of its own (``module_walk_<module>_plan.py``: feasibility, safety, monitoring,
amendment). A walk is a list of steps, each done by the role that owns it in the permission matrix
(``libs/tb_common/authz_matrix.yaml``, the row in the step's ``row``), with the refusals of the roles that do not own
it (a real request with the page's form token, answered 403 with the refusal page). Two walks begin where H-20's
walk begins (``prefix``: H-10's eleven steps and H-20's steps 12 to 15, imported from ``life_cycle_walk_plan``, not
copied): a new study, its first patient approached, given a screening number, consented and enrolled.

Every text a person clicks or reads is the product's: a key of the console's catalogue (:class:`T`, H-10's), or a
label of a built-in form (:class:`F`, ``services/datacore/builtin/forms.csv``, whose three language columns are the
forms' catalogue). The browser is H-20's driver (``tests/e2e/life_cycle_walk.js``) loaded by
``tests/e2e/module_walk.js``, which adds the acts of :class:`M`. A :class:`Stop` is a reasoned stop read from the
product: where the page shows what the product's documents say it should not (or does not show what they say it
should), the step stops with the page's own words and a finding that blocks the step; the walk never asserts the
fault as correct.

    PYTHONPATH=libs:services:. python -m tests.e2e.module_walk_common --plan safety en     # the browser's plan
    PYTHONPATH=libs:services:. python -m tests.e2e.module_walk_common --write              # rewrite the findings page
    PYTHONPATH=libs:services:. python -m tests.e2e.module_walk_common --summary LOG..      # runs' logs, summed up
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from tests.e2e import life_cycle_walk_plan as lp
from tests.e2e import new_study_walk_plan as nw
from tests.e2e.life_cycle_walk_plan import Finding, K
from tests.e2e.new_study_walk_plan import Do, Refuse, See, T

ROOT = nw.ROOT
LANGS = nw.LANGS
SEVERITIES = lp.SEVERITIES
LANES = lp.LANES
MODULES = ("feasibility", "safety", "monitoring", "amendment")
FINDINGS_PAGE = ROOT / "docs" / "handover" / "module-walks-findings-2026-11-17.md"
BEGIN = "<!-- module-walks: findings, written by tests/e2e/module_walk_common.py; do not edit by hand -->"
END = "<!-- module-walks: end of findings -->"
#: the roles of the module walks: H-10's four and the two aggregate roles, by the console role each one is
CONSOLE_ROLE = {**nw.CONSOLE_ROLE, "cro": "cro", "viewer": "viewer"}
ROLES = tuple(CONSOLE_ROLE)
#: four-account mode: the steps-mode box's own seeded accounts (tools/demo.py SEEDED; cra is the CRO account)
SEEDED_ACCOUNTS = {**nw.SEEDED_ACCOUNTS, "cro": "cra", "viewer": "viewer"}
#: the box's day: the walk's box runs on ``--day data`` (the synthetic hospital's own day, a frozen clock)
BOX_DAY = "2026-11-02"
#: the steps of H-20's walk a module walk may begin with: H-10's 1 to 11, then H-20's 12 to 15 (a participant enrolled)
PREFIX_LAST = 15
KINDS = ("label", "testid", "address", "confirmation", "way back", "required", "language", "term", "other", "stop")


# ------------------------------------------------------------------------------------------------------ the texts
@cache
def form_fields() -> dict[str, Any]:
    """The built-in forms' fields by name (``datacore.builtin``): their labels and choices in three languages."""
    from datacore.builtin import fields

    return {f.name: f for f in fields()}


@dataclass(frozen=True)
class F(T):
    """A built-in form's text: the label of field ``key`` or, with ``option``, the label of that choice."""

    option: str = ""

    def text(self, lang: str, rs: str) -> str:
        f = form_fields()[str(self.key)]
        if self.option:
            return f.options[self.option] if lang == "en" else f.option_labels.get(lang, {}).get(self.option, "")
        return str(f.label) if lang == "en" else f.labels.get(lang, "")

    def missing(self) -> list[str]:
        return [lang for lang in ("zh-TW", "ja") if not self.text(lang, "")]


@dataclass(frozen=True)
class S(T):
    """A catalogue text with a suffix the template writes after it (``Monitoring · {rs}``)."""

    suffix: str = ""

    def text(self, lang: str, rs: str) -> str:
        return T(self.key, self.values, self.prefix).text(lang, rs) + self.suffix.replace("{rs}", rs)


# ------------------------------------------------------------------------------------------------------- the acts
@dataclass(frozen=True)
class M:
    """An act of ``tests/e2e/module_walk.js`` (the acts H-20's driver does not have). ``kind``: ``field`` (type
    ``value`` into the input labelled ``label``), ``choose`` (in the group ``label``, choose ``text``), ``check`` (tick
    the box ``label``), ``pick`` (choose ``value`` in the select ``label``)."""

    kind: str
    label: T
    text: T | None = None
    value: str = ""


@dataclass(frozen=True)
class Act:
    """H-20's acts (:class:`life_cycle_walk_plan.Act`) with this module's findings: ``link_start``, ``card_link``,
    ``first_row_link``, ``remember``, ``read``, ``goto``. ``finding`` is the finding the act stands for (a guess)."""

    kind: str
    text: T | None = None
    label: str = ""
    value: str = ""
    within: str = ""
    finding: str = ""
    wait_s: int = 30


@dataclass(frozen=True)
class Stop:
    """A reasoned stop: when the page holds the expectation (``kind`` as :class:`See`: ``h1``, ``says``, ``shown``,
    ``gone``, ``path``, ``body``, or this walk's ``absent``), the step stops and the walk records ``finding`` with the
    page's own words; later steps that stand on it are recorded as not walked."""

    kind: str
    finding: str
    text: T | None = None
    value: str = ""


@dataclass(frozen=True)
class Step:
    """One step: ``n``, the role that does it, the matrix row that lets it (``row``; "" for a step that reads only
    what every signed-in role reads, with ``why_no_row``), the acts, the refusals, what the step does and what the
    product's documents say comes of it (``expect``, with the source), its lane and the steps it stands on."""

    n: int
    role: str
    row: str
    acts: tuple[Any, ...]
    refusals: tuple[Refuse, ...]
    what: str
    expect: str
    lane: str = "C2"
    after: tuple[int, ...] = ()
    why_no_row: str = ""


def refuse(role: str, method: str, path: str, why: str, fields: tuple[tuple[str, str], ...] = ()) -> Refuse:
    return Refuse(role, method, path, fields, {lang: why for lang in LANGS})


@dataclass(frozen=True)
class Module:
    """One module walk: its steps after the prefix, its findings, what a steps-mode box cannot complete, the study
    it walks (``study``, a study the box seeds; else a new study per language under ``rulesets``), and the
    committed summary of its runs (per step: the page, the clicks and their texts in en, the median seconds)."""

    key: str
    title: str
    roles: tuple[str, ...]
    steps: tuple[Step, ...]
    findings: tuple[Finding, ...]
    not_completed: tuple[tuple[int, str, str], ...]
    rulesets: dict[str, str] = field(default_factory=dict)
    study: str = ""
    prefix: bool = False
    summary: dict[int, dict[str, Any]] = field(default_factory=dict)
    sources: str = ""


@cache
def modules() -> dict[str, Module]:
    return {m: importlib.import_module(f"tests.e2e.module_walk_{m}_plan").MODULE for m in MODULES}


def finding(mod: Module, fid: str) -> Finding:
    return next(f for f in mod.findings if f.id == fid)


def _showed(mod: Module, fid: str) -> str:
    """What the finding ``fid`` says the page showed (the fast tests hold that every finding an act names exists)."""
    return next((f.showed for f in mod.findings if f.id == fid), fid)


def prefix_steps() -> tuple[Any, ...]:
    """H-10's steps and H-20's steps 12 to 15, as their plans have them."""
    return (*nw.STEPS, *(lf.step for lf in lp.LIFE if lf.step.n <= PREFIX_LAST))


def all_steps(mod: Module) -> tuple[Any, ...]:
    return (*(prefix_steps() if mod.prefix else ()), *mod.steps)


def texts_of(step: Any) -> list[T]:
    out: list[T] = []
    for a in step.acts:
        for t in (getattr(a, "text", None), getattr(a, "label", None)):
            if isinstance(t, T):
                out.append(t)
    if step.refusals:
        out.append(nw.FORBIDDEN_PAGE)
    return out


def untranslated(step: Any, lang: str) -> list[str]:
    return [f"{t.key}: no {lang} form, shown in English" for t in texts_of(step) if t.key and lang in t.missing()]


# ---------------------------------------------------------------------------------------------- the browser's plan
def _resolve(lang: str, rs: str, t: T | None) -> str:
    return "" if t is None else t.text(lang, rs)


def ids(mod: Module, environ: dict[str, str] | Any) -> dict[str, str]:
    """The study each language walks: the seeded study, or the module's new ids (``TB_WALK_ID`` gives another base:
    ``<base>S`` for safety, ``<base>A`` for amendment, each with ``ZH`` and ``JA`` added)."""
    if mod.study:
        return {lang: mod.study for lang in LANGS}
    base = (environ.get("TB_WALK_ID") or "").strip().upper()
    if not base:
        return dict(mod.rulesets)
    base += mod.key[0].upper()  # the safety and amendment walks never share an id
    return {"en": base, "zh-TW": base + "ZH", "ja": base + "JA"}


def plan_json(mod: Module, lang: str, rs: str, accounts: dict[str, str], log: str = "") -> dict[str, Any]:
    """The walk of ``mod`` in ``lang`` on study ``rs``: the prefix as H-20's plan has it (when the module begins with
    a new study), then the module's steps, every text resolved as the product writes it."""
    plan = lp.plan_json(lang, rs, accounts, log)
    plan["steps"] = [s for s in plan["steps"] if mod.prefix and s["n"] <= PREFIX_LAST]

    def fill(s: str) -> str:
        out = s.replace("{rs}", rs).replace("{v}", nw.VERSION).replace("{day}", BOX_DAY).replace("{lang}", lang.upper())
        return out.replace("{cro}", accounts.get("cro", "")).replace("{investigator}", accounts.get("investigator", ""))

    def text(t: T | None) -> str:
        return fill(_resolve(lang, rs, t))

    for st in mod.steps:
        acts: list[dict[str, Any]] = []
        for a in st.acts:
            if isinstance(a, See):
                acts.append({"do": "see", "kind": a.kind, "text": text(a.text), "value": fill(a.value)})
            elif isinstance(a, Stop):
                words = fill(a.value) or text(a.text)  # the page's words the stop records
                acts.append({"do": "stop", "kind": a.kind, "text": text(a.text), "value": words,
                             "finding": a.finding, "why": _showed(mod, a.finding)})  # fmt: skip
            elif isinstance(a, M):
                acts.append({"do": a.kind, "label": text(a.label), "text": text(a.text),
                             "value": fill(a.value), "within": "", "wait_s": 30})  # fmt: skip
            elif isinstance(a, Act):
                acts.append({"do": a.kind, "text": text(a.text), "label": a.label, "value": fill(a.value),
                             "within": fill(a.within), "finding": a.finding,
                             "guess": _showed(mod, a.finding) if a.finding else "", "wait_s": a.wait_s})  # fmt: skip
            else:
                acts.append({"do": a.kind, "text": text(a.text), "label": text(a.label),
                             "value": fill(a.value), "within": fill(a.within), "wait_s": a.wait_s})  # fmt: skip
        plan["steps"].append({
            "n": st.n,
            "key": f"{mod.key}-{st.n}",
            "role": st.role,
            "lane": st.lane,
            "after": list(st.after),
            "guesses": [{"kind": "language", "detail": g} for g in untranslated(st, lang)],
            "acts": acts,
            "refusals": [{"role": r.role, "method": r.method, "path": fill(r.path),
                          "fields": {k: fill(v) for k, v in r.fields}} for r in st.refusals],
        })  # fmt: skip
    plan["module"] = mod.key
    plan["log"] = log
    return plan


# ---------------------------------------------------------------------------------------------- the findings page
def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def counts(mod: Module) -> dict[str, int]:
    return {sev: sum(f.severity == sev for f in mod.findings) for sev in SEVERITIES}


def render_module(mod: Module) -> list[str]:
    out = [f"### {mod.title}", ""]
    study = (
        f"the seeded study {mod.study}"
        if mod.study
        else ("a new study per language (" + ", ".join(mod.rulesets.values()) + "), from H-20's steps 1 to 15")
    )
    out += [f"Roles: {', '.join(mod.roles)}. Study: {study}. Sources: {mod.sources}.", ""]
    out += ["#### The walk by step", ""]
    out += ["| Step | Role | Matrix row | What the step does | Page reached (en) | Clicks | The clicks (en) | Median s | "
            "Refused (403) | Guesses |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    if mod.prefix:
        out.append(f"| 1–{PREFIX_LAST} | (H-10, H-20) | – | H-10's new study and H-20's steps 12 to 15, unchanged: "
                   "protocol in, PI named, approval, FEAS, SCREEN, candidates; weekly page, Approach, contact outcome, "
                   "consent and enrolment | – | – | – | – | as H-10 and H-20 | – |")  # fmt: skip
    for st in mod.steps:
        sm = mod.summary.get(st.n, {})
        refused = "; ".join(f"{r.role}: `{r.method} {r.path}`" for r in st.refusals) or "–"
        stop = f" (stops: {', '.join(sm['stopped'])})" if sm.get("stopped") else ""
        out.append(
            f"| {st.n} | {st.role} | `{st.row or '–'}` | {_cell(st.what)} | `{sm.get('path', '')}` · "
            f"{_cell(sm.get('heading', ''))}{stop} | {sm.get('clicks', '')} | {_cell(' → '.join(sm.get('click_texts', [])))}"
            f" | {sm.get('seconds', '')} | {_cell(refused)} | {', '.join(sm.get('guesses', [])) or '–'} |"
        )
    out += ["", "#### The findings by step", ""]
    out += ["| Id | Step | Role | Page | Clicks | What a tester would have had to guess | Expected (from) | "
            "Severity | Lane |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for f in sorted(mod.findings, key=lambda f: (f.step, f.id)):
        clicks = mod.summary.get(f.step, {}).get("clicks", "")
        out.append(f"| {f.id} | {f.step} | {f.role} | `{f.path}` | {clicks} | {_cell(f.showed)} | "
                   f"{_cell(f.expected)} ({_cell(f.source)}) | {f.severity} | {f.lane} |")  # fmt: skip
    out += ["", "#### Cannot complete on a steps-mode box", ""]
    if mod.not_completed:
        out += ["| Step | What | What the product needs that the box does not have |", "| --- | --- | --- |"]
        out += [f"| {n} | {_cell(what)} | {_cell(why)} |" for n, what, why in mod.not_completed]
    else:
        out.append("Nothing: every step of this walk completes on a steps-mode box.")
    out += [""]
    return out


def render_findings() -> str:
    """The generated part of the findings page: per module, the walk by step, the findings by step and what a
    steps-mode box cannot complete; then the counts by severity and lane."""
    out = [BEGIN, ""]
    for key in MODULES:
        out += render_module(modules()[key])
    out += ["### Counts", "", "| Module | Steps | Refusals | " + " | ".join(SEVERITIES) + " | Lanes |",
            "| --- | --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for key in MODULES:
        mod = modules()[key]
        lanes = sorted({f.lane for f in mod.findings})
        by_lane = ", ".join(f"{ln} {sum(f.lane == ln for f in mod.findings)}" for ln in lanes) or "–"
        c = counts(mod)
        out.append(f"| {key} | {len(mod.steps)} | {sum(len(s.refusals) for s in mod.steps)} | "
                   + " | ".join(str(c[s]) for s in SEVERITIES) + f" | {by_lane} |")  # fmt: skip
    out += ["", END]
    return "\n".join(out)


#: the findings register's file form (``tools/findings_register.py``, ``--add-from``), beside the page; its rows wait
#: for lane V (the register is pinned to its seed rows), so the file is written, not added
FINDINGS_JSON = FINDINGS_PAGE.with_suffix(".json")
REGISTER_SEVERITY = {
    "blocks the step": "Medium (mapped)",
    "slows the tester": "Medium (mapped)",
    "cosmetic": "Low (mapped)",
}
REGISTER_LANE = {"integrator": "Int"}


def findings_json() -> str:
    """The findings of the four walks in the register's ``--add-from`` form (card H29), one row per finding."""
    rows = []
    for key in MODULES:
        mod = modules()[key]
        for f in sorted(mod.findings, key=lambda f: (f.step, f.id)):
            rows.append({
                "id": f"H29-{f.id}", "severity": REGISTER_SEVERITY[f.severity], "claim": f"{mod.key} step {f.step}: {f.showed}",
                "lane": REGISTER_LANE.get(f.lane, f.lane), "basis": "shown", "state": "open", "module": key,
                "step": f.step, "role": f.role, "place": f.path, "kind": f.kind, "walk_severity": f.severity,
                "expected": f.expected, "from": f.source,
            })  # fmt: skip
    doc = {"card": "H29", "title": "the module walks (feasibility, safety, monitoring, amendment)",
           "date": "2026-11-17", "source": str(FINDINGS_PAGE.relative_to(ROOT)), "decision": "D-1103",
           "findings": rows}  # fmt: skip
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def block_of(page: str) -> str:
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), page, re.S)
    return m.group(0) if m else ""


def write_page() -> bool:
    page = FINDINGS_PAGE.read_text(encoding="utf-8")
    old = block_of(page)
    if not old:
        raise SystemExit(f"{FINDINGS_PAGE}: no marker lines")
    new = page.replace(old, render_findings())
    changed = new != page or not FINDINGS_JSON.exists() or FINDINGS_JSON.read_text(encoding="utf-8") != findings_json()
    if new != page:
        FINDINGS_PAGE.write_text(new, encoding="utf-8")
    FINDINGS_JSON.write_text(findings_json(), encoding="utf-8")
    return changed


# ---------------------------------------------------------------------------------------------- the runs' logs
def summarise(logs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per step: the page and the clicks (count, texts) in en, the median seconds, the guesses, refusals and stops,
    over every run and language in ``logs`` (H-20's summary, one module's logs at a time)."""
    out = lp.summarise(logs)
    for n, rows in out.items():
        rows["seconds"] = round(float(rows["seconds"]), 1)
        rows["stopped"] = [s for s in rows["stopped"] if s]
        del rows["runs"]
        _ = n
    return out


def median(xs: list[float]) -> float:
    return float(statistics.median(xs)) if xs else 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", nargs=2, metavar=("MODULE", "LANG"), help="print the browser's plan (seeded accounts)")
    ap.add_argument("--write", action="store_true", help="rewrite the findings tables of the findings page")
    ap.add_argument("--summary", nargs="+", metavar="LOG", help="sum up one module's JSON logs")
    a = ap.parse_args(argv)
    if a.plan:
        mod = modules()[a.plan[0]]
        acc = {"mode": "four", **SEEDED_ACCOUNTS, "password": "-"}
        print(json.dumps(plan_json(mod, a.plan[1], ids(mod, {})[a.plan[1]], acc), ensure_ascii=False, indent=1))
    if a.write:
        print("rewritten" if write_page() else "the page is up to date")
    if a.summary:
        logs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in a.summary]
        print(json.dumps(summarise(logs), ensure_ascii=False, indent=1))
    return 0


__all__ = ["Act", "Do", "F", "Finding", "K", "M", "Module", "Refuse", "S", "See", "Step", "Stop", "T", "refuse"]

if __name__ == "__main__":
    sys.exit(main())

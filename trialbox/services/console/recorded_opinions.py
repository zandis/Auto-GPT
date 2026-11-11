"""Recorded first-check and second-check opinions for the demonstration box (T-515, D-323, review UX-007).

The demo runs the test model, which answers one way and never disagrees with itself, so a clinician trying the box
never sees the two-model check: no "First check / Second check" block appears on any patient page. This module lays
recorded opinions over the latest candidate list of a study, so the patient page and the weekly list show what an
agreement and a disagreement look like.

A fixture file is JSON::

    {"version": 1,
     "source": {"kind": "synthetic", "name": "...", "note": "..."},
     "cases": [{"ruleset": "GZQO", "criterion": ["GZQO-INC-05"], "case": "agree", "pid": "<optional>",
                "opinions": [{"role": "judge", "verdict": "pass", "quote": "...", "quote_date": "2026-04-02"},
                             {"role": "verifier", "verdict": "pass", "quote": "...", "quote_date": "2026-04-02"}]}]}

``source.kind`` is ``synthetic`` (made up by hand to show the page; every quote starts with ``[synthetic]``) or
``recorded`` (opinions a real model pair gave on the synthetic hospital, such as the G1 short run). The page shows
which: a synthetic opinion carries "synthetic example", a recorded one "recorded run" with the run's name.

``case`` is ``agree`` (both checks give the row's verdict) or ``disagree`` (the two verdicts differ; the row is
unknown, because a disagreement never decides). ``criterion`` is one id or a list tried in order. Without ``pid`` a
case goes to the first listed patient (high or review tier, by pseudonym) whose criterion has that verdict and no
opinions yet, so a case lands on the demo's list whatever pseudonyms the seed made. A case that finds no patient is
left out; nothing is invented on a row whose verdict would contradict it.

Only a DEV or TEST box reads fixtures, and only from ``TB_DEMO_OPINIONS`` (a file or a folder of ``*.json``). The
demo points it at ``demo/fixtures/opinions/``. The G1 short-run file drops into that folder as ``g1-short-run.json``
with ``source.kind`` ``recorded`` (see the folder's README); nothing else changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tb_common.config import environment_name

ENV_KEY = "TB_DEMO_OPINIONS"
KINDS = ("synthetic", "recorded")
CASES = ("agree", "disagree")
ROLES = ("judge", "verifier")
SYNTHETIC_MARK = "[synthetic]"
LISTED = ("high", "review")


class FixtureError(ValueError):
    """A fixture file that does not follow the shape above."""


@dataclass(frozen=True)
class Case:
    ruleset: str
    criteria: tuple[str, ...]
    case: str
    opinions: tuple[dict[str, Any], ...]
    kind: str
    source: str
    pid: str = ""

    @property
    def verdict(self) -> str:
        """The row verdict this case belongs on: the shared verdict when the checks agree, unknown when not."""
        return str(self.opinions[0]["verdict"]) if self.case == "agree" else "unknown"


@dataclass(frozen=True)
class Recorded:
    cases: tuple[Case, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.cases)

    def apply(self, cl: Mapping[str, Any] | None, ruleset: str) -> Mapping[str, Any] | None:
        """The candidate list with this study's cases laid over it (a copy; ``cl`` is not changed)."""
        mine = [c for c in self.cases if c.ruleset.upper() == ruleset.upper()]
        if cl is None or not mine:
            return cl
        rows = [dict(r) for r in cl.get("rows") or []]
        listed = sorted((r for r in rows if r.get("tier") in LISTED), key=lambda r: str(r.get("pid") or ""))
        for case in mine:
            pool = [r for r in listed if str(r.get("pid")) == case.pid] if case.pid else listed
            _place(case, pool)
        return {**cl, "rows": rows}


def _place(case: Case, pool: Sequence[dict[str, Any]]) -> bool:
    for cid in case.criteria:
        for row in pool:
            crits = list(row.get("criteria") or [])
            for i, v in enumerate(crits):
                ev = v.get("evidence") or {}
                if str(v.get("id")) != cid or v.get("verdict") != case.verdict or ev.get("opinions"):
                    continue
                ops = [{**o, "recorded": case.kind, "recorded_source": case.source} for o in case.opinions]
                crits[i] = {**v, "evidence": {**ev, "opinions": ops}}
                row["criteria"] = crits
                return True
    return False


def parse(data: Any, origin: str = "fixture") -> list[Case]:
    """The cases of one fixture file; :class:`FixtureError` names the first thing wrong."""

    def bad(msg: str) -> FixtureError:
        return FixtureError(f"{origin}: {msg}")

    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise bad("expected an object with version 1")
    src = data.get("source") or {}
    kind, name = str(src.get("kind") or ""), str(src.get("name") or "")
    if kind not in KINDS or not name:
        raise bad(f"source.kind must be one of {KINDS} and source.name set")
    out = []
    for n, c in enumerate(data.get("cases") or []):
        crit = c.get("criterion")
        crits = tuple(str(x) for x in ([crit] if isinstance(crit, str) else crit or []))
        ops = tuple(dict(o) for o in c.get("opinions") or [])
        if not c.get("ruleset") or not crits or c.get("case") not in CASES:
            raise bad(f"case {n}: ruleset, criterion and case (agree or disagree) are required")
        if sorted(str(o.get("role")) for o in ops) != sorted(ROLES):
            raise bad(f"case {n}: one judge and one verifier opinion")
        for o in ops:
            if o.get("verdict") not in ("pass", "fail", "unknown") or not o.get("quote"):
                raise bad(f"case {n}: every opinion has a verdict (pass, fail, unknown) and a quote")
            if kind == "synthetic" and not str(o["quote"]).startswith(SYNTHETIC_MARK):
                raise bad(f"case {n}: a synthetic quote starts with {SYNTHETIC_MARK}")
        same = len({o["verdict"] for o in ops}) == 1
        if (c["case"] == "agree") != same:
            raise bad(f"case {n}: an 'agree' case has one verdict, a 'disagree' case two")
        out.append(Case(str(c["ruleset"]), crits, str(c["case"]), ops, kind, name, str(c.get("pid") or "")))
    return out


def load(path: Path) -> Recorded:
    """Every case of a fixture file, or of every ``*.json`` in a folder (by name)."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    cases: list[Case] = []
    for f in files:
        cases += parse(json.loads(f.read_text(encoding="utf-8")), f.name)
    return Recorded(tuple(cases))


def from_env(env: Mapping[str, str]) -> Recorded:
    """The fixtures ``TB_DEMO_OPINIONS`` names, on a DEV or TEST box only; nothing anywhere else."""
    raw = (env.get(ENV_KEY) or "").strip()
    if not raw or environment_name(env) not in ("DEV", "TEST"):
        return Recorded()
    path = Path(raw)
    return load(path) if path.exists() else Recorded()


def view(o: Mapping[str, Any], test_model: bool) -> dict[str, Any]:
    """An opinion as a page shows it: ``label`` is ``synthetic``, ``recorded``, ``test_model`` (the box's own test
    model answered) or empty (a real model on this box)."""
    label = str(o.get("recorded") or "") or ("test_model" if test_model else "")
    return {**o, "label": label, "source_name": str(o.get("recorded_source") or "")}

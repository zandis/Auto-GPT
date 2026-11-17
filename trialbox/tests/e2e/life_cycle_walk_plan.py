"""H-20 (D-1135): the steps of the whole-life-cycle walk, in one place.

H-10's new study (``tests/e2e/new_study_walk_plan.py``, steps 1 to 11, unchanged: protocol in, PI named, approval,
feasibility, screening, candidates), then the later half of the study's life on the same box in steps mode (D-1062:
demo mode off, the stub model, the synthetic hospital), each step done by the role that owns it (the permission matrix
``libs/tb_common/authz_matrix.yaml``):

12. the coordinator opens the weekly page ("This week's patients") of the new study;
13. the investigator (the study's PI) opens a patient there and marks Approach (``task.approach``);
14. the coordinator records the contact outcome "reached, visit booked": the patient gets a screening number;
15. the coordinator takes the participant forward on its page (told about the study, consent, enrolment;
    ``study.setup``, D-134, D-399);
16. the coordinator records the participant's withdrawal (D-134);
17. the coordinator closes the study (``study.state``, D-386, D-763, D-779);
18. the data steward records the patient's opt-out, the erase (``optout.keep``, D-380, D-441, D-465);
19. the coordinator looks for the patient on the study's lists after the erase.

Every text is a key of the console's own catalogue. Where the walk must find a thing another way than by a documented
label (a data-testid, an address typed in), the act carries a ``guess`` and the walk records it; ``Stop`` is a
reasoned stop read from the product. ``FINDINGS`` holds what the documents say and the product does otherwise, each
with where the expectation comes from; the findings page (``docs/handover/life-cycle-walk-findings-2026-11-17.md``)
is checked against them by a fast test. The walk asserts what the product documents and does; it never asserts a
finding as correct.

    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --plan en     # the browser's plan
    PYTHONPATH=libs:services:. python -m tests.e2e.life_cycle_walk_plan --summary LOG  # a run's log, summed up
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.e2e import new_study_walk_plan as nw
from tests.e2e.new_study_walk_plan import T, Do, Refuse, See, Step

ROOT = nw.ROOT
LANGS = nw.LANGS
VERSION = nw.VERSION
#: the life-cycle walk's own new ruleset ids (never H-10's: the two walks may share one box)
RULESETS = {"en": "LIFEWALK", "zh-TW": "LIFEWALKZH", "ja": "LIFEWALKJA"}
FINDINGS_PAGE = ROOT / "docs" / "handover" / "life-cycle-walk-findings-2026-11-17.md"
SEVERITIES = ("blocks the step", "slows the tester", "cosmetic")
LANES = ("C2", "A2", "B2", "D", "E")
#: the matrix row each life-cycle step's action is permitted by (``libs/tb_common/authz_matrix.yaml``)
OWNER_ROW = {
    12: "task.screen",
    13: "task.approach",
    14: "request.prepare",
    15: "study.setup",
    16: "study.setup",
    17: "study.state",
    18: "optout.keep",
    19: "task.screen",
}
CONSOLE_ROLE = nw.CONSOLE_ROLE


@dataclass(frozen=True)
class Stop:
    """A reasoned stop: when the page shows ``see`` the step stops, and the walk records ``why`` with the page's own
    words (its alert). Later steps that stand on it (``Life.after``) are recorded as not walked."""

    see: See
    why: str


@dataclass(frozen=True)
class Guessed:
    """An act the walk can only do by guessing: ``act`` and the reason, recorded in the log."""

    act: Do
    why: str


@dataclass(frozen=True)
class Life:
    """A life-cycle step: H-10's :class:`Step` with the lane that owns its pages, the steps it stands on, and the
    guesses the plan knows before the walk (a text with no zh-TW or ja form is found from the catalogue)."""

    step: Step
    lane: str
    after: tuple[int, ...] = ()
    guesses: tuple[str, ...] = ()
    stops: tuple[Stop, ...] = field(default=())


def _w(en: str, zh: str, ja: str) -> dict[str, str]:
    return {"en": en, "zh-TW": zh, "ja": ja}


PICK = "{short}"  # the patient the walk took forward, by the short pseudonym the product shows

LIFE: tuple[Life, ...] = (
    Life(
        Step(
            12,
            "coordinator",
            (
                Do("nav", T("nav.week")),
                Do("link", T(None, prefix="{rs}")),
                See("h1", T("wb.title")),
                See("path", value=r"^/studies/[A-Z0-9]+/week$"),
                See("shown", value="worklist"),
            ),
            (
                Refuse(
                    "steward",
                    "GET",
                    "/studies/{rs}/week",
                    (),
                    _w(
                        "the steward cannot open the weekly page",
                        "資料管理員不能開啟本週名單",
                        "データスチュワードは今週のリストを開けない",
                    ),
                ),
            ),
            _w(
                "Open the new study's weekly page.",
                "開啟新試驗的本週病人頁面。",
                "新しい試験の今週の患者ページを開きます。",
            ),
            _w(
                "The worklist of the patients the screening found.",
                "篩選找到的病人清單。",
                "スクリーニングで見つかった患者のリスト。",
            ),
        ),
        "C2",
    ),
)


def all_steps() -> tuple[Step, ...]:
    return (*nw.STEPS, *(lf.step for lf in LIFE))


def plan_json(lang: str, rs: str, accounts: dict[str, str]) -> dict[str, Any]:
    """H-10's plan for ``lang`` and ``rs`` with the life-cycle steps after it."""
    plan = nw.plan_json(lang, rs, accounts)
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", metavar="LANG", help="print the browser's plan for one language (four seeded accounts)")
    a = ap.parse_args(argv)
    if a.plan:
        print(json.dumps(plan_json(a.plan, RULESETS[a.plan], nw.SEEDED_ACCOUNTS), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

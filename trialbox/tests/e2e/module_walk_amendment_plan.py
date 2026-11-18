"""H-29 (D-1103): the amendment walk. A protocol change after approval: who may change, what must be approved
again and by whom, what the candidates list and the weekly page show before and after, and what happens to the
patients already approached (D-364).

It begins as H-20's walk begins (H-10's steps 1 to 11, H-20's 12 to 15, imported): a new study, approved at
version 1.0.0 and screened, its first patient approached and enrolled. Then:

16. the investigator (the PI) marks Approach on another patient of the weekly page (approached, not yet contacted);
17. the coordinator reads the candidates list, then sends the amended criteria in under the study's id (the age
    limit raised from 18 to 20): version 1.1.0, waiting for approval;
18. the investigator approves version 1.1.0 with its amendment record (the IRB approval number and day);
19. the coordinator reads the weekly page before the new version has screened, then runs SCREEN on 1.1.0;
20. the coordinator opens "Re-screen after amendment" from the weekly page: who is to be looked at again;
21. the investigator reads the weekly page after the amendment: the patient approached under 1.0.0.
"""

from __future__ import annotations

from typing import Any

from tests.e2e.module_walk_common import Act, Finding, Module, See, Step, T, refuse
from tests.e2e.new_study_walk_plan import Do

#: the amendment's version: the compiler's next minor version of the study's id (criteria_compiler._next_version)
NEW = "1.1.0"
#: SITE5B's criteria (H-10's paste) with the age limit raised: one criterion changed, three kept as they were
AMENDED = (
    "Inclusion Criteria\n1. Aged 20 years or older.\n2. Diagnosis of gout (ICD-10-CM M10 or M1A).\n"
    "3. Most recent serum urate in the last year at least 7.0 mg/dL.\n\nExclusion Criteria\n"
    "1. Any history of malignancy.\n"
)
#: the amendment record the PI types (a record printed with the approval; nothing checks it, D-364 rule 2)
IRB_NO = "IRB-WALK-2"

STEPS: tuple[Step, ...] = (
    Step(
        16,
        "investigator",
        "task.approach",
        (
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            See("h1", T("wb.title")),
            Act("first_row_link", within="worklist", finding="AMD-01"),
            Act("remember", label="pid", value=r"[?&]pid=([0-9a-f]{8,64})"),
            Do("button", T("mark.approach")),
            See("says", T("wb.done.approach")),
        ),
        (
            refuse(
                "coordinator",
                "POST",
                "/studies/{rs}/patients/{pid}/mark",
                "the coordinator cannot mark Approach",
                (("mark", "approach"),),
            ),
        ),
        "As the investigator: open the first patient of the weekly page and mark Approach.",
        "The mark is saved under version 1.0.0 (D-364 rule 4).",
    ),
    Step(
        17,
        "coordinator",
        "request.prepare",
        (
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            Do("link", T("team.cand.title")),
            Act("read", label="candidates before", within="[data-testid=cand-count]"),
            Do("more", T("nav.protocol")),
            See("h1", T("protocol.title")),
            Do("fill", label=T("protocol.ruleset"), value="{rs}"),
            Do("fill", label=T("protocol.paste"), value=AMENDED),
            Do("button", T("protocol.submit")),
            See("state", value="awaiting_approval"),
            See("h1", T(None, prefix="FEAS {rs} v" + NEW)),
            Act("remember", label="job", value=r"/pilot/jobs/([0-9A-HJKMNP-TV-Z]{26})"),
        ),
        (
            refuse(
                "coordinator",
                "POST",
                "/pilot/jobs/{job}/approve",
                "the coordinator cannot approve the amendment",
                (("confirm", "yes"),),
            ),
            refuse(
                "steward",
                "POST",
                "/pilot/protocol",
                "the steward cannot send criteria in",
                (("ruleset", "{rs}"), ("criteria", AMENDED)),
            ),
        ),
        "Read the candidates; then on the protocol page type the study's own id, paste the amended criteria (age 20 "
        "or older) and send them.",
        "A new version of the study's criteria, 1.1.0, waiting for the PI's approval (D-364; the compiler's next "
        "version).",
    ),
    Step(
        18,
        "investigator",
        "criteria.approve",
        (
            Do("nav", T("nav.week")),
            Do("link", T("s20.waiting", (("rs", "{rs}"), ("v", NEW)))),
            See("h1", T("s20.title", prefix="{rs} v" + NEW + " · ")),
            See("shown", value="changes"),
            Act("read", label="changes", within="[data-testid=changes] li"),
            Act("read", label="what is approved", within="[data-testid=s20-split]"),
            Do("label_all", T("s20.label.save")),
            Do("open_all", T("s20.open_row")),
            See("shown", value="amend-record"),
            Do("fill", label=T("amend.irb"), value=IRB_NO),
            Do("fill", label=T("amend.irb_date"), value="{day}"),
            Do("button", T("s20.approve_all")),
            See("h1", T("confirm.title")),
            Do("button", T("confirm.yes")),
            See("state", value="done"),
            See("h1", T(None, prefix="APPROVE {rs} v" + NEW)),
        ),
        (),
        "As the investigator: open the criteria waiting for approval (v1.1.0), check each row, give the amendment "
        "record (IRB approval number and day) and approve all.",
        "Version 1.1.0 is approved with its own record; it screens from today (no effective date given; D-364 "
        "rules 1 to 3).",
        after=(17,),
    ),
    Step(
        19,
        "coordinator",
        "command.SCREEN",
        (
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            Act("read", label="weekly page before", within="[data-testid=week-counts]"),
            Do("more", T("nav.request")),
            Do("form", T("request.start.screen"), value="{rs}", wait_s=600),
            See("state", value="done"),
            See("h1", T(None, prefix="SCREEN {rs} v" + NEW)),
        ),
        (),
        "Read the weekly page (the list of 1.0.0), then run SCREEN on the study: it runs on version 1.1.0.",
        "The SCREEN job on 1.1.0, done (D-364 rule 3: the version in force on the run day).",
        after=(18,),
    ),
    Step(
        20,
        "coordinator",
        "task.screen",
        (
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            Act("read", label="weekly page after", within="[data-testid=week-counts]"),
            Do("link", T("team.cand.title")),
            Act("read", label="candidates after", within="[data-testid=cand-count]"),
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            Do("link", T("rescreen.link")),
            See("h1", T("rescreen.title", prefix="{rs} · ")),
            See("shown", value="rescreen-versions"),
            Act("read", label="re-screen", within="main h2, main [data-testid=rescreen-versions]"),
        ),
        (refuse("steward", "GET", "/studies/{rs}/rescreen", "the steward cannot open the re-screen list"),),
        "From the weekly page, open Re-screen after amendment.",
        "Version 1.1.0 against 1.0.0: who is back for a new look, who no longer meets the criteria, who is in "
        "screening (D-364 rule 5).",
        after=(19,),
    ),
    Step(
        21,
        "investigator",
        "task.screen",
        (
            Do("nav", T("nav.week")),
            Do("link", T(None, prefix="{rs}")),
            Act("link_start", T("wb.list.approached"), finding="AMD-05"),
            See("says", T("week.patient", (("p", "{short}"),))),
        ),
        (),
        "As the investigator: open the weekly page's list of approached patients after the amendment.",
        "The patient approached under 1.0.0 is still there, with the version of the mark (D-364 rule 4).",
        after=(19,),
    ),
)

FINDINGS: tuple[Finding, ...] = (
    Finding(
        "AMD-01",
        16,
        "investigator",
        "/studies/{rs}/week",
        "label",
        "patients are named by an 8-character pseudonym only; the walk takes the worklist's first row (as H-20 F-03)",
        "a patient the tester can be told to take",
        "D-133",
        "cosmetic",
        "C2",
    ),
    Finding(
        "AMD-02",
        17,
        "coordinator",
        "/pilot/protocol",
        "term",
        'the field reads "New ruleset id (e.g. GZQO-DEMO)"; an amendment is sent under the study\'s own id, and nothing on the page says that the same id makes the next version',
        "the protocol page says how an amendment is sent (the study's id, the next version)",
        "D-364; `protocol.ruleset`",
        "slows the tester",
        "C2",
    ),
    Finding(
        "AMD-03",
        18,
        "investigator",
        "/pilot/jobs/{job}/approval",
        "other",
        '"Changes since 1.0.0" names one criterion (INC-01, new wording), but approving 1.1.0 asks the PI to open all four amber rows again (1.0.0 asked three)',
        "the changed criteria are the ones to look at again, or the page says why every row is",
        "D-364 rule 1, `s20.changes`",
        "slows the tester",
        "C2",
    ),
    Finding(
        "AMD-04",
        18,
        "investigator",
        "/pilot/jobs/{job}/approval",
        "label",
        'the change reads "INC-01 · new wording" with the earlier wording struck through; the new wording is only in the table below',
        "the change shows the old and the new wording side by side",
        "`s20.chg.text`",
        "cosmetic",
        "C2",
    ),
    Finding(
        "AMD-05",
        21,
        "investigator",
        "/studies/{rs}/week",
        "label",
        'the list links\' names end with their count ("Approved and contacted (n)"); the walk finds the link by the start of its name (as H-20 F-05)',
        "a link named by its list",
        "D-133",
        "cosmetic",
        "C2",
    ),
    Finding(
        "AMD-06",
        21,
        "investigator",
        "/studies/{rs}/week",
        "other",
        "the patient approached under 1.0.0 is listed with the mark, but no page says which criteria version the mark was made on",
        "the mark shows its version where the version decides the re-screen list",
        "D-364 rule 4",
        "cosmetic",
        "C2",
    ),
)

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = (
    (
        18,
        "an amendment that takes effect on a later day (D-364 rule 3: the version before screens until then)",
        "a box whose day moves: the walk's box runs on `--day data`, a frozen clock, so the effective date is left "
        "empty (in force from the approval)",
    ),
    (
        20,
        "the re-screen list with patients in it (D-364 rule 5)",
        "a patient set aside, approached or in screening whom the amendment changes: the walk's amendment (age 18 to "
        "20) took 43 unmarked candidates off the list and left the walk's marked patients eligible, so all three "
        "groups are empty",
    ),
)


#: the committed summary of the walks of 2026-11-17 (three runs x three languages, ``make walk-modules`` on a
#: 4-core container), written by ``--summary`` from the logs (per step: the page and the clicks in en, the median
#: seconds); the clicks count every click of the step's log, the refusals' sign-ins included
SUMMARY: dict[int, dict[str, Any]] = {
    16: {
        "path": "/studies/{rs}/week",
        "heading": "This week's patients · {rs}",
        "clicks": 4,
        "click_texts": ["This week's patients", "{rs}", "patient {short}", "Approach"],
        "seconds": 6.5,
        "guesses": ["AMD-01"],
        "stopped": [],
    },
    17: {
        "path": "/pilot/jobs/{job}",
        "heading": "FEAS {rs} v1.1.0 waiting for approval",
        "clicks": 6,
        "click_texts": ["This week's patients", "{rs}", "Candidates", "More", "Protocol", "Compile"],
        "seconds": 3.7,
        "guesses": [],
        "stopped": [],
    },
    18: {
        "path": "/pilot/jobs/{job}",
        "heading": "APPROVE {rs} v1.1.0 done",
        "clicks": 8,
        "click_texts": [
            "This week's patients",
            "Criteria waiting for your approval: {rs} v1.1.0",
            "Open",
            "Open",
            "Open",
            "Open",
            "Approve all",
            "Yes, do it",
        ],
        "seconds": 7.1,
        "guesses": [],
        "stopped": [],
    },
    19: {
        "path": "/pilot/jobs/{job}",
        "heading": "SCREEN {rs} v1.1.0 done",
        "clicks": 5,
        "click_texts": ["This week's patients", "{rs}", "More", "New request", "Find candidates for the next visits"],
        "seconds": 41.5,
        "guesses": [],
        "stopped": [],
    },
    20: {
        "path": "/studies/{rs}/rescreen",
        "heading": "{rs} · Re-screen after amendment",
        "clicks": 6,
        "click_texts": [
            "This week's patients",
            "{rs}",
            "Candidates",
            "This week's patients",
            "{rs}",
            "Re-screen after amendment",
        ],
        "seconds": 7.2,
        "guesses": [],
        "stopped": [],
    },
    21: {
        "path": "/studies/{rs}/week",
        "heading": "This week's patients · {rs}",
        "clicks": 3,
        "click_texts": ["This week's patients", "{rs}", "Approved and contacted"],
        "seconds": 3.8,
        "guesses": ["AMD-05"],
        "stopped": [],
    },
}

MODULE = Module(
    key="amendment",
    title="Amendment: a protocol change after approval",
    roles=("coordinator", "investigator", "steward"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    rulesets={"en": "AMENDWALK", "zh-TW": "AMENDWALKZH", "ja": "AMENDWALKJA"},
    prefix=True,
    summary=SUMMARY,
    sources="D-108, D-364",
)

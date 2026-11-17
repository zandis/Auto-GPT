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
            refuse("coordinator", "POST", "/studies/{rs}/patients/{pid}/mark", "the coordinator cannot mark Approach",
                   (("mark", "approach"),)),
        ),  # fmt: skip
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
            refuse("coordinator", "POST", "/pilot/jobs/{job}/approve", "the coordinator cannot approve the amendment",
                   (("confirm", "yes"),)),
            refuse("steward", "POST", "/pilot/protocol", "the steward cannot send criteria in",
                   (("ruleset", "{rs}"), ("criteria", AMENDED))),
        ),  # fmt: skip
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

FINDINGS: tuple[Finding, ...] = ()

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = ()

MODULE = Module(
    key="amendment",
    title="Amendment: a protocol change after approval",
    roles=("coordinator", "investigator", "steward"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    rulesets={"en": "AMENDWALK", "zh-TW": "AMENDWALKZH", "ja": "AMENDWALKJA"},
    prefix=True,
    sources="D-108, D-364",
)

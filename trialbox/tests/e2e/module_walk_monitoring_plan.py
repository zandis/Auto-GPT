"""H-29 (D-1103): the monitoring walk. The monitor's role: how it is granted and by whom, each page the monitor may
open, what it may not see, and what a refusal says about who grants.

On the study the box seeds with enrolled participants and a CRO account named for it (``GZQO``; the account ``cra``,
D-380: a CRO account names its studies). Each language grants the account its own monitoring visit:

1. the CRO account signs in; before a grant, the monitor's page of one of its studies is refused;
2. the administrator reads the CRO account on Users (who opened it, its studies);
3. the data steward gives the CRO account a monitor grant for one visit on the study's delegation log (FIT-002;
   ``monitor.grant``: the PI the log names or the steward);
4. the CRO account opens Monitoring from its menu: the enrolled subjects only;
5. the CRO account opens one enrolled subject's source-reference sheet: no pseudonym, no chart number;
6. the CRO account records the monitoring visit;
7. the investigator (the study's PI) reads the visit records.
"""

from __future__ import annotations

from typing import Any

from tests.e2e.module_walk_common import Act, Finding, M, Module, S, See, Step, Stop, T, refuse
from tests.e2e.new_study_walk_plan import Do

STUDY = "GZQO"
#: the study the CRO account is named for and has no monitor grant in (tools/feas_demo.py ACCOUNTS)
NO_GRANT = "GOUT-COH"
#: the grant's last day: after the box's day (2026-11-02, ``--day data``) and the real day of these runs
GRANT_END = "2026-11-30"
#: the monitoring visit's id, one per page language (the walks of one box add a grant each)
VISIT = "WALK-MV-{lang}"
#: the enrolled participant the monitor opens, and the consented one it may not (the seed's GZQO-0001, GZQO-0002)
ENROLLED = "GZQO-0001"
CONSENTED = "GZQO-0002"
GRANT = (("username", "{cro}"), ("role", "monitor"), ("start", "{day}"), ("end", GRANT_END), ("visit", "WALK-MV-X"))

STEPS: tuple[Step, ...] = (
    Step(
        1,
        "cro",
        "monitor.read",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            See("h1", T("reports.title")),
            Act("goto", value=f"/studies/{NO_GRANT}/monitor"),
            See("h1", T("problem.h.forbidden")),
            Stop("says", "MON-01", T("problem.why.forbidden")),
        ),
        (),
        "As the CRO account: open the monitoring page of a study it is named for, before any grant.",
        "Refused, and the refusal says who grants: the PI the log names or the data steward (`monitor.grant`, D-380, "
        "FIT-002).",
    ),
    Step(
        2,
        "operator",
        "account.create.aggregate",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Do("nav", T("nav.users")),
            See("h1", T("users.title")),
            See("shown", value="users-scope-{cro}"),
        ),
        (
            refuse(
                "steward",
                "POST",
                "/ops/users",
                "the steward cannot change an account's studies",
                (("action", "scope"), ("username", "{cro}"), ("affiliation", "cro"), ("studies", STUDY)),
            ),
        ),
        "As the administrator: open Users and find the CRO account and its studies.",
        "The administrator opens a CRO account and names its studies (D-380, `account.create.aggregate`).",
    ),
    Step(
        3,
        "steward",
        "monitor.grant",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Act("goto", value="/studies/{rs}/team", finding="MON-02"),
            See("h1", T("team.log.title", prefix="{rs} · ")),
            Do("select", label=T("team.log.account"), value="{cro}"),
            Do("select", label=T("team.log.role"), value="monitor"),
            Do("fill", label=T("team.log.end"), value=GRANT_END),
            Do("fill", label=T("team.log.visit"), value=VISIT),
            Do("button", T("team.log.add.save")),
            See("says", T("team.log.done.add")),
        ),
        (
            refuse("coordinator", "POST", "/studies/{rs}/team", "the coordinator cannot give a monitor grant", GRANT),
            refuse("cro", "POST", "/studies/{rs}/team", "the CRO account cannot grant itself", GRANT),
            refuse("operator", "POST", "/studies/{rs}/team", "the administrator cannot give a monitor grant", GRANT),
        ),
        "As the data steward: on the study's delegation log, add the CRO account as monitor for one visit (its id, "
        "its last day).",
        "The grant is added and signed (FIT-002, D-380).",
    ),
    Step(
        4,
        "cro",
        "monitor.read",
        (
            Do("nav", T("nav.reports")),
            See("shown", value="monitoring-{rs}"),
            Do("nav", S("roles.monitor.title", suffix=" · {rs}")),
            See("h1", T("roles.monitor.title", prefix="{rs} · ")),
            See("says", T("sdv.list.title")),
            See("says", T(None, prefix=VISIT)),
            See("says", T(None, prefix=ENROLLED)),
            See("absent", T(None, prefix=CONSENTED)),
        ),
        (
            refuse("cro", "GET", "/studies/{rs}/week", "the monitor cannot open the weekly page"),
            refuse("cro", "GET", "/studies/{rs}/candidates", "the monitor cannot open the candidate list"),
            refuse("cro", "GET", f"/studies/{{rs}}/subjects/{ENROLLED}", "the monitor cannot open a participant page"),
            refuse(
                "cro", "GET", f"/studies/{{rs}}/monitor/{CONSENTED}", "the monitor cannot open a subject not enrolled"
            ),
            refuse("cro", "GET", "/sae", "the monitor cannot open the SAE register"),
        ),
        "As the CRO account: open Reports (its monitoring line is there now), then Monitoring from the menu.",
        "Read-only, enrolled subjects only, with the visit's id; every view recorded with the visit (D-436).",
    ),
    Step(
        5,
        "cro",
        "monitor.read",
        (
            Do("link", T(None, prefix=ENROLLED)),
            See("h1", T("sdv.sheet.title", prefix="{rs} · ")),
            See("says", T("sdv.forms.title")),
            See("gone", value="mrn"),
            Act("read", label="subject", within="main dl"),
        ),
        (),
        "Open the enrolled subject's source-reference sheet.",
        "The lifecycle facts and the values typed into TrialBox's forms, never the pseudonym, a chart number or free "
        "text (D-436, D-772).",
    ),
    Step(
        6,
        "cro",
        "monitor.visit",
        (
            Do("nav", S("roles.monitor.title", suffix=" · {rs}")),
            Do("fill", label=T("sdv.visits.day"), value="{day}"),
            M("check", T(None, prefix=ENROLLED)),
            Do("fill", label=T("sdv.visits.findings"), value="none"),
            Do("button", T("sdv.visits.save")),
            See("says", T("sdv.visits.saved")),
        ),
        (
            refuse(
                "coordinator",
                "POST",
                "/studies/{rs}/monitor/visits",
                "the coordinator cannot record a monitoring visit",
                (("visit_day", "{day}"), ("subjects", ENROLLED), ("findings", "none")),
            ),
        ),
        "Record the monitoring visit: its day, the subject verified, the findings.",
        "The visit record, with the CRA and the visit's id (D-436).",
    ),
    Step(
        7,
        "investigator",
        "monitor.grant",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Act("goto", value="/studies/{rs}/monitor", finding="MON-03"),
            See("h1", T("roles.monitor.title", prefix="{rs} · ")),
            See("says", T(None, prefix=VISIT)),
        ),
        (),
        "As the investigator (the study's PI): read the monitoring visits.",
        "The visit records only, no subject list (D-436: the PI the log names and the steward see the records).",
    ),
)

FINDINGS: tuple[Finding, ...] = (
    Finding(
        "MON-01",
        1,
        "cro",
        "/studies/GOUT-COH/monitor",
        "stop",
        'the refusal says "If you need it, ask the TrialBox administrator to change your role"; the monitor grant is given by the PI the log names or the data steward, and the administrator is refused it (step 3)',
        "the refusal of a monitor's page says who grants: the study's PI or the data steward",
        "`monitor.grant`, D-380, FIT-002; `problem.why.forbidden`",
        "blocks the step",
        "C2",
    ),
    Finding(
        "MON-02",
        3,
        "steward",
        "/studies/GZQO/team",
        "address",
        "the steward's menu and home page have no link to a study's delegation log once its PI is named; the walk types /studies/GZQO/team",
        "a way from the steward's pages to each study's delegation log, where the steward grants",
        "D-380, FIT-002",
        "slows the tester",
        "C2",
    ),
    Finding(
        "MON-03",
        7,
        "investigator",
        "/studies/GZQO/monitor",
        "address",
        "the PI reaches the monitoring visit records only by typing /studies/GZQO/monitor: no link on the study's pages, the weekly page or the delegation log",
        "a link to the monitoring visits from the study's pages for the PI who grants them",
        "D-436",
        "slows the tester",
        "C2",
    ),
    Finding(
        "MON-04",
        5,
        "cro",
        "/studies/GZQO/monitor/GZQO-0001",
        "other",
        "the sheet's \"Consent given\" and \"Enrolled on\" read 2026-11-17 (the day the seed recorded the steps, the real day) while the consent form's date on the same sheet and the state's day read 2026-11-02 (the box's day)",
        "the sheet's dates agree with the forms a monitor verifies them against",
        "D-436, D-772; as H-20 F-10 (`--day data`)",
        "slows the tester",
        "C2",
    ),
    Finding(
        "MON-05",
        5,
        "cro",
        "/studies/GZQO/monitor/GZQO-0001",
        "term",
        'the state reads "On study (on_study, 2026-11-02)": the code on_study is shown in every page language',
        "the state in words with its day",
        "`life.state.on_study`",
        "cosmetic",
        "C2",
    ),
)

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = ()

#: the committed summary of the walks of 2026-11-17 (three runs x three languages, ``make walk-modules`` on a
#: 4-core container), written by ``--summary`` from the logs (per step: the page and the clicks in en, the median
#: seconds); the clicks count every click of the step's log, the refusals' sign-ins included
SUMMARY: dict[int, dict[str, Any]] = {
    1: {
        "path": "/studies/GOUT-COH/monitor",
        "heading": "This page needs another role",
        "clicks": 4,
        "click_texts": ["Sign in", "Change", "Change", "(typed) /studies/GOUT-COH/monitor"],
        "seconds": 1.3,
        "guesses": [],
        "stopped": ["MON-01"],
    },
    2: {
        "path": "/ops/users",
        "heading": "Users",
        "clicks": 6,
        "click_texts": ["Sign in", "Change", "Change", "Users", "Sign in", "Change"],
        "seconds": 1.5,
        "guesses": [],
        "stopped": [],
    },
    3: {
        "path": "/studies/GZQO/team",
        "heading": "GZQO · Delegation log",
        "clicks": 5,
        "click_texts": ["Change", "(typed) /studies/GZQO/team", "Add and sign", "Sign in", "Change"],
        "seconds": 7.7,
        "guesses": ["MON-02"],
        "stopped": [],
    },
    4: {
        "path": "/studies/GZQO/monitor",
        "heading": "GZQO · Monitoring",
        "clicks": 2,
        "click_texts": ["Reports", "Monitoring · GZQO"],
        "seconds": 1.1,
        "guesses": [],
        "stopped": [],
    },
    5: {
        "path": "/studies/GZQO/monitor/GZQO-0001",
        "heading": "GZQO · Source references · GZQO-0001",
        "clicks": 1,
        "click_texts": ["GZQO-0001"],
        "seconds": 0.3,
        "guesses": [],
        "stopped": [],
    },
    6: {
        "path": "/studies/GZQO/monitor",
        "heading": "GZQO · Monitoring",
        "clicks": 3,
        "click_texts": ["Monitoring · GZQO", "GZQO-0001", "Save the visit record"],
        "seconds": 0.8,
        "guesses": [],
        "stopped": [],
    },
    7: {
        "path": "/studies/GZQO/monitor",
        "heading": "GZQO · Monitoring",
        "clicks": 4,
        "click_texts": ["Sign in", "Change", "Change", "(typed) /studies/GZQO/monitor"],
        "seconds": 2.4,
        "guesses": ["MON-03"],
        "stopped": [],
    },
}

MODULE = Module(
    key="monitoring",
    title="Monitoring: the monitor's role",
    roles=("cro", "operator", "steward", "coordinator", "investigator"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    study=STUDY,
    summary=SUMMARY,
    sources="D-380, D-436, D-772, FIT-002",
)

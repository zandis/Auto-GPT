"""H-29 (D-1103): the feasibility walk. Feasibility alone, as a box without a GPU would do it (D-1066: a PRODUCTION
box without a GPU is a product form that does feasibility and the structured criteria; note criteria wait for a GPU).

Lane D's second card (D-998) made the installer pin the embedder on a PRODUCTION box installed with ``--mode stub``
and RUNBOOK §1 say what such a box does; the box the walk starts is the steps-mode box (the stub model), not such an
install. So the walk is what a feasibility user does on the box master has, on a study the box seeds with approved
criteria and no feasibility report (``AD-MAB``), and it stops where the box would have to say what it cannot do:

1. the coordinator signs in and chooses the page language;
2. the coordinator runs FEAS on the approved study (New request: "Count eligible patients");
3. the coordinator opens the feasibility report from Reports: counts from coded data, the funnel, what is checked
   only at screening;
4. the investigator reads the same report;
5. the viewer (an aggregate-only account) reads the reports list and the report;
6. the CRO account reads the sponsor copy of a study it is named for (``GZQO``; ``AD-MAB`` is not its study);
7. the coordinator looks for what the box cannot do without a GPU (note criteria, screening) on the request page.
"""

from __future__ import annotations

from typing import Any

from tests.e2e.module_walk_common import Act, Finding, Module, See, Step, Stop, T, refuse
from tests.e2e.new_study_walk_plan import Do

STUDY = "AD-MAB"
#: the study the CRO account is named for (tools/feas_demo.py ACCOUNTS: cra, studies GZQO and GOUT-COH)
CRO_STUDY = "GZQO"

STEPS: tuple[Step, ...] = (
    Step(
        1,
        "coordinator",
        "",
        (Do("signin"), Do("language", T("lang.apply"), T("lang.label")), See("h1", T("wb.crc.title"))),
        (),
        "Sign in and choose the page language.",
        "Your work page.",
        why_no_row="signing in needs no row",
    ),
    Step(
        2,
        "coordinator",
        "command.FEAS",
        (
            Do("more", T("nav.request")),
            See("h1", T("request.title")),
            Do("form", T("request.start.feas"), value="{rs}"),
            See("state", value="done"),
            See("h1", T(None, prefix="FEAS {rs} v{v}")),
        ),
        (
            refuse(
                "steward",
                "POST",
                "/pilot/request",
                "the steward cannot start a run",
                (("kind", "FEAS"), ("ruleset", "{rs}")),
            ),
            refuse(
                "viewer",
                "POST",
                "/pilot/request",
                "the viewer cannot start a run",
                (("kind", "FEAS"), ("ruleset", "{rs}")),
            ),
            refuse(
                "cro",
                "POST",
                "/pilot/request",
                "the CRO account cannot start a run",
                (("kind", "FEAS"), ("ruleset", "{rs}")),
            ),
        ),
        "Open New request (More) and count eligible patients for the approved study.",
        "The FEAS job, done (D-104 §2).",
    ),
    Step(
        3,
        "coordinator",
        "phi.view",
        (
            Do("nav", T("nav.reports")),
            See("h1", T("reports.title")),
            Do("row_link", T("home.open_report"), within="{rs} v{v}"),
            See("h1", T("feas.title", prefix="{rs} · ")),
            Act("read", label="report line", within="[data-testid=feas-meta]"),
            Act("read", label="funnel", within="[data-testid=funnel] tbody tr"),
        ),
        (),
        "Open Reports and the study's feasibility report.",
        "Counts from coded hospital data, no model (`feas.meta`); the funnel names the criteria checked only at "
        "screening (D-104 §2).",
    ),
    Step(
        4,
        "investigator",
        "task.screen",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Do("nav", T("nav.reports")),
            Do("row_link", T("home.open_report"), within="{rs} v{v}"),
            See("h1", T("feas.title", prefix="{rs} · ")),
            See("gone", value="feas-none"),
        ),
        (),
        "As the investigator (the study's PI): open Reports and the study's feasibility report.",
        "The same report.",
    ),
    Step(
        5,
        "viewer",
        "report.office",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Do("nav", T("nav.reports")),
            See("h1", T("reports.title")),
            Do("row_link", T("home.open_report"), within="{rs} v{v}"),
            See("h1", T("feas.title", prefix="{rs} · ")),
        ),
        (refuse("viewer", "GET", "/studies/{rs}/candidates", "the viewer cannot open the candidate list"),),
        "As the viewer: open Reports and the study's report.",
        "Aggregate counts only (D-101, D-280).",
    ),
    Step(
        6,
        "cro",
        "report.sponsor_form",
        (
            Do("signin"),
            Do("language", T("lang.apply"), T("lang.label")),
            Do("nav", T("nav.reports")),
            See("says", T("reports.cro")),
            Do("row_link", T("home.open_report"), within=CRO_STUDY),
            See("h1", T("feas.title", prefix=CRO_STUDY + " · ")),
        ),
        (refuse("cro", "GET", f"/studies/{CRO_STUDY}/candidates", "the CRO account cannot open the candidate list"),),
        "As the CRO account: open Reports and the sponsor copy of its study's report.",
        "The sponsor copy: small counts hidden, the rest rounded (`reports.cro`, D-280).",
    ),
    Step(
        7,
        "coordinator",
        "command.FEAS",
        (
            Do("more", T("nav.request")),
            See("h1", T("request.title")),
            Stop("says", "FEA-01", T("request.start.screen")),
        ),
        (),
        "On New request: read what this box does not do without a GPU (note criteria, screening).",
        "A box without a GPU does feasibility and the structured criteria; criteria that need the notes read wait "
        'for a GPU (D-1066 ruling 1; `deploy/install.sh` --mode stub: "note criteria wait for a GPU").',
        lane="D",
    ),
)

FINDINGS: tuple[Finding, ...] = (
    Finding(
        "FEA-01",
        7,
        "coordinator",
        "/pilot/request",
        "stop",
        'New request offers "Find candidates for the next visits" (SCREEN) and the plain-words field "goes to the conversation engine"; nothing on the box\'s pages says that note criteria, screening and the engine need a GPU (RUNBOOK §1 says it, D-998; the pages are unchanged). The steps-mode box runs the stub model, so SCREEN runs here',
        "on a box without a GPU, the pages say what waits for a GPU (note criteria, SCREEN, the engine) and do not offer it as if it ran",
        'D-1066 ruling 1; `deploy/install.sh` --mode stub ("note criteria wait for a GPU"); D-998 (RUNBOOK §1: what a box without a GPU does and does not do)',
        "blocks the step",
        "D",
    ),
)

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = (
    (
        7,
        "what a box without a GPU says it cannot do (D-1066)",
        "a PRODUCTION box installed with `--mode stub` (D-998: the embedder pinned on the CPU from the bundle, no "
        "model for the notes). The steps-mode box runs the stub model, so note criteria and SCREEN run on it",
    ),
)


#: the committed summary of the walks of 2026-11-17 (three runs x three languages, ``make walk-modules`` on a
#: 4-core container), written by ``--summary`` from the logs (per step: the page and the clicks in en, the median
#: seconds); the clicks count every click of the step's log, the refusals' sign-ins included
SUMMARY: dict[int, dict[str, Any]] = {
    1: {
        "path": "/home",
        "heading": "My work",
        "clicks": 3,
        "click_texts": ["Sign in", "Change", "Change"],
        "seconds": 3.2,
        "guesses": [],
        "stopped": [],
    },
    2: {
        "path": "/pilot/jobs/{job}",
        "heading": "FEAS AD-MAB v1.0.0 done",
        "clicks": 9,
        "click_texts": [
            "More",
            "New request",
            "Count eligible patients",
            "Sign in",
            "Change",
            "Sign in",
            "Change",
            "Sign in",
            "Change",
        ],
        "seconds": 6.0,
        "guesses": [],
        "stopped": [],
    },
    3: {
        "path": "/studies/AD-MAB/feasibility",
        "heading": "AD-MAB · Feasibility report",
        "clicks": 2,
        "click_texts": ["Reports", "Open report"],
        "seconds": 0.5,
        "guesses": [],
        "stopped": [],
    },
    4: {
        "path": "/studies/AD-MAB/feasibility",
        "heading": "AD-MAB · Feasibility report",
        "clicks": 5,
        "click_texts": ["Sign in", "Change", "Change", "Reports", "Open report"],
        "seconds": 3.4,
        "guesses": [],
        "stopped": [],
    },
    5: {
        "path": "/studies/AD-MAB/feasibility",
        "heading": "AD-MAB · Feasibility report",
        "clicks": 3,
        "click_texts": ["Change", "Reports", "Open report"],
        "seconds": 0.6,
        "guesses": [],
        "stopped": [],
    },
    6: {
        "path": "/studies/GZQO/feasibility",
        "heading": "GZQO · Feasibility report",
        "clicks": 3,
        "click_texts": ["Change", "Reports", "Open report"],
        "seconds": 0.8,
        "guesses": [],
        "stopped": [],
    },
    7: {
        "path": "/pilot/request",
        "heading": "New request",
        "clicks": 2,
        "click_texts": ["More", "New request"],
        "seconds": 0.2,
        "guesses": [],
        "stopped": ["FEA-01"],
    },
}

MODULE = Module(
    key="feasibility",
    title="Feasibility alone (a box without a GPU, D-1066)",
    roles=("coordinator", "investigator", "viewer", "cro", "steward"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    study=STUDY,
    summary=SUMMARY,
    sources="D-104 §2, D-280, D-1066",
)

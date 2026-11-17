"""H-29 (D-1103): the feasibility walk. Feasibility alone, as a box without a GPU would do it (D-1066: a PRODUCTION
box without a GPU is a product form that does feasibility and the structured criteria; note criteria wait for a GPU).

The no-GPU form is lane D's second card and is not on master: the box the walk starts is the steps-mode box (the stub
model). So the walk is what a feasibility user does on the box master has, on a study the box seeds with approved
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
            refuse("steward", "POST", "/pilot/request", "the steward cannot start a run",
                   (("kind", "FEAS"), ("ruleset", "{rs}"))),
            refuse("viewer", "POST", "/pilot/request", "the viewer cannot start a run",
                   (("kind", "FEAS"), ("ruleset", "{rs}"))),
            refuse("cro", "POST", "/pilot/request", "the CRO account cannot start a run",
                   (("kind", "FEAS"), ("ruleset", "{rs}"))),
        ),  # fmt: skip
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
            Stop("says", "FEA-04", T("request.start.screen")),
        ),
        (),
        "On New request: read what this box does not do without a GPU (note criteria, screening).",
        "A box without a GPU does feasibility and the structured criteria; criteria that need the notes read wait "
        "for a GPU (D-1066 ruling 1; `deploy/install.sh` --mode stub: \"note criteria wait for a GPU\").",
        lane="D",
    ),
)

FINDINGS: tuple[Finding, ...] = ()

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = (
    (
        7,
        "what a box without a GPU says it cannot do (D-1066)",
        "the no-GPU product form (lane D's second card after D-1066: the installer pins the embedder in stub mode; "
        "the bundle carries its weights; the box plan and the runbook say what a no-GPU box does). The steps-mode box "
        "runs the stub model, so note criteria and SCREEN run on it",
    ),
)

MODULE = Module(
    key="feasibility",
    title="Feasibility alone (a box without a GPU, D-1066)",
    roles=("coordinator", "investigator", "viewer", "cro", "steward"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    study=STUDY,
    sources="D-104 §2, D-280, D-1066",
)

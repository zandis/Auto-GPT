"""H-29 (D-1103): the safety walk. A serious adverse event from the report to the notice that leaves, on a box in
steps mode, each step by the role that owns it in the permission matrix.

It begins as H-20's walk begins (H-10's steps 1 to 11, H-20's 12 to 15, imported): a new study, a participant
enrolled. Then:

16. the coordinator adds an adverse event on the participant's page: serious, hospital stay (the AE form);
17. the coordinator opens the SAE register and the case: the reporting clock and the study's rule set;
18. the coordinator meets D-415's gate: the study counts as open with no SAE type; paused, it does not open again
    until its type is chosen;
19. the coordinator chooses the study's SAE rule set on its set-up page and opens the study;
20. the investigator (the study's PI) acknowledges the SAE on the case page;
21. the coordinator records the first report sent;
22. the data steward reads the notice the box recorded (the audit trail: the notice to the PI and the office);
23. the investigator looks for the notice under "Notices received".

The box's mail is in process (no outside mail): the walk asserts the notice the product records, not a mail.
"""

from __future__ import annotations

from tests.e2e.module_walk_common import Act, F, Finding, K, M, Module, See, Step, Stop, T, refuse
from tests.e2e.new_study_walk_plan import Do

#: the reason the coordinator gives for the pause that meets D-415's gate (any text will do)
PAUSE_REASON = "the safety walk meets the SAE type check"
#: the AE term the coordinator types: words of the walk, nothing a patient record would hold
AE_TERM = "walk event"
#: the study's SAE rule set (``tw_trial``: the site's country, a trial; the set-up page offers the site's country only)
RULE_SET = "tw_trial"
REC = "{record}"


def _ae_form() -> tuple[object, ...]:
    """The AE form, as a coordinator fills it for a serious event: the term, the days, then each choice."""
    choose = (
        ("ae_serious", "1"),
        ("ae_serious_why", "3"),
        ("ae_severity", "2"),
        ("ae_outcome", "2"),
        ("ae_related", "9"),
        ("ae_sponsor_related", "9"),
        ("ae_expected", "9"),
        ("ae_unblinded", "8"),
    )
    return (
        M("field", F("ae_term"), value=AE_TERM),
        M("field", F("ae_onset"), value="{day}"),
        M("field", F("ae_aware"), value="{day}"),
        *(M("choose", F(name), F(name, option=code)) for name, code in choose),
    )


STEPS: tuple[Step, ...] = (
    Step(
        16,
        "coordinator",
        "task.enter_data",
        (
            Do("link", T("life.ae.add")),
            Stop("says", "SAF-01", T("dc.entry.noforms")),
        ),
        (),
        "On the participant's page: Add an adverse event.",
        "The AE form of the participant's next AE event (D-129, D-134).",
    ),
    Step(
        17,
        "coordinator",
        "task.enter_data",
        (
            Do("link", T("dc.forms.title")),
            See("h1", T("dc.forms.title", prefix="{rs} · ")),
            Do("button", T("dc.builtin.go")),
            See("gone", value="dc-no-forms"),
            Do("nav", T("nav.studies")),
            Act("card_link", T("life.to.subjects"), within="{rs}", finding="SAF-03"),
            Do("link", T(None, prefix=REC)),
            Do("link", T("life.ae.add")),
            *_ae_form(),
            Do("button", T("dc.entry.save")),
            See("says", T("life.entry.saved")),
            See("shown", value="ae-ae1"),
            See("says", T("life.sae.wait_pi")),
        ),
        (
            refuse("steward", "POST", "/studies/{rs}/entry", "the steward cannot enter trial data",
                   (("record", REC), ("event", "ae2"), ("form", "tb_adverse_event"), ("f_ae_term", AE_TERM))),
            refuse("operator", "POST", "/studies/{rs}/entry", "the administrator cannot enter trial data",
                   (("record", REC), ("event", "ae2"), ("form", "tb_adverse_event"), ("f_ae_term", AE_TERM))),
        ),  # fmt: skip
        "Add the built-in forms on the study's Forms page; back on the participant's page, Add an adverse event, "
        "fill the AE form for a serious event (hospital stay) and save.",
        "The AE is saved on event ae1, marked Serious, waiting for the investigator's acknowledgement (D-191, D-764).",
    ),
    Step(
        18,
        "coordinator",
        "sae.record",
        (
            Do("more", T("sae.nav")),
            See("h1", T("sae.title")),
            Do("row_link", T("sae.open"), within=REC),
            See("h1", T(None, prefix=REC)),
            Stop("says", "SAF-02", T("sae.flag.unconfirmed")),
        ),
        (
            refuse("steward", "GET", "/sae", "the steward cannot read the SAE register"),
            refuse("operator", "GET", "/sae", "the administrator cannot read the SAE register"),
        ),
        "Open the SAE register (More), then the case of the new SAE.",
        "The case with its reports and their deadlines from the study's rule set (D-277, D-415).",
    ),
    Step(
        19,
        "coordinator",
        "study.state",
        (
            Do("more", T("setup.title", prefix="{rs} · ")),
            Do("link", T("sstate.link")),
            See("h1", T("sstate.title", prefix="{rs} · ")),
            See("says", T("sstate.default")),
            Do("select", label=T("sstate.move"), value="paused"),
            Do("fill", label=T("sstate.reason"), value=PAUSE_REASON),
            Do("button", T("sstate.save")),
            See("says", K("sstate.changed", (("state", "@sstate.paused"),))),
            Do("select", label=T("sstate.move"), value="open"),
            Do("button", T("sstate.save")),
            See("says", T("sstate.sae_type")),
        ),
        (
            refuse("steward", "POST", "/studies/{rs}/state", "the steward cannot change a study's state",
                   (("state", "paused"), ("reason", PAUSE_REASON))),
        ),  # fmt: skip
        "Open the study's state: it counts as open with no state recorded. Pause it (with a reason), then try to "
        "open it again.",
        "The study does not open: its type for SAE reporting is chosen first (D-415, `sstate.sae_type`).",
    ),
    Step(
        20,
        "coordinator",
        "study.setup",
        (
            Do("more", T("setup.title", prefix="{rs} · ")),
            Do("select", label=T("sae.setup.field"), value=RULE_SET),
            Do("button", T("sae.setup.save")),
            See("says", T("setup.saved")),
            Do("link", T("sstate.link")),
            Do("select", label=T("sstate.move"), value="open"),
            Do("button", T("sstate.save")),
            See("says", K("sstate.changed", (("state", "@sstate.open"),))),
        ),
        (
            refuse("investigator", "POST", "/studies/{rs}/setup/sae", "the investigator cannot choose the SAE rule set",
                   (("rule_set", RULE_SET),)),
        ),  # fmt: skip
        "On the study's set-up: choose the SAE rule set (Taiwan, trial) and confirm it; then open the study.",
        "The rule set is saved with the coordinator's name; the study is open again (D-277, D-415).",
    ),
    Step(
        21,
        "investigator",
        "sae.ack",
        (
            Do("more", T("sae.nav")),
            See("h1", T("sae.title")),
            Do("row_link", T("sae.open"), within=REC),
            Do("button", T("sae.ack.do")),
            See("says", T("sae.ack.done")),
        ),
        (
            refuse("coordinator", "POST", "/studies/{rs}/sae/{record}/ae1/ack",
                   "the coordinator cannot acknowledge an SAE"),
        ),
        "As the investigator: open the SAE register, the case, and acknowledge it.",
        "The acknowledgement is recorded with the investigator's name (UX-028, D-143).",
        after=(17,),
    ),
    Step(
        22,
        "coordinator",
        "sae.record",
        (
            Do("more", T("sae.nav")),
            Do("row_link", T("sae.open"), within=REC),
            Do("button", T("sae.form.sent")),
            See("says", T("sae.done")),
        ),
        (
            refuse("investigator", "POST", "/studies/{rs}/sae/{record}/ae1/sent",
                   "the investigator cannot record a report sent", (("party", "sponsor"), ("on", "{day}"))),
        ),  # fmt: skip
        "Open the case again and record the first report as sent today.",
        "The day sent is written to the AE form and the register (D-191).",
        after=(20,),
    ),
    Step(
        23,
        "steward",
        "audit.browse",
        (
            Do("nav", T("nav.audit")),
            Do("select", label=T("audit.filter.event"), value="console.sae"),
            Do("button", T("audit.filter.go")),
            See("says", T(None, prefix="office_copy")),
        ),
        (refuse("coordinator", "GET", "/audit", "the coordinator cannot read the audit trail"),),
        "As the data steward: open the audit trail and filter on the event \"SAE record changed\".",
        "The notice of the new case to the study's PI (and the trial office's mailbox when the box has one), "
        "recorded without the AE term (D-764, FIT-025).",
    ),
    Step(
        24,
        "investigator",
        "",
        (
            Do("more", T("received.title")),
            See("h1", T("received.title")),
            Stop("absent", "SAF-07", T(None, prefix="{rs}")),
        ),
        (),
        "As the investigator: open Notices received and find the notice of the new SAE.",
        "\"The notices TrialBox mailed you, newest first\" (`received.help`): the SAE notice mailed to the PI.",
        why_no_row="every signed-in role reads its own notices",
    ),
)

FINDINGS: tuple[Finding, ...] = ()

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = (
    (
        23,
        "the notice leaving the box: the mail itself (D-764)",
        "outside mail: the box's mail gateway is in process with no outside mail, so the walk reads the notice the "
        "product records (the audit trail), not a mail received",
    ),
)

MODULE = Module(
    key="safety",
    title="Safety: a serious adverse event from the report to the notice",
    roles=("coordinator", "investigator", "steward", "operator"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    rulesets={"en": "SAFEWALK", "zh-TW": "SAFEWALKZH", "ja": "SAFEWALKJA"},
    prefix=True,
    sources="D-191, D-277, D-415, D-764, FIT-025, UX-028",
)

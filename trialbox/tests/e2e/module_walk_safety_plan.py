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

from typing import Any

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
            Act("read", label="reporting clock", within="[data-testid=ae-ae1]"),
        ),
        (
            refuse(
                "steward",
                "POST",
                "/studies/{rs}/entry",
                "the steward cannot enter trial data",
                (("record", REC), ("event", "ae2"), ("form", "tb_adverse_event"), ("f_ae_term", AE_TERM)),
            ),
            refuse(
                "operator",
                "POST",
                "/studies/{rs}/entry",
                "the administrator cannot enter trial data",
                (("record", REC), ("event", "ae2"), ("form", "tb_adverse_event"), ("f_ae_term", AE_TERM)),
            ),
        ),
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
            refuse(
                "steward",
                "POST",
                "/studies/{rs}/state",
                "the steward cannot change a study's state",
                (("state", "paused"), ("reason", PAUSE_REASON)),
            ),
        ),
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
            refuse(
                "investigator",
                "POST",
                "/studies/{rs}/setup/sae",
                "the investigator cannot choose the SAE rule set",
                (("rule_set", RULE_SET),),
            ),
        ),
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
            refuse(
                "coordinator", "POST", "/studies/{rs}/sae/{record}/ae1/ack", "the coordinator cannot acknowledge an SAE"
            ),
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
            refuse(
                "investigator",
                "POST",
                "/studies/{rs}/sae/{record}/ae1/sent",
                "the investigator cannot record a report sent",
                (("party", "sponsor"), ("on", "{day}")),
            ),
        ),
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
        'As the data steward: open the audit trail and filter on the event "SAE record changed".',
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
        '"The notices TrialBox mailed you, newest first" (`received.help`): the SAE notice mailed to the PI.',
        why_no_row="every signed-in role reads its own notices",
    ),
)

FINDINGS: tuple[Finding, ...] = (
    Finding(
        "SAF-01",
        16,
        "coordinator",
        "/studies/{rs}/entry",
        "stop",
        'the participant\'s page offers "Add an adverse event" in a new study that has no forms; the link opens the data-entry page, which says "This study has no forms yet. Add the built-in forms or import a REDCap data dictionary on the page: Forms"',
        "the AE form opens from the participant's page, or the page says the study's forms are to be added first",
        "D-129 (the built-in forms), D-134; `life.ae.add`",
        "blocks the step",
        "C2",
    ),
    Finding(
        "SAF-02",
        18,
        "coordinator",
        "/studies/{rs}/sae/{record}/ae1",
        "stop",
        'the new SAE has no report and no deadline: "TrialBox tracks no report for this kind of SAE", "The study has not chosen its SAE rule set". The new study counts as open with no state recorded, so its type for SAE reporting was never asked (as H-20 F-14)',
        "a trial does not open until its type for SAE reporting is chosen, so a serious AE of an open trial always has its deadlines",
        "D-415 rule 3, D-277, D-386",
        "blocks the step",
        "C2",
    ),
    Finding(
        "SAF-03",
        17,
        "coordinator",
        "/studies/{rs}/forms",
        "way back",
        'after adding the forms, no link leads back to the participant; the walk goes to My studies and the study card\'s "Participants" (as H-20 F-07)',
        "a way back to the page the coordinator came from (the participant)",
        "D-133 (three ways on), D-134",
        "slows the tester",
        "C2",
    ),
    Finding(
        "SAF-04",
        17,
        "coordinator",
        "/studies/{rs}/subjects/{record}",
        "other",
        'the AE line says "Reporting clock: no due date yet: enter the onset or the day the site learned of it" though both days were entered; the cause is the study\'s missing SAE rule set',
        "the clock names its cause: the study's rule set is not chosen (`sae.flag.unconfirmed`)",
        "`life.clock.nostart`, D-277",
        "slows the tester",
        "C2",
    ),
    Finding(
        "SAF-05",
        19,
        "coordinator",
        "/studies/{rs}/state",
        "other",
        'the type check of D-415 is reached only by pausing the study (its lists and list mails stop) and opening it again: a study with no state recorded offers no "Open"',
        "the type is asked when the study is first opened (or the set-up says it is missing)",
        "D-415 rule 3, D-386",
        "slows the tester",
        "C2",
    ),
    Finding(
        "SAF-06",
        23,
        "steward",
        "/audit",
        "term",
        'the notice the box recorded reads "page=office_copy to=<the PI\'s mailbox> event=ae1": the action is labelled "page" and given as a code, in every language',
        "the audit row says in words that the new SAE was notified, and to whom",
        "D-764, FIT-025; `console.sae`",
        "cosmetic",
        "C2",
    ),
    Finding(
        "SAF-07",
        24,
        "investigator",
        "/notices/received",
        "stop",
        "Notices received lists the morning lists only: the SAE notice the box recorded as mailed to the PI (audit `office_copy`, step 23) is not there",
        '"The notices TrialBox mailed you, newest first": the SAE notice among them',
        "`received.help`, D-764",
        "blocks the step",
        "C2",
    ),
    Finding(
        "SAF-08",
        18,
        "coordinator",
        "/sae",
        "other",
        'the steps-mode box has no trial office mailbox: the register says "This box has no trial office mailbox (TB_SAE_OFFICE_MAILBOX): a new serious adverse event is mailed to the study\'s PI only"',
        "the steps-mode box set up as a site is (a test mailbox for the trial office), so the office's copy can be walked",
        "FIT-025, D-764; `tools/demo.py`",
        "cosmetic",
        "integrator",
    ),
)

NOT_COMPLETED: tuple[tuple[int, str, str], ...] = (
    (
        23,
        "the notice leaving the box: the mail itself (D-764)",
        "outside mail: the box's mail gateway is in process with no outside mail, so the walk reads the notice the "
        "product records (the audit trail), not a mail received",
    ),
)

#: the committed summary of the walks of 2026-11-17 (three runs x three languages, ``make walk-modules`` on a
#: 4-core container), written by ``--summary`` from the logs (per step: the page and the clicks in en, the median
#: seconds); the clicks count every click of the step's log, the refusals' sign-ins included
SUMMARY: dict[int, dict[str, Any]] = {
    16: {
        "path": "/studies/{rs}/entry",
        "heading": "{rs} · Data entry",
        "clicks": 1,
        "click_texts": ["Add an adverse event"],
        "seconds": 0.2,
        "guesses": [],
        "stopped": ["SAF-01"],
    },
    17: {
        "path": "/studies/{rs}/subjects/{rs}-0001",
        "heading": "{rs}-0001 · Participants",
        "clicks": 15,
        "click_texts": [
            "Forms",
            "Add the built-in forms",
            "My studies",
            "Participants",
            "{rs}-0001",
            "Add an adverse event",
            "Serious: Yes",
            "Why serious: Hospital stay or a longer stay",
            "Severity: Moderate",
            "Outcome: Recovering",
            "Related to the study treatment or procedure: Unknown",
            "Related in the sponsor's assessment: Not yet assessed",
            "Expected per the reference safety information: Not yet assessed",
            "Treatment unblinded for this event: Open-label study",
            "Save",
        ],
        "seconds": 4.7,
        "guesses": ["SAF-03"],
        "stopped": [],
    },
    18: {
        "path": "/studies/{rs}/sae/{rs}-0001/ae1",
        "heading": "Serious adverse event {rs}-0001 · ae1",
        "clicks": 3,
        "click_texts": ["More", "SAE register", "Open"],
        "seconds": 0.9,
        "guesses": [],
        "stopped": ["SAF-02"],
    },
    19: {
        "path": "/studies/{rs}/state",
        "heading": "{rs} · Study state and identifiers",
        "clicks": 5,
        "click_texts": ["More", "{rs} · Study set-up", "Study state and identifiers", "Change state", "Change state"],
        "seconds": 1.2,
        "guesses": [],
        "stopped": [],
    },
    20: {
        "path": "/studies/{rs}/state",
        "heading": "{rs} · Study state and identifiers",
        "clicks": 5,
        "click_texts": [
            "More",
            "{rs} · Study set-up",
            "Save and confirm",
            "Study state and identifiers",
            "Change state",
        ],
        "seconds": 1.4,
        "guesses": [],
        "stopped": [],
    },
    21: {
        "path": "/studies/{rs}/sae/{rs}-0001/ae1",
        "heading": "Serious adverse event {rs}-0001 · ae1",
        "clicks": 4,
        "click_texts": ["More", "SAE register", "Open", "Acknowledge"],
        "seconds": 1.3,
        "guesses": [],
        "stopped": [],
    },
    22: {
        "path": "/studies/{rs}/sae/{rs}-0001/ae1",
        "heading": "Serious adverse event {rs}-0001 · ae1",
        "clicks": 4,
        "click_texts": ["More", "SAE register", "Open", "Record the report sent"],
        "seconds": 1.4,
        "guesses": [],
        "stopped": [],
    },
    23: {
        "path": "/audit",
        "heading": "Audit trail",
        "clicks": 2,
        "click_texts": ["Audit trail", "Show"],
        "seconds": 0.3,
        "guesses": [],
        "stopped": [],
    },
    24: {
        "path": "/notices/received",
        "heading": "Notices received",
        "clicks": 2,
        "click_texts": ["More", "Notices received"],
        "seconds": 0.1,
        "guesses": [],
        "stopped": ["SAF-07"],
    },
}

MODULE = Module(
    key="safety",
    title="Safety: a serious adverse event from the report to the notice",
    roles=("coordinator", "investigator", "steward", "operator"),
    steps=STEPS,
    findings=FINDINGS,
    not_completed=NOT_COMPLETED,
    rulesets={"en": "SAFEWALK", "zh-TW": "SAFEWALKZH", "ja": "SAFEWALKJA"},
    prefix=True,
    summary=SUMMARY,
    sources="D-191, D-277, D-415, D-764, FIT-025, UX-028",
)

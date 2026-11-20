"""9k-6b (D-1376): one failed-POST case per form converted in 9k-6b, journey 1 (the study's and the site's records), by
its ``data-fields`` name; the sibling of ``form_cases_9k6a.py``, the same shape with what these forms also need.

``tests/unit/test_form_fields_guard.py`` holds this table and the 9k-6a table together equal to the converted forms
of the tree (a form converted without a case fails); ``tests/console/test_form_errors_9k6b.py`` posts each case in
en, ja and zh-TW. A case is plain data: who posts (``role``: the coordinator ``crc1``, the study's named PI
``drsato``, the steward ``stw``), what the box needs first (``prep``, names ``test_form_errors_9k6b.PREP`` runs),
the page and the action, a POST with wrong values and the fields that must fail, in the form's order, and a POST that
saves. ``title`` is the page's title key (the page's title begins with "Error:" after a failed POST). Synthetic only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    template: str
    role: str  # "coordinator", "pi" or "steward"
    page: str
    action: str
    prefix: str  # the prefix of the form's field ids
    bad: dict[str, str]
    failing: tuple[str, ...]
    good: dict[str, str]
    testid: str  # the summary's data-testid on this page
    saved_event: str  # the audit event a saving POST writes
    want: str  # where a saving POST goes (303), as the start of the address
    title: str  # the catalogue key of the page's title
    kept: tuple[str, ...] = field(default=())  # fields whose typed value must come back as typed
    prep: tuple[str, ...] = field(default=())  # what the box needs before (names of test_form_errors_9k6b.PREP)
    japan: bool = False  # the box is made at a Japanese site (the committee record is there only then)
    checked: tuple[str, ...] = field(default=())  # checkboxes of ``bad`` that must come back ticked
    required: tuple[str, ...] = field(default=())  # fields the browser's ``required`` holds, as on master
    minlength: dict[str, str] = field(default_factory=dict)  # fields the browser's ``minlength`` holds, as on master


CASES: dict[str, Case] = {
    "irb": Case(
        template="team_irb.html",
        role="coordinator",
        page="/studies/GZQO/irb",
        action="/studies/GZQO/irb",
        prefix="irb",
        bad={
            "approval_no": "IRB-SYN-2026-014",
            "approved_on": "2026-02-30",
            "expires_on": "2026-13-01",
            "icf_version": "v1.0",
            "icf_date": "not a day",
        },
        failing=("approved_on", "expires_on", "icf_date"),
        good={
            "approval_no": "IRB-SYN-2026-014",
            "approved_on": "2026-10-01",
            "expires_on": "2027-10-01",
            "icf_version": "v1.0",
            "icf_date": "2026-10-01",
        },
        testid="irb-error",
        saved_event="console.irb",
        want="/studies/GZQO/irb?done=1",
        title="team.irb.title",
        kept=("approval_no", "approved_on", "expires_on", "icf_version", "icf_date"),
    ),
    "icf": Case(
        template="team_irb.html",
        role="coordinator",
        page="/studies/GZQO/irb",
        action="/studies/GZQO/irb/icf",
        prefix="icf",
        bad={
            "version": "v!#1",
            "version_date": "2026-10-01",
            "irb_approved_on": "2026-10-02",
            "effective_from": "2026-10-03",
            "note": "synthetic note",
        },
        failing=("version",),
        good={
            "version": "ICF-SYN-2.0",
            "version_date": "2026-10-01",
            "irb_approved_on": "2026-10-02",
            "effective_from": "2026-10-03",
            "reconsent": "1",
            "note": "synthetic note",
        },
        testid="irb-error",
        saved_event="console.icf",
        want="/studies/GZQO/irb?icf=1#icf",
        title="team.irb.title",
        kept=("version", "version_date", "irb_approved_on", "effective_from", "note"),
        required=("version",),
    ),
    "committee": Case(
        template="committee.html",
        role="coordinator",
        page="/studies/GZQO/committee",
        action="/studies/GZQO/committee",
        prefix="cmt",
        bad={
            "kind": "bogus",
            "establisher": "Synthetic University",
            "current_version": "1.0",
            "approved_version": "",
            "approved_on": "2099-01-01",
            "documents": "Sample notice, 2026-10-01",
        },
        failing=("kind", "approved_version", "approved_on"),
        good={
            "kind": "shishin",
            "establisher": "Synthetic University",
            "current_version": "1.0",
            "approved_version": "1.0",
            "approved_on": "2026-10-01",
            "central": "1",
            "documents": "Sample notice, 2026-10-01",
        },
        testid="cmt-error",
        saved_event="console.irb",
        want="/studies/GZQO/committee?done=1",
        title="cmt.title",
        kept=("establisher", "current_version", "approved_on", "documents"),
        japan=True,
    ),
    "staff": Case(
        template="site_staff.html",
        role="steward",
        page="/site/staff",
        action="/site/staff",
        prefix="st",
        bad={
            "kind": "person",
            "name": "   ",
            "department": "Cardiology",
            "practitioner_id": "P-SYN-1",
            "role": "Physician",
            "contact": "ext. 1234",
            "username": "",
        },
        failing=("name",),
        good={
            "kind": "person",
            "name": "Dr Synthetic",
            "department": "Cardiology",
            "practitioner_id": "P-SYN-1",
            "role": "Physician",
            "contact": "ext. 1234",
            "username": "",
        },
        testid="staff-error",
        saved_event="console.staff",
        want="/site/staff?done=add",
        title="team.staff.title",
        kept=("department", "practitioner_id", "role", "contact"),
        required=("name",),
    ),
    "contact": Case(
        template="site_staff.html",
        role="steward",
        page="/site/staff",
        action="/site/staff",
        prefix="ct",
        bad={"kind": "contact", "department": "", "name": "", "contact": "ext. 5678"},
        failing=("department", "name"),
        good={"kind": "contact", "department": "Radiology", "name": "Synthetic Desk", "contact": "ext. 5678"},
        testid="staff-error",
        saved_event="console.staff",
        want="/site/staff?done=contact",
        title="team.staff.title",
        kept=("contact",),
        required=("department", "name"),
    ),
    "optout": Case(
        template="site_optouts.html",
        role="steward",
        page="/site/opt-outs",
        action="/site/opt-outs",
        prefix="oo",
        bad={"chart_no": "", "pid": "deadbeef", "source": "paper", "note": "synthetic note", "unknown_reason": ""},
        failing=("pid",),
        good={"chart_no": "", "pid": "c" * 32, "source": "paper", "note": "synthetic note", "unknown_reason": ""},
        testid="optout-error",
        saved_event="console.opt_out",
        want="/site/opt-outs?done=added",
        title="team.optout.title",
        kept=("pid", "note"),
    ),
    "optout-lift": Case(
        template="site_optouts.html",
        role="steward",
        page="/site/opt-outs",
        action="/site/opt-outs",
        prefix="lift-" + "d" * 32,
        bad={"pid": "d" * 32, "lift": "1", "note": "short"},
        failing=("note",),
        good={"pid": "d" * 32, "lift": "1", "note": "synthetic reason to lift this"},
        testid="optout-error",
        saved_event="console.opt_out",
        want="/site/opt-outs?done=lifted",
        title="team.optout.title",
        kept=("note",),
        prep=("optout_d",),
        required=("note",),
        minlength={"note": "10"},
    ),
    "state": Case(
        template="study_state.html",
        role="coordinator",
        page="/studies/GZQO/state",
        action="/studies/GZQO/state",
        prefix="state",
        bad={"state": "closed", "reason": "synthetic close", "keep_years": "99"},
        failing=("keep_years",),
        good={"state": "paused", "reason": "synthetic pause"},
        testid="state-error",
        saved_event="console.study_state",
        want="/studies/GZQO/state?saved=state",
        title="sstate.title",
        kept=("state", "reason", "keep_years"),
    ),
    "take-back": Case(
        template="study_state.html",
        role="pi",
        page="/studies/GZQO/state",
        action="/studies/GZQO/state/take-back",
        prefix="take-back",
        bad={"reason": ""},
        failing=("reason",),
        good={"reason": "closed by mistake (synthetic)"},
        testid="state-error",
        saved_event="console.study_state",
        want="/studies/GZQO/state?saved=state",
        title="sstate.title",
        prep=("closed_today",),
        required=("reason",),
    ),
}

"""9k-6a (D-1376): one failed-POST case per form converted to the field macro, by its ``data-fields`` name.

``tests/unit/test_form_fields_guard.py`` holds this table equal to the converted forms of the tree (a form converted
without a case fails); ``tests/console/test_form_errors_9k6a.py`` posts each case in en, ja and zh-TW. A case is
plain data (no fixture): who posts (``role``; ``pi`` is the study's named PI), the page and the action, a POST with
wrong values and the fields that must fail, in the form's order, and a POST that saves. Synthetic values only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    template: str
    role: str  # "coordinator" or "pi"
    page: str
    action: str
    prefix: str
    bad: dict[str, str]
    failing: tuple[str, ...]
    good: dict[str, str]
    testid: str  # the summary's data-testid on this page (the one its earlier tests read)
    saved_event: str  # the audit event a saving POST writes
    kept: tuple[str, ...] = field(default=())  # fields whose typed value must come back as typed
    title_key: str = "sstate.title"  # the text key the page's title begins with (after "Error: ")
    saved_at: str = ""  # where a saving POST sends the browser (303)
    #: posted before a saving POST is counted, so that the save changes something (a form that audits only a change)
    reset: dict[str, str] = field(default_factory=dict)


CASES: dict[str, Case] = {
    "identity": Case(
        template="study_state.html",
        role="coordinator",
        page="/studies/GZQO/state",
        action="/studies/GZQO/identity",
        prefix="id",
        bad={
            "sponsor": "Synthetic Pharma",
            "protocol_no": "-SYN 001",
            "siv_date": "2026-02-30",
            "registry_jrct": "JRCT-1",
            "registry_tw": "TW-SYN-2026-001",
        },
        failing=("protocol_no", "siv_date", "registry_jrct"),
        good={
            "sponsor": "Synthetic Pharma",
            "protocol_no": "SYN-001",
            "siv_date": "2026-10-01",
            "registry_jrct": "jRCT2039990001",
            "registry_tw": "TW-SYN-2026-001",
        },
        testid="state-error",
        saved_event="console.study_identity",
        kept=("sponsor", "protocol_no", "siv_date", "registry_jrct", "registry_tw"),
        saved_at="/studies/GZQO/state?saved=identity",
    ),
    "irb-text": Case(
        template="study_state.html",
        role="pi",
        page="/studies/GZQO/state",
        action="/studies/GZQO/irb-text",
        prefix="irbt",
        bad={
            "covers": "1",
            "approval_ref": "",
            "text_version": "#1",
            "approved_on": "2099-01-01",
            "note": "synthetic note",
        },
        failing=("approval_ref", "text_version", "approved_on"),
        good={"covers": "1", "approval_ref": "IRB-SYN-2026-014", "text_version": "v2.1", "approved_on": "2026-10-30"},
        testid="irbt-error",
        saved_event="console.irb_text",
        kept=("text_version", "approved_on", "note"),
        saved_at="/studies/GZQO/state?saved=irb_text#irb-text",
    ),
    # 10F-1 (D-1387): a person's own preferences on the account page; a value outside a key's closed set fails (a
    # select: what was posted is not an option, so nothing comes back as typed)
    "prefs": Case(
        template="account.html",
        role="coordinator",
        page="/account",
        action="/account/prefs",
        prefix="pref",
        bad={"density": "dense", "text_size": "300", "mode": "neon", "lang": "fr"},
        failing=("density", "text_size", "mode", "lang"),
        good={"density": "compact", "text_size": "100", "mode": "system", "lang": "auto"},  # one change, one line
        testid="prefs-error",
        saved_event="console.pref_set",
        title_key="account.title",
        saved_at="/account?saved=prefs",
        reset={"density": "comfortable", "text_size": "100", "mode": "system", "lang": "auto"},
    ),
}

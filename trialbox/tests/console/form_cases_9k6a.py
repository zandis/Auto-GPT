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
    ),
}

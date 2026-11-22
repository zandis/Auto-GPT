"""Set-up for a test that writes its own criterion text (gate 1, the integrator's standing ruling of 2026-11-22).

Such a fixture may be given a person's recorded approval of its own exact text, in its set-up only. The approval is
made here from what the compiler proposes for that text, so the test's assertions still check that proposal: a
proposal that changes no longer matches its approval and is held. A proposal the compiler flags as negated, invalid
or unread gets no approval (``presence_approvals.approval_of`` refuses it), and a line whose concept has no code
cannot be approved. Synthetic data only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest import mock

import criteria_compiler.ir_extract.postprocess as pp
from criteria_compiler.ir_extract.presence_approvals import PresenceApprovalsRefused, RecordedApproval, approval_of
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput

REVIEWER = "synthetic test reviewer"


def approvals_of_own_text(
    ruleset: str,
    extracted: LlmExtractOutput,
    term: Terminology,
    sources: Sequence[pp.PresenceSource],
    **options: Any,
) -> tuple[RecordedApproval, ...]:
    """A person's approval of each line's exact text as the compiler proposes it (no audit: nothing is released)."""
    proposed: list[tuple[Any, Any]] = []
    gate = pp.admit_presence

    def capture(criterion: Any, source: Any, mappings: Any, term_: Any, **kw: Any) -> Any:
        proposed.append((criterion, mappings))
        return gate(criterion, source, mappings, term_, **kw)

    with mock.patch.object(pp, "admit_presence", capture):
        pp.postprocess(ruleset, extracted, term, sources=sources, **options)
    approvals = []
    for criterion, mappings in proposed:
        if criterion.class_ not in ("structured", "mixed"):
            continue
        try:
            approvals.append(approval_of(criterion, mappings, actor=REVIEWER, recorded_at="2026-11-22"))
        except PresenceApprovalsRefused:
            continue  # no code, or a flag no approval may release
    return tuple(approvals)

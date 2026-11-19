"""Card 10C-3 (plan 10, Track C; review 11 card JP-2): who sees a study's patient rows before consent. A PROPOSAL.

Lane J proposes; lane C2 decides (the matrix, accounts, the acting role and audit are C2's). This file is the table
test lane C2 can switch on if it adopts the proposal. It does not change, weaken or replace any test: the matrix and
route tests (``tests/unit/test_authz_matrix.py``, ``tests/console/test_role_route_matrix.py``,
``tests/console/test_matrix_role_walk.py``) stay as they are and keep holding today's matrix.

How it runs:

* by default (every run of ``make test``) every row is an expected failure that is not strict, with the reason
  "proposal 10C-3, awaiting lane C2's decision". A row that already holds today is reported XPASS, never red, so the
  file cannot block a change C2 makes to the matrix;
* with ``TB_PROPOSAL_10C3=1`` the table is checked for real. The rows that already hold today must pass. The rows where
  today's matrix is wider than the proposal (``WIDER_TODAY``) are strict expected failures: they stay green while the
  matrix is as it is, and turn red (XPASS strict) the day C2 changes the cell, so C2 then deletes them from
  ``WIDER_TODAY``. Adopting the proposal is: change the cells, empty ``WIDER_TODAY``, drop the switch.

One row per (person x surface). A person is a role plus a standing in the study (``tb_common.authz.Standing``, which the
console reads from the study's delegation log). A surface is a page, an export or an API that shows patient rows before
consent, named by the matrix actions that guard it today (from ``tests/console/data/route_actions.yaml``). The
proposal and the evidence: ``docs/handover/matrix-proposal-pre-consent-lists-2026-11-19.md``; decision D-1238 (status
proposed). Surfaces whose guard is code and not a matrix cell (the header search, the coordinator's mailed digest,
the mailed candidate workbook) cannot be decided by ``permit``; they are listed in the proposal's section 4 with the
test C2 would need, not here."""

from __future__ import annotations

import os

import pytest
from tb_common.authz import STUDY_TASKS, Standing, permit

pytestmark = pytest.mark.nodb

REASON = "proposal 10C-3, awaiting lane C2's decision"
SWITCHED_ON = os.environ.get("TB_PROPOSAL_10C3") == "1"

# the role the proposal asks C2 to add for the trial office (治験事務局; card 10C-16 names it); not in the matrix today
TRIAL_OFFICE = "trial_office"

# person -> (role, standing in the study). "on the log": the study's delegation log lists the account, active today,
# with the "screen" task ticked by the PI (for a sub-investigator today; for a coordinator under the proposal).
PERSONS: dict[str, tuple[str, Standing]] = {
    "pi_named_on_log": ("investigator", Standing(is_pi=True, tasks=frozenset(STUDY_TASKS), log_names_pi=True)),
    "sub_i_on_log_screen": ("investigator", Standing(tasks=frozenset({"screen"}), log_names_pi=True)),
    "sub_i_on_log_no_screen": ("investigator", Standing(tasks=frozenset({"approach"}), log_names_pi=True)),
    "investigator_not_on_log": ("investigator", Standing(log_names_pi=True)),
    "crc_on_log_screen": ("coordinator", Standing(tasks=frozenset({"screen"}), log_names_pi=True)),
    "crc_not_on_log": ("coordinator", Standing(log_names_pi=True)),
    "crc_log_names_no_pi": ("coordinator", Standing(log_names_pi=False)),
    "trial_office": (TRIAL_OFFICE, Standing(log_names_pi=True)),
    "admin": ("admin", Standing(log_names_pi=True)),
    "viewer": ("viewer", Standing(log_names_pi=True)),
    "cro_no_grant": ("cro", Standing(log_names_pi=True)),
    "steward": ("steward", Standing(log_names_pi=True)),
    "privacy": ("privacy", Standing(log_names_pi=True)),
}

# surface -> the matrix actions that must all hold for the person to see its patient rows (the guard on master)
ROW_SURFACES: dict[str, tuple[str, ...]] = {
    "weekly list /studies/{rs}/week": ("phi.view", "task.screen"),
    "candidate list and page /studies/{rs}/candidates[/{pid}] and /api/v1 twins": ("task.screen",),
    "patient view /studies/{rs}/patients/{pid}": ("phi.view", "task.screen"),
    "this week's list /api/v1/studies/{rs}/patients": ("phi.view", "task.screen"),
    "screening log page, .xlsx and /api/v1": ("phi.view", "task.screen"),
    "not-matched list /studies/{rs}/not-matched": ("task.screen",),
    "excluded, history, rescreen, conflicts pages": ("task.screen",),
    "referral print /studies/{rs}/referrals/{ref_id}/print": ("task.screen",),
    "site patients /site/patients?study=": ("task.screen",),
    "registry and cohort pages": ("phi.view", "task.screen"),
    "registry workbook /pilot/registry/{rs}/export.xlsx": ("id.reveal", "task.screen"),
    "patient twin /api/v1/studies/{rs}/patients/{pid}/twin": ("profile.read", "task.screen"),
    "CASE sheet and SCREEN job card rows": ("phi.view", "task.screen"),
}
SEES_ROWS = {"pi_named_on_log", "sub_i_on_log_screen", "crc_on_log_screen"}

# surface -> the action that opens it; counts only, small cells hidden (never a row)
COUNT_SURFACES: dict[str, str] = {
    "research office report /reports/research-office[.xlsx]": "report.office",
}
SEES_OFFICE_COUNTS = {"crc_on_log_screen", "crc_not_on_log", "crc_log_names_no_pi", "trial_office", "admin", "viewer"}

# (person, surface) where today's matrix gives more than the proposal (rows) or lacks the role (counts)
WIDER_TODAY: set[tuple[str, str]] = {
    *((p, s) for p in ("crc_not_on_log", "crc_log_names_no_pi") for s in ROW_SURFACES),
    ("trial_office", "research office report /reports/research-office[.xlsx]"),
}


def _rows_allowed(person: str, actions: tuple[str, ...]) -> bool:
    role, standing = PERSONS[person]
    return all(permit(role, a, standing).allowed for a in actions)


def _marks(person: str, surface: str) -> list[pytest.MarkDecorator]:
    if not SWITCHED_ON:
        return [pytest.mark.xfail(strict=False, reason=REASON)]
    if (person, surface) in WIDER_TODAY:
        return [pytest.mark.xfail(strict=True, reason=f"{REASON}: today's matrix differs here")]
    return []


ROW_CASES = [
    pytest.param(p, s, p in SEES_ROWS, id=f"{p}|{s}", marks=_marks(p, s)) for p in PERSONS for s in ROW_SURFACES
]
COUNT_CASES = [
    pytest.param(p, s, p in SEES_OFFICE_COUNTS, id=f"{p}|{s}", marks=_marks(p, s))
    for p in PERSONS
    for s in COUNT_SURFACES
]


@pytest.mark.parametrize(("person", "surface", "sees"), ROW_CASES)
def test_pre_consent_rows_only_for_the_studys_logged_team(person: str, surface: str, sees: bool) -> None:
    """Rows before consent: the PI the log names, a sub-investigator and a coordinator the log lists with the
    "screen" task; nobody else (no PI named: nobody)."""
    assert _rows_allowed(person, ROW_SURFACES[surface]) is sees


@pytest.mark.parametrize(("person", "surface", "sees"), COUNT_CASES)
def test_the_trial_office_sees_counts(person: str, surface: str, sees: bool) -> None:
    """The trial office reads the research office's counts (small cells hidden) and no row."""
    role, standing = PERSONS[person]
    assert permit(role, COUNT_SURFACES[surface], standing).allowed is sees


@pytest.mark.parametrize("surface", [pytest.param(s, marks=_marks("trial_office", s)) for s in ROW_SURFACES])
def test_the_trial_office_sees_no_row(surface: str) -> None:
    """Review 11 JP-2's exit: a trial-office account sees no patient row. Holds today only because the role does not
    exist (``permit`` refuses an unknown role); C2's row for the role must keep it so."""
    assert not _rows_allowed("trial_office", ROW_SURFACES[surface])

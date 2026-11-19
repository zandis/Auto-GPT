# D-1238 Pre-consent lists only for the study's logged team, counts for the trial office: proposed to lane C2 (10C-3)

- **Task:** card 10C-3 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C; card JP-2 of root review 11,
  `docs/reviews/2026-11-root/11-japan.md` section 10). Owner of the card: lane J; lane C2 decides.
- **Date:** 2026-11-19
- **Status:** proposed. Put to lane C2; not ruled. Nothing changes for any role until C2 rules and an adopting pull
  request changes the matrix. Lane J's block (D-1220 to D-1319) holds the number.
- **Builds on:** D-101 and D-280 (who reads patient-level rows; the administrator has none), D-104 and D-146
  (aggregate-only accounts), D-147 and D-273 (the delegation log decides an investigator's study rows on every page),
  D-380 (no PI named, nobody is PI; SMO and CRO accounts name their studies), D-425 (one `permit`, one question per
  page), D-430 (one break-glass rule)

## Context

Review 11 (JP-2) asks that a study's candidate list before consent be visible only to the study's PI, its
sub-investigators and the coordinators on its delegation log (the 書式2 list), and that the trial office (治験事務局)
see counts. Lane J may not change who may do or read what: the matrix, accounts, the acting role and audit are lane
C2's. So the card is a proposal.

## What was put to C2

The proposal and its evidence are in `docs/handover/matrix-proposal-pre-consent-lists-2026-11-19.md`. In short:

1. **Inventory.** 24 surfaces show pre-consent patient rows (pages, workbooks, APIs, mails, search). The matrix is
   already right for investigators, the administrator, viewers, CRO accounts, the steward and the privacy office.
2. **Wider today, by a ruled rule.** The coordinator's `task.screen` cell is `true`, as D-147 item 1 rules
   ("Coordinators and administrators keep their role's rights"). So this part proposes to narrow, not to fix. A
   coordinator not on a study's log, or in a study whose log names no PI, reads every pre-consent row of every study
   its account sees. Proposed: the cell becomes
   `[logged_tick]`, and `standing` reads the ticks of `crc` entries (today it reads `sub_pi` entries only).
3. **Missing.** No trial-office role. Proposed: a `trial_office` role (with card 10C-16) that reads the research
   office's counts and no patient row.
4. **Gaps in code, not in a cell.** The header search finds a pre-consent patient of a study the investigator's log
   does not reach, and gives the full pseudonym (observed by
   `tests/console/test_proposal_10c3_header_search.py`, an expected failure; no decision allows it, against D-147
   and D-273). The coordinator's daily mail (N2) does not ask the log. The SCREEN run mails its workbook to the study's
   `routing.list_to` addresses, which no role or log checks. Lane J reports these and fixes none of them.
5. **Test.** `tests/unit/test_proposal_10c3_pre_consent_matrix.py` is off by default (every row a non-strict
   expected failure, reason "proposal 10C-3, awaiting lane C2's decision"). With `TB_PROPOSAL_10C3=1` it checks the
   table: on master 168 rows pass and 27 are strict expected failures, the rows where today's matrix is wider.

## Decision

None yet. This record says only that the proposal was made, when, and where it is. C2 records its ruling under a
number from its own block, citing D-1238; this file's status then changes to name that ruling.

## Not decided here

- The legal reading (proposal section 12) is our reading, not legal advice; plan 10 decision 21's regulatory reader
  confirms it.
- The trial office's set-up and committee rights (card 10C-16).

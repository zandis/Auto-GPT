# D-1241 Off a study's delegation log, the header search answers as for a patient that does not exist (10C-3b)

- **Task:** card 10C-3b of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track C), lane J: the defect card 10C-3
  (D-1238, draft PR #1132) observed in the header command field. Lane J's block (D-1220 to D-1319) holds the number.
- **Date:** 2026-11-19
- **Status:** accepted. A fix of a defect against rules already ruled (D-147, D-273, D-430); it changes no role's
  rights.
- **Builds on:** D-133 (a code typed in the field opens the patient), D-147 and D-273 (the delegation log decides an
  investigator's study rows on every page that shows one study's patients), D-380 (no PI named, nobody is PI), D-425
  (one question per page), D-430 (one break-glass rule), D-875 (an erased row is no patient to find)

## Context

The header command field (`/cmd?q=`, `console.step4.search`) found a patient of any study in the account's scope
by a screening number, a pseudonym prefix or a full pseudonym, from three sources: the study's screening numbers,
this week's list (D-133) and the registry. It asked the `phi.view` row only, never the study's delegation log. An
investigator on study A's log only, refused (403) by study B's weekly list and patient pages, got for B's screening
number or a pseudonym prefix of a B patient a 303 redirect whose `Location` carried the full pseudonym (or a results
page listing it). No chart data, but the existence of the number and the pseudonym leaked.

## Decision

1. **The patient page's own question.** For each study, the search asks `Helpers.reads(user, study)`, the question
   the patient page asks first (the `phi.view` row, then the study's delegation log: `Helpers.delegated_ok`, D-147,
   D-273). No second rule is written.
2. **Where it says no, grant or no grant**, no patient of that study is looked for. The search makes no break-glass
   call at all: a search that confirmed a number-to-pseudonym link for a grant holder would do so without the use
   row the patient page writes (`Helpers.breakglass`, D-430: every use is listed). The person holding a grant opens
   the patient from the grant's own page, where the use is recorded. Break-glass stays wholly lane C2's. (Ruled by
   lane J's lead in the review of PR #1138; the first version found a grant-covered patient without recording a
   use, and is withdrawn.)
3. **A refused study is a miss.** The answer is the answer for a number or prefix that does not exist: the same
   status, headers, body and template, and the same `console.command` audit row (`intent` and `action` only, as
   before; no refusal is audited, since nothing was asked of that study's pages). The study is skipped before any of
   its sources is read, so a hit and a miss in it do the same work.
4. **Nothing else changes.** Accounts the patient page admits (a coordinator; an investigator on the log; any account
   in a study whose log the matrix does not condition) get byte for byte what they got before. The matrix
   (`libs/tb_common/authz_matrix.yaml`), the role and route tables, sign-in, accounts, the audit schema, notices and
   break-glass are untouched. Roles without `phi.view` found no patient before and find none now; the administrator
   still finds none, even with a grant. The `phi.view` guard before the loop stays; `Helpers.reads` asks `phi.view`
   too, so the two hold the same line twice.
5. **Study names stay as they are.** A study-name hit lists the studies of the account's scope (`User.sees_study`),
   the same list S22 My account shows (`studies_of`). D-147 and D-273 restrict a study's patient rows, not its
   name, so an investigator off a study's log still sees the study's name where the scope gives it.

## Held by

`tests/console/test_header_search_off_log.py`: 10C-3's proof test as written on PR #1132 (no expected-fail mark);
every role of the matrix and two investigators (on A's log only, on B's log), every input kind (a screening number as
typed and upper case, with and without the site's dash; a pseudonym prefix of 8, 12 and 16 characters and the full
pseudonym; 4 to 7 character prefixes), every source (screening numbers, the weekly list, the registry), a pseudonym
in both studies, compared byte for byte (status, headers, body, audit rows) with the answer given before the
patients existed; the on-log accounts' hits; a break-glass grant.

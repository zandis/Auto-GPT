# D-434 Copy-assist: signed values to copy into the sponsor's EDC by hand, a plain file, both audited

- **Task:** T-302c (third part of T-302; `docs/plan/28-master-plan-v6.md` §6.2.5)
- **PR:** this branch (`agent/T-302c-copy-assist`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-160 (EDC prefill: drafts, decisions, signatures), D-162 (who acts), D-281 and D-391 (signatures,
  the record lock), D-368 (T-115), D-414 (visit names of arms, events and repeating instruments), D-425 (every
  call site asks `permit`), D-435 (ODM import as proposals; the sponsor layout), D-149 (the export ledger)
- **Closes:** FIT-015 (the copy-assist half; the sponsor's screening-log layout came with D-435)

## Context

TrialBox wrote to an EDC only through the REDCap API (D-160) or an ODM file, and the REDCap send goes on only with
the sponsor's written acknowledgement on file. TB-PLAN-06 §1.2 item 5 says a study without that acknowledgement
uses copy-assist: the box shows the confirmed values with their sources and a person types them into the
sponsor's EDC. URS-CRC-10 names copy-assist and a plain file for an EDC with no import (FIT-015). Neither existed:
with the switch off nothing could be drafted, reviewed or signed at all.

## Decision

1. **A third switch state, `copy`.** Besides `off` and `on`, the study's prefill switch may be `copy`. The PI the
   delegation log names turns it to `copy` (row `edc.switch_on`), with the stored blind re-entry result as for `on`
   (E-14), and without a sponsor acknowledgement: in `copy` nothing is ever written to the sponsor's EDC. Drafting,
   the ODM import, review, the record lock and the signature work as with `on`; the REDCap send, its preview and
   "erase hidden values", and the ODM export stay refused (`edc.off`) unless the switch is `on`. Off stays "stop at
   once" for both (the PI or an administrator). Every change is a `switch_event` row and audited, as before.
2. **Only signed values are shown.** The copy-assist sheet of one subject (`EdcService.copy_sheet`) lists the
   values that are decided (confirmed or edited), signed with a version-2 signature (D-281) whose row still
   verifies, and unchanged since signing (`EdcStore.signed`). A version-1 signature row is never a source here. An
   open, rejected or decided but unsigned value is never shown; the page counts them per visit ("waiting for
   review or a signature") and links to the review page.
3. **In the order of the sponsor's form.** Per visit (D-414's names, in visit order), then per form in the data
   dictionary's order, then per item in the dictionary's order: the order a person meets the fields in the sponsor's
   EDC. Each value carries its label in the reader's language (D-398), the value and the choice's word, its source
   citation (the cited record line, or the person's own source for a typed value, or the ODM file), who signed it
   and when.
4. **"Copied" ticks, per value or per form.** `edc.copy_tick` (schema `edc` version 4, append-only by trigger as the
   other trail tables) keeps one row per tick: the draft, the hash of the signed value it was ticked for
   (`signed_sha`), `copied` or `undone` (with a reason), who and when. A tick counts only while the value is still
   the one signed: a value changed and signed again shows as not copied, with the earlier tick listed. Ticking a
   value that is not on the sheet (unsigned, another subject, an opted-out patient) refuses the whole request.
5. **Audited.** Every view of the sheet (page, file, `/api/v1`) is an `edc.copy_view` event in the orchestrator's
   chain (study, record, number of values, the format; never a value), and every tick an `edc.copy_tick` event
   (draft ids, action, reason given). The console adds its own `console.edc_copy` line with the person.
6. **The plain file.** `GET /studies/{rs}/edc/copy.csv` (one subject with `?record=`, else every subject of the
   study) is the same sheet as CSV (UTF-8 with a byte-order mark, one row per value: record, visit, form, item,
   label, value, word, source, signed by, signed at, copied by, copied at). It asks the same question as the page,
   refuses a named opted-out subject and leaves every opted-out subject out of the study file, and writes a
   `flow.export` row (channel `console_download`, level `pseudonymised`, the console role and the study as its
   approval; D-149) before the bytes leave. No chart number is in the page or the file: the record key is the
   screening number.
7. **One right for the sheet, one for the tick.** New matrix rows `edc.copy` (page, file, read API) and
   `edc.copy_tick` (tick and undo), with the same cells as `edc.review`; the orchestrator checks the role again
   (`review`). Each state-changing page route has its `/api/v1` twin, and the twin reads the body only after the
   session and the right are checked.

## Not in this decision

- The layout's XLSX for the copy file (the sponsor layout of D-435 names screening-log columns, not CRF items).
- A console page for the sponsor layout and the weekly sheet (D-435's routes); the REDCap preview and "erase hidden
  values" pages (D-414).

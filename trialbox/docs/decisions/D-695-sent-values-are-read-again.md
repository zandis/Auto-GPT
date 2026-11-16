# D-695 Sent values are read again; a change in REDCap is listed

- **Task:** NEW-EDC-5 (deep-review finding EDC-005, **High**: a value TrialBox sent and a person later corrected in
  REDCap stays "sent" in TrialBox)
- **PR:** this branch (`agent/NEW-EDC-5-sent-values-reread`), cut from NEW-EDC-4 (#618): the send's results change
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-693 (a value found already there is the person's), D-691, D-160

## Context

The send drops a value once it is sent as it is, so it was never read again. A person who corrected it in REDCap
left TrialBox showing its own value on the review page, the ODM export, the SDV and copy-assist sheets; a monitor
would verify the wrong number (review case 1a).

## Decision

1. **A reconcile read** (`EdcService.reconcile`, `POST /studies/{rs}/edc/reconcile`) reads REDCap for every value
   TrialBox delivered: signed, sent as it is, and written by TrialBox itself at least once (a value only ever found
   already there is the person's, D-693); never an opted-out patient's. It compares REDCap's value with what TrialBox
   last delivered there (its value, or blank after its own erase) and lists each one REDCap now holds differently,
   with both values. A value whose REDCap dictionary entry changed since it was sent is not compared (it would be
   formatted otherwise); a project whose export lacks `redcap_repeat_instance` is refused (`edc.repeat_keys`).
2. **Each send runs it** after its own writes and its own audit line, and lists the changes (`changed_in_redcap`);
   when REDCap cannot be read then, the send is still done and says why (`reread`: the code; the next send or a
   reconcile reads again).
3. **Each change gets one `changed_in_redcap` line** in the ledger, with REDCap's value and a short hash of it (the
   detail is cut at 300 characters); the same change read again adds none, a further change adds one; REDCap
   equal again closes it with an `equal_again` line. Audited (`edc.reconciled`: values compared, changes).
4. **Taking REDCap's value is an edit with a reason** (as before, re-authenticated for a signed value); the next
   send finds it already there and nothing is listed. Keeping TrialBox's leaves the change listed.
5. The console's send pages count it and the trail names it (three languages; lane C2's files). The route is in
   `route_callers.yaml` with the send's group.

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| TrialBox's own erase of a hidden value was listed as a change in REDCap, for good | high | fixed, test first: compared with what TrialBox last delivered |
| A value longer than the detail's 300 characters wrote a line on every read | medium | fixed, test first: a hash of REDCap's value |
| Changed back, then away again: no new line, and the trail still said changed | medium | fixed, test first: `equal_again` closes it |
| A REDCap dictionary change made values look changed | medium | fixed: not compared (a test pins it) |
| No `redcap_repeat_instance` guard | low | fixed: `edc.repeat_keys` |
| "Could not read" looked like "nothing changed"; the send's audit line came after the re-read | low | fixed, test first: `reread`, after the audit line |
| `_layout`'s refusal is audited as `edc.sent` during a reconcile | low | kept (the same refusal; named in the line) |

## Not in this card

- The nightly read (`console.rc_read`) reads the project link, not the EDC target; adding the reconcile to the night
  is a small follow-up.
- Marking the value on the review page, the ODM export and the SDV sheet from the ledger line: a follow-up; the
  change is listed on each send and in the trail now.

## Evidence

`tests/unit/test_edc_sent_values_reread.py`: case 1a (listed with both values, one line under the person who read
it); each send lists it and writes one line per change; taking REDCap's value clears it; a value never written by
TrialBox is not listed; audited and limited to the record asked; the console counts it; the review's five cases. The
first six failed before the change; the review's failed before its fixes (the dictionary case pins the rule).

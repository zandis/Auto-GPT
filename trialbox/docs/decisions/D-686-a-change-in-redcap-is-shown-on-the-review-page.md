# D-686 A change in REDCap is shown on the review page

- **Task:** NEW-EDC-5b (the follow-up D-695 recorded: mark a value that changed in REDCap where a person decides it)
- **PR:** this branch (`agent/NEW-EDC-5b-changed-in-redcap-shown`), cut from NEW-EDC-6 (#627), the EDC chain's head
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI)
- **Builds on:** D-695 (sent values are read again; `changed_in_redcap` and `equal_again` lines)

## Context

D-695 lists a value REDCap holds differently from what TrialBox sent on each send and in the trail. The review page,
where the coordinator decides the value, went on showing TrialBox's value alone.

## Decision

1. **The drafts the review page reads carry what REDCap holds** (`redcap_now`) while the item's last read-again line
   is an open `changed_in_redcap`; `equal_again` (or a later write by TrialBox) clears it. Read from the ledger
   (`EdcStore.redcap_changes`), so nothing new is stored.
2. **The review page shows it beside the value**, with what to do: take REDCap's value by changing it here with a
   reason, or correct REDCap to keep TrialBox's (three languages; lane C2's files).
3. The ledger's detail is cut at 300 characters; a value cut there is shown with "…" (REDCap holds the whole).

## Not in this card

- The nightly read: the reconcile route needs a person (the send's role); a night job has none. A small card once
  the box's timer has a service identity for it.
- Marks in the ODM file and the SDV sheet.

## Evidence

`tests/unit/test_edc_changed_in_redcap_shown.py`: through the drafts route, `redcap_now` is empty after the send,
REDCap's value after a change, empty again when REDCap is equal again; a long value is shown cut with "…"; the page
and the three languages. All three failed before the change.

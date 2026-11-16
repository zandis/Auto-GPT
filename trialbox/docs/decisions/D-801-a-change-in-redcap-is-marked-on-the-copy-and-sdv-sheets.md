# D-801 A change in REDCap is marked on the copy-assist and SDV sheets

- **Task:** NEW-EDC-5c (the follow-up D-695 and D-686 recorded: the copy-assist and SDV sheets)
- **PR:** this branch (`agent/NEW-EDC-5c-changed-on-copy-and-sdv`), cut from NEW-EDC-8c (#637), the EDC chain's head
- **Date:** 2026-11-15
- **Status:** proposed (merges on green CI)
- **Builds on:** D-695 (sent values are read again), D-686 (the review page shows REDCap's value), D-434 (copy-assist),
  D-436 (the monitor's SDV sheet)
- **Number:** lane E's block (renumbered from D-615, lane W's block)

## Context

D-686 shows what REDCap holds beside a value that changed there after TrialBox sent it, on the review page. The
copy-assist sheet (a person copies a signed value into REDCap by hand) and the monitor's SDV sheet (a value verified
against its source) went on showing TrialBox's value alone: a monitor could verify a number that is no longer the
EDC's, and a person could copy over a correction made in REDCap.

## Decision

1. **The copy-assist sheet carries what REDCap holds** (`redcap_now`, from the ledger, `EdcStore.redcap_changes`)
   for each value while its change is open, and its page shows it with "check before copying".
2. **The SDV sheet carries it too**: the drafts route already gives `redcap_now` (D-686); the sheet keeps it, and
   the page shows it beside the value.
3. Three languages (lane C2's files). The copy-assist CSV keeps its columns (a later card if a site asks).

## Evidence

`tests/unit/test_edc_changed_on_copy_and_sdv.py`: the copy-assist sheet carries REDCap's value for the changed value
only; the SDV sheet keeps it; both pages and the three languages. All three failed before the change.

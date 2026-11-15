# D-747 What leaves the box is scanned for English phone numbers; the repository is not

- **Task:** NEW-B-46 (found by D-744's review; placed with lane B2 by the integrator on #593, 2026-11-15:
  "exit-path mode, no allow-list entries")
- **PR:** this branch (`agent/NEW-B-46-exits-scan-english-phones`), on top of NEW-B-43 (#598, D-744)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** D-203 (the data-handling scan), D-723 (the support bundle's last look), D-744 (the English phone
  form of the note masker), the owner's rule "never add a scan waiver"

## Context

`tools/data_scan` is the scrub of what leaves the box: a support bundle (each flagged line removed, then the finished
archive scanned once more), the console's comment export (a flagged comment withheld) and the demo guard's scan of
stored input. It knew Taiwanese and Japanese phone numbers only: `Contact 555-0133` passed a bundle's scrub. The same
scanner also checks the repository, whose tests and evaluation sets (`eval/phi_synth`, D-744's tests) hold synthetic
English phones by design; adding the form there would need an allow-list entry for each, which the owner's rule
forbids.

## Decision

1. **A pattern may be marked `exit`** in `tools/data_scan_patterns.yaml`: it is in the scans of what leaves the box
   (`load_patterns(exits=True)`) and not in the repository scan (`load_patterns()`, as before).
2. **`en_phone`**, an exit pattern, is the note masker's form (`tb_common.phi_guard.EN_PHONE`, D-744), named, not
   copied: what the masker masks, the exits remove.
3. **The three exits use the exit patterns:** the support bundle's line scrub and its last look at the finished
   archive, the comment export, the demo guard's scan of stored input.
4. No allow-list entry is added. The planted positive (`tests/fixtures/data_scan/positives/en_phone.txt`) sits under
   the planted positives' existing path entry.

## What a person sees differently

A line of a support bundle with an English phone number is removed and the bundle says so (`en_phone`); a comment
holding one is withheld from the export; the demo guard reports one in stored input. The repository scan is as before.

## Not in this card

The forms D-744 leaves (a seven-digit number with no word before it, a second number after the first, a number split
over a line) are not found at the exits either.

## Tests

`tests/unit/test_data_scan_exits.py` (5 tests; all fail on the parent): `en_phone` is in the exit patterns only, and
the exit patterns hold every repository pattern too; the comment export, the support bundle's scrub and the demo
guard each find it; the bundle's last look and every pattern load of the bundle use the exit patterns.
`tests/unit/test_data_scan.py` loads the exit patterns too, so every pattern, `en_phone` included, finds its planted
positive. No state change.

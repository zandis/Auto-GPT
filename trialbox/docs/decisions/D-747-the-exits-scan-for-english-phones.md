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
archive scanned once more), the console's comment export (a flagged comment withheld), the demo guard's scan of
stored input, the mapping check's share report (`--share`, the one report that leaves the site, D-588) and the
command line an administrator runs on a ticket's attachment (runbooks 03 and 21). It knew Taiwanese and Japanese phone numbers only: `Contact 555-0133` passed a bundle's scrub. The same
scanner also checks the repository, whose tests and evaluation sets (`eval/phi_synth`, D-744's tests) hold synthetic
English phones by design; adding the form there would need an allow-list entry for each, which the owner's rule
forbids.

## Decision

1. **A pattern may be marked `exit`** in `tools/data_scan_patterns.yaml`: it is in the scans of what leaves the box
   (`load_patterns(exits=True)`) and not in the repository scan (`load_patterns()`, as before).
2. **`en_phone`**, an exit pattern, is the note masker's form (`tb_common.phi_guard.EN_PHONE`, D-744), named, not
   copied: what the masker masks, the exits remove.
3. **The exits use the exit patterns:** the support bundle's line scrub and its last look at the finished archive
   (`last_look`), the comment export, the demo guard's scan of stored input, the share report's scan, and the
   command line with `--exits` (runbooks 03 and 21 now say it).
4. **The form itself stops reading log text as a phone** (it is also the masker's and the gate's, D-744): a word
   that only names a phone (`tel`, `phone`, `mobile`, `fax`, `pager` …) takes a number written any way; a word
   that is often something else (`call`, `contact`, `home`, `number is`, `T:` and `M:` in capitals) takes one
   written as a phone (a separator in seven digits, an area code in ten); a country code by `00` needs a separator
   after it (never `0012345678`, an id); a date is never the rest of a number (`+0800 2026-11-15`,
   `job 001 2026-11-15`). The PHI evaluation set's phones stay masked (119 of 120, as with D-744).
5. No allow-list entry is added. The planted positive (`tests/fixtures/data_scan/positives/en_phone.txt`) sits under
   the planted positives' existing path entry.

## What a person sees differently

A line of a support bundle with an English phone number is removed and the bundle says so (`en_phone`); in a table
member (`.csv`) the scrub reads lines, the last look reads the table with its header's labels, so a labelled phone
there refuses the whole bundle instead (as the other labelled patterns already do). A comment holding one is withheld
from the export; the demo guard reports one in stored input; the share report is not written; the command line with
`--exits` exits 2. The repository scan is as before. At the exits the line is normalised first (full-width digits,
dashes), so the exits find a few forms the masker does not (full-width digits, D-744's "not masked").

## Not in this card

The forms D-744 leaves (a seven-digit number with no word before it, a second number after the first, a number split
over a line) are not found at the exits either.

Not either: a dashed 3-3-4 number of any kind is read as North American (`range 200-300-4000`); a table column named
`phone_number` or `電話` does not label its values (the scan's header rule).

## Tests

`tests/unit/test_data_scan_exits.py` (10 tests; all fail on the parent): `en_phone` is in the exit patterns only, and
the exit patterns hold every repository pattern too; the comment export, the support bundle's scrub, the demo guard,
the share report and the command line with `--exits` each find it; the bundle's last look finds it in a real
archive; ordinary log lines (zero-padded counters before a date, ids, counts after "call" or "contact", `T: … ms`,
time-zone offsets before a date) are no phone; every phone of D-744's tests is still found.
`tests/unit/test_data_scan.py` loads the exit patterns too, so every pattern, `en_phone` included, finds its planted
positive. No state change.

## Review

One adversarial read-only review by a fresh agent (every use of the data scan in services, tools, runbooks, CI and
hooks; the exit scan over synthetic log lines and the repository; tables; eight mutants). Findings, fixed test-first
in the second commit: the command line and the share report still used the repository's patterns (the record listed
three exits); ordinary log lines were read as phones (and the same form masks notes and refuses calls); the last-look
test read the call's shape only (now a real archive). Said above, not changed: a table's labelled phone refuses the
bundle; `phone_number` headers give no label; full-width digits are caught at the exits only.

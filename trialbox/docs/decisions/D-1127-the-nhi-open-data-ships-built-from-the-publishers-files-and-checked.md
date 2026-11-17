# D-1127 The NHI open data ships, built from the publisher's files and checked

- **Task:** lane H, card H-17 (terminology that moves the share), on the owner's ruling D-1028 point 3 (NHI open
  data may ship with attribution)
- **PR:** this branch (`claude/lane-h-17-nhi-and-site-list`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-1115 (TERM-2's `nhi-drugs` and `nhi-services`), D-1114 point 3 (a name several codes share),
  D-1029 (how ICD-10-CM's blocks and index ship), D-170 and D-317 (lane E's readers of the same files)

## Context

TERM-2 loads the two NHI lists at install from a file the site's IT supplies. D-1028 point 3 lets the product ship
them, so a box answers from them without a site step. What was missing: the exact files to fetch, a build that turns
them into a committed table with its manifest line, a check of what ships, and a reader that takes the files as the
publisher really writes them (Big5 as well as UTF-8, header variants, a malformed row named). Lane E's readers
(`tb_common.refdata_tw`) read UTF-8 only and skip a row without a code silently; they are not changed.

## Decision

1. **What to fetch** is written in `docs/licences/nhi-open-data-fetch.md`: data.gov.tw 23715 and 174450 (verified
   online on 2026-11-17), their CSV download URLs, columns, update rhythm, version naming, licence (OGDL 1.0), its
   attribution annex and what it does not give. The integrator alone fetches; the sha256 and the day are filled in
   there.
2. **One reader for both commands** (`installed.nhi_drug_rows`, `installed.nhi_service_rows`, through `nhi_csv`):
   - UTF-8 with or without a BOM, else Big5 (cp950);
   - headers compared after NFKC, without spaces, quotes or a BOM, Latin letters in upper case; a renamed column is
     given with `--column OURS=THEIRS`, never guessed;
   - a missing column, a column twice, a row with more or fewer fields than the header, a code not shaped as its
     system's (an NHI drug code has 10 characters; a service or order code 2 to 12 letters and digits) or a date that
     is not one refuses the whole file, naming the row and its line;
   - one row per code, the newest period (as lane E's readers keep it). For valid files the table is the one TERM-2
     wrote: a test compares both on the public samples.
3. **The build** (`nhi-build drugs|services <csv> --version --fetched-on --sha256`) refuses a file whose sha256 is not
   the one recorded at the fetch, and writes the table into the shipped folder beside the mapper with its manifest
   line: the source and its whole sha256, the version, the day it was fetched (no clock: a rebuild writes the same
   bytes), the licence, TERM-2's attribution, and the OGDL annex's statement with the version (`ogdl_statement`).
4. **The check** (`nhi-check`, exit 1 on a problem) fails when a shipped table has no manifest line or other bytes,
   lacks the licence, an attribution or the source's sha256, is not NHI open data, or has no `cleared` OGDL row in
   the licence register naming it. A test runs it on the repository, so CI checks whatever ships. Row
   `nhi-open-data-full` stays `site-loaded` with no paths until the integrator ships; it then becomes `cleared` with
   the shipped folder's paths in the same commit.
5. **How the mapper reads them (class B, minimal):** `Terminology._load_term2` reads a shipped NHI table when the box
   loaded none of its own, through the same manifest check (a changed shipped table is refused and reported). A
   table loaded at install is read in its place. `installed.not_loaded` counts a shipped NHI table as there. Nothing
   ships now, so nothing answers differently, and the goldens stay identical.
6. **Ended codes and shared names** behave as TERM-2 decided: an ended code answers nothing; a name several codes
   share answers with all of them, for review.

## Measured

A made-up extract in the publisher's layout (29 drugs, 19 service codes, both encodings) moves P1b's mapped share
from 266 to 281 of 1,273 (medication 6 to 13, all for review; procedure 0 to 8, 3 for review). Its names were chosen
to equal a few words P1b drafted. It is a mechanism test, not a coverage figure. What the real lists move cannot be
known until they are loaded; the drug list answers a medication only by its ingredient (成分, for review) and the
service list a procedure only when its name equals an item's whole name.

## Two tests changed

TERM-2's `test_with_nothing_loaded_nothing_changes` and `test_doctor_names_each_system_and_who_accepted` now set the
shipped folder to an empty one. They state "nothing loaded"; once NHI tables ship, the image is no longer "nothing",
and these tests keep their meaning. Every assertion in them stays.

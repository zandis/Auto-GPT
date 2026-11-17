# D-1128 A made-up site list of 50 lines measures the mechanism and the scale, not the product

- **Task:** lane H, card H-17 (terminology that moves the share)
- **PR:** this branch (`claude/lane-h-17-nhi-and-site-list`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-1113 (the site's lists win), D-1116 (never committed; the coverage tool), D-1028 point 2

## Decision

1. **A made-up list is a test fixture.** `tests/fixtures/terminology/site_list_synthetic.csv` has 50 lines in
   TERM-2's `site-list` format over the most frequent names P1b left unmapped: 20 conditions with real ICD-10-CM codes
   (public domain, each checked against the shipped full list), 15 observations with made-up LOINC-shaped codes (7
   digits from 9900001: beyond any issued LOINC number), 9 medications with made-up ATC-shaped codes (group `Z`, which
   ATC does not have) and 6 procedures with made-up NHI order codes (`ZZ...`). Every row says it is no hospital's
   list. It passes the never-committed guard through its licence-register row `term-synthetic-fixtures` (status
   `synthetic`), as the adapter's demo maps pass through theirs. A site's real list never enters the repository.
2. **The measure runs in CI without the archive.** `tools.terminology_coverage --write-concepts` derives launch P1b's
   drafted concepts into `tests/fixtures/terminology/p1b_concepts.csv`: 1,045 distinct (domain, name as drafted)
   with counts, 1,273 in all, 34 KB, ClinicalTrials.gov trial wording as the compiler drafted it (row
   `p1b-concept-names`). `--concepts` measures from it and gives the archive's own figures (266 of 1,273). The JSON
   output also counts, by domain, the resolved concepts whose answer is for review.
3. **What may be quoted.** Loading the list through the real `site-list` command moves the mapped share from 266 to
   396 of 1,273 (130 more, every one from the list). 83 of the 130 answer for review, because their codes are in no
   table; the 47 conditions do not. This may be quoted as: "on P1b's concepts, each line of a site list maps about 2.6
   drafted concepts at the head of the frequency list, and the rate falls fast down the tail". It may not be quoted as
   a product figure, a site's coverage, or a mapping's correctness: the list is made up, and its observation,
   medication and procedure codes mean nothing.
4. **The scale.** Of the 1,007 concepts P1b left unmapped, 888 names are distinct and 801 occur once. The 50 most
   frequent cover 132 (13 %), 200 cover 319 (32 %), 400 cover 519 (52 %). A site's list that names the trial's own
   words would need hundreds of lines to move half of what remains; a list written in the hospital's own words moves
   only what a trial's words equal. The figures are in `docs/plan/measurements/term-site-list-2026-11-17.md`.

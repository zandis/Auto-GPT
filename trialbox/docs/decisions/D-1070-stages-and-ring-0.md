# D-1070 Stages, not one complete release; ring 0 is confirmed and frozen

- **Task:** an owner's ruling, numbered by the integrator; every lane's cards
- **Date:** 2026-11-22
- **Status:** accepted (the owner's rulings of 2026-11-22; recorded here the same day)

## Ruling

1. "One complete release for the first site; no reduced first version" (D-1068 point 3; decision 39 of plan 10) is
   withdrawn. The work goes in stages: rc1, a supervised demonstration; then a pilot-ready core for one site; then
   release 1.0.
2. The second data doors, customisation beyond what is built, and the multicentre track beyond what the first site
   uses are deferred past the pilot.
3. The work is cut into rings. **Ring 0, the core, is confirmed and frozen as written below.** Rings 1 to 4 are
   named here and confirmed one at a time, each by its own decision.
4. The rule of the rings (below) holds from now on.

## Ring 0: the core, the MVP

- **Does.** On synthetic data, on one box: a protocol compiled with unclear lines held for a person; a synthetic
  SS-MIX2 storage and a CSV read; a screening night that decides coded criteria by rule and note criteria by the two
  models, where unknown, a single model, or a negated, family or suspected quote never excludes, and an inclusion
  "not met" from notes goes to review (D-1069); the week's list with the quote and the reason; an investigator's
  recorded decision; an audit chain that detects truncation; a nightly backup and one rehearsed restore; an install
  by a person who did not write it. Screens in English and Japanese.
- **Does not.** No real patient data and no hospital; no delta night; no 50,000-patient night; no tier but the one
  it is shown on; no gate programme; no masking claim in Japanese; no accuracy bound (a measured sheet only); no
  multicentre, customisation or EDC; no data door other than SS-MIX2 and CSV.
- **Proved by.** The rc1 checklist (ten lines, each with its evidence) and one walk of the whole loop on a
  hospital-sized machine from the release bundle.
- **Plan cards.** 10A-1, 10A-2, 10A-3, 10A-4, 9c-6, 9c-9, 9e-9, 10B-1 to 10B-4, 9b-15, 10C-1, 10D-15, 10E-9, 9i-1,
  9i-2, 9l-22, 9g-11, 9g-16, 10G-3, 10G-6, 9h-2, 9h-15, 10H-1, 10K-3, 10K-4, 10K-21 (28; 21 were done on the day of
  this ruling), and the faults in this ring's own promise that the review of 2026-11-22 found.

## The other rings, named and not yet confirmed

- **Ring 1:** one Japanese hospital, supervised.
- **Ring 2:** trustworthy at a site without supervision.
- **Ring 3:** multicentre.
- **Ring 4:** breadth (other data doors, customisation, other tiers, the EDC door, reimbursement).

## The rule of the rings

1. One page per ring: does, does not, proved by, its cards. The owner confirms it by a decision; a confirmed ring is
   frozen.
2. A frozen ring changes only for a fault in its own promise: a finding that shows one of its "does" lines false,
   with an input. Everything else goes to the next unconfirmed ring.
3. Only the owner adds to a frozen ring, and only by a swap of something of equal size, in the same decision.
4. Reviews file findings, not cards. The integrator sorts each finding into "a fault in the frozen ring" or "a
   later ring".
5. One ring is built at a time. The next ring's page is written meanwhile and confirmed when the current ring's
   proof is recorded.
6. Each train reports the current ring's count.

## What it changes in earlier records

- D-1068 point 3 is superseded. Its other points stand, among them point 4's order of events.
- Plan 10's decision 39 (`docs/plan/47-plan-10-2026-11-18.md`, section 8) is superseded; its cards keep their ids
  and are read by ring.

## Where the wording comes from

Two rulings of the owner on 2026-11-22. The first, at 10:40 UTC, relayed by the integrator on the inbox (#639
comment 7077918101, ruling 2): stages. The second, about 11:05 UTC in the reviewer's session, after the count of
how the plan had grown, in his words: 「收回一次完整發行，確認第0圈」 (withdraw the one complete release; confirm
ring 0); and then: 「第0圈要有哪些，讓integrator安排全速完成」 (what ring 0 needs; the integrator arranges it at
full speed). The rings and the rule are those of the plan 10 review, pull request #1327, section 10.

## Used by

The integrator's schedule; every lane's choice of the next card; the rc1 checklist.

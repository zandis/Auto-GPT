# D-1271 Ring 1 is the first real sites, supervised (draft for the owner to sign)

- **Task:** lane R1's ring 1 page (`docs/plan/ring-1-2026-11.md`); the number is from lane M's block, given for this
- **Date:** 2026-11-23 (drafted)
- **Status:** **draft, not in force.** It takes effect when the owner signs it, and not before ring 0's proof is
  recorded (D-1070 rule 5). Until then nothing below binds a lane.

## Ruling (as drafted)

1. **Ring 1 is confirmed and frozen** as written on its page, `docs/plan/ring-1-2026-11.md`, sections 3 and 5
   (does; does not; proved by; its cards). D-1070's rule of the rings holds for it.
2. **Its sites are two**, each supervised: Chang Gung Memorial Hospital in Taiwan (its CGRD-type SQL views;
   ICD-10-CM, NHI order codes, LOINC where present and the hospital's own codes; screens in Traditional Chinese), and
   the Japanese hospital group the owner names, as the answer to the page's question 1 records it (SS-MIX2 storage;
   WHO ICD-10 and JJ1017; screens in Japanese). This replaces D-1070's provisional line "Ring 1: one Japanese
   hospital, supervised".
3. **No patient data leaves a site.** A real-site run is measured on the site's box, and only counts files of the
   page's section 4.1 form leave it, sent by a named person of the hospital. The owner's own data is held to the same
   rule on the owner's own machines (the owner's ruling of 2026-11-23, #639 comment 7099836527).
4. **The FHIR store stays HAPI FHIR in ring 1.** BD-01 stands; Medplum is evaluated after the pilot, in ring 4.
5. **A cloud GPU VM is a demonstration and test box only**, on synthetic or public data, never PRODUCTION and never a
   ring 1 site. Each run goes through the integrator with its estimate.
6. The page's questions 1 to 7 are answered in this decision's signed version; where an answer moves a card (question
   2 moves 10B-20; question 3 moves 17 cards; question 4 adds R1-4), the page is amended in the same pull request.

## What it changes in earlier records

- D-1070's "Ring 1" line under "The other rings" is replaced by point 2.
- Plan 10's decision 32 (a 32 GB consumer card at the first Japanese site) is read for ring 1 through question 3.
- Nothing else. Ring 0 is not changed by this decision (D-1070 rule 2).

## Where the wording comes from

The owner's ruling of 2026-11-23, "ring 1 is the first real sites, supervised", naming CGMH and the Japanese group,
as relayed to lane R1 in its brief; it is not on #639. The owner's ruling on owner data, #639 comment 7099836527.
The ring 1 page's sections 4, 7 and 8.

## Used by

The integrator's schedule after ring 0's proof; the ring 1 page; every lane's choice of the next card in ring 1.

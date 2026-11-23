# D-1271 Ring 1 is the MVP, and plan 11 is its page (draft for the owner to sign)

- **Task:** lane R1, plan 11 (`docs/plan/48-plan-11-2026-11.md`); the number is from lane M's block, given for this
- **Date:** 2026-11-23 (drafted)
- **Status:** **draft, not in force.** It takes effect when the owner signs it. Until then nothing below binds a
  lane beyond the rulings on #639 it records.

## Ruling (as drafted)

1. **Ring 0 and ring 1 together are the new ring 1, the MVP** [#639 7108087457]. Plan 11 is its page, with D-1070's
   four parts (does; does not; proved by; its cards). When signed, ring 1 is confirmed and frozen under D-1070's rule
   of the rings.
2. **Ring 1 is built in steps S0 to S8**, in this order: S0 ring 0 finished in full; S1 install first and every code
   system preloaded; S2 the clinical database design and the patient profile; S3 CGMH's and 医誠会's sources on
   synthetic stand-ins; S4 Medplum; S5 the EDC; S6 every public Lind figure met or beaten; S7 every hardware profile
   and Windows; S8 the whole test set three times in a row. Each step's cards are plan 11's section 4.
3. **A step is done only when the B200 walks it from a fresh release bundle and every line passes**, its walk repeats
   every earlier step, and its lines are on #639 with their logs. Nothing counts as done on CI or a lane's container
   alone. Every function is installed by a hospital person, runs, and is validated against its stated figure on
   public or synthetic sets, with the evidence filed [#639 7108012824].
4. **The sites** are Chang Gung Memorial Hospital (CGRD-type SQL views; ICD-10-CM, NHI order codes, LOINC, its own
   codes; Traditional Chinese) and 医誠会 (Iseikai), plan 10's first site, reading the SS-MIX2 storage of its chart
   vendor SSI (Software Service, Inc.; WHO ICD-10, JJ1017; Japanese) [#639 7107908330, 7108195110].
5. **Ring 1 integrates Medplum fully**, in place of HAPI FHIR, with a same-nights-same-results test on both stores
   for each card. This overrides BD-01 for ring 1 [#639 7107908330, 7108195110]. A CQL evaluator is kept beside it
   (plan 11 R1-M3).
6. **The EDC is in ring 1**, integrated as plan 11 section 8 defines it (forms, pre-fill, write-back, audit), on the
   REDCap door and on EDC-lite. No REDCap source, SQL or text is in this repository [#639 7108012824].
7. **Ring 1 meets or beats every public Lind figure, like with like** [#639 7107908330, 7108816601]. One metric,
   Lind's whole-system per-criterion agreement, measured on our whole system (coded rules and the model pair, product
   path, installed box) per (patient, criterion), with the label mapping written first, on a synthetic hospital with
   coded data and notes whose gold labels are made blind (plan 11 section 10.0, card R1-L0, the first card of S6).
   Every other product is compared only on its own definition and set; a row whose definitions differ is marked "not
   comparable".
8. **No patient data leaves a site.** Real data is read only on the hospital's own machine or the owner's own;
   only counts files of plan 11 section 7's form leave, sent by a named person [#639 7099836527].
9. **A cloud GPU VM is a demonstration and test box only**, on synthetic or public data, never PRODUCTION and never a
   site; each run goes through the integrator with its estimate.

## The owner's answers to plan 11's choices [#639 7116870102]

- **(a)** The machines are evaluated, not fixed: card R1-H1 compares the 32, 48, 96 and 128 GB profiles and Windows
  and recommends one for each site; a profile passes whatever a smaller one passes.
- **(b)** An outside penetration test of the installed box before each site's first real-data run, its findings fixed
  first (R1-P1).
- **(c)** No small-count suppression: use is internal to the hospital, with IRB approval.
- **(d)** At least 94.8 % agreement by Lind's definition, per language: ten per cent fewer errors than Lind.

## What it changes in earlier records

- D-1070: its ring 0 page becomes step S0 of ring 1; its line "Ring 1: one Japanese hospital, supervised" is
  replaced by points 1 and 4; its rings 2 to 4 stand.
- BD-01 (`docs/plan/design/00-baseline-decisions.md`): its "HAPI FHIR stays; Medplum after the pilot" is replaced for
  ring 1 by point 5.
- Plan 10's cards keep their ids and are read by step (plan 11 section 5).

## Where the wording comes from

The owner's rulings of 2026-11-23 on #639: 7107908330, 7108012824, 7108087457 and 7108195110, relayed by the
integrator; the owner's ruling to compare like with like, 7108816601; the owner's answers to the four choices,
7116870102; the owner's data rule, 7099836527.

## Used by

The integrator's schedule; every lane's choice of the next card; the B200 walk of each step.

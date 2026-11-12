# D-375 Catalogue gaps: the instrument copyright register, phenotype status, Athena licence acknowledgements

- **Task:** T-307 (TB-PLAN-06 §6.2.6, "shrunk to what PR #80 leaves"; scope in
  `docs/reviews/2026-11-09-assessment-and-tasks.md`, "T-307 Catalogue gaps and the instrument copyright register")
- **PR:** this branch (`agent/T-307-catalogue-gaps`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-180 (the catalogue's verification and licence notes), D-353 (the catalogue as data and the
  storable gate), D-301 (vocabulary releases), STD-034 (the Athena allow-list)
- **Replaces:** the reservation D-248 of the old card (voided; this card took D-375)

## Context

PR #80 already did most of the old card's catalogue work: the seven LOINC look-ups (DLCO, anti-MDA5, KL-6, PD-L1
CPS, FeNO, TRAb, PIVKA-II), the JLAC10 fit flags and the ICD-10-CM concept sets of the OHDSI phenotypes. T-107 reads
the items and holds the storable gate. Left: a register of what each licensed instrument's terms say, a way for a
site with a licence to keep more, a status per phenotype, and a record of the licences an Athena load brings.

## Decision

1. **The register is data.** `catalogue/instruments.csv` lists the 18 instruments of the card with holder,
   `licence` (`needed`, `free-with-terms`, `unclear`), what the terms say, the public source and the date read, and
   the catalogue items it covers. EQ-5D, SF-36, FACT, EORTC and PROMIS have no catalogue item: nothing of them can be
   stored until an item is added. `tb_common.instruments` reads it and refuses a row that names an unknown item or an
   item another instrument already holds. TrialBox asks nobody for a licence; the register reports public terms only.
2. **The catalogue's `storable` stays the default.** The register does not change `items.csv` (the CDR keeps its
   global and box scores, as D-180 recorded).
3. **A site switch needs a licence reference.** A switch raises what the site keeps of every item of one instrument
   (one setting `instrument_switches` of the site set-up store). With an empty or blank reference it is refused, and
   the console audits the refusal (`instrument.switch_refused`); an accepted switch is an `instrument.switch` event
   with actor, level and reference. Going back to the catalogue's level needs no reference; going below it is
   refused. A stored switch without a reference is never honoured.
4. **The gate reads the switches.** Chart extraction calls `instruments.refused_fact`, which is T-107's
   `catalogue.refused_fact` unless the site switched that instrument to a level that keeps item answers.
5. **Phenotype status.** `tb_common.phenotypes` loads all 164 phenotypes. The seven first definitions (RA, gout,
   dementia, epilepsy, lung cancer, CKD, type 2 diabetes) are `synthetic`: their ICD-10-CM sets find exactly the
   planted patients of the synthetic hospital and none of the near misses (`phenotype_status.csv`). The other 157
   are "not validated here". The status never changes `may_exclude` (unknown never excludes).
6. **Athena licence acknowledgements.** `load_athena` records one `tb_vocab_release` row `LICENCE:<vocabulary>` per
   licensed vocabulary of the bundle (LOINC, UCUM, RxNorm, RxNorm Extension, ATC) with a summary of its terms, the
   bundle's sha256 and who loaded it. They are not compile releases. `python -m omop vocab status` lists them.

## Not done here

A page for the phenotypes and running them over the OMOP store (T-204, T-308); the question whether the CDR's
licence should lower its `storable` (an owner question); the ATC permission question (T-617b).

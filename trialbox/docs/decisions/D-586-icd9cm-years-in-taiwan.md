# D-586 A Taiwanese diagnosis from the ICD-9-CM years says so: it is never tagged ICD-10-CM

- **Task:** NEW-STD-1 (finding STD-001 of the deep review of 2026-11-12, `docs/reviews/2026-11-12-deep-review/11-standards.md`; plan v7.2 section 5, lane E, wave 1)
- **PR:** this branch (`agent/NEW-STD-1-icd9cm-years`)
- **Date:** 2026-11-12
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-130 and the coverage rule (`matching/coverage.py`: a diagnosis in a code system no value set
  reads makes a FALSE inclusion `unknown`, never "absent"), T-619a (the TW Core ICD-10-CM editions by date)

## Context

Taiwan's National Health Insurance coded diagnoses in ICD-9-CM until 2015-12-31 and in ICD-10-CM from 2016-01-01. The
canonical diagnosis table has one code column and no code-system column. Every row was emitted as ICD-10-CM and, with
TW Core, tagged with the ICD-10-CM 2014 edition: `714.0` of 2014 became an ICD-10-CM code. CGRD holds records from
2001. A history criterion could see nothing before 2016, and ICD-9-CM V and E codes share shapes with ICD-10-CM
chapters (`V58.69`).

## Decision

1. **The site says when its ICD-9-CM years ended.** A site mapping carries `params: {icd9cm_before: "2016-01-01"}`
   (the two Taiwanese site templates ship it). A diagnosis dated before that day carries the code system
   `http://hl7.org/fhir/sid/icd-9-cm` and no ICD-10-CM coding and no TW Core edition; one dated from that day on is
   ICD-10-CM as before.
2. **A row may say its own system.** The optional canonical column `diag_code_system` (`icd9cm` or `icd10cm`) wins
   over the date. Any other value in it gives the diagnosis no code.
3. **Unknown stays unknown.** With the parameter set, a diagnosis with no date and no `diag_code_system` gets no
   code: nobody can say which edition it is. A diagnosis with no code, or in ICD-9-CM, is what the coverage rule
   already reads as "a code no value set can read": a FALSE inclusion becomes `unknown` with the rows as evidence.
4. **A mapping without the parameter is unchanged.** The shared base mapping and the synthetic sites declare none:
   their diagnoses are ICD-10-CM whatever the date, and no golden moves. (The synthetic hospitals have no ICD-9-CM
   era by construction.)
5. Two small additions to the mapping language carry this: a condition `any: [[...], [...]]` (one of the lists
   holds), and a date bound written as `{param: <name>}` (a parameter the mapping does not set makes `date_before`
   false and `date_from` true).

## Not in this card (the second half of NEW-STD-1)

- **The ICD-9-CM to ICD-10-CM map.** An exclusion on a diagnosis of the ICD-9-CM years still cannot fire: no value
  set reads ICD-9-CM, and a FALSE exclusion keeps the patient. The repair is an ICD-10-CM coding beside the
  ICD-9-CM one wherever the CMS General Equivalence Mappings (public domain) map one to one. The full table is not
  in the repository (`mapping/mimic/tables/icd9_to_icd10cm.csv` is a sample); it belongs in the reference-data
  pack. Until then the diagnosis is honestly ICD-9-CM, which the coverage rule and a person can see.
- OMOP: `omop/vocab.py` knows no ICD-9-CM vocabulary; the row loads with its source value and no standard concept.
- Site survey question 37 gains the years (the survey is a handover document, lane D).

## Consequences

- A Taiwanese site that sets the parameter stops claiming ICD-10-CM for its older diagnoses.
- Inclusions on history become `unknown` (a person looks) instead of silently "not met"; exclusions on history
  stay silent until the map above lands. That is said here so nobody reads this card as the whole repair.

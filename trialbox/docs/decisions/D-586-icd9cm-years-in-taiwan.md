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
   (the two Taiwanese site templates ship it). A diagnosis keyed before that day carries the code system
   `http://hl7.org/fhir/sid/icd-9-cm` and no ICD-10-CM coding and no TW Core edition; one keyed from that day on is
   ICD-10-CM as before.
2. **The day the code was keyed decides** (`recorded_date`); the day of the diagnosis (`diag_date`) only when the
   row has no keyed day. A code keyed in 2019 for an illness that began in 2014 is an ICD-10-CM code.
3. **A row may say its own system.** The optional canonical column `diag_code_system` (`icd9cm` or `icd10cm`) wins
   over both dates. Any other value in it gives the diagnosis no code; a site whose column spells the edition
   otherwise translates it in the table's `values:` map.
4. **Unknown stays unknown.** With the parameter set, a diagnosis with neither day and no `diag_code_system` gets no
   code: nobody can say which edition it is. A diagnosis with no code, or in ICD-9-CM, is what the coverage rule
   already reads as "a code no value set can read": a FALSE inclusion becomes `unknown` with the rows as evidence.
5. **A mapping without the parameter is unchanged.** The shared base mapping and the synthetic sites declare none:
   their diagnoses are ICD-10-CM whatever the date, and no golden moves. (The synthetic hospitals have no ICD-9-CM
   era by construction.)
6. **The parameter is checked when the mapping loads.** It must be a day written `YYYY-MM-DD` and a condition of
   the mapping must read it; anything else (another date form, a blank, a misspelt name) stops the mapping from
   loading, because the bound is compared as text and a wrong one moves every diagnosis to the wrong edition.
7. Two small additions to the mapping language carry this: a condition `any: [[...], [...]]` (one of the lists
   holds), and a date bound written as `{param: <name>}` (a parameter the mapping does not set makes `date_before`
   false and `date_from` true).

## What a site must know

- **After the parameter is set, one full load.** A delta night re-reads only rows that changed; diagnoses loaded
  before keep their ICD-10-CM tag until a full night or a back-fill re-reads them.
- **A diagnosis with no code counts in the night's validation sample** (`Condition.code` is required there). A site
  with many undated diagnoses and no edition column can pass the sample limit and have its night held: that is the
  signal to supply the column or the dates.

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
- Inclusions on history become `unknown` (a person looks) instead of silently "not met". Still silent until the
  map above lands: an exclusion on history, an inclusion written as "no history of" (the coverage rule reads
  positive atoms only), and the same two for a diagnosis that has no code. That is said here so nobody reads this
  card as the whole repair.
- Two readers match a diagnosis by its code alone, from before this card: `orchestrator/scenarios/facts.py` and
  `edc/prefill.py`. An ICD-9-CM `V58.69` can still meet an ICD-10-CM code there (sent to the integrator).

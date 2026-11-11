# Record of processing (処理の記録 / 個人資料處理紀錄)

| Field | Value |
| --- | --- |
| Document ID | TB-PRV-01 |
| Version | 0.1 (2026-11-11, T-318, D-411) |
| For | each hospital's privacy office; the IRB pack (TB-PRV-04) and the data-processing agreement point here |
| Status | Draft from the code on master and the record inventory (`docs/validation/record-inventory.md`). The hospital fills §3 or §4 on its own copy. |
| Source | TB-PLAN-05 WS-13.6; the data classes of `docs/plan/design/14-ethics-pack.md` §3; the record inventory R-01 to R-27 and O-01 to O-03; retention from `deploy/settings.example.yaml` and SECURITY §6 |

## 1. Parties and data classes

| Item | Value |
| --- | --- |
| Controller | the hospital (Japan head hospital; CGMH) |
| Processor | Aimedics, under the data-processing agreement; Aimedics never holds patient data (data-handling rule 1) |
| Where processing happens | only on the hospital's hardware: the appliance (Japan) or containers on the hospital's shared B200 server (CGMH) |
| Transfers abroad | none |
| Automated decisions about a person | none: TrialBox decides nothing about a patient; a qualified person decides on every output (TB-IU-01) |

| Class | Meaning | Examples on the box |
| --- | --- | --- |
| D4 identified | directly identifies a patient | chart number in the pid map; the original note text before the scrubber |
| D3 pseudonymised | a pseudonym in place of the chart number; re-identified only with the key | clinical rows, scrubbed notes, candidate lists, summaries, the screening log |
| D2 de-identified | a registered transform, no reasonable means of re-identification by the recipient | none in the pilot |
| D1 confidential, no patient data | not public, no patient-level data | counts with small cells suppressed, configuration, logs without patient data |
| D0 public | may be published | trial registry text, documentation |

## 2. Processing activities

| Id | Activity | Purpose | Classes | Stores (record inventory) | Who reads | Retention |
| --- | --- | --- | --- | --- | --- | --- |
| P-01 | Nightly ingest from the hospital's systems; pseudonyms made at the door | build the research repository from the hospital's own records | D4 in, D3 stored | R-24 pid map; R-25 OMOP rows and lake snapshots | nobody reads the pid map directly; the adapter writes it | snapshots 3 nightly and 36 month-ends; OMOP rows replaced by each load |
| P-02 | Reading notes with a local language model | find the passages a criterion rests on | D3 | R-18 jobs; O-03 model traces | investigator, coordinator (through the pages) | traces 7 days in PRODUCTION; job outputs `outputs_days` (365) |
| P-03 | Feasibility counts | estimate how many patients may meet a study's criteria | D3 in, D1 out | R-18, R-21 | investigator, coordinator, CRO (counts only) | outputs 365 days |
| P-04 | Candidate lists and the not-matched list | lists for the investigator's review, with passages | D3 | R-18, R-22 | investigator, coordinator of the study | outputs 365 days; review traces kept |
| P-05 | Chart-number reveal | contact a candidate through the treating physician | D3 to D4 for one patient | R-12 (every reveal audited) | investigator and coordinator with reveal rights for the study | the reveal event kept with the audit |
| P-06 | Patient summaries with citations | prepare a screening visit | D3 | R-18 | investigator, coordinator | outputs 365 days |
| P-07 | Screening log, consent and enrolment records | the trial's own records | D3 | R-03, R-05, R-06, R-10, R-11 | PI, coordinator, trial office | kept (essential records) |
| P-08 | EDC prefill drafts | values for a qualified person to confirm before they go to the sponsor's EDC | D3 | R-08, R-16 | PI, coordinator | kept |
| P-09 | Mail and notices | send lists and the morning mail inside the hospital | D3 (links, not attachments, by default) | R-26 | named internal recipients | mail log 5 years (Japan), 7 years (Taiwan) |
| P-10 | Audit and export ledger | show who did what and what left the box | D3 pseudonyms, no clinical values | R-01, R-02 | data steward, site administrator | audit 10 years on the box; archive never deleted |
| P-11 | Backups | restore after a fault | D3 and D4, encrypted to a key the box does not hold | the backup target on the hospital network | hospital IT (the private key) | 3 nightly, 36 month-ends |
| P-12 | Support | fix faults | D1 only: the PHI-free support bundle (D-405) | none on the box | Aimedics tier 2 and 3 | as the ticket |
| P-13 | Steward's note access | check mapping and conflicts; run the opt-out | D3 | R-20, R-23 | data steward | as R-25 |
| P-14 | Planned, not built: patient profiles, the vector index of notes, the clinician role | see the DPIA (TB-PRV-02 §2) | D3 | not yet | not yet | assessed before each is turned on |

The opt-out register (R-06) removes a patient from P-02 to P-06 and P-13. Until the opt-out worker of T-206a and
T-206b passes its test, the notice of TB-PRV-05 is not published (REG-009).

## 3. Japan head hospital (the hospital fills)

| Item | Value |
| --- | --- |
| 利用目的 published where (URL, notice board) | |
| Data source (SS-MIX2 export, a CSV export) | |
| Years of records in the repository | |
| Departments whose investigators may reveal across departments | |
| Retention changes from §2 (with the reason) | |
| Privacy office comment, date | |

## 4. CGMH (the hospital fills)

| Item | Value |
| --- | --- |
| CGRD tables read (from the site survey) | |
| IRB approval that covers the use (number, date) | |
| Platform team for the shared B200 server | |
| Retention changes from §2 (with the reason) | |
| Privacy office and CISO's office comment, date | |

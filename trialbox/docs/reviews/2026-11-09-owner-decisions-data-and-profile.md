# Owner decisions: patient data, profile, roles and consortium (2026-11-09)

Changfu's answers in the 2026-11-09 session, made while reading:

- the design proposal (`2026-11-09-design-patient-data-and-roles.md`)
- the independent review (`2026-11-09-standalone-db-vector-profiling-review.md`)
- his own concept (`2026-11-09-owner-patient-profiling-concept.md`)

These decisions govern the OMOP, profile and vector work. They will be entered as a numbered decision in DECISIONS.md when that work's first PR merges.

## Scope and roles

| Topic | Decision |
|---|---|
| Scope | A full clinical repository now, used first for trials. The later Anamnesis layers are built on the same base. |
| Who is in | Structured facts for every patient in the hospital feed. Written profiles for the departments that take part. |
| History | **All history now.** Every year the hospital has goes in from the start: structured data and notes. *(Overrides the review's 5-year recommendation.)* |
| Data steward | Named hospital staff at each site. Aimedics never holds patient data. |
| Steward and notes | **The steward may read all free-text notes at any time.** Every view is audited. *(Overrides the review's "when needed".)* |
| PI | Sees everything for their own studies' patients, chart numbers included (D-143). |
| Treating physicians (clinician role) | Have access from the start. "Own patients" means seen or ordered for in the last 24 months, or booked in the next 90 days. Each site's privacy office can add the inpatients of the physician's ward. |
| Profile access | Steward: all patients. PI: their own studies' patients. CRC: their study's patients. Clinician: their own patients. Every view is audited and kept 10 years. |
| Monitors (CRA) | SDV access to enrolled subjects only, limited to the cited record items. |
| Break-glass | The user gives a reason and a second person on the steward/admin rota confirms. Time-limited and audited. |

## Whole-hospital screening, sub-investigators and referral

The aim of a study is to screen the **entire database** for potential patients. Candidates may belong to a sub-PI or to another treating physician, so the PI needs to see them, choose whom to include, and ask for a referral.

| Topic | Decision |
|---|---|
| Sub-investigators (sub-PI) | Rights come by delegation. The PI adds sub-PIs to the study's delegation log (ICH E6 style) and ticks the tasks each may do: screen and see candidates, mark Approach, request referrals, enter data. Only the PI approves criteria and signs off. Every action records who did it. |
| Candidate view | The PI and delegated sub-PIs see **everything needed to decide** about any candidate the study's screen finds anywhere in the hospital: identifiers, the cited record and profile, and why the candidate fits or doesn't. Each view is logged with the study and purpose, and is rate-limited. |
| Referral | The treating physician is asked first. The PI or sub-PI sends a referral request in TrialBox. The treating physician gets it on the console and by mail, sees why the patient may fit, and answers: *agree to introduce*, *decline with a reason*, or *discuss*. The PI contacts the patient only after agreement. Each step is logged and counted in the screening log. |
| Referral target | **The treating physician may be unknown to TrialBox.** The hospital data that reaches the box may carry no provider, or an outdated one. The PI usually finds the physician in the real EMR or through their own working relationships. So: (1) where the data names an attending physician, TrialBox only *suggests* that physician, and the PI confirms or changes the choice; (2) where it doesn't, the PI enters the physician from a staff directory the steward maintains, or types a name; (3) the PI may also choose "arranged outside TrialBox" (by phone, in person or through the EMR) and record the outcome afterwards; (4) the steward's department contact list is the last fallback. A referral never stalls because a field is missing. The screening log records each referral's route and outcome. |

## Site operations (after the clinical-operations assessment)

| Topic | Decision |
|---|---|
| Treating doctor's answer to a referral | At the first site, **the CRC records it.** The CRC asks the doctor by phone, in person or by EMR message, then records the answer. The doctor needs no account. Mail with answer buttons and doctor accounts come later. |
| IRB approval and consent-form version before Approach | **A warning, not a hard gate.** TrialBox warns if the IRB approval date or the current ICF version is missing or expired, but still lets the user mark Approach. Each override is logged. |
| Delegation log | The trial office's signed log stays the official record. TrialBox holds a copy that grants rights in the system (screen, approach, refer, enter data), with training dates. The two are compared every month. |
| Opt-out | Kept by the office. The research office or the steward records each patient's opt-out in TrialBox. That patient is then removed from screening, profiles, vectors and future exports, and the removal is logged. |

## Data model

| Topic | Decision |
|---|---|
| Core | OMOP CDM v5.4 in Postgres is the store of record. FHIR (JP Core, TW Core) is used only for exchange. Screening runs on a lake exported from OMOP with the same table names, so the counts stay identical. |
| Vectors | pgvector in the same Postgres. |
| Specialties | All subspecialties, in one generic model. Items are mapped to standards through the clinical item catalogue (LOINC, OMOP, OHDSI Phenotype Library, CDISC QRS, NIH CDE). The first templates are rheumatology, neurology, oncology and nephrology/general internal medicine. |
| PI spreadsheets | Trusted as coded, with the source shown. |
| Sheet vs feed disagreement | Recorded as a conflict. The item counts as unknown until the steward, or the PI for their own study, picks a value. |
| Conflicts | Resolved by the steward for the whole database, or by the PI for their own study. While unresolved, the item is unknown and never excludes a patient. |
| Local code maps | Mapped by the steward. A PI of the specialty confirms the clinically important ones. |
| SNOMED CT | **Ask about a licence.** Aimedics would hold it for the product, and the consortium lead if the consortium buys its own. Get a quote now. Until then, ICD-10-CM plus the WHO ICD-10 bridge is the condition standard. |
| Consortium | Counts **and de-identified profiles** may leave a hospital, under IRB approval and a data-sharing agreement. Export defaults: project pseudonyms, dates shifted ±180 days, k = 5, no quotes, no vectors. A contract may only tighten these. Counts travel as signed files. The shared code-map registry is hosted at CGMH, and Aimedics ships it. |

## Profile

| Topic | Decision |
|---|---|
| Form | A wiki page per patient written by the model, with every sentence cited and verified. Physician annotations sit beside it. A machine-readable twin (JSON) and pgvector come with it. |
| v1 layers | Cited record, timeline, phenotype, eligibility, personal lab setpoints, gap finder, similar patients. |
| SaMD and clinicians | **Clinicians see the setpoint and gap layers, clearly labelled "research use, not for diagnosis".** *(Overrides the review's "PI and steward only until a device-qualification view".)* A written device-qualification view should still be prepared. |
| Physician annotations | A signed structured entry counts as confirmed data. Free text is read by the models as a note. Neither can exclude a patient silently: every exclusion is listed on the "excluded and why" page. |
| Narrative | Written by the judge model at night, in the site's language, with English on request. Nobody edits it. Corrections are made by annotating or by fixing the data. The model abstains when fewer than 95 % of its sentences can be cited. |
| Freshness | Facts and the twin update within minutes. The narrative updates nightly, or on request for one patient. |
| First build | Study patients first, at night only. |
| Gap rules | Approved by a PI of the specialty. A rule goes live after at least 7 of 10 sample hits are confirmed. Rules proposed by a model are allowed only after a prompt-injection and false-positive test suite passes. |
| Patients like me | Structured catalogue items are matched first, then note embeddings re-rank the results. Every match is explained. |
| Embeddings | bge-m3 is the default. Qwen3-Embedding-0.6B will be tested on our ja/zh-TW data. All note types across the history are embedded. Vectors are included in backups. |
| GPU cost | One paid test (about US$15–30) on the RTX PRO 6000 VM measures the profile cost before the build at scale. The VM is stopped and verified afterwards. |

## Hardware and order

- First hospital box: 2 TB disk and 128 GB RAM, confirmed per site.
- Order: Wave 1 and gate G1 (the 50,000-patient run) first. The OMOP, catalogue and profile work runs in parallel and merges only after Wave 1.

## Accepted as recommended

The owner accepted every other recommendation in §6 of `2026-11-09-standalone-db-vector-profiling-review.md`, including:

- profile versions kept 10 years
- an open conflict blocks the "ready" state
- setpoints are shown as numbers with a "check" mark on screening values, never as alerts
- the counts transport is a signed file
- the first export is reviewed by both the exporter's privacy office and the lead site
- consortium registry work starts now

Where a recommendation conflicts with an overriding decision above, the decision above wins.

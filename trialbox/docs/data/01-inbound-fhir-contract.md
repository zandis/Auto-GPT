# DATA §1 part: the inbound FHIR contract

This is what TrialBox reads from FHIR R4. It is the interface contract of `--source fhir_bulk`, and the same reading
applies to the snapshot the adapter writes from any other source. The lake (`services/lake/flatten.py`) and the
OMOP store (`services/omop/load.py`) use one reader, so both paths read the same thing (T-616, D-400). The table in
code is `lake.flatten.READ`.

| Resource | Elements read | Lake table |
| --- | --- | --- |
| Patient | `birthDate`, `gender` (male, female; anything else is unknown), `deceasedDateTime`, `deceasedBoolean` | `patient` |
| Practitioner | `identifier[0]`, `name[0]` | `practitioner` |
| Encounter | `status`, `class`, `serviceType`, `subject`, `participant[0]`, `period` | `encounter` |
| Appointment | `status`, `serviceType[0]`, `start`, `participant` | `appointment` |
| Condition | `code` (first coding with a code), `subject`, `clinicalStatus`, `verificationStatus`, `onsetDateTime`, `recordedDate`, `encounter` | `condition` (a suspected one: `site_fact`) |
| Observation | `status`, `code` (LOINC first), `subject`, `category[0]`, `effectiveDateTime`, `effectiveInstant` or `effectivePeriod.start`, `valueQuantity` (with its comparator), `valueString`, `valueCodeableConcept`, `component` | `observation` |
| MedicationRequest | `status`, `subject`, `medicationCodeableConcept` or `medicationReference`, `authoredOn`, `dosageInstruction[0]`, `dispenseRequest` | `medication` |
| MedicationStatement | `status`, `subject`, `medicationCodeableConcept` or `medicationReference`, `effectivePeriod` or `effectiveDateTime`, `dateAsserted`, `dosage[0]` | `medication` |
| Medication | `code`, through a `medicationReference` | (the order's drug) |
| Procedure | `status`, `code`, `subject`, `performedDateTime` or `performedPeriod.start` | `procedure` |
| DiagnosticReport | `status`, `code` (LOINC first), `subject`, `effectiveDateTime`, `conclusion` | `report` |
| DocumentReference | `status`, `docStatus`, `type`, `subject`, `date`, `content[0].attachment.data`, `context.encounter[0]` | `document` |
| Consent | `patient`, `status`, `provision.type`, `dateTime` | `consent` |
| Claim and ClaimResponse | `patient`, `created`, `item[0].productOrService`; `request`, `disposition` or `outcome`, `preAuthPeriod` | `claim` |

Every resource also gives its `id` and its `meta` (the row provenance and the basis tag, DATA-010 and D-135).

**Rules of reading.**

- **Death.** `deceasedDateTime` gives the date. `deceasedBoolean: true` with no date still marks the patient
  deceased (`patient.deceased`). The base cohort of every compiled ruleset leaves out a deceased patient with no
  date at every index date; a patient with a date is left out from that date on, as before. `deceasedBoolean:
  false` is no evidence and reads as unknown. In OMOP, a death with no date gets a `death` row dated the night it
  was loaded (the latest it can be), with type concept `2000000013` (TB-SHARED `death-date-imputed`); the lake
  reads that date back as unknown (STD-013).
- **The drug.** `medicationCodeableConcept` first. Otherwise `medicationReference` names a Medication contained in
  the resource (`#id`) or one in the same snapshot (`Medication/id`); its `code` is the drug. A reference that
  names no Medication keeps the record with its drug unknown. The ATC code is the coding whose system contains
  `atc`; the first other coding is the national code (STD-014).
- **The therapy period** of an order, in this order: `dosageInstruction[0].timing.repeat.boundsPeriod`, then
  `dispenseRequest.validityPeriod`, then `authoredOn` plus `dispenseRequest.expectedSupplyDuration` (days or weeks
  only). A statement's period is its `effectivePeriod` (STD-012).
- **Times.** A date-time with an offset or `Z` is the same instant in the site's zone (`site.tz`). A source column
  mapped with an offset keeps that offset in the snapshot; only a naive time takes the mapping's `tz` (STD-015).
- **Status.** The states of D-275 apply: an entered-in-error, cancelled or not-done record is not a fact. For a
  MedicationStatement, `not-taken` and `intended` are not facts either; `unknown` keeps the record without a date.
- **Presence words.** A LOINC-coded Observation whose `valueString` is a presence word (陽性, 陰性, 未檢出,
  Non-reactive, 2+) is read as the LOINC answer `LA6576-8` Positive or `LA6577-6` Negative, as the mapped sources
  read it (D-334). The text stays in `valueCodeableConcept.text`, and the result is tagged
  `urn:trialbox:value-source|presence-word`. A held or borderline word (判定保留, ±, equivocal) stays text, and
  screening reads it as unknown. The audit entry of the night counts them (`presence_words_read`; D-418).

**Not read.** AllergyIntolerance, MedicationAdministration, MedicationDispense, Immunization, Specimen and any other
type; and any element not in the table (for example `Condition.abatement[x]`, `Condition.onsetPeriod`,
`Observation.interpretation`, `Observation.note`, extensions, narrative `text`). The ingest report counts them:
`fhir_unread` in `ingest_report.json` gives, per resource type, how many resources carry each element that is not
read, and `*` for a type that is not read at all. It holds element names only, never values. A count that is not
zero is not an error. It shows the steward what the feed carries that screening does not use.

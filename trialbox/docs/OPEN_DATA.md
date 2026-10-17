# Open-data end-to-end test

TrialBox is tested mostly on synthetic hospitals (`tools/make_fixtures.py`). This test adds one run on open,
real-world-like data. It uses the public MIMIC-IV FHIR demo (100 de-identified ICU patients) and two real
ClinicalTrials.gov trials, and runs the same code the appliance runs: adapter (`fhir_bulk`) → lake (DuckDB) → FEAS.
It runs in process, with no compose stack and no network once the data are fetched.

```
make open-data-e2e                       # fetch (sha256-verified) + run; writes .cache/open_data/report.{json,md}
python -m pytest -m slow tests/integration/test_open_data_e2e.py   # the same run as a test (skipped without data)
```

## 1. Datasets and licences

| Dataset | Use | Licence | Where |
| --- | --- | --- | --- |
| MIMIC-IV Clinical Database Demo on FHIR v2.1.0 (PhysioNet) | patients, encounters, ICU stays, diagnoses, labs, medication orders, procedures | Open Data Commons Open Database License v1.0 (ODbL) | downloaded by `tools/fetch_open_data.py` into `.cache/open_data/mimic-iv-fhir-demo/` (gitignored, **never committed**) |
| ClinicalTrials.gov API v2 records NCT04157751, NCT02568722 | eligibility text the rulesets are written from | public registry data (U.S. National Library of Medicine) | `tests/fixtures/open_data/ctgov_<NCT>.json` (with retrieval date; refresh with `tools/fetch_open_data.py --ctgov`) |

`tools/fetch_open_data.py` downloads only the files the pipeline reads:
- Patient, Encounter, EncounterICU, Condition, ObservationLabevents, MedicationRequest, Medication, MedicationMix,
  Procedure, ProcedureICU;
- `LICENSE.txt`.

Each file is checked against the release's `SHA256SUMS.txt`, and a mismatch aborts the fetch.

**NOTICE.** This test uses the MIMIC-IV Clinical Database Demo on FHIR, made available under the Open Data Commons
Open Database License v1.0 (https://opendatacommons.org/licenses/odbl/1-0/). Cite it as:
- Bennett A, Ulrich H, Wiedekopf J, Szul P, Grimes J, Johnson A. MIMIC-IV Clinical Database Demo on FHIR
  (version 2.1.0). PhysioNet (2025). RRID:SCR_007345. DOI (latest version) 10.13026/vphg-y548.
- Bennett AM, Ulrich H, van Damme P, Wiedekopf J, Johnson AE. MIMIC-IV on FHIR: converting a decade of in-patient
  data into an exchangeable, interoperable format. *J Am Med Inform Assoc* 2023;30(4):718–25.
  https://doi.org/10.1093/jamia/ocad002
- Johnson AEW, Bulgarelli L, Shen L, et al. MIMIC-IV, a freely accessible electronic health record dataset.
  *Sci Data* 2023;10:1.
- Pollard T, Moody BE, Lehman L, et al. PhysioNet as a global platform for biomedical research. *Nature Health*
  (2026). https://doi.org/10.1038/s44360-026-00096-z (the standard PhysioNet citation requested on the release page).

The derived lake, reports and mapped NDJSON are produced locally under `.cache/` and are not redistributed. If you
publish a database derived from the demo, the ODbL share-alike terms apply to it.

## 2. What runs

1. **Normalisation** (`services/adapter/mapping/mimic/normalise.py`). MIMIC-on-FHIR is FHIR R4, but its code
   systems and dates are MIMIC-specific. The normaliser streams the release, one resource at a time, into the
   `fhir_bulk` layout. Every mapping is table-driven, with the tables in `services/adapter/mapping/mimic/tables/`:

| Table | Maps | Scope |
| --- | --- | --- |
| (rule) | `mimic-diagnosis-icd10` `I5023` → ICD-10-CM `I50.23` | all ICD-10 diagnoses |
| `icd9_to_icd10cm.csv` | `mimic-diagnosis-icd9` → ICD-10-CM; the ICD-9-CM code is kept as second coding | the concepts the two rulesets use (CMS GEM forward targets); other ICD-9 codes stay ICD-9-CM |
| `labitem_to_loinc.csv` | `mimic-d-labitems` item id → LOINC + UCUM unit; the MIMIC item id becomes the lake's `local_code` | 12 common chemistry/haematology items (the demo has no LOINC codes) |
| `drug_to_atc.csv` | MIMIC drug name (whole word, case-insensitive; mixes by ingredient names) → ATC | loop diuretics and a few cardiometabolic drugs |
| `icu_item_to_snomed.csv` | ICU charted procedures (`mimic-d-items`) → SNOMED CT | CRRT, haemodialysis, invasive ventilation |
| (rule) | ICD-9 / ICD-10 procedure systems → ICD-9-CM / ICD-10-PCS | all procedures |
| (rule) | hospital service (`MED`, `CMED`, …) → department code; ICU stays → department `ICU` | all encounters |

   The normaliser also does the following:
   - **Dates.** It gives each diagnosis the start of its encounter as `recordedDate`, because MIMIC diagnoses carry
     no date.
   - **Elements.** It trims resources to the SPEC §3.1 elements. Lab events whose item has no LOINC row are not
     loaded (about 80 k of the 108 k events), and no criterion could reference them.
   - **Timeline.** It moves each patient's timeline into the FEAS lookback. MIMIC dates are shifted per patient
     into 2100–2200, so the normaliser moves every date of a patient by the same whole number of days. That puts
     the start of the patient's last encounter at a deterministic, hash-chosen day between 2023-11-14 and
     2026-09-10. Ages and intervals within a patient are kept; calendar dates, seasons and weekdays are not real.
2. **Ingest** (`adapter.pipeline.run_ingest`, source `fhir_bulk`). This step pseudonymises ids with a fixed demo
   key, writes the NDJSON snapshot, runs the structural validation sample and rebuilds the lake. The validation
   error rate is reported but does not gate the run, because MIMIC resources are not TW Core (for example,
   Encounter.participant and Condition.clinicalStatus are missing).
3. **Rulesets** (`tests/fixtures/open_data/rulesets/{EMPULSE,STARRT-AKI}`). These are hand-written Criterion IR,
   ValueSets and a manifest carrying `nct_id`, `source_documents` and `source_last_update`, written from the cached
   registry text. The SQL is rendered at run time by the compiler's template generator; it is never written by
   hand. Criteria that structured data cannot decide are `note` or `human` class, so FEAS lists them but does not
   apply them. The manifests are `status: draft` because they did not go through the APPROVE loop.

| Trial | Structured (applied) | note / human (listed, not applied) |
| --- | --- | --- |
| EMPULSE, NCT04157751: empagliflozin in hospitalised acute HF (completed) | age ≥18; acute HF diagnosis ≤30 d; NT-proBNP ≥1600 pg/mL (≥2400 with AF); loop diuretic ≤30 d; excl. cardiogenic shock, PE/stroke/AMI ≤30 d, ACS/stroke/TIA ≤90 d, transplant/assist device/palliative/ventilation, eGFR <20 or dialysis, T1DM, ketoacidosis | LVEF documented (note), timing 24 h–5 d, stabilisation, further criteria, not volume overload (note), recent interventions, valve surgery planned |
| STARRT-AKI, NCT02568722: RRT timing in severe AKI (completed) | age ≥18; ICU stay ≤30 d; creatinine ≥1.13 mg/dL (F) / ≥1.47 mg/dL (M); creatinine ≥4.0 mg/dL; excl. K >5.5, HCO₃ <15, RRT ≤60 d, kidney transplant ≤365 d, CKD 5/ESRD, obstruction/RPGN/vasculitis/TMA/AIN | overdose needing RRT, no commitment to life support (note), clinician-mandated immediate or deferred RRT |

4. **FEAS** (`orchestrator.scenarios.feas_compute.compute`). The settings are run date 2026-10-01, snapshot
   2026-09-30, 36 month-ends and small cell 5. FEAS produces the funnel, unknowns, sensitivity variants
   (EMPULSE `egfr: 15,25`, STARRT-AKI `INC-04: 2,3` mg/dL), monthly incidence and the enrolment simulation. The
   test adds per-criterion counts on the same SQL: patients meeting each criterion alone at one or more month-ends.
5. **Invariants**, checked by `tools/open_data_e2e.py` and the test:
   - the funnel is monotone and no step exceeds the population;
   - every count is between 0 and the 100 patients;
   - prevalent ≤ final count, and the first-eligible months add up to the final count;
   - every released count is `<5` or a multiple of 5 (controlled rounding);
   - a second, independent ingest + FEAS gives byte-identical results (`results_sha256`).

## 3. Results (2026-10-17 run; `.cache/open_data/report.md`)

Exact counts are shown because the data are a public demo. TrialBox would release only the rounded column.

Population: 100 of 100 patients have an encounter in the lookback. Both runs passed every invariant and were
reproducible (`results_sha256` `eab5b4c6fe818530…`). Only the applied (structured) steps change the count.

| EMPULSE step (applied) | remaining released | remaining exact | met alone (exact) |
| --- | --- | --- | --- |
| INC-01 age ≥18 | 100 | 100 | 100 |
| INC-02 acute HF diagnosis ≤30 d | 15 | 17 | 17 |
| INC-06 NT-proBNP ≥1600 (≥2400 with AF) | <5 | 3 | 9 |
| INC-07 loop diuretic ≤30 d | <5 | 3 | 48 |
| EXC-01 cardiogenic shock | <5 | 2 | 5 |
| EXC-02 … EXC-10 (PE/stroke/AMI, ACS/TIA ≤90 d, transplant/MCS/ventilation, eGFR <20/dialysis, T1DM, DKA) | <5 | 2 | 10, 9, 39, 8, 1, 4 |

Sensitivity: eGFR cut-off 15 or 25 → `<5`; unknown-as-pass → 10.

| STARRT-AKI step (applied) | remaining released | remaining exact | met alone (exact) |
| --- | --- | --- | --- |
| INC-01 age ≥18 | 100 | 100 | 100 |
| INC-02 ICU stay ≤30 d | 80 | 78 | 78 |
| INC-03 creatinine ≥100 (F) / ≥130 (M) µmol/L | 20 | 22 | 28 |
| INC-04 creatinine ≥354 µmol/L | 5 | 7 | 10 |
| EXC-01 K >5.5, EXC-02 HCO₃ <15 | 5 | 7 | 2, 1 |
| EXC-05 RRT ≤60 d | <5 | 3 | 6 |
| EXC-06 kidney transplant ≤365 d | <5 | 3 | 0 |
| EXC-07 CKD 5/ESRD, EXC-08 obstruction/RPGN/vasculitis/TMA/AIN | <5 | 2 | 5, 1 |

Sensitivity: INC-04 at 2 mg/dL → 10; at 3 mg/dL → `<5`; unknown-as-pass → `<5`.

Mapping coverage on this run:
- diagnoses: 2313 ICD-10 converted, 139 ICD-9 cross-walked, 2054 ICD-9 left unmapped;
- labs: 26 905 of 107 727 lab events loaded with LOINC;
- medication orders: 644 of 17 552 with an ATC code;
- ICU: 140 ICU stays and 85 ICU procedures given SNOMED CT codes.

## 4. Limits

- **No free text.** The FHIR demo has no notes (no DocumentReference). Note-class criteria are therefore never
  judged and the RAG/judge path is not exercised. The funnel counts only structured criteria.
- **US codes.**
  - ICD-9/ICD-10-CM, ICD-10-PCS and NDC are US code systems; the appliance's NHI drug/order codes and TW Core
    profiles are not tested here.
  - The ICD-9 crosswalk covers only the concepts the two rulesets use (about 60 codes), so most ICD-9-era
    diagnoses stay unmapped (see `normalisation.unmapped_icd9_top` in the report).
  - The lab and drug tables are deliberately small; the ValueSets are explicit, abbreviated lists to review before
    any reuse.
- **Acute trials on month-end index dates.** FEAS evaluates the lookback's month-ends, so "current
  hospitalisation" is approximated as "in the 30 days before a month-end". Exclusions such as "RRT in the previous
  2 months" are then evaluated at the same month-end and can remove patients whose RRT belongs to the qualifying
  episode.
- **Not expressible in IR v1.** A relative creatinine rise (STARRT-AKI 2-fold arm), urine output (chartevents not
  loaded), drug dose and route, primary-diagnosis rank and BNP are not used. Each criterion's `fallback` field says
  so.
- **Synthetic calendar.** The re-anchored dates make the month-by-month incidence and the simulation a mechanics
  test, not an estimate.
- **Scale.** 100 patients, so most cells are small: the released funnel is mostly `<5`, which is the intended
  behaviour.
- **Runtime.** About 1.5 min per ingest + FEAS on a 4-core VM, and the test does two independent runs. It is
  marked `slow` and skipped when `.cache/open_data/mimic-iv-fhir-demo/` is absent, so CI without network passes.

# TrialBox data and integration

*Owner: Aimedics engineer. Status: living; changed in the same pull request as the code it describes. History: the git log of this file; the merge into eight documents is D-139.*

For hospital IT and the people who own the data. It says what TrialBox reads, how a site maps its data, how trial
data syncs with REDCap and spreadsheets, and which open data the tests use. Stores and services:
[Architecture](ARCHITECTURE.md). Laws: [Security §7](SECURITY.md#7-laws-a-site-must-check).

## 1. What the box reads

| Source | Reader | Country | Direction |
| --- | --- | --- | --- |
| CSV export from the HIS | `adapter run --source csv` | TW, JP | one way in |
| CGRD-type SQL views | `--source cgrd_sql` | TW | one way in |
| SS-MIX2 standardized and extended storage | `--source ssmix2` (`services/adapter/sources/ssmix2/`) | JP | one way in |
| FHIR bulk NDJSON | `--source fhir_bulk` | any | one way in |
| REDCap project | `services/rc_bridge` (API, no External Module) | any | two way |
| a PI's spreadsheet (CSV in UTF-8, Shift_JIS or Big5; XLSX) | data core sheet import | any | two way |
| FHIR bundle of QuestionnaireResponses | data core | any | in |
| charts one by one (text, Word, PDF, scans, pasted EMR text) | site set-up (`services/sitesetup`) | any | in, as *proposed* facts |

TrialBox never writes to a hospital record system (owner decision 2, 2026-11-08). The nightly ingest makes a FHIR
R4 snapshot with pseudonyms (`HMAC(site key, chart number)`) and rebuilds the lake; HAPI gets only new or changed
resources (D-122).

**SS-MIX2 (Japan).** The reader walks `<id[0:3]>/<id[3:6]>/<id>/<date>/<type>/`, keeps the newest message per
patient, type and order, and reads HL7 v2.5 in ISO-2022-JP or UTF-8: ADT-00/12/22/52 (patient, visits, class changes),
PPR-01 (標準病名 with the ICD-10 code, or `byomei_to_icd10.csv`), OMP-01/02 (orders) and OMP-11/12
(administrations) with YJ and ATC, and OML-11 (labs with JLAC10). Extended storage is read by folder kind (no
`_contents.xml` index yet); tables SS-MIX2 does not standardize come from `<root>/extended/<table>.csv` (D-122,
D-137). Output claims JP Core 1.1.0 and is validated on a sample at ingest, offline
(`services/adapter/validate/jpcore.py`).

**Code lists.** ICD-10-CM 2026 in full (98,186 codes, public domain) for lookups and family groupers. The licensed
Japanese lists (MEDIS 標準病名, JLAC10, YJ) are loaded by the site from its own licensed files
(`python -m adapter.licensed load --kind medis|jlac10|yj --file … --version …`, D-137); each release is kept with its
version, sha256 and who loaded it, and every load is audited. The demo rows are synthetic and marked `verify`.
The clinical item catalogue (scores, labs, findings and phenotypes mapped to LOINC, OMOP, OHDSI phenotypes and
CDISC QRS) is in `catalogue/`; code reads only its score definitions, through a generated file (§8); its design is
`docs/reviews/2026-11-09-clinical-item-catalogue.md`.

## 2. Mapping a site

1. Copy `services/adapter/mapping/templates/csv_site.yaml` (or `cgrd_sql_site.yaml`; Japan:
   `services/adapter/mapping/jp_core/ssmix2_site.yaml`) to the site's mapping file.
2. Fill in `tables:`: `source`, `rename` (local to canonical columns, `services/adapter/mapping/templates/CANONICAL.md`)
   and `values` (local to canonical codes). Copy and edit the lab lookup CSV.
3. Check it against a real export:
   `python tools/mapping_check.py --mapping <file> --source csv --path <dir>` (also `--source ssmix2`). It must show 0
   missing columns and 0 structural errors. It lists unmapped lab codes for the lab team, and the rows with no
   ICD-10 or ATC code.

No code change is needed for a new site. A code nobody can read is never a "no": the answer becomes unknown with
reason `unknown_code_system`, and the feasibility page counts those patients (D-130).

## 3. Trial data: the data core

TrialBox's own data lives in schema `datacore` of `trialbox_wf` (D-123, D-126):

- **Forms** are FHIR Questionnaires. A REDCap data dictionary or one of the seven built-in forms becomes one.
  Identifier fields of a dictionary are dropped.
- **Answers** are rows, one per study, record, event and field, with who changed it and when; every change is in
  `history`. FHIR QuestionnaireResponse is an export, made on request.
- **The record key** is one rule: the screening number first, else the pseudonym (the chart number turned into the
  HMAC pseudonym at import), else the row is refused and listed with its place in the source, never guessed.
- **Ownership** is per field: TrialBox or one source. A source-owned change is taken. A TrialBox-owned field is pushed
  when it changed. A different value on the other side is a **conflict**: listed once, never forced, closed by a
  person (keep TrialBox's or take the source's), and the trail kept.
- **Sync** runs at 03:00 and on a button. Pages: Sources, Conflicts, Forms; the same calls under `/api/v1`.
- **Exports:** CDISC ODM 1.3, REDCap CSV and XLSX (D-129). An ODM export re-imports into the REDCap simulator with
  every value equal (`e2e_simple` stage 10).

**REDCap.** Attach a project on the study's set-up page (guided; variable names are read from the dictionary). The
screening write-back fills three fields on TrialBox's own instrument (`tb_screen_date`, `tb_status`,
`tb_status_date`) and never a field REDCap owns; modes `off`, `existing`, `create`. A blank never erases a value
(`overwriteBehavior=normal`). The site's REDCap builder creates the instrument from the dictionary in
`services/rc_sim/fixtures/`. Evidence: `tests/unit/test_rc_writeback.py`, `tests/unit/test_datacore.py`,
`e2e_simple` stages 8 and 9.

## 4. Site set-up and imperfect data

The readiness page shows trial, patients and trial records as green, amber or red, with what is missing (D-131,
D-135). A site can start with a protocol and pasted charts only.

- **Proposed facts.** A fact a model reads from a chart is *proposed*, shown beside its quote, and goes only to the
  lake's `site_fact` table. The compiled SQL never reads it, so it can never count as met or exclude; a decided answer
  it could change becomes unknown (reason `proposed_fact`) until a coordinator confirms it with one tap.
- **Safe fixes** made automatically and listed: era and 民國 dates, full-width characters, units, merged cells.
  Everything else goes to a "please check" list.
- **Code mapping** once per site; patients from several inputs joined by pseudonym.

## 5. Integration scenarios

From the 2026-11-05 catalogue (full text, with sources: `spec/archive/INTEGRATION_SCENARIOS.md`):

| Scenario | Data flow | Status |
| --- | --- | --- |
| A. Full hospital EMR | nightly export or views, one way in | built: CSV, CGRD views, SS-MIX2, FHIR bulk |
| B. A PI's own registry | periodic import | built: REDCap and sheets, two way |
| C. Consortium, multi-site | per-site boxes, aggregate tables only | COHORT tables and merge; no DP |
| D. Manual entry, referral letters, scans | one chart at a time | built: chart upload and proposed facts; OCR wired but not run on a real scan |
| E. Staged (manual first, EMR later) and air-gapped | start small | supported: a site can start with charts only; offline updates |
| F. Imaging, check-ups, claims, wearables, cloud, SMO or CRO boxes, research zones | other feeds | not built |

Gaps from that catalogue still open: no TOTP in the console; no erasure path for an opt-out (a delta night drops what
the source deleted since D-149, but a patient's facts are not removed from kept snapshots); no SMART Backend Services
client for live FHIR Bulk (the reader takes NDJSON from disk); an IQ/OQ/PQ package is a document, not code.

## 6. Open and public data in the tests

| Data | Use | Licence | Where |
| --- | --- | --- | --- |
| Synthetic hospital (`tools.synth_hospital`) | every gate: JP and TW sites, notes in ja, zh-TW and en, planted findings | ours, all fictional | generated |
| Synthetic sites A and B (`tools/make_fixtures.py`) | unit and integration tests, 600 + 520 patients | ours | `tests/fixtures/` |
| SIGIR 2016 patient descriptions (TrialGPT) | the public site's English notes | US government work, public domain | `eval/criterion_ml/LICENSE.NCBI` |
| NTCIR-16 MedTxt-CR and MedTxt-RR | the public site's Japanese notes | CC BY 4.0 (Sociocom, NAIST) | fetched to `.cache/medtxt`, never committed |
| MIMIC-IV Clinical Database Demo on FHIR v2.1.0 | the open-data test | ODbL 1.0 | fetched to `.cache/open_data/`, never committed |
| ClinicalTrials.gov NCT04157751, NCT02568722 | open-data test rulesets | public registry | `tests/fixtures/open_data/` |
| TREC Clinical Trials 2021/22 | N-12 | NIST qrels, NCBI corpus | fetched by `tools/trec_ct_eval.py` |

The public site (`tools/public_site.py`) keeps every note verbatim; age, sex and diagnoses are derived from the text
by fixed rules; chart numbers, visit dates and staff are placed. Its `PROVENANCE.md` says which is which.
ClinicalTrials.gov records in the cassettes are fictional (`NCT990000xx`, titled `[SYNTHETIC]`).

**MIMIC notice.** The open-data test uses the MIMIC-IV Clinical Database Demo on FHIR under the Open Data Commons
Open Database License v1.0. Cite: Bennett A, Ulrich H, Wiedekopf J, Szul P, Grimes J, Johnson A. MIMIC-IV Clinical
Database Demo on FHIR (version 2.1.0). PhysioNet (2025). DOI 10.13026/vphg-y548. Also Bennett AM et al., JAMIA
2023;30(4):718–25; Johnson AEW et al., Sci Data 2023;10:1; Pollard T et al., PhysioNet, Nature Health (2026). A
database derived from the demo falls under the ODbL share-alike terms; the derived lake stays in `.cache/`.

How the MIMIC data is normalised and what the test found: [Validation §5](VALIDATION.md#5-the-open-data-test).

## 7. The OMOP store of record

OMOP CDM v5.4 in the box's Postgres is the store of record for clinical facts (D-144); the first slice is D-151. The
schema `omop` of the trial database holds the official v5.4 tables (DDL from OHDSI/CommonDataModel v5.4.2, pinned by
sha256 in `services/omop/ddl/pin.json`) and TrialBox's `tb_*` tables beside them: record status, provenance (batch,
file, row), the history of every record, and open and resolved conflicts. It is in every backup.

- **What goes in.** The adapter's NDJSON snapshot (the hospital feed) and the site's published inputs, with
  pseudonyms only: `person_source_value` is the pseudonym, `person_id` an integer minted once. Every code is kept as
  sent in `*_source_value` (ICD-10, LOINC, ATC, NHI, YJ, ...) with a local source concept (ids from 2,100,000,000;
  `TB_OMOP_CONCEPT_BLOCK`); the standard `*_concept_id` is 0 until the vocabulary bundle is loaded.
- **Deletes are tombstones.** A record the hospital no longer sends leaves the standard table; its last content and
  the night it went are kept in `tb_record_event`.
- **Disagreements are recorded.** Two sources that give a patient different birth dates, sexes or dates of death open
  a conflict; screening reads the item as unknown until the steward (or the PI, for their study) resolves it.
- **The lake.** `TB_LAKE_SOURCE=omop` builds the screening lake from OMOP with the same tables and rows; the default
  is still `legacy` (flattened from the NDJSON) until the flag flips (WS-03.5). Commands: `python -m omop load
  --lake <lake>`, `python -m omop status` and `python -m omop dqd` (the Data Quality Dashboard-style checks).

## 8. Derived scores

A derived score is computed from other rows: eGFR (CKD-EPI 2021 or JSN 2009), BMI, DAS28, BASDAI, ASDAS, CDAI and
SDAI. Code: `libs/tb_common/derived.py` (formulas, units, same visit), `libs/tb_common/scores.py` (definitions),
`libs/tb_common/derived_store.py` (stored rows) (D-149, D-189, D-190).

**Definitions come from the catalogue.** Each score is a YAML file in `catalogue/scores/`: inputs, units, windows,
coefficients, edge cases and published worked examples. `python tools/gen_score_defs.py` writes them to
`libs/tb_common/score_defs.json`; the box reads only that file. A definition is named `<score_id>@<version>` (for
example `rheum.cdai@1`) and carries the sha256 of its YAML. A YAML that changed but kept its version is refused:
bump the version. The same-visit windows of CDAI, SDAI, DAS28-ESR and DAS28-CRP are read from the definitions.

**Units.** Every input is converted to the unit its formula expects (CRP mg/dL x 10 = mg/L; creatinine µmol/L /
88.4 = mg/dL). The CDAI and SDAI globals are on a 0-10 scale (LOINC 75844-1 and 75846-6); a 0-100 mm VAS recorded
under them is divided by 10, a 10 cm VAS is already 0-10, and a value outside 0-10 gives no value. SDAI takes the
CRP in mg/dL.

**No value is unknown.** A missing input, or a unit or scale that does not fit, gives no value and a reason
(`derived_missing_input:<input>`, `derived_unit:<input>`). Screening reads this as unknown, never as "no". A proposed
fact (read from a chart, not yet confirmed) never counts as an input; nor does a rejected or preliminary row.

**Screening.** The SQL and CQL engines compute the score per patient at the index date, from one visit: the newest
anchor input in the window (the joint count; the creatinine for eGFR) and the other inputs near it. CDAI and SDAI are
in both engines and in the Python reference, and a test checks that all three give the published worked examples
(`tests/unit/test_derived_definitions.py`). A criterion names its score (`cdai`, `sdai`, `egfr_jsn`, ...).

**Stored rows.** The `derive` batch (`derived_store.run_batch`, one patient at a time with
`DerivedStore.recompute`) writes CDAI, SDAI, DAS28-ESR, DAS28-CRP and both eGFRs to schema `derived` of the trial
database, one row per patient, score and anchor row:

| Table | What it holds |
| --- | --- |
| `definition` | the definitions in use: version, sha256, the full text |
| `score_row` | value (or no value and the reason), unit, anchor date, definition version and sha, the site mapping version, and every input: source table, row id, date, value and unit as recorded, status, and the value and unit the formula used |
| `input_link` | one row per input ("derived from") |
| `conflict` | a documented score that does not match the computed one |

A row is written only when something it depends on changed: an input added, corrected, confirmed or deleted, a new
mapping version, or a new definition version. Otherwise the batch writes nothing. A new row supersedes the old one;
rows are never changed in place or deleted. An anchor deleted at the source retires its row. A definition that
changed under the same version stops the store from opening.

**Documented scores.** A score written in a note (a proposed fact) or signed by a physician is compared with the
computed row within 7 days of it. When they differ by more than the score's tolerance (CDAI and SDAI 0.5, DAS28 0.2,
eGFR 5), a `derived_vs_documented` conflict opens. Neither value is overwritten. The score reads as unknown until a
person chooses `keep_derived`, `keep_documented` or `both_at_dates`. A documented score with no computed row near it
stands alone, as what it is.

Not yet: screening still computes scores in its own SQL and CQL rather than reading the stored rows; an approved
ruleset does not pin definition versions; nothing schedules the `derive` batch and the console has no page for
derived conflicts; DAS28, BASDAI, ASDAS and MELD 3.0 still need clinician worked examples before approval.

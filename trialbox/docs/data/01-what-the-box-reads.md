# 1. What the box reads

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

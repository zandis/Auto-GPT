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

**SS-MIX2 (Japan).** The reader walks `<id[0:3]>/<id[3:6]>/<id>/<診療日>/<type>/`, keeps the newest message per
patient, 診療日, type and order number (the specification's key; a site may declare `unique`, D-594, D-1000), and
reads HL7 v2.5 in ISO-2022-JP or UTF-8: ADT-00/12/22/52 (patient, visits, discharges, class changes), PPR-01 (one
snapshot per patient: deletions, ICD-10 from PRB-10, dates, 転帰, 主診断, 修飾語), OMP-01/02 (orders: one dose, the
doses a day from the 用法, YJ from RXE-31) and OMP-11/12 (administrations) with YJ and ATC, and OML-11 (labs with
JLAC10). Extended storage is read in the guideline's layout (content folders under data-type folders that carry the
LOINC document code) and in the older one (files in folders named by kind); `_contents.xml` is not read. Tables
SS-MIX2 does not standardize come from `<root>/extended/<table>.csv` (D-122, D-137). Output claims JP Core 1.1.0 and
is validated on a sample at ingest, offline (`services/adapter/validate/jpcore.py`).

What of the specification the reader reads, after plan 10 cards 10B-2 to 10B-5 (review 12 §4.9, which counted 26
types: 1 parsed, 8 partly, 17 not). It is tested against a storage written from the specification
(`tests/ssmix2_spec_kit.py`, `tests/unit/test_ssmix2_to_specification.py`), not yet against a vendor's storage.

| Type or part | State | What is still not read |
| --- | --- | --- |
| Tree, names, flags 0/1/2, record key | Parsed | Flag 2 is read as "an older version" (newest wins) |
| Multi-volume manifest | Not | One root only (10B-11) |
| ADT-00 | Partly | IN1; A23 is read only as flag 0 (10B-8) |
| ADT-12 | Parsed | – |
| ADT-22 | Partly | A11 cancellation only through flag 0 (10B-8) |
| ADT-52 | Partly | A13 (cancel discharge) not undone (10B-8) |
| ADT-01, 21, 31, 32, 41, 42, 51, 61 | Not | 10B-7, 10B-8 |
| PPR-01 | Parsed | ZPR's field layout is read loosely (every coded value a 修飾語); a diagnosis missing from a newer snapshot without PRB-1 `DE` is kept; 主診断 is not yet carried to the lake (no `diagnosis_role` reader) |
| OMP-01, 02 | Partly | JAMI 標準用法 codes are not decoded (the site's `usage.csv` gives doses a day, else "1日N回" in the text); RXE-12 refills |
| OMP-11, 12 | Parsed | – |
| OML-11 | Parsed | Microbiology shape untested (10B-9) |
| OML-01, OMG-01/02/03/11/12/13, OMD | Not | 10B-9, 10B-10 |
| Extended storage | Partly | `_contents.xml`, CDA sections (HS032, HS008) |

Count: of the 26 types, **5 parsed** (ADT-12, PPR-01, OMP-11, OMP-12, OML-11), **5 partly** (ADT-00, ADT-22,
ADT-52, OMP-01, OMP-02), **16 not**.

**Code lists.** ICD-10-CM 2026 in full (98,186 codes, public domain) for lookups and family groupers. The licensed
Japanese lists (MEDIS 標準病名, JLAC10, YJ) are loaded by the site from its own licensed files
(`python -m adapter.licensed load --kind medis|jlac10|yj --file … --version …`, D-137); each release is kept with its
version, sha256 and who loaded it, and every load is audited. The demo rows are synthetic and marked `verify`.
The clinical item catalogue (scores, labs, findings and phenotypes mapped to LOINC, OMOP, OHDSI phenotypes and
CDISC QRS) is in `catalogue/`; its design is `docs/reviews/2026-11-09-clinical-item-catalogue.md`. Code reads its
score definitions through a generated file (§8) and its items through `tb_common.catalogue` (D-353):
`python -m omop.catalogue_load` gives each item one concept (LOINC from the vocabulary, a local item at its
TB-SHARED id; a LOINC code the vocabulary lacks is listed as unmapped), chart extraction drops item answers of an
instrument whose `storable` is `score`, and `/data/items` shows the items by specialty to the administrator.
The instrument copyright register (`catalogue/instruments.csv`, D-375) says, from public sources, who holds each
licensed scale or questionnaire and what its terms say; `/data/instruments` shows it to the administrator. A site
that holds a licence may keep more of an instrument than the catalogue allows only by giving its licence reference
(an empty one is refused and audited). TrialBox asks nobody for a licence. The phenotypes load with a status
(`tb_common.phenotypes`): seven ICD-10-CM sets are checked on the synthetic hospital, the other 157 are "not
validated here". An Athena load records one licence acknowledgement per licensed vocabulary in the bundle
(`python -m omop vocab status` lists them).

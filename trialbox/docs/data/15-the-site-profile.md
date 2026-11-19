# 15. The site profile

Card 10B-6 of plan 10 (`docs/plan/47-plan-10-2026-11-18.md`, Track B), commitment C-6, decision D-1233. Source:
review 12 section 7 (`docs/reviews/2026-11-root/12-ssi-data.md`). Built at the plan's "essential" grade.

Every hospital writes the same standards with its own habits: its own lab, drug and diagnosis codes, the data
types it really stores, the standard versions it writes. Before this card those habits lived in code (the SS-MIX2
reader read the image's sample tables, with no setting to change them), in mapping files and in settings. The site
profile is one folder of data per site that holds them. Fitting a new hospital is filling its profile, not changing
code. A site with no profile reads exactly as before.

## What a profile is

One versioned folder, `deploy/site/mapping/profile/` on the box. It sits in the site mapping folder, so it is
mounted read-only into the adapter at `/etc/trialbox/mapping/profile` and kept by every update (D-367).

```
profile/
  profile.yaml      the manifest (libs/tb_common/site_profile.schema.json)
  codes/<name>.csv  one code table per file
```

The manifest holds:

- `format: tb-site-profile/1`;
- `id`, and `site_id`: the site's `settings.site.id`;
- `country`: the layer above it (C-7, card 10C-25);
- `version`: the steward's, MAJOR.MINOR.PATCH;
- `synthetic`;
- `door`: the `data_source.type` it describes;
- `standards`: the standard versions the hospital writes;
- `data_types`: the SS-MIX2 data types, or the source tables, the site stores;
- `tables`: the code tables. Each names its file, its key column (the site's code), its target column (the
  standard code), its state column, where the rows came from, and `used_by` (where the product reads it).

Every row of a table has a state: `verified` (a person checked the standard code against its release) or `verify`
(a sample, a suggestion, a row nobody checked). The legacy words of the shipped tables are read as follows:

- `yes` and `confirmed` read as `verified`;
- `local` reads as `verify`. It marks a TrialBox-local score code with no standard behind it, so it takes the safe
  side.

**What a profile is not.** It holds no credentials (those stay in environment variables), and no hospital name or
address (those stay in settings). It holds nothing per study (that is the study package, C-8), and no patient data:
a table with a column such as `mrn`, `birth_date` or `patient_id` is refused. The repository's profiles are
synthetic, their ids start with `synthetic-`, and only they may point at a table shipped in the image
(`file: shipped:<path>`), so that a sample code is written in one place only.

## Where each site-specific fact lives

One fact lives in one place. Where a fact moves into the profile, its old place stops being read for that site. The
mapping YAML keeps the *shape* of the export (columns, renames, value words, date calendars per column, overlays).
The profile keeps the *codes and habits*.

| Fact | Before 10B-6 | After 10B-6 | Moves with |
| --- | --- | --- | --- |
| Local lab codes → LOINC (csv, SQL and SS-MIX2 doors) | The mapping's `lookups.lab` CSV beside the YAML | The profile table with `used_by: [mapping.lab]` (the YAML is untouched, so the mapping version is unchanged) | **Moved here** |
| 病名 → ICD-10, YJ → ATC and the known JLAC10 codes of the SS-MIX2 reader | Hard-wired in code to the image's `jp_core` samples; no setting | Profile tables `ssmix2.diagnosis`, `ssmix2.drug`, `ssmix2.lab`, given at the call site (`adapter.pipeline.make_source`) | **Moved here** |
| The data types the site stores | Nowhere | `data_types`, read by the coverage lines | **Moved here** |
| The standard versions the site writes | Comments in the mapping; `settings.profiles` for TW Core | `standards` (a declaration; nothing decides on it yet) | Here, as a declaration. `settings.profiles` stays the value the code reads until 10C-25 sets the layer |
| Character set of the export | `settings.data_source.encoding` | Unchanged | 10B-19 (the questionnaire asks it) |
| SS-MIX2 order-number (visit-key) habit | `TB_SSMIX2_ORDER_NUMBERS` (D-594) | Unchanged | 10B-2 (the specification's key by default), then 10B-19 |
| Usage (用法) codes → doses per day | Not modelled | Unchanged | 10B-4 (`codes/usage.csv`, a new `used_by`) |
| Hospital drug master and ingredient → ATC (T-610) | `drug_master.csv` and `ingredient_atc.csv` beside the image's `jp_core` mapping | Unchanged | 10B-4 |
| Document types (`_DOC_KINDS`) and extended-storage folders | In code, in the SS-MIX2 reader | Unchanged | 10B-5, then 10B-15 (`documents.csv`) |
| Template fields → coded observations | Not modelled | Unchanged | 10B-15 (`templates.csv`) |
| Note section labels (【既往歴】, SOAP, ＃n) | One heading pattern in `services/matching/excerpts.py` | Unchanged | 10C-23 (`sections.yaml`) |
| DPC codes and payloads | Not read | Unchanged | 10B-12 |
| Older-records boundary per source | Not modelled | Unchanged | 10C-22 |
| National calendar, words, legal pack | Spread across the code | Unchanged | 10C-25 (the Japan profile, the layer above this one) |
| Non-working days of the site | Not modelled anywhere | Unchanged | 10C-25 (national calendar), with site days as an override after it |
| Unit spellings and default units per analyte | The mapping's `unit_spellings` (D-590) and `unit_defaults` (D-149) | Unchanged | No card names it; proposed with 10B-16 (the second synthetic profile) |
| Department codes → names | `settings.departments` | Unchanged | 10B-19 |
| Site set-up's suggestions | Read the image's `jp_core` and `tw_core` samples | Unchanged, but a suggestion from a `verify` row says so (below) | 10B-19 (read the site's profile instead) |
| `settings.data_source.lab_local_to_loinc` | In the settings schema; no code reads it | Unchanged | Remove with 10B-19 (the lab table is the profile's) |
| Licensed MEDIS, JLAC10 and YJ releases | The terminology store (`adapter.licensed`, D-137) | Unchanged: national releases the site buys, not habits | Stays |
| Regimens and order sets | Not modelled | Unchanged | 10A-8 (regimens), 10B-15 |

## Loading, validation and the `verify` state

`tb_common.site_profile.load(folder)` is the one way the product gets a profile. It refuses a profile and names the
file, the line and the reason:

- a manifest that does not match the schema, an unknown key included;
- a table outside its folder, or missing;
- a table without its key, target or state column, or with a patient column;
- a row with an empty or repeated key, an empty target, or a state that is not one of the words above;
- a table the SS-MIX2 reader would read by other columns;
- two tables for one `used_by`;
- a `synthetic` flag that does not match the id.

The night loads the profile before it reads anything. A refused profile ends the night with an `ingest.failed`
event, as any other error does. The mapping engine refuses a profile table for a look-up the mapping does not
declare.

`Table.find(code)` returns the row with its state, so a value taken from a profile carries its state to wherever it
is shown:

- **Coverage lines and the work list** count and list every `verify` row.
- **Site set-up** (D-135): a suggestion taken from a shipped sample row that says `verify` comes with the method
  `lookup_verify` and the confidence 0.80, and the Local codes page says "from a sample row nobody has verified
  (check it)" in en, ja and zh-TW. Before this card such a row was shown as "from TrialBox's code table" at 100 %.

The state does not travel into the FHIR resources, because that would change every golden. That is a seam for the
card that next changes the lake's columns.

## Versions, audit, roll-out and roll-back

The digest is the SHA-256 of the manifest and of every table's bytes. `adapter.site_profile.activate` compares a
profile with the one the box last read: `site_profile.json` in the lake folder holds the active profile and its
history.

- **A new digest** is recorded with who, when, the old and new version, both digests and the direction (first,
  forward, back). It is written as one `site_profile.load` event in the hash-chained audit through the one audit
  writer.
- **The same id and version with other content** is refused: the steward changes the version with the content.
- **Roll-out.** Put the new folder in place, check it (`python -m adapter.site_profile check`), and load it by name
  (`load --by`, recorded). If nobody loads it, the next night loads it and records the actor as `adapter`.
- **Roll-back.** Put the earlier folder back from the backup and load it. It is recorded as `direction: back`.

Every night read with a profile writes `site_profile.json` beside its snapshot: the profile's id, version and digest,
and the coverage lines. "Which profile version produced this night's read" is
`python -m adapter.site_profile which --lake <dir> --snapshot <day>`. The `ingest.done` event carries the same
stamp and the coverage counts.

## Coverage lines and the work list

Coverage lines are counts only, never a patient's value. They are built from the night's own files
(`completeness.json`, `reader.json`, `unmapped_codes.json`), so any kept night can be asked again. They say:

- each declared data type and its rows;
- the declared types that did not arrive;
- the types that arrived but are not declared;
- per table, how many codes and rows no table could map;
- per table, how many rows are still `verify`.

There are two ways to read them:

- **Command:** `python -m adapter.site_profile coverage --night <lake>/ndjson/<day>`.
- **Page:** a "Site profile" section on the night's data-operations page (`/data-ops/batches/<id>`, en, ja and
  zh-TW, 390 px), and the same in `/api/v1/data/batches/<id>`.

The work list is `python -m adapter.site_profile worklist --night <dir> --out <file.csv>`. It lists the unmapped
codes, most rows first, then every `verify` row with its file and line. A cell that a spreadsheet would run as a
formula is quoted. **A page for the work list is not built here.** It belongs with 10B-19's site-setup form, which
is where a steward edits the rows.

## The proof

The plan says: "a second synthetic profile gives the same funnel with no code change". It is held in three ways.

1. **Goldens.** The goldens' synthetic Taiwan site (`synthetic-tw-a`, csv) and synthetic Japanese hospital
   (`ssmix2-jp`, SS-MIX2 storage) are read through their profiles (`services/adapter/mapping/profile/`,
   `tools/omop_parity.py` `PROFILES_OF`). `make goldens-check` is identical from both lake sources.
2. **Byte-identical NDJSON.** The same night with and without its profile gives the same NDJSON
   (`tests/unit/test_site_profile.py`).
3. **A second profile.** The same synthetic patients, with the hospital's lab codes renamed in its export and its
   own profile carrying the renamed table, read the same coded facts (who, when, LOINC, value). Patients,
   diagnoses, medicines and visits are byte-identical. No mapping file and no code changes between the two.

## Seams left for the cards that wait

| Card | What it adds | Where it plugs in |
| --- | --- | --- |
| 10B-4 | `codes/usage.csv` (用法 → doses per day), the drug master | A new `used_by` (`ssmix2.usage`, `ssmix2.drug_master`) in the schema's list and `make_source` |
| 10B-5 | Extended-storage folders and `_contents.xml` | `documents.csv` beside it; the declared `data_types` already count what arrives |
| 10B-12 | DPC readers | `door: dpc` or a second door. The DPC codes are tables with `used_by` |
| 10B-15 | Document types and templates | `documents.csv`, `templates.csv`: tables with their own `used_by` |
| 10B-19 | The questionnaire as a form that fills the profile | It writes `profile.yaml` and `codes/`, then `load --by <person>`. The work list's page goes there |
| 10C-22 | The older-records boundary per source | A manifest key per door (a schema change, version 1.1.0) |
| 10C-23 | Note sections and their roles | `sections.yaml` beside the manifest, named in it |
| 10C-25 | The Japan layer (C-7) | `country` already names the layer. A country profile sits above, and the site profile overrides only listed keys |

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
| The standard versions the site writes | Comments in the mapping; `settings.profiles` for TW Core | `standards`, a declaration. Where both name a standard (`tw_core`, `twpas_version`), they must agree: the night and `load` refuse otherwise | Here, as a declaration. `settings.profiles` stays the value the code reads until 10C-25 sets the layer |
| The site's country | `settings` (the zone, else the page language: `tb_common.derived.country_of`; the set-up defaults in `tb_common/site_country.py`) | `country` must be the one the settings give: the night and `load` refuse otherwise | Stays in settings; the profile is checked against it |
| Lab codes a person mapped in site set-up (D-135) | The `local_code` store of site set-up (`sitesetup/store.py`, with who and when): it maps the codes of sheets and charts, not of the feed | Unchanged. Where it and the profile's lab table map one code differently, **the store wins** (a named person's recorded act; `adapter.site_profile.store_wins`) and the work list lists each disagreement (`worklist --setup-db`). **Not yet applied at night**: the adapter does not read the set-up store, and giving it that right is lane C2's (a read right on the `sitesetup` schema) | 10B-19 makes the form the one way to fill both |
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
| `settings.data_source.lab_local_to_loinc` | In the settings schema; **dead**: no code reads it | Unchanged (removing a settings key is a schema change of its own) | Remove with 10B-19 (the lab table is the profile's) |
| Licensed MEDIS, JLAC10 and YJ releases | The terminology store (`adapter.licensed`, D-137) | Unchanged: national releases the site buys, not habits | Stays |
| Regimens and order sets | Not modelled | Unchanged | 10A-8 (regimens), 10B-15 |

## Loading, validation and the `verify` state

`tb_common.site_profile.load(folder)` is the one way the product gets a profile. It refuses a profile and names the
file, the line and the reason:

- a manifest that does not match the schema, an unknown key included;
- a table outside its folder, or missing;
- a table without its key, target or state column, or with no rows;
- a column a patient's data could ride in: a deny list (`mrn`, `birth_date`, `patient_id` and the like) and, for a
  table only the SS-MIX2 reader reads, an allow list of the columns it reads;
- free text (a table's `source`, a standard's version) holding `://`, `@` or a long token: nothing secret;
- a row with an empty or repeated key, an empty target, or a state that is not one of the words above;
- a table the SS-MIX2 reader would read by other columns;
- two tables for one `used_by`;
- a `synthetic` flag that does not match the id.

A table a mapping reads (`used_by: [mapping.<look-up>]`) is also held to that mapping (`check_mapping`): the mapping
must declare the look-up, the table must be keyed by the look-up's key and hold every column of the mapping's own
look-up file (the columns its elements and builders read: code system, code, display, unit, category, ...) and no
other column. Without this, a three-column table passed and every lab result lost its code at night.
`python -m adapter.site_profile check <folder> --mapping <file>` runs the same check; without `--mapping` a profile
with such a table is refused.

The night loads the profile before it reads anything and checks it against the mapping, the country and the
standard versions of the settings. A refused profile ends the night with an `ingest.failed` event, as any other error
does.

`Table.find(code)` returns the row with its state, so a value taken from a profile carries its state to wherever it
is shown:

- **Coverage lines and the work list** count and list every `verify` row.
- **Site set-up** (D-135): a suggestion taken from a shipped sample row that says `verify` comes with the method
  `lookup_verify` and the confidence 0.80, and the Local codes page says "from a sample row nobody has verified
  (check it)" in en, ja and zh-TW. Before this card such a row was shown as "from TrialBox's code table" at 100 %.

- **The lake** (the coordinator's ruling on #1128): a fact whose standard code comes from a `verify` row carries
  D-135's basis tag (`meta.tag` `urn:trialbox:basis`, code `verify`), the same mechanism that marks a site's own
  facts as proposed or confirmed. Only `proposed` keeps a fact out of the coded tables. A `verify` fact stays coded,
  as it was before this card, and the lake also lists it in `site_fact` with basis `verify`, so how much of a count
  rests on unverified rows can be asked. The night's coverage lines count these facts per table.
  - A mapping's look-up table: every row that looks up a `verify` code is tagged.
  - An SS-MIX2 table: the reader is not changed here (#1095 is changing it). A diagnosis or medicine row is tagged
    when its local code is a `verify` row and its standard code is the one that row gives. A message that carried the
    same code itself is tagged too: an over-count on the safe side.

**Open question (no rule exists; not decided here).** May a fact whose standard code rests on an unverified mapping
exclude a patient? Today it does exactly what any coded record does: it can meet an inclusion and it can exclude.
D-135's rule ("a proposed fact can only send a patient to needs information") is about facts read from a chart,
not about mappings, and D-130 covers codes nobody maps, not codes mapped but unchecked.
The test `test_a_fact_from_a_verify_row_stays_coded_and_is_listed_as_resting_on_one` in
`tests/unit/test_site_profile.py` pins today's behaviour. Tagging such facts `proposed` instead would apply D-135's rule to them, and would take every lab
result of the synthetic Japanese hospital out of its funnels: that is the owner's decision to make.

## Versions, audit, roll-out and roll-back

The digest is the SHA-256 of the manifest and of every table's bytes. `adapter.site_profile.activate` compares a
profile with the one the box last read: `site_profile.json` in the lake folder holds the active profile and its
history.

- **A new digest** is recorded with who, when, the old and new version, both digests and the direction (first,
  forward, back). It is written as one `site_profile.load` event in the hash-chained audit through the one audit
  writer.
- **Every row whose state changed** (added, removed, `verify` to `verified` or back) is named in the same event with
  its table, code, old and new state; who and when are the event's. The rows' states as last activated are kept in
  `site_profile.states.json` beside the record.
- **No audit, no profile.** Without an audit folder nothing is activated (the night and `load` refuse).
- **An id and version read before with other content** is refused, asked of the whole history, not only of the
  active profile: the steward changes the version with the content.
- **The site** is the settings' `site.id`: `load` reads it from the settings and refuses a profile of another site.
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
- the declared types this version does not read at all (an allergy type, say): "declared, not read by this version",
  not "none arrived";
- the declared types that did not arrive;
- the types that arrived but are not declared;
- per table, how many codes and rows no table could map;
- per table, how many rows are still `verify`;
- per table, how many facts of the night rest on a `verify` row.

There are two ways to read them:

- **Command:** `python -m adapter.site_profile coverage --night <lake>/ndjson/<day>`.
- **Page:** a "Site profile" section on the night's data-operations page (`/data-ops/batches/<id>`, en, ja and
  zh-TW, 390 px), and the same in `/api/v1/data/batches/<id>`.

The work list is `python -m adapter.site_profile worklist --night <dir> --out <file.csv>`. It lists the unmapped
codes, most rows first; with `--setup-db <url>` every lab code the site set-up store maps otherwise than the
profile (`disagree`, the store's code marked as the one that wins); then every `verify` row with its file and line.
A cell that a spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`, a tab or a carriage return) is
quoted. **A page for the work list is not built here.** It belongs with 10B-19's site-setup form, which
is where a steward edits the rows.

## The proof

The plan says: "a second synthetic profile gives the same funnel with no code change". It is held in three ways.

1. **Goldens.** The goldens' synthetic Taiwan site (`synthetic-tw-a`, csv) and synthetic Japanese hospital
   (`ssmix2-jp`, SS-MIX2 storage) are read through their profiles (`services/adapter/mapping/profile/`,
   `tools/omop_parity.py` `PROFILES_OF`). Before the `verify` tag, `make goldens-check` was identical from both
   lake sources. The tag moves only what it should: the pull request names each golden file and value that moved.
2. **The same NDJSON but for the tag.** The same night with and without its profile gives byte-identical NDJSON for
   every type but `Observation`, and the same `Observation` lines once the `verify` tag is removed; exactly the
   results of the `verify` codes carry it (`tests/unit/test_site_profile.py`).
3. **A second profile at the csv door.** The same synthetic patients, with the hospital's lab codes renamed in its
   export and its own profile carrying the renamed table, read the same coded facts (who, when, LOINC, value).
   Patients, diagnoses, medicines and visits are byte-identical. No mapping file and no code changes between the two.
4. **A second profile at the SS-MIX2 door.** The same synthetic storage with every 病名 code renamed in its PPR-01
   messages (they carry no ICD-10 of their own, so the reader takes it from the table) and a profile whose diagnosis
   table carries the renamed codes give the same diagnoses: who, visit, ICD-10, dates and status.

## Seams left for the cards that wait

**With a seam now** (a new kind of table is one `used_by` word in the schema, one argument at the call site, and the
mapper's `verify` rule if its codes reach the lake):

| Card | What it adds | Where it plugs in |
| --- | --- | --- |
| 10B-4 | `codes/usage.csv` (用法 → doses per day), the hospital drug master | `ssmix2.usage` and `ssmix2.drug_master` in the schema's list, passed by `adapter.pipeline.make_source` (the reader already takes `drug_master`) |
| 10B-12 | DPC readers | A `door` value and its tables with their own `used_by`; `data_types` and the coverage lines need nothing new |
| 10C-25 | The Japan layer (C-7) | `country` names the layer and is checked against the settings. A country profile sits above; the site profile overrides only listed keys |

**Without a seam yet** (each needs a manifest key, a schema version 1.1.0, and code that reads it):

| Card | What it needs |
| --- | --- |
| 10B-5, 10B-15 | Document types and templates: a `documents.csv` and a `templates.csv`, and the reader's `_DOC_KINDS` read from them (an edit of the SS-MIX2 reader, after #1095) |
| 10C-23 | Note sections: a `sections.yaml` named in the manifest, and the matcher's heading pattern read from it |
| 10C-22 | The older-records boundary per source: a key per door, and the engine's look-back reading it |
| (none yet) | Calendar overrides of the site: a key after 10C-25's national calendar exists |
| 10B-19 | The questionnaire: a form that writes `profile.yaml` and `codes/` and then loads them by the person's name; the work list's page goes there |

## Known limits

- A night read under one version is not read again, nor flagged, when a later version changes a mapping: the next
  full night reads with the new one, and each night says which version read it.
- The record in the lake folder is read, changed and written without a lock: two loads at the same moment can lose
  one history entry (the audit chain keeps both events).
- #1095 (the SS-MIX2 reader to the specification) changes the default visit key and the goldens, and touches
  `tests/unit/test_japan_completeness.py` and the decision registry, as this card does: whichever merges second
  runs the identical-output check again.

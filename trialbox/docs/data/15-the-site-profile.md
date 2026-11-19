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
| Lab codes a person mapped in site set-up (D-135) | The `local_code` store of site set-up (`sitesetup/store.py`, with who and when): it maps the codes of sheets and charts. **It does not reach the nightly feed at all**: only tests call `lab_lookup_rows` and `merge_lookup`, so a mapping recorded on the console's Local codes page does not change what the night reads | Unchanged. Where it and the profile's lab table map one code differently, **the store wins** (a named person's recorded act; `adapter.site_profile.store_wins`) and the work list lists each disagreement (`worklist --setup-db`). **Not yet applied at night**: the adapter does not read the set-up store, and giving it that right is lane C2's (a read right on the `sitesetup` schema) | 10B-19's form fills the profile only; the store stays the Local codes page's (the form has no route, D-1249) |
| Character set of the export | `settings.data_source.encoding` | Unchanged | The questionnaire asks it (9.1 question 8); no profile field, so 10B-19 does not move it |
| SS-MIX2 order-number (visit-key) habit | `TB_SSMIX2_ORDER_NUMBERS` (D-594) | Unchanged | 10B-2 (the specification's key by default); the questionnaire asks it (question 7), no profile field |
| Usage (用法) codes → doses per day | Not modelled | Unchanged | 10B-4 (`codes/usage.csv`, a new `used_by`) |
| Hospital drug master and ingredient → ATC (T-610) | `drug_master.csv` and `ingredient_atc.csv` beside the image's `jp_core` mapping | Unchanged | 10B-4 |
| Document types (`_DOC_KINDS`) and extended-storage folders | In code, in the SS-MIX2 reader | Unchanged | 10B-5, then 10B-15 (`documents.csv`) |
| Template fields → coded observations | Not modelled | Unchanged | 10B-15 (`templates.csv`) |
| Note section labels (【既往歴】, SOAP, ＃n) | One heading pattern in `services/matching/excerpts.py` | Unchanged | 10C-23 (`sections.yaml`) |
| DPC codes and payloads | Not read | Unchanged | 10B-12 |
| Older-records boundary per source | Not modelled | Unchanged | 10C-22 |
| National calendar, words, legal pack | Spread across the code | The country layer above this profile (`libs/tb_common/japan_profile.json`, `tb_common.country_layer`, D-1250): the holiday list and the New Year break (P9) read from it; words and the legal pack declared there, not built | **Moved** by 10C-25 (calendar); the cards of P1 and P5 build the rest |
| Non-working days of the site | Not modelled anywhere | Unchanged: the site's own days stay `TB_DAYS_OFF` and `TB_DAYS_OPEN` (D-1230), which win over the country layer's | A site key after 10C-25, if a site asks |
| Unit spellings and default units per analyte | The mapping's `unit_spellings` (D-590) and `unit_defaults` (D-149) | Unchanged | No card names it; proposed with 10B-16 (the second synthetic profile) |
| Department codes → names | `settings.departments` | Unchanged | No profile field (10B-19 asks no new one: 9.2 sample 3's 診療科 table is listed as filling none) |
| Site set-up's suggestions | Read the image's `jp_core` and `tw_core` samples | Unchanged, but a suggestion from a `verify` row says so (below) | Not moved by 10B-19 (a command, not a page): still open |
| `settings.data_source.lab_local_to_loinc` | In the settings schema; **dead**: no code reads it | Unchanged (removing a settings key is a schema change of its own) | Not removed by 10B-19 (a settings schema change of its own): still open |
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
- a table that is not UTF-8 (with the line where the first byte fails);
- a row with an empty key, a key that is another row's key once folded (`UA`, `ua` and full-width `ＵＡ` are one
  code: `tb_common.codekey.fold_key`, the same fold the mapping's look-up uses), an empty target, or a state that is
  not one of the words above;
- a standard code that is not a code of its system, named by file, line and column. The system is the row's
  `system` column or the reader's (ICD-10 for diagnoses, ATC for medicines). Checked: LOINC (a number with no leading zero,
  a hyphen and its Mod-10 check digit), the WHO ICD-10 shape (U codes such as U07.1 included), the 7-character ATC,
  TrialBox's score codes; all ASCII (a full-width `４５４８-４` is refused). The system's name is kept in one spelling
  (`LOINC`, `Loinc` and `loinc` are all kept as `loinc`, the word the mapping reads), so a row's standard code is
  never lost at night for the way its system was written. Any other system (SNOMED CT, say) is refused, and the licence
  register's row for it is named;
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
  - A mapping's look-up table: the tag is decided by the row the look-up actually matched (`Lookup.find`, as
    written or by its folded form), never by a second comparison: ` UA`, `ua` and `ＵＡ` in the feed are tagged
    exactly when they get UA's standard code.
  - An SS-MIX2 table: the reader is not changed here (#1095 is changing it). A diagnosis or medicine row is tagged
    when its local code is a `verify` row and its standard code is the one that row gives. A message that carried the
    same code itself is tagged too: an over-count on the safe side. The follow-up, once #1095 has merged: the reader
    says which code it took from the table, and only those rows are tagged.

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
  forward, back). It is written as one `terminology.site_profile_load` event in the hash-chained audit through the one audit
  writer.
- **Every row whose state changed** (added, removed, `verify` to `verified` or back) is named in the same event with
  its table, code, old and new state; who and when are the event's. The rows' states as last activated are kept in
  `site_profile.states.json` beside the record.
- **No audit, no profile.** Without an audit folder nothing is activated (the night and `load` refuse).
- **The kept copy is checked every night.** Its content is hashed again and must be what was recorded and audited
  when it was loaded, and every row is checked again. A copy edited by hand, cut short or unreadable is refused with
  one `terminology.site_profile_copy_refused` event.
- **A profile that cannot be applied stops the night** (as before versions existed): a kept copy that is refused, or
  a folder on a box where nobody has loaded one, ends the night with `ingest.failed`, and the box keeps serving the
  night before. Why: a night read without the site's profile would leave its codes unread and could miss patients
  with no sign on any list. Only a folder taken away on purpose (audited) lets the nights read without a profile.
- **Only a version a person loaded is applied.** `load --by <name>` keeps the profile as loaded and checked in the
  lake folder (`site_profile/<digest>.json`); the night reads that copy (its tables written trimmed to the lake's
  scratch), never the raw files. A folder whose content is not the loaded version (a file dropped in, an edit, an
  unreadable table) is not applied: the night reads the loaded version, says so on its record and on the night's
  page, and the audit has one `terminology.site_profile_not_loaded` event per content. A folder on a box where nobody loaded one
  stops the night (above).
- **Taking it off.** A folder taken away takes the profile off the box: one `terminology.site_profile_removed` event, the record's
  active profile is empty and that night's record says so. `unload --by <name>` does the same by name.
- **A delta night after a change reads whole.** When the night a delta merges over was read with another profile
  (or none), the night reads every row, so no fact carried over keeps a tag of the version before
  (`read_whole_because_the_profile_changed` on its record).
- **An id and version read before with other content** is refused, asked of the whole history, not only of the
  active profile: the steward changes the version with the content.
- **The site** is the settings' `site.id`: `load` reads it from the settings and refuses a profile of another site.
- **Roll-out.** Put the new folder in place, check it (`python -m adapter.site_profile check`), and load it by name
  (`load --by`, recorded). Until a person loads it, the nights keep the loaded version and say a new one waits.
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
- per table, how many facts of the night rest on a `verify` row;
- a problem line per table for results in a unit their row does not give (D-590's counter): they are kept without a
  value, never converted; the work list lists them by code (`unit`).

There are two ways to read them:

- **Command:** `python -m adapter.site_profile coverage --night <lake>/ndjson/<day>`.
- **Page:** a "Site profile" section on the night's data-operations page (`/data-ops/batches/<id>`, en, ja and
  zh-TW, 390 px), and the same in `/api/v1/data/batches/<id>`. It also says that a folder nobody loaded was not
  applied, and that lab codes mapped on the Local codes page do not reach the night yet: where they and the profile
  disagree, the site set-up mapping is the one that counts, and the work list lists each difference.

The work list is `python -m adapter.site_profile worklist --night <dir> --out <file.csv>`. It lists the unmapped
codes, most rows first; with `--setup-db <url>` every lab code the site set-up store maps otherwise than the
profile (`disagree`, the store's code marked as the one that wins); then every `verify` row with its file and line.
A cell that a spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`, a tab or a carriage return) is
quoted. **A page for the work list is not built.** 10B-19's form is a command, not a page (D-1249); a console page for
the questionnaire and the work list would be a new route, and it is with the owner.

## The questionnaire form

Card 10B-19, decision D-1249. The questionnaire is review 12 section 9 (`docs/reviews/2026-11-root/12-ssi-data.md`):
9.1 holds thirty questions for the hospital's IT and 9.2 lists the sample exports to ask for. A hospital's answers,
written in one answers file, become a profile folder in this section's format, so that nobody hand-writes the
folder. (`docs/plan/sites/site-survey.md` is TB-SITE-01's survey for a site mapping, not this questionnaire.)

```
python -m adapter.site_profile fill --template --lang ja > answers.yaml       # the answers file, its questions as comments
python -m adapter.site_profile fill --answers answers.yaml --out <new folder> --check-only   # what is refused, nothing written
python -m adapter.site_profile fill --answers answers.yaml --out <new folder>                # writes; does not load
python -m adapter.site_profile check <new folder> --mapping <the site mapping>               # then load --by, as above
```

**A command, not a page.** No site-setup page managed the profile, so a page would have been a new route. Its account
would then write code tables that the night reads once they are loaded. The lane lead ruled for a command: the people
who may run it are the people who run `load` on the box. No route, role or permission row changes.

**It writes and never loads.** The files are built beside `--out` and read back by `tb_common.site_profile.load`.
Only then is `--out` made: if a folder of that name appeared in the meantime, nothing is replaced and the command
refuses. The checked files are written into the new folder as new files. Folders are mode `0755` and files `0644`,
whatever the operator's umask, so the box's user can read them. If the disk refuses, or Ctrl-C stops the command,
nothing of the folder is left: one line says why (exit 2, or 130 for Ctrl-C), never a traceback. A missing folder
above `--out` is made, and the command says so. Loading is still `load --by` (versioned, audited, refused when the
content changes under the same version), and a profile that cannot be applied still stops the night. The command
refuses:

- a folder that exists;
- a folder above it that is a file, or that the operator cannot write in;
- a folder inside a site mapping folder the box reads: those named by `TB_MAPPING_DIR` in the shell that runs the
  command, the mount `/etc/trialbox/mapping` (always, whatever `TB_MAPPING_DIR` says), and `deploy/site/mapping`;
- a folder inside the image's mapping folder.

The limit: a mapping folder mounted somewhere else, and not named by `TB_MAPPING_DIR` in that shell, is not known to
the command. The steward checks the new folder and puts it in place.

**Every answer is text.** The answers file is parsed once, by a YAML reader that builds no number, no boolean and no
date: `factor: 010`, `0x10`, `1:30` and `1_0` are the text written, never 8, 16, 90 or 10. Each typed answer is then
accepted by one pattern of its own, or refused:

- a factor: a plain decimal above 0 and at most 1000 (no sign, exponent, leading zero, other base, `_` or `:`);
- a version: `MAJOR.MINOR.PATCH` of whole numbers without a leading zero;
- a date: `YYYY-MM-DD`, a real day;
- `synthetic`: exactly `true` or `false` (`yes`, `on` and `True` are refused).

**Validation by allow-list** (`adapter.site_questionnaire.parse`). An answer is accepted only when it is recognised:

- a key of the form;
- a name from a list: a country, a door, a data type, a standard, a master, a category, a kind of result, or a UCUM
  unit `tb_common.labunit` knows;
- a value of a fixed shape: a profile name, a version, a date, a local code (1 to 32 ASCII letters, digits, `.`, `_`
  and `-`), a YJ code, a standard code checked exactly as the loader checks it, or a LOINC answer code;
- a bounded plain decimal.

**Answers must go together** (`adapter.site_questionnaire.GOES_WITH`). For each country, the table lists the doors,
the standards and each code table's masters. An answer outside its country's row is refused, and the message names
both answers. Examples: `tw` with the SS-MIX2 door; `jp` with `cgrd_sql`, `tw_core` or `icd10cm`; a lab table whose
master is the MEDIS disease-name master. Also, the SS-MIX2 version goes with the SS-MIX2 door only. Every shipped
profile goes together (a test). When Japan's layer (10C-25) is on master, this table should be read from it (D-1249).

The form makes a profile for `jp` and `tw` only. Its tables are the SS-MIX2 reader's (Japan) and the lab look-up,
whose results carry Japan's or Taiwan's FHIR profile. For `us` or `other` it refuses and says why: nothing it wrote
could be read for that country.

**Units.** A lab row's factor turns a result in its `source_unit` into its `unit`, as the mapping engine applies it.

- A quantity needs its unit (`1` for a count or a score). A coded result has no unit, no source unit and factor 1.
- Same unit (or a spelling of it), or no source unit given: the factor is 1. The engine reads such a row's results
  as already in the unit. A different factor is refused.
- Different units: the factor must be given. Where `tb_common.labunit.conversion` knows the pair, the factor must
  agree with it (`g/L` from `mg/dL` is 0.01, so 100 is refused). Where it does not know the pair (`mg/dL` from
  `mmol/L` with no analyte table), the row is stored as `verify` whatever the answer said, and the summary says so.

**What a refusal says.** Each refusal comes from the console's catalogue (`profileform.err.<code>`), in en, ja and
zh-TW. It gives the answer's key (`tables.lab.rows[3].unit`), its line in the answers file and its length, then what
is expected. It never repeats what the answer said, so a patient's name typed into the wrong field is not shown back.
A key that is not a plain word is shown by its length only. Every refusal the parser finds is reported in one run,
also inside a coded result's answers. A refusal that stops the reading is reported alone: a file that is not YAML,
an alias (`*`), a key written twice, a key that is not text, a second document, a file over 5 MB, or nesting deeper
than 16 levels (the form itself nests seven). The file is read from the parser's events with a stack of the reader's
own, never by recursion, and the reading stops as soon as the bound is passed: a deeply nested file is told "not a
form", never a traceback.

**No free text unescaped, no path from an answer.**

- A name or a display is printable text: 1 to 120 characters, starting with a letter, a digit or a bracket (never
  `=`, `+`, `-` or `@`), with no control or format character such as a line break or a direction override. Text
  that looks like a web address with a user name or password is refused. The csv module writes the text, so commas
  and quotes are quoted.
- The template says that no patient data and no password goes in the form. The form does not look for them, beyond
  the address rule above.
- The manifest holds no answer text. The table files are always `codes/diagnosis.csv`, `codes/drug.csv` and
  `codes/lab.csv`, and a table's `source` is the form's own words for a master from the list, with its checked date.

**An unchecked mapping stays unchecked.** A row is `verified` only when the answer says exactly `verified`. A row with
no state is `verify`, as this section stores a row nobody checked. An empty state is refused: leave the key out for
`verify`. The open question above (may such a fact exclude a patient?) is not touched.

**Every default is said.** The template says what the form decides when an answer is left out. The command prints a
summary before it writes, also with `--check-only`. It covers:

- the profile's name, version, `synthetic`, country and door, each as answered (none has a default; the template
  leaves them empty);
- each table's rows;
- the rows stored as `verify` because no state was given;
- the rows given factor 1 because of one unit or no source unit;
- the rows with no source unit;
- the rows whose factor was checked against the product's conversion;
- the rows stored as `verify` because the product has no factor for their units.

**What the form fills.** Diagnoses and medicines are for the SS-MIX2 door only. A lab table needs the country `jp` or
`tw` (above).

| Field | Filled from |
| --- | --- |
| `door` | 9.1 question 4 (SS-MIX2 running: `ssmix2`; otherwise `csv` or `cgrd_sql`) |
| `data_types` | 9.1 questions 6, 12, 14 and 15 |
| `standards` | 9.1 questions 8 (SS-MIX2 version), 9 (ICD-10 version) and 21 (each master's release date) |
| `tables.diagnosis` | 9.2 sample 3 (病名 → ICD-10), with question 21's master |
| `tables.drug` | 9.1 question 10 and 9.2 sample 3 (YJ → ATC) |
| `tables.lab` | 9.1 question 11 and 9.2 sample 3 (local or JLAC10 → LOINC, unit, factor, coded answers) |
| `format`, `id`, `site_id`, `country`, `version`, `synthetic` | No question: the form's header, asked of the steward (`site_id` and `country` are the settings'; `load` refuses others) |

The questions that fill no field, each with its reason, are in `adapter.site_questionnaire.QUESTIONS`:

- 9.1 questions 1 to 3, 5, 7, 13, 16 to 20 and 22 to 30;
- 9.2 samples 1, 2 and 4 to 7;
- the parts of questions 8 to 12 and 21 that no field holds: the character set, the order-number habit, PRB and RXE
  habits, the share of codes mapped, and document types;
- 9.2 sample 3's 用法 and 診療科 tables.

Where a card gives one of these a field (10B-4 usage, 10B-5 and 10B-15 documents and templates), that card adds the
question to the form.

**The worked example** is the repository's synthetic Japanese hospital, and only it:
`tests/fixtures/site_questionnaire/synthetic-jp-ss.answers.yaml`. These are the same codes as the shipped sample
tables, every row `verify`, as version 1.1.0 of `synthetic-jp-ss`. The profile the form writes from it passes the
loader, the mapping check and `activate`, and reads every code to the same standard code as the shipped profile
(`tests/unit/test_site_questionnaire.py`). Every lab cell is as shipped, but for one difference: the two joint counts
(TJC28, SJC28) have the unit `1` where the shipped table leaves it empty, because a quantity needs its unit.

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
| 10C-25 | The Japan layer (C-7), **done** (D-1250) | `country` names the layer and is checked against the settings. The layer is `tb_common.country_layer` (parts P1 to P16); its version and digest are written in the profile's record at each load (the audit event is unchanged). A setting the site made wins over the layer |

**Without a seam yet** (each needs a manifest key, a schema version 1.1.0, and code that reads it):

| Card | What it needs |
| --- | --- |
| 10B-5, 10B-15 | Document types and templates: a `documents.csv` and a `templates.csv`, and the reader's `_DOC_KINDS` read from them (an edit of the SS-MIX2 reader, after #1095) |
| 10C-23 | Note sections: a `sections.yaml` named in the manifest, and the matcher's heading pattern read from it |
| 10C-22 | The older-records boundary per source: a key per door, and the engine's look-back reading it |
| (none yet) | Calendar overrides of the site: a key after 10C-25's national calendar exists |

## Known limits

- A night read under one version is not read again, nor flagged, when a later version changes a mapping: the next
  full night reads with the new one, and each night says which version read it.
- An SS-MIX2 code is tagged by the reader's own exact match (the reader is not changed here). The reader does not
  fold: a code written in lower case or with a trailing blank in a message stays uncoded there, and is in the
  unmapped counts instead.
- The one fold (`tb_common.codekey.fold_key`) trims every blank Python counts as one, the no-break and ideographic
  spaces, tabs and newlines in a quoted cell included, and it folds the Kelvin sign (U+212A) to `k`: two spellings
  that fold alike are one code, both in the table check and in the look-up, so the tag stays consistent.
- The record in the lake folder is read, changed and written without a lock: two loads at the same moment can lose
  one history entry (the audit chain keeps both events).
- #1095 (the SS-MIX2 reader to the specification) changes the default visit key and the goldens, and touches
  `tests/unit/test_japan_completeness.py` and the decision registry, as this card does: whichever merges second
  runs the identical-output check again.

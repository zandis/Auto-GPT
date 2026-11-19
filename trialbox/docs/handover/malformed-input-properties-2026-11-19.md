# Malformed-input properties on seven readers (2026-11-19)

**Reader:** the people who build TrialBox: lane B2 (the rule-set install), lane D (the update verifier), the lanes of
the adapter, the data core and the site set-up, lane H and the integrator. Findings for builders, so in one language.

Plan 10 row 10G-43 (review 21, item OT-5). It waited for 10G-6 (the rule-set zip caps, D-1102), which is on master,
so the whole row is done here. Findings in the register's `--add-from` form:
`malformed-input-properties-2026-11-19/findings.json`. No decision was needed.

## The property

**Returns or refuses; no other exception; under N s and M MB.** Each reader, given generated input, either returns
or raises its own documented refusal: the exception its caller catches (or, for the two file readers that refuse by
quarantine, no exception at all). Anything else fails. Each call is also timed and its peak Python allocation
measured (`tracemalloc`): **N = 2 s, M = 64 MB**, for generated inputs of at most 64 KB (`tests/malformed_kit.py`).

| Reader | Called as | Refusal allowed |
| --- | --- | --- |
| HL7 v2 decode and parse | `hl7.decode_bytes`, `hl7.parse`, then every accessor the walker uses | `hl7.Undecodable`; `ValueError` from `parse` |
| SS-MIX2 walker | `Ssmix2Source(...).rows`, `deleted_rows`, `quarantine_reason`, `reader_summary` on a generated storage | none: a file is quarantined (STD-020) |
| CSV source | `CsvSource(...).rows` on a generated `lab.csv`, each declared character set, with and without `--since` | none: a file is quarantined (T-615b) |
| Bundle verifier | `tools.verify_update.verify` on a generated `.tar` | `verify_update.Rejected` |
| Rule-set zip | `criteria_compiler.import_ruleset.read_zip`; the 10G-6 caps check `check_ruleset_zip` on its own | `ImportRefused`; `ZipRefused` for the caps check |
| REDCap dictionary | `datacore.forms.read_dictionary`, then `forms.questionnaires`, as `POST /studies/{rs}/forms/dictionary` does | `forms.FormError` |
| Site intake | `intake.read_grid`, `messy.clean`, `intake.refuse_chart_column`, `intake.sheet_facts`, `intake.preview_roles`, as `add_sheet` and `reread` do | `intake.IntakeError` |

The inputs are generated only: bytes, pieces of each format (HL7 delimiters and ISO-2022-JP escape sequences,
Shift_JIS and Big5 bytes, CSV quotes and line ends, zip and tar members with names that leave the folder, links,
duplicates), real files made by the test and then cut or with one byte changed, and, for the verifier, manifests
changed and **signed again with a key made by the test** so what is read after the signature is tried too. The
REDCap dictionaries are made from the column names the reader itself knows (`forms._COLS`, keys and values); no
REDCap source is used. No patient data: the patient numbers and names in the generators are made up.

## The files

Seven test files in `tests/property/` (so `make property` and the CI `property` job run them, with
`-k "property or test_safety_properties"`), one per reader, and the helper `tests/malformed_kit.py`:
`test_malformed_hl7.py`, `test_malformed_ssmix2_walker.py`, `test_malformed_csv_source.py`,
`test_malformed_update_bundle.py`, `test_malformed_ruleset_zip.py`, `test_malformed_redcap_dictionary.py`,
`test_malformed_site_intake.py`.

Settings: 60 examples a property (the walker 200: a storage is the most varied input), no deadline (the bound is N,
measured in the helper), **derandomized** (the gate is the same on every run; the other property tests do not set it,
and a property that found a new input by chance on one CI run would make the gate flaky), no example database. The
seven files: 17 tests, about 16 s on this container, the same five times in a row.

**Proof of the row.** An `IndexError` planted in `hl7.parse` (a `parts[1]` on a line without `|`, not committed)
fails three tests: both HL7 parse properties and the walker's.

## Results

| Reader | Examples | Result |
| --- | --- | --- |
| HL7 decode and parse | 3 properties x 60, plus 12 explicit | holds |
| SS-MIX2 walker | 200, plus 4 explicit (about 190 messages read into rows, about 30 quarantined over a run) | holds |
| CSV source | 60, plus 6 explicit (a 131,073-character cell, NUL, a bare CR, an open quote) | holds |
| Bundle verifier | 2 properties x 60, plus 3 explicit; the good bundle itself verifies | holds; H10G43-04 (a cut bundle) is fixed (58e7cf2, card H-44) |
| Rule-set zip | 2 properties x 60, plus 3 explicit | the caps check holds; `read_zip` holds on intact zips with a mapping manifest, except H10G43-01 and -02 |
| REDCap dictionary | 60, plus 5 explicit | holds, except H10G43-03 |
| Site intake | 60, plus 3 explicit (CSV and XLSX, damaged files, merged cells) | holds, except H10G43-05 |

## Findings

All five are a reader letting a library's exception out where its caller expects the reader's refusal; none lets a
bad input through. Each one's minimal input is an explicit `@example` in a test marked `xfail(strict=True,
raises=Escaped)` with the finding id: the suite stays green, and the fix makes that test pass, which fails the run
until the fixing card removes the mark. The properties around them are not weakened: the input class of a finding
is set apart in its own test, named in the docstring of the property it is set apart from.

| Id | Severity | Lane | Reader | What | Minimal input |
| --- | --- | --- | --- | --- | --- |
| H10G43-01 | Low | B2 | rule-set zip | `read_zip` lets `zipfile.BadZipFile` out (`import_ruleset.py:33`: the zip is opened outside the try) | `b""` |
| H10G43-02 | Low | B2 | rule-set zip | `read_zip` lets `AttributeError`, `UnicodeDecodeError` or a yaml error out when `manifest.yaml` is no UTF-8 YAML mapping (`import_ruleset.py:44-45`) | a zip holding `manifest.yaml` = `- a` |
| H10G43-03 | Low | A2 (a guess) | REDCap dictionary | `read_dictionary` lets `csv.Error` out (`forms.py:172`); the route catches `FormError` only (`datacore_api.py:239`): a 500, nothing stored | `field_name,form_name\na\rb,f\n` |
| H10G43-04 | Low | D | bundle verifier | `verify` lets `tarfile.ReadError` out for a bundle cut inside a member: `tf.getmembers()` (`verify_update.py:215`) is outside the try that makes a `TarError` a `Rejected`; nothing staged, but a traceback, not the exit-1 refusal. Fixed 58e7cf2 (card H-44): refused as "a damaged or cut-short tar bundle", the xfail removed | the first 512 bytes of a tar of one 1-byte file |
| H10G43-05 | Low | A2 (a guess) | site intake | `read_grid` lets `csv.Error` out (`intake.py:61`); the setup route catches `IntakeError` and `SetupError` only (`setup_api.py:328`): a 500, nothing stored | `a\rb\r\n` as a CSV sheet |

H10G43-03 and -05 also come from a cell over 131,072 characters (the `csv` module's field limit); the CSV source
does not have the defect, because it catches `csv.Error` and quarantines.

## Not done or not verified

* No reader was changed by this card (they belong to other lanes); H10G43-04 was fixed after it (58e7cf2, card H-44),
  the other four wait for their lanes.
* The memory bound counts Python's own allocations only (`tracemalloc`), not the process's resident size.
* The XLSX inputs are files openpyxl writes; a hand-made XLSX (an XML bomb, a sheet with no rows element) was not
  generated beyond one byte changed.
* The verifier's payload staging was tried on the one good payload only; the host tree (`kind: host`) was not built.

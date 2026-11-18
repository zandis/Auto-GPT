# Imperfect hospital data through the nightly ingest (2026-11-18)

**Reader:** the people who build TrialBox: lane E (the data sources), lane B2 (the night), lane V (the findings
register) and the integrator. Findings for builders, so in one language.

Card H-34 (was lane V's V-10), decision D-1100: "imperfect hospital data (cut-off file, the same file twice, wrong
column count, Big5, 0000-00-00 and ROC years, a two-megabyte note, unknown code, two chart numbers, empty export):
nothing crashes, each rejected row counted with its reason." It is part of plan 8's V15 ("imperfect data"). This page
reports and fixes nothing: no product file was changed. The findings are in
`imperfect-feed-2026-11-18/findings.json` beside this page, in the findings register's `--add-from` form; lane V adds
them to the register.

## The answer

- **Entry point:** the box's own command line, `python -m adapter.cli run --source <kind> --path|--dsn <feed>
  --snapshot <night> --no-fhir`, as a process of its own, configured by a settings file the settings wizard writes
  from the box rehearsal's answers (`tools/rehearse_box/site_answers.yaml`), the lake step local
  (`TB_ADAPTER_LAKE=local`, the hash embedder). `adapter.run_job`, which the adapter service starts at night, calls
  the same `run_ingest` with the same `build_config`. Each run has its own lake, secrets, audit folder and database
  prefix.
- **43 cases, 103 runs** in the four source formats the adapter reads (CSV 39, CGRD SQL 23, FHIR Bulk 25, SS-MIX2 16);
  69 case-and-format pairs do not apply and say why. A live HL7 v2 feed and a live FHIR feed **do not exist yet**.
- **Crashes: 5**, all in the FHIR Bulk reader (a cut-off line, Big5, UTF-16, a UTF-8 byte-order mark).
- **Silently wrong in the lake: 10 runs** (a value cut short, a note cut short, a row with a field missing, 200
  results with no value, two people merged under one chart number, a garbled diagnosis name), and **9 runs** where
  an impossible value or a split patient is served as the hospital wrote it, counted nowhere.
- **Uncounted:** a zero-byte FHIR file loses 200 results with no count; rejected rows under 1 % are counted only in
  `completeness.json`, which no surface a person reads shows.
- 23 findings: 9 High, 9 Medium, 5 Low; lane E 18, lane B2 5.

## How it was run

`make imperfect-feed` (about two minutes; `TABLE=1` prints the table below). The tool is `tools/imperfect_feed.py`;
its fast tests are `tests/unit/test_imperfect_feed.py`, whose last test runs the real adapter on three nights.

1. **A clean export, made up here.** `clean_export()` writes 50 fictional patients and every table of the demo HIS
   mapping (`services/adapter/mapping/tw_core/demo_his.yaml`): 150 visits, 150 diagnoses, 200 lab results, 100
   prescriptions, 150 notes in Chinese and English, and the rest. No value is copied from anywhere; no national ID or
   phone number is made, not even a fake one. Every fact the lake keeps is unique, so a value changed, a row twice or
   a row under another patient can be told from the right one.
2. **Written in each format.** The CSV site export; a CGRD-style database (SQLite, every column text, read through
   `--dsn`); a FHIR Bulk Data export (one NDJSON file per type); SS-MIX2 standardized storage written by
   `tools/ssmix2_export.py` from the CSV, read with `mapping/jp_core/ssmix2_site.yaml` (a Japanese site: zone
   Asia/Tokyo).
3. **The clean export ingests.** Its lake was compared with what the generator says it holds: equal for CSV, SQL and
   FHIR Bulk; for SS-MIX2 equal but for the four discharge summaries the exporter adds to extended storage.
4. **One variant per case,** each run as a first night (the same-file-twice case runs two nights). Recorded: the exit
   status and any traceback; `ingest_report.json` (passed, held, its error lines); `completeness.json` (rows read
   per table, rejected rows by reason, duplicate keys, files set aside, dates left out, codes not mapped) and the
   SS-MIX2 reader's `reader.json`; the steward's batch row (`dataops.batch`, what the admin's page shows) and the
   night's audit event; the lake's own Parquet tables of the night compared with the clean night's (a value that
   differs, a row twice, a good row lost); the strings of the served snapshot's NDJSON that hold a replacement
   character or half-width katakana (the marks of bytes read in the wrong character set); and one FEAS computation
   (GOUT-COH, 36 months) over the served lake. D-1100 says what "counted with its reason" and "silently wrong" mean
   here.

What a person is told: the report's error lines (`ingest_report.json`, which the orchestrator's INGEST job mails as
"finished with N error(s)": its line count, `services/orchestrator/scenarios/admin.py`), the steward's batch row
(the keys of `datacore.dataops.DETAIL_KEYS`: gate, incomplete, orphans, quarantined, duplicate keys, unmapped, error)
and the audit event. A rejected-row count is in none of them (H34-11).

## The table

Exit: `0 published` (the night served), `1 held` (the gate held it; the lake keeps the previous night), `1 failed`
(a publish step failed), `crash (traceback)`. Counted: what `completeness.json` and `reader.json` say for the night;
`UNCOUNTED` when rows the case made bad are missing from the lake and nothing counts them. Reason given: the error
lines of `ingest_report.json` (the "night held" line left out). Silently wrong: `YES` when the lake holds what the
file does not say (counted or not; D-1100), `kept as written` when it holds an impossible value or a split patient
as the hospital wrote it. Night goes on: the lake rebuilt and served, and FEAS ran over it.

| Case | Format | Exit | Counted (completeness.json, reader.json) | Reason given (ingest_report.json) | Good rows kept | Silently wrong in the lake | Night goes on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cut-mid-row | csv | 0 published | nothing counted | none (no error line) | all | YES: 1 wrong | yes |
| cut-mid-row | fhir_bulk | crash (traceback) | nothing counted | none (no error line) | no night served | not served | no: json.decoder.JSONDecodeError: Expecting ',' delimiter: line 1 column 424 (char 423) |
| cut-mid-row | ssmix2 | 0 published | reader.json: OML-11:sample time from folder 1 | none (no error line) | all | YES: 1 wrong | yes |
| cut-mid-char | csv | 1 held | note: file set aside | note: note.csv quarantined: FORM-ENCODING: the file mixes two character sets (line 151); moved to quarantine/note.csv | held: nothing served | not served | held (lake keeps the previous night) |
| cut-mid-char | fhir_bulk | crash (traceback) | nothing counted | none (no error line) | no night served | not served | no: json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 2 (char 1) |
| cut-mid-char | ssmix2 | 0 published | reader.json: PPR-01:quarantined (unreadable bytes) 1 | none (no error line) | all | no | yes |
| cut-in-quotes | csv | 0 published | nothing counted | none (no error line) | all | YES: 1 wrong | yes |
| twice-same-name | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-same-name | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-same-name | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-same-name | ssmix2 | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-other-name | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-other-name | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-other-name | ssmix2 | 0 published | nothing counted | none (no error line) | all | no | yes |
| twice-in-one-file | csv | 0 published | lab: duplicate_keys 200, unmapped 2 | none (no error line) | all | no | yes |
| twice-in-one-file | cgrd_sql | 0 published | appointment: duplicate_keys 50; claim: duplicate_keys 5; diagnosis: duplicate_keys 150; encounter: duplicate_keys 150; lab: duplicate_keys 200; medication: duplicate_keys 100; note: duplicate_keys 150; patient: duplicate_keys 50; practitioner: duplicate_keys 3; procedure: duplicate_keys 10; report: duplicate_keys 50; vital: duplicate_keys 50 | none (no error line) | all | no | yes |
| twice-in-one-file | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| column-short | csv | 0 published | nothing counted | none (no error line) | all | YES: 1 wrong | yes |
| column-extra | csv | 0 published | lab: rejected 1 "MappingError: unparseable datetime <value>" | none (no error line) | all | no | yes |
| header-renamed | csv | 0 published | nothing counted | none (no error line) | 200 of 800 lost | YES: 200 wrong | yes |
| header-dropped | csv | 1 held | nothing counted | validation error rate 7.14% exceeds 0.5% | held: nothing served | not served | held (lake keeps the previous night) |
| header-dropped | cgrd_sql | 1 held | nothing counted | validation error rate 4.76% exceeds 0.5% | held: nothing served | not served | held (lake keeps the previous night) |
| big5 | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| big5 | fhir_bulk | crash (traceback) | nothing counted | none (no error line) | no night served | not served | no: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa7 in position 290: invalid start byte |
| big5 | ssmix2 | 0 published | reader.json: PPR-01:read as cp932 1 | none (no error line) | all | YES: 2 garbled texts in the snapshot | yes |
| big5-hkscs | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| utf8-bom | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| utf8-bom | fhir_bulk | crash (traceback) | nothing counted | none (no error line) | no night served | not served | no: json.decoder.JSONDecodeError: Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0) |
| utf8-bom | ssmix2 | 0 published | nothing counted | none (no error line) | all | no | yes |
| utf16 | csv | 1 held | note: file set aside | note: note.csv quarantined: FORM-ENCODING: the file reads as UTF-16 without a byte order mark (a NUL byte beside every character); moved to quarantine/note.csv | held: nothing served | not served | held (lake keeps the previous night) |
| utf16 | fhir_bulk | crash (traceback) | nothing counted | none (no error line) | no night served | not served | no: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte |
| utf16 | ssmix2 | 0 published | reader.json: PPR-01:quarantined (unreadable bytes) 1 | none (no error line) | all | no | yes |
| big5-one-row | csv | 1 held | note: file set aside | note: note.csv quarantined: FORM-ENCODING: the file mixes two character sets (line 11); moved to quarantine/note.csv | held: nothing served | not served | held (lake keeps the previous night) |
| date-zero | csv | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-zero | cgrd_sql | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-zero | fhir_bulk | 1 failed | nothing counted | lake rebuild failed: ValueError: LAKE-BUILD: the lake could not build the snapshot. The error's own message can hold a value of a row and is not sent; the lake's log says where the build failed | no night served | not served | no: the night did not end |
| date-roc-slash | csv | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-roc-slash | cgrd_sql | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-roc-compact | csv | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-roc-compact | cgrd_sql | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-roc-words | csv | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-roc-words | cgrd_sql | 0 published | diagnosis: rejected 1 "MappingError: unparseable date <value>" | none (no error line) | all | no | yes |
| date-9999 | csv | 0 published | diagnosis: rejected 1 "DateRangeError: date <value>" | none (no error line) | all | no | yes |
| date-9999 | cgrd_sql | 0 published | diagnosis: rejected 1 "DateRangeError: date <value>" | none (no error line) | all | no | yes |
| date-9999 | fhir_bulk | 0 published | nothing counted | none (no error line) | all | kept as written: 1, not counted | yes |
| birth-after-visit | csv | 0 published | nothing counted | none (no error line) | all | kept as written: 1, not counted | yes |
| birth-after-visit | cgrd_sql | 0 published | nothing counted | none (no error line) | all | kept as written: 1, not counted | yes |
| birth-after-visit | fhir_bulk | 0 published | nothing counted | none (no error line) | all | kept as written: 1, not counted | yes |
| birth-zero | csv | 1 held | patient: rejected 1 "MappingError: unparseable date <value>" | patient: 1 of 50 rows rejected (over 1 %): MappingError: unparseable date <value> (1) | held: nothing served | not served | held (lake keeps the previous night) |
| birth-zero | cgrd_sql | 1 held | patient: rejected 1 "MappingError: unparseable date <value>" | patient: 1 of 50 rows rejected (over 1 %): MappingError: unparseable date <value> (1) | held: nothing served | not served | held (lake keeps the previous night) |
| birth-zero | fhir_bulk | 1 failed | nothing counted | lake rebuild failed: ValueError: LAKE-BUILD: the lake could not build the snapshot. The error's own message can hold a value of a row and is not sent; the lake's log says where the build failed | no night served | not served | no: the night did not end |
| ssmix2-birth-zero | ssmix2 | 1 held | patient: rejected 1 "MappingError: unparseable date <value>" | patient: 1 of 50 rows rejected (over 1 %): MappingError: unparseable date <value> (1) | held: nothing served | not served | held (lake keeps the previous night) |
| ssmix2-birth-9999 | ssmix2 | 0 published | patient: implausible_dates 1 | none (no error line) | all | no | yes |
| ssmix2-birth-after-visit | ssmix2 | 0 published | nothing counted | none (no error line) | all | kept as written: 1, not counted | yes |
| note-2mb | csv | 1 held | note: file set aside | note: note.csv quarantined: not a readable CSV (field larger than field limit (131072)); moved to quarantine/note.csv | held: nothing served | not served | held (lake keeps the previous night) |
| note-2mb | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-2mb | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-nul | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-nul | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-nul | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-blank | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-blank | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| note-blank | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| long-line | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| long-line | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| long-line | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-unknown-lab | csv | 0 published | lab: unmapped 2 | none (no error line) | all | no | yes |
| code-unknown-lab | cgrd_sql | 0 published | lab: unmapped 2 | none (no error line) | all | no | yes |
| code-trailing-space | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-trailing-space | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-lower-case | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-lower-case | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-unknown-dx | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-unknown-dx | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-unknown-dx | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| code-unknown-drug | csv | 0 published | medication: unmapped 2 | none (no error line) | all | no | yes |
| code-unknown-drug | cgrd_sql | 0 published | medication: unmapped 2 | none (no error line) | all | no | yes |
| code-unknown-loinc | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| two-charts-one-person | csv | 0 published | nothing counted | none (no error line) | all | kept as written: 5, not counted | yes |
| two-charts-one-person | cgrd_sql | 0 published | nothing counted | none (no error line) | all | kept as written: 5, not counted | yes |
| two-charts-one-person | fhir_bulk | 0 published | nothing counted | none (no error line) | all | kept as written: 5, not counted | yes |
| two-charts-one-person | ssmix2 | 0 published | nothing counted | none (no error line) | all | kept as written: 5, not counted | yes |
| one-chart-two-people | csv | 0 published | patient: duplicate_keys 1 | none (no error line) | all | YES: 2 wrong | yes |
| one-chart-two-people | cgrd_sql | 0 published | patient: duplicate_keys 1 | none (no error line) | all | YES: 2 wrong | yes |
| one-chart-two-people | fhir_bulk | 0 published | nothing counted | none (no error line) | all | YES: 2 wrong | yes |
| one-chart-two-people | ssmix2 | 0 published | nothing counted | none (no error line) | all | YES: 1 wrong | yes |
| empty-zero-bytes | csv | 1 held | nothing counted | incomplete feed (against snapshot none): lab: table empty and no earlier good night had it (every table of the mapping is required until one has; a table this site does not have goes under feed_completeness.optional_tables). A missing or broken extract? To load it anyway set TB_FEED_DROP_OVERRIDE='2 | held: nothing served | not served | held (lake keeps the previous night) |
| empty-zero-bytes | fhir_bulk | 0 published | UNCOUNTED: 200 bad rows absent, nothing counted | none (no error line) | all | no | yes |
| empty-zero-bytes | ssmix2 | 1 held | lab: file set aside; reader.json: OML-11:quarantined (not an HL7 message) 4 | lab: 4 of 200 SS-MIX2 files quarantined (more than 1 %): not an HL7 message | held: nothing served | not served | held (lake keeps the previous night) |
| empty-header-only | csv | 1 held | nothing counted | incomplete feed (against snapshot none): lab: table empty and no earlier good night had it (every table of the mapping is required until one has; a table this site does not have goes under feed_completeness.optional_tables). A missing or broken extract? To load it anyway set TB_FEED_DROP_OVERRIDE='2 | held: nothing served | not served | held (lake keeps the previous night) |
| empty-folder | csv | 1 held | nothing counted | incomplete feed (against snapshot none): appointment: table missing and no earlier good night had it (every table of the mapping is required until one has; a table this site does not have goes under feed_completeness.optional_tables); claim: table missing and no earlier good night had it (every tabl | held: nothing served | not served | held (lake keeps the previous night) |
| empty-folder | cgrd_sql | 1 held | nothing counted | incomplete feed (against snapshot none): appointment: table missing and no earlier good night had it (every table of the mapping is required until one has; a table this site does not have goes under feed_completeness.optional_tables); claim: table missing and no earlier good night had it (every tabl | held: nothing served | not served | held (lake keeps the previous night) |
| empty-folder | fhir_bulk | 1 held | nothing counted | lake rebuild failed: lake snapshot 2026-11-10: <run folder>/lake/ndjson/2026-11-10 holds no patient or clinical record; nothing built, CURRENT unchanged | held: nothing served | not served | held (lake keeps the previous night) |
| empty-folder | ssmix2 | 1 held | nothing counted | incomplete feed (against snapshot none): appointment: table empty and no earlier good night had it (every table of the mapping is required until one has; a table this site does not have goes under feed_completeness.optional_tables); claim: table empty and no earlier good night had it (every table of | held: nothing served | not served | held (lake keeps the previous night) |
| crlf | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| crlf | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| crlf | ssmix2 | 0 published | nothing counted | none (no error line) | all | no | yes |
| lone-cr | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| lone-cr | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| lone-cr | ssmix2 | 0 published | nothing counted | none (no error line) | all | no | yes |
| newline-in-field | csv | 0 published | nothing counted | none (no error line) | all | no | yes |
| newline-in-field | cgrd_sql | 0 published | nothing counted | none (no error line) | all | no | yes |
| newline-in-field | fhir_bulk | 0 published | nothing counted | none (no error line) | all | no | yes |
| cut-mid-row | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| cut-mid-char | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| cut-in-quotes | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| cut-in-quotes | fhir_bulk | not applicable: a FHIR export has no columns | | | | | |
| cut-in-quotes | ssmix2 | not applicable: an HL7 v2 message has no header row | | | | | |
| twice-other-name | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| twice-in-one-file | ssmix2 | not applicable: one message per file | | | | | |
| column-short | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| column-short | fhir_bulk | not applicable: a FHIR export has no columns | | | | | |
| column-short | ssmix2 | not applicable: an HL7 v2 message has no header row | | | | | |
| column-extra | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| column-extra | fhir_bulk | not applicable: a FHIR export has no columns | | | | | |
| column-extra | ssmix2 | not applicable: an HL7 v2 message has no header row | | | | | |
| header-renamed | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| header-renamed | fhir_bulk | not applicable: a FHIR export has no columns | | | | | |
| header-renamed | ssmix2 | not applicable: an HL7 v2 message has no header row | | | | | |
| header-dropped | fhir_bulk | not applicable: a FHIR export has no columns | | | | | |
| header-dropped | ssmix2 | not applicable: an HL7 v2 message has no header row | | | | | |
| big5 | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| big5-hkscs | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| big5-hkscs | fhir_bulk | not applicable: JSON is Unicode by RFC 8259 | | | | | |
| big5-hkscs | ssmix2 | not applicable: SS-MIX2's character sets are ISO-2022-JP and UTF-8 | | | | | |
| utf8-bom | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| utf16 | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| big5-one-row | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| big5-one-row | fhir_bulk | not applicable: JSON is Unicode by RFC 8259 | | | | | |
| big5-one-row | ssmix2 | not applicable: one message per file | | | | | |
| date-zero | ssmix2 | not applicable: PPR-01 dates are written by the exporter from the CSV; see ssmix2-birth-zero | | | | | |
| date-roc-slash | fhir_bulk | not applicable: FHIR dates are typed: no ROC form is a valid FHIR date | | | | | |
| date-roc-slash | ssmix2 | not applicable: HL7 v2 dates are typed (DTM): no ROC form is a valid HL7 date | | | | | |
| date-roc-compact | fhir_bulk | not applicable: FHIR dates are typed: no ROC form is a valid FHIR date | | | | | |
| date-roc-compact | ssmix2 | not applicable: HL7 v2 dates are typed (DTM): no ROC form is a valid HL7 date | | | | | |
| date-roc-words | fhir_bulk | not applicable: FHIR dates are typed: no ROC form is a valid FHIR date | | | | | |
| date-roc-words | ssmix2 | not applicable: HL7 v2 dates are typed (DTM): no ROC form is a valid HL7 date | | | | | |
| date-9999 | ssmix2 | not applicable: see ssmix2-birth-9999 | | | | | |
| birth-after-visit | ssmix2 | not applicable: see ssmix2-birth-after-visit | | | | | |
| birth-zero | ssmix2 | not applicable: see ssmix2-birth-zero | | | | | |
| ssmix2-birth-zero | csv | not applicable: the same case for them: birth-zero | | | | | |
| ssmix2-birth-zero | cgrd_sql | not applicable: the same case for them: birth-zero | | | | | |
| ssmix2-birth-zero | fhir_bulk | not applicable: the same case for them: birth-zero | | | | | |
| ssmix2-birth-9999 | csv | not applicable: the same case for them: date-9999 | | | | | |
| ssmix2-birth-9999 | cgrd_sql | not applicable: the same case for them: date-9999 | | | | | |
| ssmix2-birth-9999 | fhir_bulk | not applicable: the same case for them: date-9999 | | | | | |
| ssmix2-birth-after-visit | csv | not applicable: the same case for them: birth-after-visit | | | | | |
| ssmix2-birth-after-visit | cgrd_sql | not applicable: the same case for them: birth-after-visit | | | | | |
| ssmix2-birth-after-visit | fhir_bulk | not applicable: the same case for them: birth-after-visit | | | | | |
| note-2mb | ssmix2 | not applicable: notes are extended storage (a CSV source): see the csv row | | | | | |
| note-nul | ssmix2 | not applicable: see the csv row | | | | | |
| note-blank | ssmix2 | not applicable: see the csv row | | | | | |
| long-line | ssmix2 | not applicable: see the csv row | | | | | |
| code-unknown-lab | fhir_bulk | not applicable: FHIR carries LOINC itself: see code-unknown-loinc | | | | | |
| code-unknown-lab | ssmix2 | not applicable: the exporter writes only codes it knows | | | | | |
| code-trailing-space | fhir_bulk | not applicable: typed codes | | | | | |
| code-trailing-space | ssmix2 | not applicable: typed codes | | | | | |
| code-lower-case | fhir_bulk | not applicable: typed codes | | | | | |
| code-lower-case | ssmix2 | not applicable: typed codes | | | | | |
| code-unknown-dx | ssmix2 | not applicable: the exporter writes only codes it knows | | | | | |
| code-unknown-drug | fhir_bulk | not applicable: typed codes | | | | | |
| code-unknown-drug | ssmix2 | not applicable: the exporter writes only codes it knows | | | | | |
| code-unknown-loinc | csv | not applicable: the same case for it: code-unknown-lab | | | | | |
| code-unknown-loinc | cgrd_sql | not applicable: code-unknown-lab | | | | | |
| code-unknown-loinc | ssmix2 | not applicable: the exporter writes only codes it knows | | | | | |
| empty-zero-bytes | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| empty-header-only | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| empty-header-only | fhir_bulk | not applicable: a FHIR export has no columns | | | | | |
| empty-header-only | ssmix2 | not applicable: an HL7 v2 message has no header row | | | | | |
| crlf | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| lone-cr | cgrd_sql | not applicable: the CGRD source is a database read through its driver: no file to cut, no bytes to decode, no line ending (the driver gives typed values) | | | | | |
| newline-in-field | ssmix2 | not applicable: see the csv row | | | | | |
| every case | hl7v2_feed | does not exist yet: a live HL7 v2 feed (MLLP or a file drop of v2 messages outside SS-MIX2): the adapter has no such source (`adapter run --source` offers cgrd_sql, csv, fhir_bulk, ssmix2) | | | | | |
| every case | fhir_feed | does not exist yet: a live FHIR feed (REST pushes or subscriptions): the adapter reads a FHIR Bulk Data export folder only (`fhir_bulk`) | | | | | |

## Findings

Severity by the card's rule (the integrator's words for this card): data silently wrong in the lake is High; a
crash is High; a rejection not counted is Medium; a reason nobody can act on is Low or Medium. The register's own
rule is the same in effect: a value served wrong can make a patient wrongly matched or excluded. Owning lane: E
builds the data sources (the CSV, SQL and FHIR Bulk readers, the mapping); B2 builds the night (what the report and
the steward's row carry) and, by plan 10's cards 10B-1 to 10B-5, the SS-MIX2 reader's repairs.

| Id | Runs (case/format) | What happened, in the product's words | Expected, and from where | Severity | Lane |
| --- | --- | --- | --- | --- | --- |
| H34-01 | cut-mid-row/csv | a CSV export cut inside its last row: that lab result is served with its value cut short (6.5 for a two-decimal value) and no sample time; nothing counted, no error line, the night published | the cut row rejected and counted, or the file set aside; never a value short of its digits in the lake (STD-025 (T-615a: a row the mapping cannot read is rejected and counted by reason); T-615b (a file that is not a readable CSV is quarantined)) | High | E |
| H34-02 | cut-mid-row/ssmix2 | an SS-MIX2 lab message cut inside OBX-5: the value is served cut short (6.5) with the sample time taken from the folder's date; counted only as 'OML-11:sample time from folder' in reader.json | the cut message set aside and counted (as an unreadable message is), never its cut value (T-615a; the reader's own rule for a file it cannot read (PPR-01:quarantined in reader.json)) | High | B2 |
| H34-03 | cut-in-quotes/csv | a CSV export that ends inside a quoted field (no closing quote): the last note is served cut short; nothing counted, the night published | the file set aside as not a readable CSV, or the row rejected and counted (T-615b (not a readable CSV: quarantined); STD-025) | High | E |
| H34-04 | column-short/csv | a CSV row one field short is mapped with the missing column taken as empty: a lab result is served with no sample time; nothing counted | a row with fewer fields than the header rejected and counted (STD-025; DATA-017 (the reader's row count is the export's)) | High | E |
| H34-05 | header-renamed/csv | a CSV whose header names the value column otherwise (result_val): all 200 lab results are served with no value; nothing counted, no error line, the night published | a column the mapping reads that is missing from the file refuses the table or holds the night with its name (T-611 (a table that is not whole holds the night); mapping_check's column check before the first night) | High | E |
| H34-06 | one-chart-two-people/csv, one-chart-two-people/cgrd_sql, one-chart-two-people/fhir_bulk | one chart number on two people's patient rows: the lake serves one patient with the second person's birth date and sex and the second person's visit; CSV and SQL count 'duplicate_keys 1' and publish; FHIR Bulk counts nothing | two different people under one key held for a person (the night held, or the key refused), never merged into one patient (DATA-017 (a duplicate source key is counted; the last row wins) does not cover two people; T-659b (identity changes are a person's)) | High | E |
| H34-07 | one-chart-two-people/ssmix2 | SS-MIX2: a second person's ADT-00 (another birth date and sex) in the same patient folder, newer: it replaces the first person's birth date and sex; nothing counted | an ADT-00 that changes birth date and sex of a patient said (counted, or held for a person) (SS-MIX2 newest-wins (S22 3.1.2) is for corrections of one person; T-659b) | High | B2 |
| H34-08 | cut-mid-row/fhir_bulk, cut-mid-char/fhir_bulk, big5/fhir_bulk, utf8-bom/fhir_bulk, utf16/fhir_bulk | a FHIR Bulk export with one cut-off line, a Big5 or UTF-16 file, or a UTF-8 byte-order mark: adapter run ends with a traceback (JSONDecodeError, UnicodeDecodeError) and the whole night fails; the audit and the steward's row say FAILED with the error's type only, no file or line | the bad line or file counted with its reason (or set aside, as the CSV reader does) and the rest of the export read (T-615b (the CSV reader's quarantine); D-668 (a failure in words); the card's 'nothing crashes') | High | E |
| H34-09 | big5/ssmix2 | SS-MIX2: a diagnosis message in Big5 under MSH-18 ~ISO IR87 is read as Shift_JIS: its 標準病名 name is served garbled in the snapshot (code.text and display; the code is right); counted only as 'PPR-01:read as cp932' in reader.json | a message whose bytes do not read in its declared character set set aside and counted (as unreadable bytes are), never served garbled (T-615b and D-215 (no guessed character set reaches a record); STD-020) | High | B2 |
| H34-10 | date-zero/fhir_bulk, birth-zero/fhir_bulk | a FHIR Bulk resource dated 0000-00-00 (an onset, or a birth date) fails the night's lake build: 'lake rebuild failed: ValueError: LAKE-BUILD: the lake could not build the snapshot ... the lake's log says where'; no row counted or named, nothing of the night served | the date refused and counted at the read, as the CSV path rejects it ('MappingError: unparseable date'), and the night goes on (STD-025; DIN-012 (a placeholder is not a fact); D-669) | Medium | E |
| H34-11 | date-zero/csv, column-extra/csv, date-roc-slash/cgrd_sql, cut-mid-char/ssmix2, utf16/ssmix2 | rows rejected under 1 % of a table, and SS-MIX2 files set aside under 1 %, are counted only in completeness.json or reader.json: ingest_report.json has no error line, the audit event and the steward's batch row carry no rejected count, and the INGEST job's mail counts error lines only | each rejected row counted with its reason where a person reads the night (the report's lines, the steward's page) (STD-025 (counted by reason); the card's 'each rejected row counted with its reason'; datacore DETAIL_KEYS) | Medium | B2 |
| H34-12 | empty-zero-bytes/fhir_bulk | a FHIR Bulk export whose Observation file is zero bytes is published on a first night with no lab result at all; nothing counted, no error line | an empty or missing type of a bulk export held on a first night, as a CSV table is (T-611, NEW-DIN-8) (T-611; NEW-DIN-8 (D-583: every table required on the first night)) | Medium | E |
| H34-13 | birth-after-visit/csv, birth-after-visit/cgrd_sql, birth-after-visit/fhir_bulk, ssmix2-birth-after-visit/ssmix2 | a birth date after the patient's visits is served as written and counted nowhere in every format (F9 checks only a life longer than 122 years) | an impossible date left out and counted (as F9 does for 122 years), the patient kept (F9 (D-811); DIN-012) | Medium | E |
| H34-14 | date-9999/fhir_bulk | a FHIR Bulk onset 9999-12-31 is served as written and counted nowhere, where the CSV and SQL paths reject the same date ('DateRangeError: date <value>') | a FHIR export's dates held to the same range as a mapped source's (DIN-012 (EARLIEST_YEAR, LATEST_YEARS_AHEAD in the mapping engine)) | Medium | E |
| H34-15 | two-charts-one-person/csv, two-charts-one-person/cgrd_sql, two-charts-one-person/fhir_bulk, two-charts-one-person/ssmix2 | one person under two chart numbers (same name, birth date and sex) is served as two patients and FEAS counts 51 where the export holds 50 people; nothing tells a person that two charts look alike | the box keeps the hospital's two charts until a person merges them, and says which charts look alike so a person can (T-659b (adapter pid-merge is a person's act); DATA-017) | Medium | E |
| H34-16 | note-2mb/csv | one CSV note longer than 131,072 characters sets the whole note file aside and holds the night ('not a readable CSV (field larger than field limit (131072))'); the SQL and FHIR paths keep the same note whole; the row is not named | the long note kept whole, or that row rejected and counted; never every note of the night set aside for one (T-615b; STD-025 (a row, not the table)) | Medium | E |
| H34-17 | header-dropped/csv, header-dropped/cgrd_sql | a lab table without its sample-time column holds the night with 'validation error rate 4.76% exceeds 0.5%' (the number moves with the random sample); the reason names neither the table nor the missing column | the hold says which table lacks which column (T-611; D-668 (a reason in words a person can act on)) | Medium | E |
| H34-18 | column-extra/csv | a CSV row with one field more (a decimal comma) is rejected as 'MappingError: unparseable datetime <value>': the reason points at a date, not at the row's extra field | a row with more fields than the header rejected as such (STD-025 (counted by reason)) | Low | E |
| H34-19 | cut-mid-char/csv | a CSV file cut inside a multibyte character is set aside as 'the file mixes two character sets (line 151)': the file is cut short, not mixed | the reason says the file ends inside a character (a cut file) (T-615b; D-668) | Low | E |
| H34-20 | utf16/csv | a UTF-16 CSV with its byte-order mark is set aside as 'the file reads as UTF-16 without a byte order mark' | the reason says UTF-16 (with its mark) is not read (T-615b; D-215) | Low | E |
| H34-21 | twice-other-name/csv | a second copy of a table under another name (lab (1).csv) is ignored with no word: a corrected file sent under a new name would be lost unseen | a file in the export folder that no table reads named in the night's report (T-611 (what the export holds is said)) | Low | E |
| H34-22 | code-unknown-loinc/fhir_bulk | a FHIR Observation with a code the box does not know is served and counted nowhere; the mapped sources count such codes in unmapped_codes.json | unknown codes of a bulk export counted as a mapped source's are (NEW-DIN-6 (D-580)) | Low | E |
| H34-23 | ssmix2-birth-9999/ssmix2 | a patient whose birth date the mapping left out (counted as implausible_dates) fails the night's structural validation when the random sample takes that patient (a Patient needs birthDate): the same SS-MIX2 storage was published on one run and held on the next with 'validation error rate 2.38% exceeds 0.5%' | a value the mapping left out and counted does not also hold the night by chance; the same export gives the same night (F9 (D-811: the patient is kept); D-457 (the sample); D-668) | Medium | B2 |

H34-09 is High by the card's rule (wrong data served without a word on a surface); its harm is the name a page
shows, since the code a criterion reads is right. H34-15 is Medium, not High: the hospital's own records hold two
charts, and the box serves them as written; what is missing is a word that they look like one person (FEAS counted
51 where the export holds 50 people).

## What is right

- **CSV:** Big5 (CP950), Big5-HKSCS (one HKSCS-only character kept), UTF-8 with a byte-order mark, CRLF, a lone CR,
  a quoted newline, a note of 100,000 characters, a note with NUL bytes, a note of blanks, a lab code with a trailing
  space or in lower case (read as CRE): read as the clean export. A file in UTF-16, a file with one Big5 row, a
  file cut inside a character: set aside with a reason and the night held (T-615b).
- **Dates on the mapped sources (CSV, SQL):** 0000-00-00, 113/02/29, 1130229, 民國113年2月29日 and 9999-12-31 are
  each one rejected row, counted with its reason ("MappingError: unparseable date <value>", "DateRangeError: date
  <value>"), the night published with every good row. No ROC date was read as the year 113 or 1130: the demo mapping
  declares no ROC column, so they are refused, not guessed (D-589). A birth date 0000-00-00 rejects that patient's
  row; one patient in 50 is over the 1 % of STD-025, so the night is held with the reason.
- **Unknown codes (CSV, SQL):** a lab code in no table is left out and counted in `unmapped_codes.json`; a drug
  code in no table is kept and counted as not mapped; a diagnosis code in no table is kept as itself (D-130).
- **The same export twice** (two nights, every format; the lab file twice in one delivery, CSV and SQL): the lake is
  not doubled; the duplicate keys are counted (DATA-017).
- **Empty exports:** a zero-byte file or a header only (CSV), a zero-byte message file (SS-MIX2), an empty folder or
  a database with no table (every format): the night held, every missing or empty table named (T-611). H-32
  (lane H) found that an empty feed shows on no surface; that is not repeated here.
- **SS-MIX2:** a UTF-8 byte-order mark, CRLF after each segment, LF only: read as the clean storage. A message cut
  inside a character, or in UTF-16, is set aside and counted in `reader.json` (but see H34-11). PID-7 99991231 is
  left out and counted (`implausible_dates`), the patient kept (but see H34-23).
- **The night goes on** wherever it was published: the lake was rebuilt and served, and FEAS ran (50 patients; 51
  where one person has two charts).

## Not the same twice

The night's validation takes a random sample (D-457). Three cases depend on it. The hold of `header-dropped` gives a
different percentage on each run (2.38 % to 9.52 % seen). A FHIR birth date 0000-00-00 is held by validation when
the sample holds that patient and fails the lake build otherwise (both seen; H34-10). An SS-MIX2 birth date 99991231
is left out and the patient kept, and the night is then published, or held when the sample takes that patient
(both seen across the four runs made for this page; H34-23). The table is the first of the two runs on the final
tool; the second differed only in a validation percentage.

## Cited, not repeated

- Root review 12 (`docs/reviews/2026-11-root/12-ssi-data.md`, section 4.10) found four faults of the SS-MIX2 reader
  against the specification (the record key that drops the day, the diagnoses, the dose, the extended-storage
  layout; plan 10's cards 10B-1 to 10B-5). This card's SS-MIX2 storage is written by TrialBox's own exporter, the
  shape that review warns tests only against; none of its findings is one of those four.
- H-32 (lane H): an empty feed shows on no surface.

## Formats that do not exist yet

D-1067 puts every data connector in release 1.0. The adapter reads `cgrd_sql`, `csv`, `fhir_bulk` and `ssmix2`
(`adapter run --source`). Not built, so not tested: a live HL7 v2 feed (MLLP, or a drop of v2 messages outside
SS-MIX2) and a live FHIR feed (REST pushes or subscriptions). The CGRD source was tested on SQLite, not on the
hospital's database engine.

## Not verified

- The FHIR store (`--no-fhir`: no FHIR server runs here), the OMOP dual write and the PostgreSQL side of the NUL
  bytes a note keeps: a NUL in a text is refused by PostgreSQL, so the FHIR store or OMOP may fail on it.
- The steward accepting a held night, and what a held night's NDJSON would then serve.
- A delta night (`--since`), the back-fill (`adapter backfill`), the data contracts (`TB_DATA_CONTRACTS`) and a site
  that declares its encoding or ROC columns; a CGRD database on its own engine; real vendor SS-MIX2 files.
- The admin's page itself in a browser: the steward's row was read from the database, as the page reads it.
- The mail: the INGEST job's text was read from the code, not sent.

# D-368 EDC prefill controls: what a draft was built under, the stored re-entry result, REDCap formats, ODM by the schema

- **Card:** T-115 (EDC prefill controls, merged card; TB-PLAN-06 `docs/plan/28-master-plan-v6.md` §6.2.5), branch
  `agent/T-115-edc-prefill`
- **Date:** 2026-11-11
- **Status:** accepted
- **Builds on:** D-160 (EDC prefill), D-162 (review E-01 to E-11), D-281 (record lock, keyed signature), D-204
  (checksummed migrations)
- **Closes:** review E-12, E-14 (part), E-15, E-16, E-23 (a to e), E-25 (schema part) of
  `docs/reviews/2026-11-09-edc-prefill-review.md`; deep-review STD-061, STD-062, SEC-14; CR-062 (first half, part),
  CR-036 (rest), LIFE-021 (part)

## The problem

A draft did not record the map row, the dictionary entry or the REDCap project it was built for. After a map change
its open drafts could still be confirmed, signed values stayed sendable, and a changed `token_ref` sent values signed
for one project to another; one connection could be any study's target (E-15). A code confirmed as "Yes" was sent
even when its meaning had changed in REDCap since (E-16). The switch went on with two numbers typed by the person who
turned it on (E-14). The review page showed only a "signed" pill (E-12). The REDCap dictionary reader knew seven
validation types and sent values unformatted, so `number_1dp` and decimal-comma fields would fail a whole import
batch (STD-061). The ODM file had no `Length` on numbers, the unit as free text, repeat keys on non-repeating
definitions, one fixed `SignatureDef`, and nothing checked it against the schema (E-23, E-25, STD-062). The REDCap
client accepted `http://` (SEC-14) and had never been run against a real REDCap (CR-062).

## The decision

1. **Built under (E-15, E-16).** Each draft stores `map_sha` (the hash of its item's map row, per item, not the whole
   map), `dict_sha` (the hash of its dictionary entry: name, form, type, validation, choices with labels, range) and
   `target` (the `token_ref`). All three are in `draft_sha` when set, so in what the signature covers; a draft from
   before keeps its hash. Edc schema version 3.
2. **Map change.** Saving the map supersedes every draft of a changed or removed row that is not signed: open ones
   simply, decided ones with a `superseded` decision row. A signed value stays as signed and is not sent
   (`stale_map`) until the person decides it again under the new row (the record lock applies: password again and a
   reason). A per-item hash keeps an edit of one row from holding back every other value.
3. **Confirm** re-reads the item's row and dictionary entry and checks the value against the field again: a draft
   built under another one is refused (`edc.stale_map`, `edc.stale_dictionary`), audited.
4. **Send** reads the project's dictionary again (`content=metadata`) and holds back, each listed and kept in `sent`
   with its reason: a value built for another target (`target_changed`), under a changed map row (`stale_map`),
   whose live dictionary entry differs from the one it was drafted under (`dictionary_changed`), or that REDCap's
   import would refuse (`format`). Values go in the format of the field's validation.
5. **One study per connection.** A `token_ref` that is one study's EDC target is refused as another study's target
   or dictionary source (`edc.token_bound`), audited.
6. **The re-entry result is stored (E-14).** `edc.reentry_record` (append-only) holds pages, accuracy, the id of the
   filed report and who recorded it. Only an administrator records it (`POST /studies/{rs}/edc/reentry`). The switch
   goes on with the newest record, never with typed numbers, and refuses when the person turning it on recorded it
   (`edc.reentry_same_person`). A DEV or TEST box with no record keeps the typed numbers (demos and their tests),
   and the switch then shows `reentry_id` 0.
7. **The signature beside each value (E-12).** The drafts route gives each signed value its signature (printed name,
   role, time, meaning words, language, method); the review page shows them; the trail lists the values each
   signature covers.
8. **REDCap validation types (STD-061).** The dictionary reader keeps the validation type when it says more than the
   FHIR type (decimal places, decimal comma, `datetime_dmy`/`mdy`, time, e-mail, phone); `file` is never entered,
   `sql` reads as calculated, a slider as a whole number. A value with more decimals than the field allows is refused
   by the item's name (never rounded); on send `number_1dp` gets its one decimal place (`72` becomes `72.0`) and a
   comma type gets the comma. The simulator now refuses a value off its decimal validation, as REDCap does.
9. **ODM by the schema (E-23, E-25, STD-062).** Both exporters validate against the CDISC ODM 1.3.2 schema in the
   tests (`tests/fixtures/odm/`, MIT licence, unchanged), with `lxml` and with `xmllint` where installed. The EDC
   file now has `Length` (and `SignificantDigits` on a float), `BasicDefinitions/MeasurementUnit` with a
   `MeasurementUnitRef`, no repeat keys, `SDSVarName` only for SDTM names (not CDASH dates such as `BRTHDAT`), and one
   `SignatureDef` per meaning, language and words actually signed. The schema check found that the data-core export
   wrote `TransactionType="Snapshot"` on `SubjectData`, which the schema does not allow; it is gone.
10. **History in the file (E-23 f).** The file carries each value as decided and signed, with its `AuditRecord`.
    Earlier values stay in the trail (`decision`, `signature_void`), not in the file: a REDCap import of a file with
    several `ItemData` for one item keeps the last one, which would be wrong.
11. **`https` only (SEC-14).** The REDCap client refuses any URL that is not `https://` (the in-process simulator's
    `inproc://` stays for demos and tests).
12. **Cassettes (STD-060, CR-062).** `rc_bridge.cassette` records the ICD-04 calls (version, project, metadata,
    events and form-event mapping, data access groups, the record export with and without `dateRangeBegin`, an
    import with `forceAutoNumber`) without the token, and replays them; `tools.rc_cassette record` makes one against
    a REDCap test project, and CI replays every file in `tests/fixtures/redcap_cassettes/`. The one committed today is
    recorded from the simulator and says so.

## Not in this decision

- A cassette from a real REDCap test project: it needs the site's REDCap sandbox (owner question 2). Run
  `tools.rc_cassette record` against it and commit the file.
- Re-authentication at switch-on, a console page for the re-entry record, and a filed document id for the sponsor's
  letter (no document store yet): the rest of E-14.
- The names of people who decided but never signed in the ODM `AdminData` (E-23 g): TrialBox's EDC store has no
  printed name for them; the delegation log could give one later.
- Arms, events per arm and repeating instruments: T-302b. Signing with a directory account: T-205.

## Evidence

`tests/unit/test_edc_t115.py`, `tests/console/test_edc_pages_t115.py`, `tests/unit/test_datacore_capture.py`
(schema test), `tests/unit/test_edc.py` (ODM shape), `tests/unit/test_migrations.py` (edc version 3 pinned).

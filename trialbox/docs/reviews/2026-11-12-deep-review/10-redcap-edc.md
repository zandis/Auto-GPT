# 10. REDCap automation and EDC automation

| Field | Value |
| --- | --- |
| Document ID | TB-DR2-10 |
| Date | 2026-11-12 |
| Tree | `514ae9b` (branch `claude/deep-review-2026-11-12`) |
| Scope | `services/rc_bridge`, `services/rc_sim`, `services/edc`, `services/datacore` (forms, store, export, sync: the "own EDC"), `services/console/{edc_pages,copy_assist_page,sdv_page,rc_read,instruments_page,coded_view,i18n_cdash,i18n_edc}.py`, `services/orchestrator/{edc_api,study_api,studystore}.py` (parts), `tests/{rc_kit,edc_kit,odm_xsd}.py`, D-461, TB-REV-EDC-01 |
| Run | The 11 existing unit files of the area (251 tests, all pass, 110 s). 31 scripted cases of my own (three throw-away pytest files driving `EdcService`, `StudyService`, `DataCore` and `rc_sim` in-process on a private PostgreSQL; synthetic data from `tests/edc_kit.py` and `tests/rc_kit.py`). ODM files checked with `tests/odm_xsd.py` (lxml and `xmllint`). |
| Read only | Console pages and templates (no browser run), `edc_api.py` authentication path, OIDC signing (T-205), SDV page, copy-assist page, `tools/e2e_simple.py` stage 16, D-461, D-281, D-434, D-435. |
| Not run | A real REDCap (none exists for the project), the console in a browser, `tools/e2e_simple.py`, the Docker stack. |

The scripts are not kept in the repository. Each case below gives its exact inputs so it can be rebuilt from
`tests/edc_kit.py` in a few lines.

## 1. Reading in ten lines

1. The EDC prefill service is the most careful code in the product: no value without a citation, unknown is never "No",
   keyed signature over the whole act, signed values locked, send never overwrites a foreign value, every value read back.
   The 28 findings of TB-REV-EDC-01 are almost all closed and I could not reopen one of them by a run.
2. **Nothing in this area has ever talked to a real REDCap.** `rc_bridge/client.py:18` says so. Every "REDCap would
   refuse" test is TrialBox's own rule checked against TrialBox's own simulator.
3. The simulator is laxer than REDCap where it matters: it takes a choice code that is not in the dictionary, text in a
   number field, `115/11/01` in a date field, a checkbox as one bare column; it has no locking, no per-right tokens, no
   DAG enforcement. Shown by a run (EDC-001).
4. One silent-wrong on the write path: on a repeating instrument TrialBox writes its non-conflicting fields into an
   instance a person already used for a different adverse event. A human's "Rash" became "serious, hospitalised" (EDC-002).
5. Two silent-stale cases: the hospital corrects a value after the CRC confirmed it and nothing says so (EDC-004); a
   person corrects TrialBox's value in REDCap and TrialBox keeps showing, exporting and offering for SDV its old one (EDC-005).
6. One refused row blocks the whole study's send (locked form, checkbox item, any REDCap validation). Loud, but the other
   subjects' values are not written and nothing says which row was the cause beyond REDCap's own sentence (EDC-003, EDC-007).
7. A protocol amendment that removes an item which was already sent blocks the study's ODM export for good; there is no
   way out in the product (EDC-006).
8. Network drop, rate limit, lost answer: no duplicate record, no duplicate value, retry converges. But the write that
   REDCap applied has no line in TrialBox's ledger, and the retry books it as "already in REDCap" (EDC-008).
9. The "own EDC" is two things. The prefill store (`edc`) is close to Part 11 shape. The data core's built-in capture
   (`datacore`) is not: its history can be updated and deleted, has no reason for change, no signature, no lock (EDC-009).
10. Go-live answer: keep the REDCap link and the prefill review/sign store; go live in **copy-assist** mode (no API write
    to a sponsor's project) until a conformance run on a real REDCap passes; freeze the data core's capture as a working
    aid, not an EDC of record.

## 2. The eleven cases asked for (and what else was scripted)

Verdicts: **pass** (right result), **loud** (refused with a message a person sees), **silent-wrong** (wrong or stale
result, no message). "E" = the prefill send (`EdcService.send_redcap`); "L" = the link write-back of TrialBox's three
fields (`StudyService.read` with `write_mode`).

| # | Case and exact input | Result | Verdict |
| --- | --- | --- | --- |
| 1a | E: confirm `weight` 72.5, `urate` 8.4, `sex` 1 for S-001; sign; send. Then a person sets `weight=80` in REDCap (`/sim/records`). Send again; draft again. | First send: 3 sent. Second send: nothing to do. Re-draft keeps `confirmed 72.5`. The ledger still says `weight sent`. TrialBox never learns REDCap holds 80. | **silent-wrong (stale)** EDC-005 |
| 1b | Then TrialBox edits `weight` to 73 (unlock, reason), signs, sends. | `conflict: [weight]`; REDCap keeps 80. | pass |
| 1c | E: a person typed `weight=72.5` in REDCap first. TrialBox confirms 72.5, signs, sends; later edits to 73, signs, sends. | First send `already_there`. Second send `sent`: REDCap now 73. A value TrialBox did not write was overwritten. | **silent-wrong** EDC-012 |
| 1d | E: confirm `weight` 72.5; the lake row `o1` then changes to 82.5 (same day); draft again; sign; send. | Re-draft returns `confirmed 72.5`, no flag. Signed and sent as 72.5. | **silent-wrong (stale)** EDC-004 |
| 1e | L: first write sets `tb_status=4`; a person sets `tb_status=6` in REDCap; read again. | `conflicts: 1`, REDCap keeps 6, an open conflict row (`/data/conflicts` resolves it). | pass |
| 2a | E: `rc_sim._import_records` patched to answer 400 "…instrument that is locked for record '1'" (what a locked form does; the simulator has no lock). Send `weight`. | `RC-UPSTREAM` 502 with REDCap's sentence. Nothing written, ledger empty. The client has no call that reads a lock. | loud |
| 2b | E: two subjects (records 1 and 2) signed; record 1 locked as above; study-wide send. | The whole import is refused. Record 2 is not locked and is not written. A per-subject send of S-002 then works. | loud, **blocks others** EDC-007 |
| 3a | E: edit `sex` to `9` (choices `1, Male \| 2, Female`). | `edc.invalid: '9' is not a choice of sex`. | loud |
| 3b | Simulator alone: import `sex=9`, then `mh_gout=maybe`, `weight=heavy`, `brthdat=115/11/01`. | All four accepted and exported back. Real REDCap refuses each. | **simulator gap** EDC-001 |
| 4a | Lake gives `birth_date` / observation day as `049/05/01`/`115/11/01`, `0490501`/`1151101`, `昭和35年5月1日`/`令和8年11月1日`, `1960/05/01`/`2026/11/01`. | Both items unknown (`no_record`, `out_of_window`). Safe; the reason shown is not the real one. | pass (misleading reason) |
| 4b | Lake gives `0049-05-01` (a ROC year in ISO shape). | `brthdat` is drafted as `0049-05-01` with a citation. | **silent-wrong draft** EDC-016 |
| 4c | Note item of kind date; the note says `民國113年1月10日`, `令和6年1月10日`, `113/01/10`; a model stand-in answers `2024-01-10` with the right quote. | Unknown, `quote_not_found`, three times. The same note with `2024-01-10` drafts. | pass (zero yield) EDC-016 |
| 4d | A person types `049/05/01`, `昭和35年5月1日`, `1960/05/01`, `1960-5-1` into `brthdat`. | `edc.invalid: brthdat is a date (YYYY-MM-DD)` each time. | loud |
| 5a | E: the import reaches REDCap, then the client raises `RC-UPSTREAM … (ReadTimeout)`. Retry. | First call: 502, ledger empty, REDCap holds the three values. Retry: `already_there` x3. One record, no duplicate. | pass; **ledger gap** EDC-008 |
| 5b | L, `write_mode=create`: REDCap creates record 3 for GZQO-0042, the answer is lost. Read twice more. | First: `error RC-UPSTREAM`. Second: `updated 1, created 0`. Third: `unchanged 1`. Still one record with GZQO-0042. | pass |
| 6 | E: the import answers 403 "You do not have permissions to use the API" (the simulator has one token per project, no rights). | `RC-TOKEN` 409 "REDCap refused the token (no API rights for this project)". Nothing written. | loud |
| 7 | E: after signing, in REDCap: `sex` labels swapped (`1, Female \| 2, Male`); `weight` label `(kg)` to `(lb)`; `urate` gets branching logic `[mh_gout] = '0'`. Send. | `sex` held (`dictionary_changed`), `urate` held (`hidden`), `weight` **sent**. | pass, except the label EDC-015 |
| 8a | E, longitudinal project with repeating `ae` (the kit of `test_edc_t302b.py`). A person entered instance 2 with `ae_term=Rash`. TrialBox's `week4_arm_1__ae__2` holds `ae_term=Headache`, `ae_serious=1`, `ae_sae_reason=hospitalised`. Send. | `conflict: [ae_term]`, `sent: [ae_serious, ae_sae_reason]`. REDCap instance 2 is now `Rash / 1 / hospitalised`. | **silent-wrong** EDC-002 |
| 8b | E: send instance 9 when only instance 2 exists. | Written; instances are now 2 and 9. Nothing offers the next free number. | pass (see EDC-014) |
| 9a | E: two `send_redcap` calls at the same time. | Both answer `sent` x3; six ledger lines for three values. REDCap right. | pass (noise) EDC-021 |
| 9b | E: a person saves `weight=80` between TrialBox's read and its import. | `sent`, read back equal; REDCap holds 72.5. The person's value is gone; only REDCap's own log shows it. | **silent-wrong** (narrow window) EDC-011 |
| 9c | Two people: crc1's sign page is stale because crc2 confirmed another value. Then both edit `sex` at once. | Sign refused `edc.sign_changed`. Both edits stored in order, both in the trail. | pass |
| 10a | Sign three values; edit `weight` without re-authentication; with unlock and no reason; with unlock and a reason, as crc2. | `edc.locked` 423; `edc.reason`; accepted. `weight` loses its signature; `sex`, `urate` stay covered and sendable; decisions show `confirm`, `signature_void`, `edit` with old and new, who, when, why; `signature_void` row written. ODM then holds `sex`, `urate` only. | pass |
| 10b | Direct SQL: `UPDATE draft SET final='9.9'` for `urate`; `UPDATE signature …`; `DELETE FROM decision`. | The value is no longer sendable (hash differs); the two trail statements are refused by trigger. No trail row records the tamper (detection only). | pass |
| 10c | Data core: write `weight` 72.5 then 80; `UPDATE history …`; `DELETE FROM history …`. | Both accepted. History has old, new, by, at, source; no reason. | **fail** EDC-009 |
| 11a | E: ODM export with seven values, Japanese text, `<`, `&`, `"`, `]]>`. | Valid against ODM 1.3.2 (lxml and `xmllint` exit 0). `Length`, `SignificantDigits`, `MeasurementUnit`, one `SignatureDef` per meaning and language, CDASH `Alias`. | pass |
| 11b | E and data core: a value with U+000B in the middle, or U+FFFE. | Accepted at entry, sent to REDCap, and the ODM file is **not well-formed XML**. | **fail** EDC-010 |
| 11c | E: ODM of the repeating project of 8a. | Valid. | pass |
| 12 | REDCap allows 4, then 5 calls a minute (`SimState.rate_limit`). | 4: refused before the import, retry sends. 5: the import lands, the read-back is refused; ledger empty; retry says `already_there`. | loud; ledger gap EDC-008 |
| 13 | Amendment: `urate` (signed and sent) is renamed `uric_acid` in REDCap; dictionary read again; map saved with the new name; ODM export; then try to reject, then to edit, the old value. | Export refused `edc.odm_gap`. Reject refused (`edc.sent`). Edit refused (`edc.not_in_dictionary`). Export stays blocked. | **dead end** EDC-006 |
| 14 | A checkbox item `joints` (`1, Toe \| 2, Ankle \| 3, Knee`) typed as `1,3`, signed, sent. | The import row is `{"record_id": "1", "joints": "1,3"}`; the simulator takes it and exports a `joints` column. REDCap's flat format is `joints___1`, `joints___2`, `joints___3`. | **simulator gap + product fault** EDC-003 |

## 3. Status of earlier findings

Checked in code and by run on this tree, not from the response tables.

| Old ID | Severity | Status | Evidence |
| --- | --- | --- | --- |
| LIFE-021 (07) / CR-035, CR-036, CR-062 | High | **fixed** | Record lock: case 10a (`edc.locked` 423, unlock needs a reason). Keyed signature: `store.py:230-250`, case 10b. Arms and repeating instruments: `test_edc_t302b.py` passes; case 8, 11c. A new fault in the repeating path is EDC-002. |
| REG-021 (05b) | High | **fixed** | ODM `LegalReason` is now "Electronic signature of the person named; see the site's validation summary" (case 10 output); `test_the_odm_file_makes_no_part_11_claim` passes. |
| REG-024 (05b) | High | **partly** | `ODM_MEANING` (`service.py:69-71`) now says what the signer did and that a quote is a copy. No step makes the CRC open the EMR; the source/copy rule is still not a document (TB6-REG-05). |
| REG-025 (05b) | High | **fixed (read only)** | `METHODS` includes `oidc+mfa` (`store.py:120`); `PendingSign` and the provider round trip in `edc_pages.py:74-82, 718`. Not run against a provider. |
| REG-026 (05b), EDC part | Medium | **partly** | EDC trail tables are append-only by trigger (case 10b). The data core's `history` is not (EDC-009). No general reason-for-change in the data core. |
| E-12 | Medium | **fixed** | `test_e12_each_signed_value_shows_who_signed_when_and_the_meaning` passes; trail lists items per signature. |
| E-13 | Medium | **fixed** | Lock: case 10a. Second factor: `password+totp`, `oidc+mfa`. A sent wrong value still cannot be withdrawn in REDCap, only replaced (and see EDC-006). |
| E-14 | Medium | **fixed** | Stored re-entry record by another person (`test_e14_*` pass). |
| E-15, E-16 | Medium | **fixed** | Case 7; `test_e15_*`, `test_e16_*` pass. Gap: the label is outside the hash (EDC-015). |
| E-20 | Medium | **partly** | Decide, sign, sent, erase refusals are audited. Still raising before any audit line: `build` (`service.py:211-227`: switch off, bad date, no map, stale map), `put_map` (`:170-180`), `import_dictionary` (`:147-150`), `send_redcap` (`:369-372`), `preview` (`:568-571`), `export_odm` (`:677`). EDC-019. |
| E-21 | Medium | **fixed** for `edc` | Triggers on eight tables (case 10b). T-718 (roles that cannot drop a trigger) still open on the plan. |
| E-23 | Medium | **mostly fixed** | (a) `Length`/`SignificantDigits`, (c) `MeasurementUnit`, (d) OIDs, (e) `SignatureDef` per meaning and language: seen in case 11a. (b) repeat keys: the repeating file validates (11c). (f) still one `AuditRecord` per item (last decision only). (g) not checked. |
| E-24 | Medium | **open** | `grep -rl LakeFacts tests` finds only `tests/edc_kit.py`. The SQL of `prefill.py:64-108` and "proposed facts never count" are still proven against `FakeFacts` only. EDC-020. |
| E-25 | Medium | **mostly fixed** | Schema validation is a test (`test_e23_the_edc_odm_file_validates…`). No test with two users at once (my case 9c passes). |
| CR-034 (admin has seen the password) | - | not checked | Outside what I ran. |

## 4. Findings

Counts: 2 Critical, 8 High, 10 Medium, 2 Low.

| ID | Severity | Finding | Evidence | Impact | Fix | Card | Flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EDC-001 | Critical | **No code of this area has run against a real REDCap, and the simulator accepts what REDCap refuses.** | `rc_bridge/client.py:18-19` ("Tested only against rc_sim so far"). Case 3b: `rc_sim` took `sex=9`, `mh_gout=maybe`, `weight=heavy`, `brthdat=115/11/01`. `rc_sim/app.py:234-244` checks decimal formats only. No lock, no rights per token, no DAG per token, checkbox as one column (case 14). The simulator computes calculated fields with TrialBox's own `edc.logic` (`app.py:351-390`), so "REDCap's calculation equals ours" compares the evaluator with itself. | Every write-path guarantee is unproven at the first real site. A fault shows as a refused batch or, worse, as a value on the wrong row in a sponsor's project. | A conformance run on a real REDCap (section 7), recorded as cassettes (`rc_bridge/cassette.py` exists), replayed in CI; then make the simulator refuse what the cassettes show REDCap refuses. Until it passes, a study goes live in `copy` mode only. | NEW-EDC-1 "REDCap conformance run on a real instance, cassettes, simulator made as strict" (M) | Go-live both |
| EDC-002 | Critical | **On a repeating instrument TrialBox merges its values into a person's different instance.** Conflict is judged per field, so the fields the person left blank are filled. | Case 8a, by run: REDCap instance 2 `ae_term=Rash` (human) became `Rash / ae_serious=1 / ae_sae_reason=hospitalised`. `service.py:471-484`. | A human-entered adverse event is marked serious with another event's reason, in the EDC of record, with a "sent, read back equal" line. Wrong safety data. | For a repeat instance, treat the row as one unit: if any field of the instance holds a value TrialBox did not write, hold every value of that instance (`instance_taken`) and say so. Offer "next free instance" (EDC-014). | NEW-EDC-2 "A repeat instance is written whole or not at all" (S) | Go-live both |
| EDC-003 | High | **A checkbox item is sent as one bare column.** | Case 14: import row `{"joints": "1,3"}`. `service.py:501-503`. `mapping.check` stops drafting a `multi` item, not a typed and signed one. The conflict read also looks for a `joints` column that REDCap never exports. | On REDCap the whole import is refused (EDC-007: every other value of the send with it). Not seen in any test because the simulator takes it. | Hold a `multi` item at send with its own reason until the import writes `field___code` columns and the read folds them back (`rows.py:99` already reads `___`). Make the simulator export and require `___` columns. | NEW-EDC-3 "Checkbox items: hold now, `___` columns next" (S+M) | Go-live both |
| EDC-004 | High | **New source data after a confirmation is never shown.** A re-draft skips decided items. | Case 1d: source 72.5 to 82.5, re-draft answers `confirmed 72.5`, signed, sent. `store.py:460-488` (`add_drafts`). | The signature says "I compared each value with the source cited"; the source has since changed and nobody is told. Late lab corrections are routine. | On every draft run, build the item anyway and compare with the decided value's citation (row, day, value). When it differs: mark "source changed since" on the review page, hold the value from signing and sending until a person keeps or changes it (with a reason). | NEW-EDC-4 "Source changed since confirmation" (M) | Go-live both |
| EDC-005 | High | **A value TrialBox sent and a person later corrected in REDCap stays "sent" in TrialBox.** | Case 1a. `sendable` drops a value once `sent_value == final` (`store.py:757`), so it is never read again. | The ODM export, the SDV sheet and the copy-assist sheet show a value that is no longer the EDC's. A monitor verifies the wrong number. | A reconciliation read (on each send and in the nightly `rc_read`): for every value with a `sent` line, read REDCap; list "changed in REDCap" with both values; one action takes REDCap's value as an edit with a reason, another keeps TrialBox's (conflict stays open). | NEW-EDC-5 "Sent values are re-read; drift is listed and resolved" (M) | Go-live both |
| EDC-006 | High | **An amendment that removes a sent item blocks the study's ODM export for good.** | Case 13, by run: `edc.odm_gap`; reject refused `edc.sent`; edit refused `edc.not_in_dictionary`. `service.py:680-686`, `store.py:626-627`, `service.py:305-307`. | After the first protocol amendment that renames or drops a field, the site cannot produce its electronic copy of signed records. | A "retire" decision for a value whose item left the dictionary (re-authentication, reason; kept in the trail). The export lists retired values in the audit line and leaves them out, or writes them under the dictionary version they were signed under. | NEW-EDC-6 "Retire a value whose item an amendment removed" (S) | Go-live both |
| EDC-007 | High | **One refused row stops the whole study-wide send.** One import call carries every record (`service.py:515`). There is no read of a form's lock before the write. | Case 2b: record 1 locked, record 2 not written. | Month-end sends fail for all subjects because one form was locked, one field is a checkbox, or one value fails a REDCap rule TrialBox does not know. The message is REDCap's sentence cut at 200 characters (`client.py:126`). | When a multi-record import is refused, send again one record at a time; ledger each record's outcome with REDCap's sentence (`refused`). Show them per subject. | NEW-EDC-7 "Per-record fallback and a `refused` result" (S) | Go-live both |
| EDC-008 | High | **A write REDCap applied can have no line in TrialBox's ledger.** | Cases 5a and 12 (limit 5): REDCap holds the values, `sent` is empty, the audit line says `refused: RC-UPSTREAM`/`RC-RATE`. The retry books `already_there` under whoever retries. | The trail of the box cannot say who wrote the value into the sponsor's EDC and when. With EDC-012 it also decides wrongly who owns the value. | Write an `attempt` row (who, when, value hash) before the import; on the next send, an attempt whose value is read back equal becomes `sent` under the first person. | NEW-EDC-8 "Ledger the attempt before the import" (S) | Go-live both |
| EDC-009 | High | **The data core's capture is not an EDC of record.** Its `history` can be updated and deleted; a change has no reason; no signature; no lock. | Case 10c: `UPDATE history …` and `DELETE FROM history …` accepted; columns `at, by, event, field, id, new, old, record, source, study`. `datacore/store.py:124-147`. `entry_pages.py` has no reason field. | If a registry or an investigator-initiated study uses the built-in forms as its only data capture, the record fails Part 11 §11.10(e) and the ER/ES 真正性 requirement at the first question. | Decide its standing (section 5). If it stays a working aid: say so on the entry page and in the record inventory. Either way make `history`, `conflict`, `subject_step` append-only by the same trigger as `edc` (a few lines) and ask a reason on a change of an existing value. | NEW-EDC-9 "Data core trail append-only; reason on change" (S); standing under T-718 | Go-live both |
| EDC-010 | High | **One control character makes the ODM file unreadable.** | Case 11b: values `ok \x0b vertical tab` and `… ￾` are accepted, signed, sent, and both exporters write a file lxml refuses ("invalid character in attribute value"). `edc/odm.py`, `datacore/export.py:199`. A NUL raises an uncaught `DataError`. | Text pasted from a hospital note often carries a vertical tab or form feed. The whole study's export breaks; the value also goes to REDCap as it is. | Refuse characters XML 1.0 does not allow at entry (`datacore.forms.problem`, code `chars`) and at ODM import; test with U+000B, U+000C, U+FFFE, NUL. | NEW-EDC-10 "No XML-illegal character in a value" (S) | Go-live both |
| EDC-011 | Medium | A value a person saves in REDCap between TrialBox's read and its import is overwritten. | Case 9b. The read is at `service.py:443`, the import at `:515`, with the hidden-value loop and a database read between. | Rare, silent; REDCap's API has no conditional write, so it cannot be closed, only narrowed. | Read the planned rows once more immediately before the import and drop any that changed; keep the value seen before in the ledger line. | NEW-EDC-8 (same change) | Go-live both |
| EDC-012 | Medium | `already_there` makes TrialBox the owner of a value a person typed. | Case 1c: later overwritten. `store.py:783-788` counts `already_there` as written by TrialBox. | A human-entered value is replaced without a conflict line. | Ownership from `sent` (and reconciled `attempt`) only; after `already_there` a different value in REDCap is a conflict. | NEW-EDC-8 (same change) | Go-live both |
| EDC-013 | Medium | The send banner drops six reasons and never shows a conflict's REDCap value; there is no resolution step for a send conflict. | By reading: `console/edc_pages.py:244-257` lists 12 results; `edc/service.py:763-765` has 18 (`not_on_event`, `wrong_arm`, `repeating_form`, `not_repeating_form`, `hidden`, `logic` missing). The service returns `redcap: there`; the page passes counts only (`:538`). The link fields have `/data/conflicts`; the prefill has nothing. | A value held as hidden or on the wrong arm shows as nothing after "Send". The coordinator finds it only on the trail page. | One list of results (import the service's tuple); after a send, list each held value with its reason and, for a conflict, both values, with "take REDCap's value" (an edit with a reason). | NEW-EDC-11 "Send results page" (S+M) | Go-live both |
| EDC-014 | Medium | The visit, and the instance of a repeating instrument, are typed as free text (`week4_arm_1__ae__2`). | `templates/edc.html:55` (`<input name="visit" placeholder="event_1_arm_1">`). Case 8b: instance 9 accepted. | Typing errors become `no_event` at send, after review and signature; a wrong instance number is EDC-002. | A select filled from the project's events and repeating set, with "new instance (next free)". | NEW-EDC-2 (same card) | Go-live both |
| EDC-015 | Medium | A changed field label is not seen; in REDCap the unit lives in the label. | Case 7: label `(kg)` to `(lb)`, `weight` sent. `datacore/forms.py:407-416` leaves the label out on purpose. | A sponsor edits the label to another unit; TrialBox keeps sending the old unit. | Keep a second hash over label and field note; a change holds the value (`label_changed`) until a person confirms the item again. | NEW-EDC-12 "Label change holds a value" (S) | Later |
| EDC-016 | Medium | Dates in local form. (a) A date written in a note as 民國 or 令和 or `113/01/10` can never be drafted, and the reason shown is `quote_not_found`. (b) A lake date `0049-05-01` is drafted as a birth date. | Cases 4b, 4c. `prefill.py:333-340` (digits of the value must be in the quote); `prefill.py:208-213` (no check of the year). | (a) no yield for date items from notes at both sites; the CRC is told the quote was not found. (b) a wrong birth year reaches the review page with a citation. | (a) Compare the quote after turning era and ROC years into Gregorian digits. (b) A drafted date before 1900 is `invalid`. | NEW-EDC-13 "Era and ROC dates in prefill" (S) | Go-live both |
| EDC-017 | Medium | The REDCap API token is a plain file. | `orchestrator/studystore.py:213-224` (0600, ASCII). The signature key beside it is wrapped under the KEK (`edc/store.py:187-210`). | The token writes to a sponsor's project as one REDCap user. A copy of the secrets folder is a copy of that right. REDCap's log names that user for every API write, never the signer. | Wrap the token like the signature key; ask each site for a service user per study with export and import rights only, and say in the sponsor letter how API writes are attributed. | T-717 (extend) | Go-live both |
| EDC-018 | Medium | Fixed 10 s timeout, no retry, and a whole-project export on every send. | `rc_bridge/client.py:79` (`timeout: float = 10.0`, not a setting: OD-10). `service.py:428` exports `[id, key, items]` of every record. 429/503 raise at once (`client.py:120`). The prefill path answers `RC-RATE` as 409 (`service.py:540`) while `RcError.STATUS` says 503. | A large project or a slow hospital proxy makes every send fail. | The timeout as a setting with its reason; export only the records of the send (by the link's record ids, one lookup call for unknown ones); wait once on `Retry-After`. | NEW-EDC-14 "REDCap client: timeout setting, narrow export, one polite retry" (S) | Go-live both |
| EDC-019 | Medium | Early refusals are still not audited (E-20). | `service.py:211-227`, `170-180`, `147-150`, `369-372`, `568-571`, `677`. | "Every refusal is audited" is not true for six entry points. | One wrapper that audits any `EdcError` raised by a public method. | T-115 follow-up, NEW-EDC-15 (S) | Later |
| EDC-020 | Medium | `LakeFacts` has no test on a lake (E-24). | `grep -rl LakeFacts tests`: `tests/edc_kit.py` only. | The SQL that feeds every draft, and the rule that proposed facts never count, are proven against a fake written to pass. | A lake-backed test with proposed, suspected, refuted, cancelled and entered-in-error rows, and a ROC-year date. | NEW-EDC-16 (S) | Go-live both |
| EDC-021 | Low | Two sends at once both write and both ledger `sent`. | Case 9a: six lines for three values. | Noise in the trail. | An advisory lock per study around the send; the second caller is told a send is running. | NEW-EDC-8 (same change) | Later |
| EDC-022 | Low | A reason for change and a citation text are cut at 300 characters without a word. | `store.py:610, 639, 643, 650` (`[:300]`). | A long reason is stored incomplete in a regulated trail. | Refuse over the length with a message, or store whole. | NEW-EDC-15 (same card) | Later |

### EDC-001: what the simulator does not model

| REDCap behaviour | Simulator | Why it matters here |
| --- | --- | --- |
| Value validation on import (choice codes, yes/no, integer, number, date and datetime formats, min/max as hard or soft) | only `number_Ndp` and comma decimals | TrialBox's `forms.problem` is the only guard; nobody knows where it differs from REDCap |
| Checkbox columns `field___code` (import and export) | one column with `1,3` | EDC-003 |
| Record and form locking, e-signature module; the lock cannot be read through the core API (an external module is needed) | none | EDC-007; the real error text and whether one locked form refuses the batch are unknown |
| User rights of the token: export without import, no API right, expired user, DAG-restricted user | one token per project, all rights | case 6 was scripted by patching; the real status and body for "export yes, import no" must be recorded |
| `returnContent`, `returnFormat`, the shape of errors (JSON, plain text or XML bodies; 400 with a list of per-value errors) | JSON `{"error": …}` only | `client.py:122-126` reads `.json().get("error")`; a list body gives an empty message |
| `forceAutoNumber` with a DAG prefix in record names (`12-3`) and record auto-numbering off | integer max + 1 | `writeback.py` create mode |
| Date format parameter and project date settings; decimal character | none | dates are sent as Y-M-D, which is the API default, but unproven |
| Data access groups: a DAG-bound token sees and writes only its group | export filter only | the prefill path never names a DAG |
| Survey fields, `_complete` status fields, file and signature fields, descriptive fields, missing-data codes, `@READONLY`/`@CALCTEXT` action tags, piping | none | `_complete` is never written by TrialBox: decide whether a prefilled form stays "Incomplete" |
| Branching logic and calculations as REDCap evaluates them | TrialBox's own evaluator | the comparison is circular |
| Rate limit (per minute, per user, 429 text), request size limits, project in production with draft mode | a counter | case 12 |
| REDCap's own logging of API writes | none | what the sponsor's audit shows for a TrialBox write |

## 5. Should the product carry both for go-live?

There are three parts, not two.

| Part | What it is | Evidence | Verdict |
| --- | --- | --- | --- |
| REDCap link (`rc_bridge`, S21) | Reads status back by screening number; writes TrialBox's three fields on its own instrument | Cases 1e, 5b pass; conflicts are listed and have a page; never touches a REDCap-owned field (`link.py:151-171`) | **Keep.** Needs EDC-001 before the first real project. |
| Prefill store (`services/edc`: draft, review, sign, trail, ODM, copy-assist, SDV sheet) | A review-and-sign layer over source data; not a data-capture system | Cases 9c, 10a, 10b, 11a pass; trail append-only; keyed signature; re-authentication; lock | **Keep. Go live in `copy` mode** (D-434: no API write to a sponsor's project). Turn the API send on per study only after EDC-001 to EDC-008. |
| Data core capture (`datacore` built-in forms, entry and history pages, its own ODM/CSV exports) | A small EDC of its own | Case 10c: trail alterable, no reason, no signature, no lock; ODM without audit records; EDC-010 | **Freeze.** Keep it for what the box needs itself (screening log, lifecycle, SAE register working copy, the three link fields). Do not offer it as the EDC of record for go-live. Make the trail append-only anyway (EDC-009). |

Reasons to freeze and not drop: the lifecycle, the screening log and the link sync all store their values in the data
core, so it cannot go. Reasons not to grow it: a second EDC needs the whole Part 11 and ER/ES set again (signature, lock,
reason for change, validated export, an EDC management sheet for PMDA), both sites already run REDCap, and every hour
there is an hour not spent on EDC-001.

## 6. What to drop or simplify

- `rc_bridge/writeback.py` `plan()`, `WritePlan`, `digest()`: the module text says it "stays as the rules' reference
  (tests)"; the live path is `LinkSource` through `datacore.sync`. Two writers' rules for the same three fields. Drop
  `plan()` and move its tests to `LinkSource`.
- Two ODM exporters (`edc/odm.py` and `datacore/export.py`) with their own escaping and OID rules; EDC-010 is in both.
  One writer module.
- Two lists of send results (console and service) and two `SOURCES`/`WHAT` tables (`edc_pages.py:62-64`,
  `mapping.py:32-41`). Import one from the other.
- The simulator's `/sim/records` lever writes anything; after NEW-EDC-1 it should refuse what REDCap refuses, with one
  explicit "force" flag for tests that need a broken state.
- `erase_hidden` (`overwriteBehavior=overwrite`) is the only destructive call. It is careful, but it rests on TrialBox's
  own reading of REDCap's branching logic. Keep it off until that reading is checked on a real instance.

## 7. What the plan must change

1. **NEW-EDC-1 (M), first, needs the owner's instance (section 8).** Blocks turning the API send on anywhere. Order: get
   the instance, record cassettes for the 14 behaviours of the table in EDC-001, fix what differs, tighten the simulator.
2. **Go-live mode is `copy`** for every sponsor study at both sites; say so in plan v7. The API send is a per-study
   switch after NEW-EDC-1 to NEW-EDC-8. This removes EDC-002, 003, 007, 008, 011, 012 from the go-live path without
   removing the value of prefill.
3. **Before any real prefill, also in copy mode:** NEW-EDC-4 (source changed, M), NEW-EDC-6 (retire, S), NEW-EDC-10
   (illegal characters, S), NEW-EDC-13 (era dates, S), NEW-EDC-16 (lake test, S). None depends on REDCap.
4. **With the API send:** NEW-EDC-2 (S), NEW-EDC-3 (S then M), NEW-EDC-5 (M), NEW-EDC-7 (S), NEW-EDC-8 (S),
   NEW-EDC-11 (S+M), NEW-EDC-14 (S). NEW-EDC-8 before NEW-EDC-5 (drift needs a true ledger).
5. **Data core:** NEW-EDC-9 (S) now; write its standing ("working aid, not an EDC of record") into the record inventory
   that REG-022 asks for. T-718 stays as planned and should cover `datacore` after `edc`.
6. T-731 (REDCap as a read source) should reuse `rc_bridge.client` and wait for the cassettes of NEW-EDC-1.

## 8. Needs GCP / owner hardware

No GPU is needed. What is needed is a REDCap.

**How to get one.** REDCap is not open source. An institution gets it free of charge by signing the REDCap Consortium
licence with Vanderbilt; the licence is for a non-profit institution and the code may not be passed on, so it cannot sit
in this repository or in CI. Two ways:

- (preferred) each site's own REDCap, which both hospitals are expected to run already: the owner asks the REDCap
  administrator for a **test project (development status, no real data)** per site;
- or the owner's institution, as a consortium partner, installs a local REDCap (PHP and MySQL, one small VM) from its
  own download and gives the reviewers network access to it.

**What the owner must provide:** the REDCap version; the base URL; a test project built from `tests/edc_kit.py` `CRF`
plus the repeating and longitudinal set of `tests/unit/test_edc_t302b.py`, with one checkbox field, one `date_dmy` field
and one `number_1dp` field; four API tokens (export and import; export only; a user bound to a DAG; an expired user);
the Locking/E-signature right for one user so a form can be locked by hand; whether the "Locking API" external module is
installed; the site's API rate limit.

| Test | Command and inputs | Record | Pass |
| --- | --- | --- | --- |
| R1 validation | `RedcapClient.import_records` with `sex=9`, `mh_gout=maybe`, `weight=heavy`, `brthdat=115/11/01`, `weight=72` on a `number_1dp` field | status, body, whether the batch is refused whole | each refused; the body is read into `RcError.message` in full; `forms.problem` refuses the same five |
| R2 checkbox | import `joints=1,3`, then `joints___1=1` | status, body, export columns | bare column refused; `___` columns round-trip |
| R3 lock | lock form `baseline` of record 1 by hand; `send_redcap` for records 1 and 2 | status, body, what was written | TrialBox reports record 1 `refused` with REDCap's sentence and writes record 2 (after NEW-EDC-7) |
| R4 rights | send with the export-only token, the expired user, the DAG user on a record of another DAG | status, body | `RC-TOKEN` or `RC-FORBIDDEN` with a sentence that names the missing right; nothing written |
| R5 repeat and arms | the round trip of `test_round_trip_with_arms_events_and_a_repeating_ae_instrument` against the instance | every row | equal to the simulator's rows |
| R6 logic | the 30 expressions of `test_the_evaluator_computes_as_redcap` and `test_branching_logic_shows_as_redcap` as real calc fields and branching | REDCap's value per case | equal; any difference listed and `erase_hidden` kept off |
| R7 auto-number | create mode with and without a DAG, auto-numbering on and off | `returnContent=auto_ids` body | ids parsed; one record per screening number after a forced retry |
| R8 limits | 1,000 synthetic records; one send | seconds per call, any 429 | under the configured timeout; a 429 is retried once |
| R9 log | after one send, REDCap's Logging page | the user and the text of the entry | written into the sponsor letter template |

## 9. Small certain fixes

1. **EDC-013 (Medium, but certain and three lines):** `services/console/edc_pages.py:244-257`: add `"not_on_event",
   "wrong_arm", "repeating_form", "not_repeating_form", "hidden", "logic"` to `SEND_RESULTS` and one more span in
   `templates/edc.html:11` and `edc_review.html:16`. Failing test first: a console test that sends a value REDCap hides
   and expects the count in the redirect query.
2. **EDC-010 (High):** `services/datacore/forms.py:328` (`problem`), before the type checks:
   `if re.search("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]", value): return {**p, "code": "chars"}` and a `_WHY` line.
   Failing test first: `svc.decide(..., "edit", value="ok \x0b x", …)` must raise `edc.invalid`; today the export that
   follows fails `odm_xsd.problems` with a parse error.
3. **EDC-003 (High), the hold only:** `services/edc/service.py:416-420`, add a branch
   `elif lf.kind == "multi": why, text = "format", "a checkbox item is not sent yet"`. Failing test first: my case 14
   (a typed `joints=1,3` must come back under `format`, and no import row may hold a bare `joints`).
4. **EDC-009 (High), the trigger only:** `services/datacore/store.py`: the `_append_only` routine of
   `services/edc/store.py:269-288` for `history` (and `conflict` inserts stay, updates of `resolved*` allowed).
   Failing test first: `UPDATE history SET new='x'` must raise.
5. **EDC-016 b (Medium):** `services/edc/prefill.py:198-201` (`_value`): a `date` value below `1900-01-01` is
   `invalid`. Failing test first: case 4b.

## 10. What is good

- The send's order of checks (target, map row, dictionary entry, format, duplicate key, event, arm, instance, hidden
  field, foreign value, re-read before import, read-back) is right and each has a test.
- Dictionary change between signature and send is caught, including swapped choice labels (case 7).
- No duplicate record or value after a lost answer, on both write paths (cases 5a, 5b, 12).
- The signature: keyed, covers who, role, meaning text and language, method, time and every value hash; a changed
  value loses it with a `signature_void` row; version 1 rows cover nothing (D-461); trail tables refuse UPDATE and DELETE.
- Signing a stale page is refused (case 9c). A signed value is locked (423) and needs re-authentication and a reason.
- The ODM file validates against the official schema, in CI, with `xmllint` as a second reader, and makes no Part 11
  claim any more.
- Unknown never becomes "No", for coded items and for notes; proposed facts never count; another unit is not converted.
- The link write-back cannot touch a REDCap-owned field, and a human change of a TrialBox field is a listed conflict
  with a resolution page.
- Copy-assist exists, so prefill has value without any API write.

## 11. What was not checked

- Anything against a real REDCap (the whole of section 8).
- The console pages in a browser; EDC-013 and EDC-014 are by reading the templates and the route code.
- OIDC signing against a provider; the TOTP path; CR-034.
- The orchestrator's actor assertion on the EDC routes (E-01): the existing tests pass; I did not attack it again.
- `tools/e2e_simple.py` stage 16 and the Docker stack.
- The SDV page's access rule, the instruments page, `coded_view.py`: read at the level of their module text only.
- ODM import (D-435) beyond its existing tests; CDASH tag tables beyond the aliases seen in case 11a.
- The database roles on a box (T-718): my SQL ran as the test owner; on a box the service role is what counts.
- Test-bed note, not a product finding: `tools/pglocal` could not start its cluster under this session's scratch folder
  because the folder's parent kept losing the search bit; the runs used a root under `/var/tmp/trialbox-0/` (the
  Makefile's default `TB_SCRATCH`), removed afterwards.

# D-1257 The SS-MIX2 reader answers its independent reviews

- **Card:** 10B-2c (plan 10, `docs/plan/47-plan-10-2026-11-18.md` Track B), lane J. In rc1's scope: no release tag
  while a delta night can lose or mis-attach a record.
- **PR:** #1238 (branch `agent/10b2c-ssmix2-second-review`, cut from master `d28f6c03`)
- **Date:** 2026-11-20
- **Status:** proposed. Lane J ruled Z1 and I2 on 2026-11-19 (both as written below) and gave the real shapes of
  the MEDIS release (section "The MEDIS master as MEDIS ships it").
- **Amends:** D-1252 (P6, P8, class F, "the specification's own ZPR shape without the master", the shape of
  修飾語区分, and "one MEDIS code on two different rows is read for neither"), #1095's reading of an end day, a
  repeated usage, an offset and a lab correction. D-1000 (the record key) stands.
- **Supersedes (dated note, 2026-11-20):** the sentence of D-1252 section B "ZPR-2 and ZPR-5 must name PRB-3's own
  disease ...; then the diagnosis may be confirmed" and class F's link through ZPR-5. Lane J reversed that ruling:
  what cannot be verified is not confirmed. D-1252 is not rewritten; it carries a pointer here.

## Context

Three reviews by tools that did not write the reader: the second tool's review of #1189 (seven findings and the
test helper) and two reviews of #1095 (seven findings run, ten read). Each finding was first reproduced on master
`d28f6c03` as a storage tree, and on `8bfebd70` (master before #1189) to say whether #1189 brought it.

## What was wrong

1. **The delta proof compared against the wrong thing.** The test helper seeded the "full rebuild" with night
   one's rows, so a record night two neither sent nor tombstoned passed in both lakes.
2. **A tombstone could name a record still in force.** A delta night sends only its window; a tombstone for an id
   an unchanged record carries removed that record (the plain key of two re-keyed prescriptions was also an
   injection's id).
3. **An id the reader had published was rewritten.** #1189 published the order number normalised (`RX01` for a file
   named `ＲＸ０１`); the id an earlier night stored was neither replaced nor tombstoned, so a cancelled order stayed
   active beside its cancellation.
4. **An administration was tied by its number alone**: across the days of a reused number, and across prescriptions
   and injections.
5. **A newer version did not delete what it dropped** for lab results (the ids published while two versions tied,
   and any result a newer version or a deleted file no longer held), and a newer order message with no drug line
   deleted every line of the order.
6. **A change that was not a hospital file was not a change**: a diagnosis read through the licensed master stayed
   as it was read after the master changed.
7. **Something not positively recognised was read as confirmed, ended or dosed**: a ZPR-5 exchange code without
   the master; an end or outcome day that had not come; the first of several usages; a date with half a time.
8. **A document named for another patient was stored under its folder's patient.**
9. An out-of-range offset written full-width was not seen, and an order number shaped like a time with an offset
   quarantined its message; a lab correction replaced another day's result.

## Decision: the rules

- **T1 (tombstones).** A tombstone is never sent for a patient and key that a row of the table's whole read
  carries. One id, one tombstone.
- **T2 (lab versions).** One file is one order's results (D-1252 R7): a result an older version named and the
  version in force does not is a tombstone; a deleted file tombstones what every older version named.
- **I1 (ids are written as published; amends P8).** The order number is compared after `key_part` and never
  rewritten: an id is built from the number as the record's oldest file wrote it. A record whose versions write it
  in several widths has the ids each version's own name would give tombstoned, and its rows sent, on every night.
- **I2 (one number, two types; extends P6; ruled by lane J).** The record is patient, day, データ種別 and オーダNo (R1).
  A prescription and an injection of one patient with one number are keyed `<number>@<データ種別>` (then `@<day>`
  by P6) from the first night both are filed, any flag; every earlier form of the id is tombstoned. No doubt is
  added: unlike two days of one number, neither is read as unknown.
- **A1 (administrations).** OMP-11 is of a prescription, OMP-12 of an injection. When the order number is filed on
  several days the administration fills no line (it is a row of its own, counted). An administration with no order
  never takes the id of an order of the other kind.
- **V1 (a version must be readable as one).** A newest order message with an ORC and no RXE is not a version: the
  older versions are read as unknown (P4). A file of flag 0 deletes whatever it holds.
- **M1 (the master is part of a row's change time).** A diagnosis read by the master rule, or whose ICD-10 was
  looked up in the licensed disease table, carries the load time of the newest active release, which
  `adapter.licensed.tables()` now gives with its tables (`loaded_at_of`); it is taken as the latest local time it
  can be (UTC+14). Tables whose load time is not known: such rows are sent on every night.
- **Z1 (ZPR without the master; changes D-1252; ruled by lane J).** A 病名管理番号 and a 病名交換用コード cannot be
  compared without the master, so a right ZPR-5 and a conflicting one look the same. Without the master a ZPR-2 or
  ZPR-5 code confirms only when it is literally a code PRB-3 itself carries. The specification's own example shape
  (ZPR-2 the number, ZPR-5 the exchange code) is unknown without the master and confirmed with it. D-1252 had it
  confirmed without the master (and class F let ZPR-5 link a ZPR-2 it could not check). The whole class is counted
  under one reason, "a ZPR disease code cannot be verified without the MEDIS master", in the night's reader counts
  (`reader.json`, `read`), so a site sees one cause and its cure: **an SS-MIX2 site that sends ZPR segments needs
  the MEDIS disease and modifier masters loaded for those diagnoses to read confirmed.**
- **D1 (dates).** An end or outcome day after the file was written is unknown, never ended. A date is real only
  with 8, 10, 12 or 14 digits.
- **U1 (usage).** TQ1-3 repeated: no code, every text kept, no daily dose.
- **O1 (offsets).** Checked in the fields the reader reads as times (`hl7.TIME_FIELDS`), digits and sign in any
  width; a value in any other field is not a time.
- **L1 (lab corrections).** Under the specification's key a `C` replaces only results of its own day; under
  `unique` the days are one record, as before.
- **X1 (documents).** A file or content folder of the extended storage whose seven-part name names another patient
  than its folder is set aside, counted and listed; the id an earlier night stored it under is tombstoned.

## The MEDIS master as MEDIS ships it

The owner's decision (2026-11-19): the master is not bundled and never enters the repository; a site downloads it
from MEDIS and the box loads it. Lane J ran master against the real release (ICD10対応標準病名マスター V5.18,
2026-06-01) and sent its shapes; every fixture here is invented in those shapes. Four faults, none visible with the
synthetic tables D-1252 was tested on, and a fifth found on the first run of this card's loader:

- **R1 修飾語区分.** Every value of the release is a letter and seven digits (`A2000000`); D-1252 read only eight
  digits, so with the real master every diagnosis that carried a modifier read unknown. Rule: exactly eight ASCII
  characters, the second a digit 1 to 9; the class is the second character (`licensed.modifier_class`).
- **R2 rows and concepts.** The loader keyed the 病名基本テーブル by 病名交換用コード and read neither row of a code
  "given twice with different content". In the release one exchange code is shared by design (a renamed entry
  beside its old 表記, a main name and its synonym). Rule: the row key is the 病名管理番号; an exchange code names a
  concept, the set of its rows. A diagnosis coded by exchange code is in the master when a current row (変更区分 0,
  3, 5) carries the code, and its display name is the 病名表記 of any current row of the code. Deleted rows are
  stored and marked. A fault is only two different rows with one 病名管理番号 (neither is read), or current rows of
  one code that disagree on ICD-10 (the code reads as unknown and the load lists it).
- **R3 no header row.** The tables have none; the titles are in `option/ttl_*.txt`. `licensed.load_release(store,
  source, *, by)` takes the release's folder or zip, reads the titles from it and the version and date from
  readme's first line (a readme that does not give them refuses the load; no version is guessed), and writes the
  three tables in one transaction. `licensed.check_release(source)` is the same code and writes nothing. A zip is
  read in memory by base names only (no path is taken from a member name, nothing is extracted), within bounds on
  its size, its members and each file.
- **R4 the titles.** The ICD-10 title is ＩＣＤ１０‐２０１３ with U+2010, which NFKC leaves, so the column was lost
  and every row had no ICD-10. Titles (never values) are compared with every hyphen written as `-`; `レセ電算コード`
  is a receipt-code title.

- **R5 the character set is declared.** Lane J ran the release loader on the real release and it was refused: one
  line of the index table is Shift_JIS bytes that are also valid UTF-8, which the shared detector reads as two
  character sets mixed. MEDIS publishes the release in Shift_JIS, so its files are read as that, strictly, and the
  detector is not asked; a byte Shift_JIS does not hold refuses the release with its line. The detector is unchanged
  for every other caller; a single table is loaded the same way with `load --encoding cp932`.

**What is stored** (`adapter.licensed`; the contract of card 10B-21/22's page):

- `medis` (as `tables()["medis"]` gives it): key the 病名交換用コード. `display` and `target_code` (ICD-10, exactly
  as the release writes it) of the concept's preferred row: of its current rows the lowest 採択区分, else of all its
  rows when every one is deleted. `extra` (JSON): the preferred row's `management_no`, `change`, `adoption`,
  `kana`, `receipt_code`, `multi_class`, `field`, `successor`, `no_solo`, `no_claim`; `rows`, every row of the code
  as `{no, name, icd, kana, change, adoption, multi_class, field, successor, no_solo, no_claim, receipt_code}`
  (empty fields left out); `icd_conflict` when its current rows disagree. `licensed.medis_rows(tables["medis"])`
  gives every row by 病名管理番号.
- `medis_modifier`: key the 修飾語管理番号; `display` the 修飾語表記; `extra`: `change`, `exchange_code`, `position`,
  `modifier_class` (as written), `class` (its second character, when valid), `exclusive_group`, `kana`,
  `receipt_code`.
- `medis_index` (the 索引テーブル): the pair (対応用語コード, 索引用語); `extra`: `target_kind` (病名修飾語区分),
  `kana_kanji`, `synonym`, `variant`. It is not carried by `tables()` and is listed by `status` only when asked;
  `TermStore.lookup_term(term)` gives a term's rows. `0000` is stored and never resolved.
- `status`: per list also `released`, `table_rows`, `current_rows`, `loaded_by` and `sha256` (of the whole
  release). Terminology schema version 2 adds `release.meta`.

**The master's ICD-10 forms** (lane J's ruling): undotted codes are read dotted as before; a lower-case letter
after the code (a Japanese sub-classification) is dropped for comparison and the store keeps the original; the form
with a hyphen inside (`A99-9`) is not an ICD-10 code until someone shows what it means. A diagnosis whose PRB-3
carries the 病名管理番号 now finds its ICD-10 in its own row (before, only an exchange code was looked up).

Tests: `tests/unit/test_medis_release.py` (each fails on master unless it says it is a guard). Lane J's run of
this card's `check_release` on V5.18: 27,877 disease rows (27,684 current), 2,509 modifier rows, 112,967 index
rows, nothing skipped.

## Findings

Reproduced on master `d28f6c03` by the named test of `tests/unit/test_ssmix2_10b2c_reviews.py` unless another file
is named; "guard" passes on master (the finding was already fixed).

| Finding | Reproduced | New with #1189 | Rule | Test |
| --- | --- | --- | --- | --- |
| #1189 High :1913 ZPR-5 conflicting code | yes | yes | Z1 | `test_without_the_master_a_zpr_disease_code_that_is_not_prb3s_own_is_never_confirmed` |
| #1189 High :777 normalised id | yes | yes | I1 | `test_a_cancellation_reaches_the_id_an_earlier_reader_published`, `test_an_order_id_is_written_as_every_earlier_reader_wrote_it` |
| #1189 High :2141 administration and the day | yes | no (#1095) | A1 | `test_an_administration_of_a_reused_order_number_never_fills_another_days_prescription` |
| #1189 High :1348 re-key tombstones another type's id | yes | yes | T1, I2 | `test_a_cross_day_rekey_never_deletes_the_id_another_record_still_carries`, `test_no_tombstone_ever_names_an_id_a_record_in_force_carries` |
| #1189 Medium :1016 lab tie | yes | yes | T2 | `test_a_lab_tie_resolved_by_a_newer_file_tombstones_the_ids_only_the_tie_published` |
| #1189 Medium :1524 master change | yes | yes | M1 | `test_a_master_change_reaches_a_diagnosis_whose_file_did_not_change_on_a_delta_night` |
| #1189 Medium :2048 no RXE | yes | no (#1095) | V1 | `test_a_newer_order_message_with_no_drug_line_carries_the_older_version_forward_as_unknown` |
| #1189 Medium test helper :63 | yes (read) | yes | – | `tests/ssmix2_nights.py`; the ten tests of `test_ssmix2_10b2b_delta.py` still pass |
| #1095 A :1674, B :1665 misnamed document | yes | no | X1 | `test_a_document_named_for_another_patient_is_never_stored_under_the_folders_patient` |
| #1095 A :1208, B :1208 supersession across patients | fixed by #1189 | – | – | guard `test_one_diagnosis_number_of_two_patients_is_two_diagnoses_in_supersession`, `test_another_patients_deleted_number_never_hides_a_patients_own_removal` |
| #1095 A :843 only the newest predecessor | fixed by #1189 | – | – | guard `test_a_diagnosis_removed_before_the_newest_predecessor_is_still_tombstoned_on_a_delta_night` |
| #1095 A :1373, B :1373 second-day re-key | fixed by #1189 | – | – | guard `test_a_prescription_number_filed_on_a_second_day_leaves_no_first_id_in_the_lake` |
| #1095 A :1286 end day after the file | yes | no | D1 | `test_an_end_or_outcome_day_after_the_file_was_written_is_unknown_never_ended` |
| #1095 A :551 repeated TQ1-3 | yes | no | U1 | `test_a_repeated_usage_gives_no_daily_dose_and_keeps_every_text` |
| #1095 A hl7 :407 full-width offset | yes | no | O1 | `test_an_out_of_range_offset_in_full_width_quarantines_the_message` |
| #1095 B :1565 lab fallback key without the patient | yes, at the lake's id | no | not the reader's | `test_a_lab_result_with_no_id_of_its_own_is_one_record_per_patient` (the reader's rows; the id is D-1253's) |
| #1095 B :900 misfiled older snapshot | fixed by #1189 | – | – | guard `test_a_misfiled_older_snapshot_never_names_a_tombstone` |
| #1095 B :1487 administration pooling | yes | no | A1 | `test_an_injection_administration_never_fills_a_prescription_line` |
| #1095 B :1579 correction across days | yes | no | L1 | `test_a_correction_on_another_day_never_replaces_that_days_own_result` |
| #1095 B :1430 two lines to one | fixed by #1189 | – | – | guard `test_an_amendment_that_removes_one_of_two_drugs_keeps_the_other_on_a_delta_night` |
| #1095 B :413 half-read date | yes | no | D1 | `test_a_date_with_a_time_part_that_is_not_read_makes_the_diagnosis_unknown` |
| #1095 B hl7 :413 identifier read as an offset | yes | no | O1 | `test_an_identifier_shaped_like_a_time_with_an_offset_never_quarantines_its_message` |

Found while reproducing :1348, same family: a prescription and an injection with one number had one id
(`test_a_prescription_and_an_injection_with_one_number_are_two_records_with_two_ids`, rule I2).

## Measurement: toward unknown, against master `d28f6c03`

- **Shipped samples** (the exporter's 400-patient hospital, the same with `--hard-cases`, and the specification
  kit; each without licensed tables and with the four licensed samples of `tests/fixtures/licensed`): 10,760,
  10,772 and 23 rows. No row, id, reading, tombstone or statistic differs between master and this head. The
  exporter's 1,193 diagnoses read confirmed and active on both.
- **A site without the master** (rule Z1): of the shipped sample's 1,193 diagnoses, 0 move (0 %; the exporter
  writes no ZPR-5). In the probe sets, 13 of the 200 diagnoses read without the master move (6.5 %), below.
- **A licensed site, per night** (rule M1): on the shipped sample with the four licensed samples, 398 of 1,193
  diagnoses (33 %, those whose ICD-10 is looked up in the disease table) are re-sent on a delta night with nothing
  new when the tables' load time is not known, and 0 when it is. Through `adapter.licensed.tables()`, which is how
  the pipeline gives the reader its tables, it is known. At a site whose diagnoses carry `MDCDX2` codes the share
  without a known load time would be all of them.
- **The probe sets** (`tests/ssmix2_probes.py`, 699 cases, 817 ids): 13 ids move from confirmed to unknown, none
  the other way and no id changes. All 13 are read without the master and are rule Z1: the ZPR-2 and ZPR-5 shape
  (nine controls, the specification's example twice, class F, and the finding's own conflicting code). With the
  master none moves, and every correct-site shape reads confirmed. Wrong / dangerous outside the stated limit: 0
  and 0 in all four sets (master read against these labels: 13).

## Tests whose input changed

`test_4_a_diagnosis_with_an_end_date_and_no_outcome_is_ended_never_active` (third review) and
`test_a_an_outcome_date_with_no_outcome_code_is_ended` (fourth review) wrote an end day of 20 October in a file of
1 October. Under D1 that is unknown, so their day is now 20 September; what they assert (ended, never active) is
unchanged. `test_without_the_master_the_specifications_own_zpr_shape_is_confirmed` is replaced by two tests that
state Z1. The synthetic modifier tables (`tests/ssmix2_probes.py`,
`tests/fixtures/licensed/medis_modifier_sample.txt`, the modifier tests) now write 修飾語区分 in the release's shape
(`A2000000`, was `22000000`).

## What remains

- **Lane J checks each head against the real release** (the worker never sees it). Confirmed there: the title
  files are one line of quoted titles; no 病名表記, 修飾語表記 or index pair collides after NFKC; no exchange code
  has two current rows sharing its lowest 採択区分.
- **`pipeline.py` needs no change for M1** (the store reports the load time with its tables). A caller that builds
  the reader with its own dictionary may pass `licensed_loaded_at`.
- **The reason counts are in `reader.json`** and no page lists them by reason; the coverage lines of the site
  profile carry types, not reasons. Showing the Z1 count is the console's (card 10B-21/22).
- **The lake's ids** are made of the key column alone on master; SS-MIX2 numbers are unique only with the patient
  (#1095 B :1565 and the same for `diag_no` and `rx_no`). That is D-1253's card (#1192), not the reader.
- **Other licensed lists.** A new YJ or JLAC10 release changes the ATC and look-up columns of order and lab rows
  whose files did not change; M1 covers diagnoses only. After loading one, a site runs a full night.
- **Rows that share an id:** two administrations of one order that cannot be tied to a line
  (`<order>~<drug code>`), two administrations with no order (`<order>`), and an OMP file filed under "ALL9" whose
  ORC-2 is another order's number. T1 keeps a tombstone from removing them; the lake still keeps one row.
- **The other types' newest flag 2** (ADT, OMP-11/12, OML-11: set aside, D-1252's stated limit): a record set aside
  on a later night stays in a delta lake as an earlier night stored it, and is absent from a full rebuild.
- **Back-filing** stays D-1252's limit.

## How to revert

Each rule is named in a comment `D-1257` in `services/adapter/sources/ssmix2/source.py` and `hl7.py`; M1's store
side is `loaded_at_of` in `services/adapter/licensed.py`.

# D-1252 The SS-MIX2 reader supersedes records by the guideline, and reads disease-name modifiers by their codes

- **Card:** 10B-2b (plan 10, `docs/plan/47-plan-10-2026-11-18.md` Track B; the open part of 10B-2 left by #1095)
- **PR:** #1189 (branch `agent/10B-2b-ssmix2-supersession-and-modifiers`, cut from #1095's head)
- **Date:** 2026-11-19
- **Status:** proposed. The rules for what the guideline does not settle (P1 to P10 below), the modifier classes and
  the JHSD0005 change were ruled by lane J at the card's checkpoint.
- **Amends:** #1095's reading of PPR-01 snapshots, condition flag 2, cross-day deletes, ZPR and PRB-13 "0". D-1000
  (the record key) stands.

## Sources (cited, not copied; nothing of them is in the repository)

| Id | Document | Publisher | Version, date | Sections read | Where |
| --- | --- | --- | --- | --- | --- |
| G | SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン | 一般社団法人 日本医療情報学会 (JAMI), the standard's maintainer | Ver.1.2j, 2026-08-14 | 3.1.2 (2) (表3.1-3 items 4, 5, 7, and the last paragraph on 病名), 3.1.2 (3) ③ ④, 3.1.4 (2) ⑥ 1) to 3), 3.1.4 (3) ① 4) 5) and ② 1) 2) | https://www.jami.jp/wp-content/uploads/2026/08/SS-MIX2-標準化ストレージ-構成の説明と構築ガイドライン-Ver.1.2j.pdf (listed at https://www.jami.jp/jamistd/ss-mix2/) |
| S | SS-MIX2 標準化ストレージ 仕様書 | JAMI | Ver.1.2j, 2026-08-14 | 3.7 (表3-46 PPR^ZD1), 3.7.3 (表3-47 PRB), 3.7.4 (表3-48 ZPR), the PPR^ZD1 example | https://www.jami.jp/wp-content/uploads/2026/08/SS-MIX2-標準化ストレージ-仕様書-Ver.1.2j.pdf |
| C | SS-MIX2 標準化ストレージ 仕様書 別紙：コード表 | JAMI | Ver.1.2j, 2026-08-14 | 表34 (HL7 0241), 表35 (HL7 0287), 表95 (JHSD0005), 表96 (JHSD0006), 表97 (JHSD0007) | https://www.jami.jp/wp-content/uploads/2026/08/SS-MIX2-標準化ストレージ-仕様書-Ver.1.2j_コード表.pdf |
| M | ICD10対応標準病名マスター 仕様書 | 一般財団法人 医療情報システム開発センター (MEDIS-DC), keeper of the MHLW-adopted master | Ver.5.18, 2026-06 | §2 the files; (1) 病名基本テーブル; (2) 修飾語テーブル ① to ⑩ | https://www2.medis.or.jp/stdcd/byomei/spc518.pdf |

The master itself is licensed: a site loads its own copy (`python -m adapter.licensed load --kind medis_modifier
...`). The tests use a synthetic table with M's column names and made-up codes.

## Context

#1095 (D-1000) read a newest version of flag 2 as "set aside" (its meaning was not cited), counted a delete filed
under another day without applying it, gave an "ALL9" PPR-01 snapshot and a per-diagnosis PPR-01 file of one
patient two rows with one key, and read every coded value of ZPR as a modifier. A qualifier written only in a coded
diagnosis's display text ("肺炎（未確定）") read as confirmed. Review 12 had described the documents; none had been
opened. They are now.

## Decision

### A. Supersession (G)

What G says, applied:

- **R1** A record is patient, 診療日, データ種別 and オーダNo (G 3.1.2 (3) ③, 3.1.4 (3) ② 2)); corrections and
  deletions are made per record.
- **R2** Files are never removed; every change is a new file (G 3.1.2).
- **R3** Versions are ordered by the 発生日時 of the file name (G 表3.1-3 No.5), never by arrival or file time.
- **R4** A new version: the earlier flag-1 file is renamed to 2 (過去履歴), the new one written as 1 (G 3.1.4 (2) ⑥
  1), (3) ① 4)).
- **R5** A deletion: every flag-1 and flag-2 file of the record becomes 0, and the delete message is written as 0 (G
  ⑥ 2), (3) ① 4) 5)).
- **R6** A correction is a deletion and then a new version (G ⑥ 3)).
- **R7** One file is one message is one order (G 3.1.2 (2)): a newer version replaces the whole order, all its lines.
- **R8** PPR-01 is one file per patient holding all its diagnoses, 診療日 "-", オーダNo "ALL9" (G 3.1.2 (2), 表3.1-3
  No.4): the newest file in force is the whole problem list.

So, per record (`resolve` in the reader): the newest file of flag 1 is in force; older files are superseded; a
newest file of flag 0 deletes exactly that record, with every line or diagnosis any older version of it named.

What G does not settle (lane J's rulings):

- **P1** Several flag-1 files of one record: the newest decides; counted.
- **P2** A newest flag 0 while an older flag-1 file remains: deleted; counted.
- **P3** A newest file of flag 2 (no newer flag 1): no version is in force.
- **P4** A newest file that cannot be read or is quarantined (bytes, another patient, no PID, a duplicate diagnosis
  number, a delete whose patient is not certain): the older version is never read as in force.
- **P5** Two live files of one record with one 発生日時: no version is in force (a deletion still wins a tie). For
  OML-11 too: the result is read with status `unknown` (FHIR Observation.status unknown), counted.
- In P3 to P5, for PPR-01 and OMP-01/02, every version that could be in force is read and its rows go out as unknown
  (diagnosis status `U`, certainty `U`; order status `unknown`) with the reason in `version_note`, their text kept,
  counted. They pass the delta window, so what an earlier night stored as confirmed and active changes on the night
  the newer file arrives.
- **P6** (the reader's caution, not G's rule) An order number of OMP-01/02 filed on several days: each day is its own
  record (G's key), keyed `<number>@<day>` from the first night the number is on a second day, whatever the flag, so
  an id never changes later; the plain key an earlier night stored is tombstoned. A delete deletes only its own day.
  A day whose number another day holds with a newer file (a version, a delete, a flag 2, an unreadable file) is read
  as unknown. "ALL9" and the ADT types repeat across days by design: no link. Under a site's `unique` the days are
  one record already (D-1000).
- **P7** A file arriving later with an older 発生日時 is an older version (R3).
- **P8** The order number is compared after the reader's one normalisation (`key_part`: NFKC, blanks removed; case
  kept): `ＲＸ０１` and `RX01` are one record. Counted.
- **P9** G defines only the snapshot (R8). TrialBox's own exporter writes one PPR-01 file per diagnosis under its own
  number and day; that layout is read as records of their own. Beside a snapshot, a per-diagnosis record older than
  the snapshot in force is superseded by it; a newer one is unknown. One diagnosis number given by two records of a
  patient is unknown.

### B. Disease-name modifiers (S, M)

ZPR is read by its fields (S 3.7.4, 表3-48): ZPR-1 the prefix 修飾語管理番号 (repeating), ZPR-2 the 病名管理番号
(`MDCDX2`), ZPR-3 the suffix 修飾語管理番号, ZPR-4 / ZPR-6 their 修飾語交換用コード, ZPR-5 the 病名交換用コード,
ZPR-7 a comment. (S's text for ZPR-4 says 接尾語 under a 接頭語 field name; the field position is read.)

- **Without the site's licensed master:** ZPR-2 and ZPR-5 must name PRB-3's own disease (ZPR-2 the code of an
  `MDCDX2` PRB-3, ZPR-5 its text); then the diagnosis may be confirmed (S's own example shape; #1095 gave U). Any
  modifier field, a comment or a second ZPR is unknown. A modifier code with no text, which #1095 read as suspected,
  is unknown. **Limit:** doubt written only in the display text (「肺炎（未確定）」, 「肺炎既往」) is not read without
  the master; no word list is kept.
- **With it** (licensed kinds `medis`, indexed by 病名管理番号, and the new `medis_modifier`, both loaded; the
  disease table alone, loaded for the ICD-10 look-up of D-137, keeps the reading without the master). **The rule is
  chosen per diagnosis, never per site** (lane J's ruling): it reads a diagnosis whose PRB-3 carries an `MDCDX2` code
  (the 病名管理番号 or the 病名交換用コード, S 3.7.4 names `MDCDX2` for both; alone or beside a local code), or whose
  ZPR names an `MDCDX2` disease or modifier (then the display name must be what the ZPR names, else it disagrees with
  PRB-3 and is unknown). A diagnosis coded only locally keeps the reading without the master exactly as on #1095's
  head, with the stated limit, whether or not the master is loaded. `stats` counts each night how many diagnoses
  each rule read (`read by the master rule`, `read without the master (coded locally)`, `read without the master
  (the tables are not loaded)`). Under the master rule: confirmed only when the
  display name (PRB-3's text) is exactly the prefixes' 修飾語表記, the 病名表記 and the suffixes' 修飾語表記, after
  `key_part`; every modifier is a current row of the master (変更区分 not 1) in its own position (接続位置区分: 10 and
  over before the name, 9 and under after it, M (2)⑥); the exchange codes given are the master's; and every
  modifier's class (the second character of 修飾語区分, M (2)⑦) is recognised: **1 部位, 2 位置, 9 歯科**; **3 病因**
  only when the master gives the modified name no code of its own (else the coded concept would silently be the
  unmodified one: unknown). **4 経過表現, 5 状態表現** (they can say "old", "after", "in remission"; M defines no
  finer class), **6 患者帰属, 7 その他, 8 接尾語** (where "の疑い" is): unknown. An `MDCDX2` code the master does not hold is
  unknown. No modifier's words are listed anywhere; only the master's own columns are read.
- **P10** PRB-13: the code table of JHSD0005 (C 表95) holds one value, `1` 疑いあり. A `0`, with any text, is not a
  value of it: unknown. PRB-13 confirms only when empty. TrialBox's writers never write PRB-13.

### C. The independent tester's classes (lane J, at `2bc79278`)

An independent tester wrote 136 supersession and 353 modifier scenarios from the standard without reading the code;
the supersession core held, and 75 runs were dangerous in these classes, each now read as follows:

1. A modifier field (ZPR-1, 3, 4, 6) with a text and no code is a modifier: without the master unknown; with it, a
   component with no code is unknown.
2. With the master, every ZPR component's text must be the master's 表記 for its code (ZPR-1 / 3 modifiers; ZPR-4 / 6
   by exchange code; ZPR-2 / 5 the disease), else unknown; without it, ZPR-2 / 5 texts must be PRB-3's name.
3. PRB-3's names (its triples other than ICD-10) must agree, else unknown.
4. 変更区分 (M (1)① and (2)①): 0 unchanged, 3 added and 5 changed are current rows; 1 is deleted; any other value, or
   none, is not read as current: unknown. Checked for the modifier and the disease. A table without the 変更区分
   column, or with it empty in every row, is a site-level fact: `adapter.licensed` refuses it at load with the column
   named, and a store that holds one (loaded before this decision) is read as "tables not loaded", counted.
5. "ALL9" is the guideline's "all nines": 表3.1-3 No.4 says ALL9, and the guideline's own example (図3.1-1, p.16) names
   the ADT-00 file `…_ADT-00_9999999999999999999999_…` with the note 「-」「All9」などで埋める. `no_order` reads "-",
   "ALL9" (any width or case, blanks removed) and a run of four or more nines as data no order manages; a run of
   fewer nines is an order number (a counter that reaches 9, 99 or 999 is one). TrialBox's kit and exporter write
   the letters; both forms are read.
6. A file in a record's folder whose name is not in the guideline's form (a type or patient part in another case or
   width, a flag such as `０` or `0 `, an extension, another part count, a 発生日時 that is not a real time or is after
   tonight, UTC+14), or whose name disagrees with its folders, may be a newer version or a deletion: the records it may
   belong to (by its folders and by its name after `key_part`; a name that cannot be split: every record of its
   folder) have no version in force, unknown for PPR-01 and OMP-01/02. Counted, never ignored.
7. PPR^ZD1 segments (S 表3-46): before the first PRB, MSH, SFT, PID, PV1 and PV2; after a PRB, ZPR (read), ZPD (歯式),
   ZI1 (insurance) and ORC (◎). NTE (marked "-", not used by SS-MIX2), VAR, ROL, PTH, OBX, GOL, OBR and any other
   segment are not read: the diagnosis they follow is unknown; one before the first PRB makes every diagnosis of the
   snapshot unknown. Counted.
8. A file whose オーダNo and ORC-2 disagree (`rx01` or `RX001` named, `RX01` in ORC-2), live or deleted: the order ORC-2
   names and the line itself are unknown. A 発生日時 after tonight is not a version in force (class 6). The same Rp and
   drug twice in one order: those lines are unknown.
9. Each of these is counted in `stats` with its reason.
10. Where the full name is written (S 表3-47: PRB-3 "病名表記を一意に表すコード", recommended the 病名管理番号; PRB-17
    "患者の病態をあらわすために実際に入力される文字列", the text actually entered): both layouts are read under the
    master rule. PRB-3's text is the full name (PRB-17 empty or the same), or PRB-3's text is the 病名表記 alone and
    PRB-17 the full name. Without the master, PRB-17 must be the same name as PRB-3 (as before).

Kept stricter, as lane J ruled: ties, a newest flag 2 over an older flag 1, an empty PRB-1, PRB-13 holding only a
table name, a one-character 修飾語区分, a repeated identical ZPR, a locally coded diagnosis with a ZPR.

### D. The second tester's round (lane J, at `5ae5593f`)

- **The delta window (class A).** Every row of every type the reader reads carries the newest 発生日時 of the files that
  decide its record: its versions (flag 2 and deleted ones included), for an order number filed on several days all
  of them, and for ADT-52 and OMP-11/12 the record they change. A newer version written after the window opened is
  sent whatever its clinical dates (ORC-9, the sample time, the visit time), and a re-keyed record (two lines to
  one; a number on a second day) is sent on the night its old key is tombstoned. The day-keyed rows of an order
  number filed on several days are sent on every night, since their plain key is tombstoned on every night.
  **Limit:** the reader knows "new since last night" only by the 発生日時 in the name, and keeps no state between
  nights. A file that arrives late with a 発生日時 before the window (back-filed) is not seen by a delta night unless
  it re-keys another record; a site that back-files runs full nights. Before this, a cancelled order or a
  corrected lab result written on a delta night was not sent (also on master `8bfebd70`). The proof is
  `tests/unit/test_ssmix2_10b2b_delta.py`: night 2 as a delta gives the lake night 2 in full gives, for orders, labs,
  a snapshot and a discharge (`pipeline.check_delta` keeps exempting SS-MIX2: these tests are why).
- **Fields (class B).** PRB is read in fields 1 to 4, 7, 9, 10 and 13 to 18, and 25 (S 表3-47; the specification's own
  example fills 25, the confidentiality code); any other field holding data (11, 12, 19 certainty, 20 probability,
  21 to 24, 5, 6, 8), or a component beyond those read (PRB-3 component 7 and on, such as its original text;
  PRB-17 component 2; PRB-14 component 4 and on), makes the diagnosis unknown. ZPR-8 and on, and an ORC after a PRB
  whose ORC-1 is not NW (the specification's example) or that fills a field the reader does not read, the same. A
  second MSH before the first PRB makes the snapshot unknown; a PPR-01 file whose MSH-9 is not PPR^ZD1 is set aside.
  The order segments (ORC, RXE, TQ1 of OMP-01/02) are not given such a list in this card: their status comes only
  from ORC-1 and ORC-5 by allow-lists (#1095), and their other fields describe the drug, the dose and the timing.
- **Class C.** A ZPR whose disease is not its PRB's makes that diagnosis unknown and also any diagnosis of the
  message it names.
- **Class D.** 修飾語区分 must be eight digits (M (2)⑦), else the class is not read. One 病名管理番号 on two different
  rows of the disease table is read for neither; the loader reads neither row of a MEDIS code given twice with
  different content (an identical repeat keeps the row, as before). Under the master rule, an ICD-10 in PRB-10 (or
  PRB-3's ICD-10 triple) that is not the master's for the disease makes it unknown.
- **Class E.** Tombstones of an older snapshot are compared by patient. Files of a type the reader does not read
  (OML-01, OMG-01, ...) are counted by type.
- **Class F.** Without the master, PRB-3's 病名交換用コード and ZPR-2's 病名管理番号 are linked only by ZPR-5 (the
  exchange code); without that link the reason is "ZPR-2 and PRB-3 cannot be compared without the master".

## Measurement (named inputs: `tests/ssmix2_probes.py`)

Four sets, each labelled before the reading it measures: 232 supersession cases (328 ids), 300 modifier cases (150
diagnoses without and with a synthetic master, the mixed site included), "independent set 1" (102 cases, 118 ids)
and "independent set 2" (45 cases, 51 ids, the correct-site shapes included), the last two written from lane J's
descriptions of the testers' classes. Wrong / dangerous (an id read confirmed and active where it is not):

| Set | #1095 head `5a4ee5f9` | `5ae5593f` | this head |
| --- | --- | --- | --- |
| Supersession | 106 / 57 | 0 / 0 | 0 / 0 |
| Modifiers | 130 / 95 | 47 / 47 | 43 / 43 |
| Independent set 1 | 69 / 64 | 0 / 0 | 0 / 0 |
| Independent set 2 | 28 / 22 | 27 / 26 | 0 / 0 |

The 43 left are all the stated limit (doubt only in the display text of a diagnosis read without the master: none
loaded, or coded only locally); outside it 0 and 0. Against `5ae5593f` the reading moved toward unknown only in the
second tester's classes and for the two malformed 修飾語区分 rows, and toward confirmed once (class F's link). The
correct-site shapes read confirmed with the master. `make e2e-simple` with all four licensed samples loaded: the
GOUT-COH funnel from SS-MIX2 equals its CSV export.

## How to revert

Part A: `resolve`, `_record_rows`, `_snapshots`, `_across_days` and `_uncertain_deletes` in
`services/adapter/sources/ssmix2/source.py`. Part B: `_modifiers`, `medis_master` and the `medis_modifier` kind in
`services/adapter/licensed.py`. P10: `flag_confirmed`. Each is its own commit on #1189.

## Not in this decision

- Verifying `jp_core/prb14_outcome.csv` against C 表34 (HL7 0241) and 表96 (JHSD0006): it turns unknown outcomes into
  recognised ones and needs its own measurement (a follow-up card).
- The other message types (ADT-00, 12, 22, 52, OMP-11/12, OML-11) keep #1095's reading of a newest flag 2 (set
  aside) and of an unreadable newest file (skipped); a cross-day number of OML-11 is counted only (OML-11's ties are
  read as unknown, P5). Their rows pass the delta window by the rule of section D.
- Field allow-lists for the order segments (ORC, RXE, TQ1); the MSH-9 check covers PPR-01 only.
- The modifiers are kept as text in `modifiers`; FHIR `bodySite` and laterality are not written.
- The lake's resource ids are made of the key column alone (`rx_no`, `diag_no`); SS-MIX2 numbers are unique only
  with the patient (reported to lane J, outside this card).

## Superseded in part (2026-11-20)

D-1257 supersedes one sentence of section B ("then the diagnosis may be confirmed" for ZPR-2 and ZPR-5 without the
site's licensed master) and class F's link: see `D-1257-the-ssmix2-reader-answers-its-independent-reviews.md`.

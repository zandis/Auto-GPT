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
- **P5** Two live files of one record with one 発生日時: no version is in force (a deletion still wins a tie).
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
  disease table alone, loaded for the ICD-10 look-up of D-137, keeps the reading without the master, so loading it
  never by itself turns a site's locally coded diagnoses unknown; an `MDCDX2` code in PRB-3 may be the 病名管理番号 or
  the 病名交換用コード, S 3.7.4 names `MDCDX2` for both): confirmed only when the
  display name (PRB-3's text) is exactly the prefixes' 修飾語表記, the 病名表記 and the suffixes' 修飾語表記, after
  `key_part`; every modifier is a current row of the master (変更区分 not 1) in its own position (接続位置区分: 10 and
  over before the name, 9 and under after it, M (2)⑥); the exchange codes given are the master's; and every
  modifier's class (the second character of 修飾語区分, M (2)⑦) is recognised: **1 部位, 2 位置, 9 歯科**; **3 病因**
  only when the master gives the modified name no code of its own (else the coded concept would silently be the
  unmodified one: unknown). **4 経過表現, 5 状態表現** (they can say "old", "after", "in remission"; M defines no
  finer class), **6 患者帰属, 7 その他, 8 接尾語** (where "の疑い" is): unknown. A PRB-3 code the master does not hold,
  or a local code, is unknown. No modifier's words are listed anywhere; only the master's own columns are read.
- **P10** PRB-13: the code table of JHSD0005 (C 表95) holds one value, `1` 疑いあり. A `0`, with any text, is not a
  value of it: unknown. PRB-13 confirms only when empty. TrialBox's writers never write PRB-13.

## Measurement (named inputs: `tests/ssmix2_probes.py`)

232 supersession cases (328 labelled ids) and 242 modifier cases (121 diagnoses, without and with a synthetic
master), labelled before the implementation. #1095's head `5a4ee5f9` -> this card:

- supersession: wrong 106 -> 0, dangerous (an id read confirmed and active where it is not) 57 -> 0;
- modifiers: wrong 110 -> 35, dangerous 82 -> 35; the 35 are all the stated limit (no master, doubt only in the
  display text); outside it 0 and 0.
- Moved toward confirmed: without the master, 8 (ZPR naming only PRB-3's own disease) and 2 (a snapshot superseding
  an older per-diagnosis file that held the diagnosis ended); with the master, 20, each by the master's own tables.

## How to revert

Part A: `resolve`, `_record_rows`, `_snapshots`, `_across_days` and `_uncertain_deletes` in
`services/adapter/sources/ssmix2/source.py`. Part B: `_modifiers`, `medis_master` and the `medis_modifier` kind in
`services/adapter/licensed.py`. P10: `flag_confirmed`. Each is its own commit on #1189.

## Not in this decision

- Verifying `jp_core/prb14_outcome.csv` against C 表34 (HL7 0241) and 表96 (JHSD0006): it turns unknown outcomes into
  recognised ones and needs its own measurement (a follow-up card).
- The other message types (ADT, OML-11) keep #1095's reading of a newest flag 2 (set aside) and of an unreadable
  newest file (skipped); a cross-day number of OML-11 is counted only.
- The modifiers are kept as text in `modifiers`; FHIR `bodySite` and laterality are not written.
- The lake's resource ids are made of the key column alone (`rx_no`, `diag_no`); SS-MIX2 numbers are unique only
  with the patient (reported to lane J, outside this card).

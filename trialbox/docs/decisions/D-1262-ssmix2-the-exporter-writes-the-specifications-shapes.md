# D-1262 The SS-MIX2 exporter writes the specification's shapes; the old shapes stay as the "legacy vendor" variant

- **Card:** 10B-1 (plan 10, `docs/plan/47-plan-10-2026-11-18.md` Track B; review items 12-10 and 9b-14; plan row F1)
- **PR:** #1247 (branch `agent/10b1-ssmix2-exporter-spec-shapes`)
- **Date:** 2026-11-20
- **Status:** proposed

## Context

Defect (b) of plan 10: TrialBox's SS-MIX2 reader had only been tested against TrialBox's own exporter
(`tools/ssmix2_export.py`), which writes shapes the standard does not (review 12 §4.9). So reader and exporter agreed
with each other, and both could be wrong. This card gives the exporter the specification's shapes and adds a check
written only from the specification's tables. It measures the old exporter with that check, and runs master's
reader, unchanged, over the new output.

## Sources (cited, not copied; nothing of them is in the repository)

All documents are JAMI's (一般社団法人 日本医療情報学会, the standard's maintainer), listed at
https://www.jami.jp/jamistd/ss-mix2/ and fetched on 2026-11-19. Pages are the printed page numbers.

| Id | Document | Version, date | Used |
| --- | --- | --- | --- |
| G | SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン | Ver.1.2j, 2026-08-14 | 2.2, 図2.2-1, 表2.3-1, 表3.1-1, 表3.1-2, 3.1.2, 表3.1-3, 図3.1-1, 3.1.4 |
| S | SS-MIX2 標準化ストレージ 仕様書 | Ver.1.2j, 2026-08-14 | 2.1.3, 2.1.4, 3.3 (表3-4), message tables 表3-13 to 3-99, segment tables 表3-34 to 3-98, 付録1 |
| C | the same, 別紙 コード表 | Ver.1.2j, 2026-08-14 | 表2 to 表12 (coding-system names), 表34, 35, 49, 78, 94 to 97, 107 |
| E | SS-MIX2 拡張ストレージ 構成の説明と構築ガイドライン and 別紙 標準文書コード表 | Ver.1.2j, 2026-08-14 | 2.2 (3) to (7), 表2.2-1, 表2.2-2; 表1 |

The card names the 1.2i code table. 1.2j is the current publication. Its revision history says the guidelines are
unchanged since 1.2h ("変更点なし"), and the code tables only add rows, so 1.2j is cited. D-1252 used the same
documents.

## Decision

### A. The exporter has a declared variant

`tools.ssmix2_export.export(src, out, variant=...)` and `--variant`:

- **`legacy_vendor`** is the default. It is the exporter's existing output, byte for byte. On the 60-patient
  synthetic hospital (seed 42), master `d28f6c03` and this branch give the same SHA-256 over all 1,509 files
  (`7429bd27…`), pinned in `test_legacy_vendor_is_byte_identical_to_the_exporter_before_the_card`. The legacy PDFs
  carry their creation time and differ from run to run on master too, so both runs set reportlab's invariant mode.
- **`spec`** (`tools/ssmix2_spec_export.py`) writes the shapes below. It imports nothing from
  `adapter.sources.ssmix2`, and a test enforces that.
- **The default stays `legacy_vendor`.** Section D shows the reader does not yet read every `spec` shape, so the
  synthetic Japanese hospital and the goldens are unchanged (`make goldens-check`: no change). Changing the default
  is for card 10B-16, after the gap cards.
- `--hard-cases` (T-615a's vendor byte patterns) is refused with `--variant spec`.

### B. The shapes the `spec` variant writes

**Tree and names.**

| Shape | Written | Source |
| --- | --- | --- |
| Folder tree | `<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>/<file>`; patient data under "-" | G 2.2 (2) ③ to ⑤, 図2.2-1 |
| File name | `患者ID_診療日_データ種別_オーダNo_発生日時_診療科コード_フラグ`, no extension | G 3.1.2 (1), (3) ① |
| 発生日時 | 17 digits, distinct within a record, ascending by version | G 表3.1-3 No.5 |
| オーダNo | `ALL9` for ADT-00, PPR-01, ADT-61 (and ADT-01, see E); the order number (ORC-2) for orders; a per-day sequence for the other ADT types | G 表3.1-3 No.4 |
| 診療科コード | ORC-17 or PV1-10, `-` when there is none | G 表3.1-3 No.6 |
| 診療日 | per event, the date in the field 表3.1-1 names (36 rows) | G 表3.1-1 |
| Encoding | ISO-2022-JP; MSH-18 `~ISO IR87`, MSH-20 `ISO 2022-1994`; segments end with `<CR>` | G 3.1.2 (3) ②; S 表3-34; S 2.1.4 |
| MSH | `^~\&`, MSH-5 `GW`, MSH-7 to the second, MSH-9 type^event^structure, `P`, `2.5`, MSH-21 `SS-MIX2_1.20^SS-MIX2^1.2.392.200250.2.1.100.1.2.120^ISO` | S 表3-34; each message's "メッセージ構造は" |

**Versions.** Every change is a new file. An earlier version is renamed to flag 2: an ADT-00 phone change, a
preliminary lab result before its final, an ADT-61 allergy list, a PPR-01 snapshot, a corrected document. A
deletion renames the record's files to 0 and writes the cancelling message as 0 (G 3.1.4 (2) ⑥ 1) to 3)).
Cancellations written: A23, A55, A27, A11, A52, A53, A26, A12, A25, A13, and RDE^O11 with ORC-1 `CA`.

**The 26 data types (G 表3.1-2, 36 rows).**

| データ種別 | HL7 message^event | Synthetic content |
| --- | --- | --- |
| ADT-00 | ADT^A08 / ADT^A23 | every patient; one entered by mistake and deleted |
| ADT-01 | ADT^A54 / ADT^A55 | doctor in charge, every 10th patient |
| ADT-12 | ADT^A04 | every CSV visit |
| ADT-21 | ADT^A14 / ADT^A27 | planned admission (one cancelled and re-planned) |
| ADT-22 | ADT^A01 / ADT^A11 | admission after every 40th visit (one cancelled) |
| ADT-31, ADT-32 | ADT^A21 / A52, ADT^A22 / A53 | leave and return |
| ADT-41, ADT-42 | ADT^A15 / A26, ADT^A02 / A12 | planned transfer and transfer |
| ADT-51, ADT-52 | ADT^A16 / A25, ADT^A03 / A13 | planned discharge, discharge (one cancelled, discharged the next day) |
| ADT-61 | ADT^A60 | IAM allergies, every 10th patient |
| PPR-01 | PPR^ZD1 | one snapshot per patient, older snapshot flag 2, a `DE` row |
| OMD | OMD^O03 | diet per admission, `NPO` (C 表107) or a local diet |
| OMP-01, OMP-11 | RDE^O11, RAS^O17 | prescriptions; 実施 of every 5th |
| OMP-02, OMP-12 | RDE^O11, RAS^O17 | injections: RXE-2 the 注射種別 (C 表78), the drug in RXC |
| OML-01, OML-11 | OML^O33, OUL^R22 | an order per result; every 10th result first preliminary |
| OMG-01, OMG-11 | OMG^O19, OMI^Z23 | imaging from `report.csv` |
| OMG-02, OMG-12 | OMG^O19, OMI^Z23 | endoscopy, every 50th visit |
| OMG-03, OMG-13 | OMG^O19, ORU^R01 | ECG, every 30th visit |

**Field shapes.**

- **PRB** (S 表3-47): PRB-1 HL7 0287; PRB-3 `<病名管理番号>^name^MDCDX2`; PRB-7 the diagnosis day, PRB-16 onset;
  PRB-10 `<ICD-10>^^I10^O^外来時^JHSD0004`, only for a WHO ICD-10 code (the table's example K297; the synthetic
  hospital's ICD-10-CM codes such as M10.071 get none); PRB-14 HL70241; PRB-18 `1^主診断^JHSD0007` for the
  patient's first diagnosis.
- **ZPR** (S 表3-48): ZPR-2 the 病名管理番号, ZPR-5 the 病名交換用コード, as the specification's own PPR^ZD1 example
  has it.
- **RXE** (S 表3-57): RXE-2 `<HOT9>^name^HOT9^<local>^name^99DRG`, RXE-3 one dose, RXE-10 / RXE-11 the amount
  dispensed, RXE-31 `<local>^^99DRG^<YJ>^^YJ` (the local code also in RXE-2); TQ1-3 the 用法; RXR-1 the route;
  ORC-5 the status.
- **Coding-system names** are only those of C 表2 to 表12, `I10`, `YJ`, `DCM`, or a local `99zzz` (HL7 table 0396).

**Extended storage (E).**

- **Layout:** `<root>/<pid 1-3>/<pid 4-6>/<pid>/<診療日>/<データ種別>/<コンテンツ>/<files>`.
- **The data-type folder** is `L0101^退院時サマリー^99DOC^18842-5^退院時サマリ^LN` (or `^18748-4^画像検査報告書^LN`, E 別紙
  表1).
- **The content folder** is named `pid_診療日_コード_特定キー_発生日時_診療科_flag`; one corrected summary is
  renamed to 2.
- **Files** carry an extension (表2.2-1) and a `_contents.xml` (表2.2-2).

**Codes.** Codes a licensed master would hold are invented in the master's shape: 病名管理番号 `9999nnnn`, exchange
codes the shipped sample's 4-character `ZBnn` (and `Z9Q1` in the F1 fixture), HOT9 codes made up, study UIDs under
`2.25.`. No MEDIS row is copied.

### C. The shape check (`tools/ssmix2_shape_check.py`)

It has 37 rules, each naming its table: T1 to T4 (tree), N1 to N6 (file name), K1 to K3 (versions), D1 (表3.1-1),
M1 to M3 (MSH), E1 and E2 (encoding, terminators), G1 (each message table's segments outside every `[ ]`), F1 (each
segment table's SS-MIX2 "R" fields), C1 (coding systems), P1 to P5 (PRB), R1 (RXE-31), and X1 to X7 (extended
storage). `python -m tools.ssmix2_shape_check --rules` prints them with their sources.

**What a test proves:**

- each rule has a test that breaks exactly its shape;
- on a separate worktree, disabling each rule's check made its test fail (37 of 37);
- `_contents.xml` is read with no document type or entity (the pattern of `tools/public_accuracy/sets.py`).

**Results on the 400-patient synthetic hospital** (`synth_hospital --profile ci --sites jp-a:JP:400 --ref-date
2026-11-01`):

- **`spec`:** 0 failures over 26 types, 13,354 messages, and 62 extended files in 31 content folders.
- **`legacy_vendor`: 71,031 failures.** This is the measured size of defect (b). 17 of the 26 types are absent:
  ADT-01, 21, 31, 32, 41, 42, 51, 61; OMD; OML-01; all six OMG.

| Type | Files | Failures (rule: count) | What it is |
| --- | --- | --- | --- |
| ADT-00 | 400 | F1 400, G1 400, N4 400 | no EVN; オーダNo `-`, not ALL9 |
| ADT-12 | 2,653 | F1 7,959, G1 2,653, M2 2,653 | no EVN; PID-5, 7, 8 empty; MSH-9 `ADT^A04` without its structure |
| ADT-22 | 68 | F1 204, G1 68, M1 68, M2 68 | admissions written as ADT^A04 |
| ADT-52 | 68 | F1 204, M1 68, M2 68 | a class change (ADT^A07), which is not an SS-MIX2 event |
| OML-11 | 1,897 | D1 1,897, F1 9,485, G1 1,897, M2 1,897 | no SPM (the day has no SPM-17); MSH-9 without its structure |
| OMP-01 | 2,744 | C1 5,029, F1 13,720, G1 2,744, M2 2,744 | `HOT` and `99YJ`, not code-table names; no RXR; RXE-10/11 empty |
| OMP-02 | 165 | C1 302, F1 825, G1 165, M2 165 | the same, and the drug in RXE-2 |
| OMP-11 | 1,077 | C1 1,974, F1 3,231, G1 1,077 | no RXR; RXA-1, 2 empty |
| OMP-12 | 109 | C1 206, F1 327, G1 109 | the same |
| PPR-01 | 1,142 | D1 1,142, F1 3,426, M2 1,142, N4 1,142, P3 1,142 | one file per diagnosis, dated, order No the diagnosis; PRB-14 `A` / `R` without a table |
| extended | 30 | X4 30 | no content folder; `DSC-01` / `RPT-01` folders |

### D. Master's reader over the `spec` output (unchanged; card 10B-2c, PR #1238, owns the reader)

**Criterion F1's four probes** (`tests/ssmix2_f1_fixtures.py`, written with the spec writer) all read today:

- three visits on three days read as three;
- the diagnosis sample reads as K29.7, onset 2011-08-31, not resolved, 主診断;
- "1回2錠 1日3回" reads as 6 a day (ATC through RXE-31's YJ);
- the guideline layout reads 2 of 2 documents.

The pathology report (11526-1) is typed `report`: the reader has no pathology note type.

**Per type, on the 400-patient hospital** (pinned on the 60-patient one by
`tests/unit/test_ssmix2_10b1_reader_on_spec.py`; each gap is a strict expected failure naming its card):

| Type | Today | Gap | Card |
| --- | --- | --- | --- |
| ADT-00 | read: 400 patients, the deleted one absent | read wrongly: phone (PID-13 component 12, the XTN shape of S 付録1) is empty for 400 of 400 | 10B-8 |
| ADT-01 | not read (54 files, counted) | doctor in charge | 10B-8 |
| ADT-12 | read: 2,721 of 2,721 visits | – | – |
| ADT-21, 31, 32, 41, 42, 51 | not read (70, 24, 23, 34, 34, 68 files, counted) | planned admission, leave, return, transfers, planned discharge; their cancellations | 10B-8 |
| ADT-22, ADT-52 | read: 67 admissions, 67 discharges; the A11-cancelled admission absent; the A13-cancelled discharge replaced by the next day's | – | – |
| ADT-61 | not read (60 files) | allergies (IAM) | 10B-7 |
| PPR-01 | read: 1,142 of 1,142, onset, 主診断, the 12 `DE` rows absent | not read: ICD-10 of a diagnosis without PRB-10 (287 of 1,142, the ICD-10-CM codes): the reader looks up PRB-3's 病名管理番号, never ZPR-5's exchange code, so without the licensed MEDIS table no ICD-10 | 10B-3 |
| OMD | not read (68 files) | diet orders | 10B-10 |
| OMP-01, OMP-11 | read: 3,429 orders with ATC from RXE-31, daily dose, status; 685 実施 tied to their orders | – | – |
| OMP-02 | read wrongly: 219 of 219 orders take RXE-2's 注射種別 (`00^一般^99I02`) as the drug, so no ATC | the drug in RXC | 10B-4 |
| OMP-12 | read wrongly: 44 of 44 実施 "not tied to an order line (another drug)" | follows from OMP-02 | 10B-4 |
| OML-01 | not read (1,897 files) | lab orders | 10B-9 |
| OML-11 | read: 1,897 of 1,897, the final value where a preliminary came first | – | – |
| OMG-01, 02, 03, 11, 12, 13 | not read (48, 55, 91, 48, 55, 91 files) | orders, 実施, physiology results | 10B-9 |
| Extended storage | read: 30 of 30 live documents, typed `discharge` and `report`; the flag-2 folder set aside | `_contents.xml` counted, not read (30); no pathology type | 10B-5 |

### E. Not settled (the old shape kept, or both read)

1. **ADT-01's オーダNo.** 表3.1-3 No.4 gives ALL9 to 患者基本・病名・アレルギー "等" (and so on). `ALL9` is written; the check requires it only for the three types the table names.
2. **ALL9 or all nines.** The table says "ALL9"; its example (図3.1-1) names `9999…` and says 「-」「All9」などで埋める.
   `ALL9` is written; the check accepts both.
3. **`<FS><CR>` at a file's end.** S 2.1.3 ends a gateway telegram with it; G does not say a stored file does. The
   old shape is kept: no `<FS>`.
4. **A character JIS X 0208 cannot write.** The old fallback is kept (UTF-8 under `UNICODE UTF-8`). Check E1 fails
   such a file. The synthetic hospital has none.
5. **Where the extended storage's root lies.** G and E name it a separate root. The old place is kept:
   `<out>/extended_storage`, with the non-SS-MIX2 CSV tables under `<out>/extended`. The check takes both as
   arguments.
6. **The content folder's データ種別コード** (local or standard). The LOINC code is written; the check only needs it
   non-empty.
7. **`createVender` or `createVendor`.** 表2.2-2 spells it `createVender`, its own example `createVendor`. The table's
   spelling is written; the check accepts both.
8. **A document file's text encoding** (E is silent). The old Shift_JIS is kept.
9. **The 標準文書コード表's membership** is not checked: the table is not copied. The check verifies the LOINC check
   digit and `LN`.
10. **The 診療科 code** is ORC-17's "or an equivalent" (表3.1-3 No.6). The check needs it non-empty only.
11. **ORC in the result messages.** OMI, RAS, OUL and ORU refer back to the order tables; only the order messages'
    ORC fields are checked.
12. **Not written:** the multi-volume manifest (G 別添; card 10B-11), CDA documents, JJ1017 and JAMI 標準用法 codes
    (local codes instead; no master in the repository).

## Consequences

- **The goldens and the synthetic Japanese hospital do not change** (the default is `legacy_vendor`).
- **10B-3, 10B-4, 10B-5, 10B-7, 10B-8, 10B-9 and 10B-10** each have a strict expected failure to turn into a plain
  test.
- **10B-16** switches the synthetic hospital to `spec` once those cards are in.

## How to revert

- Drop `--variant` and `tools/ssmix2_spec_export.py`; the default path is untouched.
- The check and the tests are new files.

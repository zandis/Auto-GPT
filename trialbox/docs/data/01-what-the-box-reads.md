# 1. What the box reads

| Source | Reader | Country | Direction |
| --- | --- | --- | --- |
| CSV export from the HIS | `adapter run --source csv` | TW, JP | one way in |
| CGRD-type SQL views | `--source cgrd_sql` | TW | one way in |
| SS-MIX2 standardized and extended storage | `--source ssmix2` (`services/adapter/sources/ssmix2/`) | JP | one way in |
| FHIR bulk NDJSON | `--source fhir_bulk` | any | one way in |
| REDCap project | `services/rc_bridge` (API, no External Module) | any | two way |
| a PI's spreadsheet (CSV in UTF-8, Shift_JIS or Big5; XLSX) | data core sheet import | any | two way |
| FHIR bundle of QuestionnaireResponses | data core | any | in |
| charts one by one (text, Word, PDF, scans, pasted EMR text) | site set-up (`services/sitesetup`) | any | in, as *proposed* facts |

TrialBox never writes to a hospital record system (owner decision 2, 2026-11-08). The nightly ingest makes a FHIR
R4 snapshot with pseudonyms (`HMAC(site key, chart number)`) and rebuilds the lake; HAPI gets only new or changed
resources (D-122).

**SS-MIX2 (Japan).** The reader walks `<id[0:3]>/<id[3:6]>/<id>/<診療日>/<type>/`, resolves each record (patient,
診療日, type and order number: the specification's key; a site may declare `unique`, D-594, D-1000) from all its files
by the guideline's rules for versions, deletions and condition flags (D-1252, below), and
reads HL7 v2.5 in ISO-2022-JP (with its katakana and extended sets) and, for 8-bit files, in the encoding MSH-18
names, else the one the site declares (`TB_SSMIX2_ENCODING`: EUC-JP, SHIFT_JIS or UTF-8; an unknown value stops
the reader), read first and strictly, never falling back to another; an undeclared 8-bit file is read only when it
can be one encoding alone (UTF-8 holding Japanese, or Shift_JIS that is not also EUC-JP), else set aside, never
guessed. Every reading must keep its separators and hold no control character but the segment ends (C0 and C1).
Every message must carry exactly one PID whose PID-3 names the patient of its file name and folders, and no other
patient (in PID-3's other repetitions, PID-2, PID-4, or an MRG outside ADT); else it is set aside. Every table
carries one form of the id (NFKC, blanks removed). A diagnosis is confirmed and active only when everything about it
is recognised. It reads ADT-00/12/22/52 (patient, visits, discharges, class changes), PPR-01 (one
snapshot per patient: deletions, ICD-10 from PRB-10, dates, 転帰, 主診断, 修飾語), OMP-01/02 (orders: one dose, the
doses a day from the 用法, YJ from RXE-31) and OMP-11/12 (administrations) with YJ and ATC, and OML-11 (labs with
JLAC10). Extended storage is read in the guideline's layout (content folders under data-type folders that carry the
LOINC document code) and in the older one (files in folders named by kind); `_contents.xml` is not read. Tables
SS-MIX2 does not standardize come from `<root>/extended/<table>.csv` (D-122, D-137). Output claims JP Core 1.1.0 and
is validated on a sample at ingest, offline (`services/adapter/validate/jpcore.py`).

What of the specification the reader reads, after plan 10 cards 10B-2 to 10B-5 (review 12 §4.9, which counted 26
types: 1 parsed, 8 partly, 17 not). It is tested against a storage written from the specification
(`tests/ssmix2_spec_kit.py`, `tests/unit/test_ssmix2_to_specification.py`), not yet against a vendor's storage.

Each row says what is read and what is not; "Partly" means only what the row lists. No type is read in full.

| Type or part | State | What is read | What is not read |
| --- | --- | --- | --- |
| Tree, file names, flags | Partly | `<pid 1-3>/<pid 4-6>/<pid>/<day>/<type>/<file>`, seven-part names, flags 1 有効, 0 無効(削除), 2 過去履歴 (構築ガイドライン Ver.1.2j 表3.1-3 No.7), the key (patient, 診療日, type, order no; `unique` by declaration; the order number compared after NFKC with blanks removed). Each record is resolved from all its files by 発生日時 (表3.1-3 No.5), never by arrival: the newest flag 1 is in force and replaces the whole record (3.1.2 (2), 3.1.4 (2) ⑥ 1)); a newest flag 0 deletes exactly that record, with every line or diagnosis any older version named (⑥ 2)); a deletion wins a tie. For PPR-01 and OMP-01/02, a record with no version in force (a newest flag 2, two live files with one 発生日時, a newest file that cannot be read or is set aside, a delete whose patient is not certain) is read from every version that could be in force, as unknown, with the reason in `version_note` (D-1252). Other depths, extensions, other part counts and flags counted, not read; symbolic links not followed (both storages) | For ADT and OML-11 a record with no version in force keeps #1095's reading (a newest flag 2 set aside, an unreadable newest skipped); a delete filed under another day reaches only its own day's record (the key); multi-volume manifest (10B-11) |
| ADT-00 | Partly | PID-3 (PI), PID-5 (漢字), PID-7, PID-8, PID-13, PID-29, PID-30 | IN1; A23 only as flag 0 (10B-8) |
| ADT-12 | Partly | PV1-2, PV1-7, PV1-10, PV1-19, PV1-44 | Other PV1 fields |
| ADT-22 | Partly | As ADT-12, PV1-45 | A11 cancellation only through flag 0 (10B-8) |
| ADT-52 | Partly | A03 discharge (PV1-45), a class change (PV1-2) | A13 (cancel discharge) not undone (10B-8) |
| ADT-01, 21, 31, 32, 41, 42, 51, 61 | Not | – | 10B-7, 10B-8 |
| PPR-01 | Partly | Active only when PRB-1 is AD, UP, CO or UC, PRB-14 is empty or exactly one recognised code-and-table pair (a verified row, or the reader's legacy `A` / `R` alone), no field is repeated (PRB-3, 13, 14, 17, any date), no onset, diagnosis or record date is after its file was written, and every date is a real date (full-width digits read) and no end, outcome day or outcome code says otherwise (else U, or E with a readable end or outcome day; an unreadable or repeated date's text kept in `end_date_text` / `outcome_date_text` / `date_text`); confirmed only when PRB-3 or PRB-10 carries a code, PRB-13 is empty (the code table of JHSD0005, 表95, holds only `1` 疑いあり, so a `0` is unknown, D-1252), the ZPR segment is recognised (below) and PRB-17 is empty or the same name (else U); two diagnoses with one number (compared with NFKC, blanks removed, case folded) set the snapshot aside, and the version before it is read as unknown. ZPR by its fields (仕様書 Ver.1.2j 3.7.4, 表3-48): ZPR-1 / ZPR-3 the prefix and suffix 修飾語管理番号, ZPR-2 the 病名管理番号, ZPR-4 / ZPR-6 their exchange codes, ZPR-5 the 病名交換用コード, ZPR-7 a comment. Without the site's licensed MEDIS master, ZPR-2 and ZPR-5 must name PRB-3's own disease and any modifier or comment is unknown; with it, the display name must be exactly the prefixes' 修飾語表記, the 病名表記 and the suffixes' 修飾語表記, every modifier a current row in its own position, of class 1 部位, 2 位置 or 9 歯科, or 3 病因 when the modified name has no code of its own (classes 4 to 8 unknown), and a PRB-3 code the master lacks, or a local code, is unknown (ICD10対応標準病名マスター Ver.5.18 仕様書 (2), D-1252). The guideline's layout is one snapshot per patient under "ALL9" and the day "-" (構築ガイドライン 3.1.2 (2)): the newest in force (any day folder) is the whole list, and a diagnosis an older one holds and it does not is deleted in the lake, as by `DE`. One file per diagnosis under its own number is TrialBox's exporter's layout, not the guideline's: it is read as records of their own; beside a snapshot, one older than the snapshot is superseded by it and one newer is unknown; one diagnosis number in two records is unknown. PRB-1 `DE` (also full-width), PRB-2, PRB-3, PRB-4, PRB-7, PRB-9, PRB-10, PRB-13, PRB-14 (the code is kept; a status is applied only from a row of `jp_core/prb14_outcome.csv` marked verified, and none is, so every coded 転帰 is unknown (U), never active; a code whose own text says another outcome is U; an end day (PRB-9) with no read outcome is E, ended: inactive with its end day), PRB-15, PRB-16, PRB-17, PRB-18, ZPR-1 to ZPR-7 | Without a licensed master, doubt written only in the display text (see the limits below); FHIR `bodySite` and laterality from the modifiers (kept as text in `modifiers`). A diagnosis is suspected when the flag (JHSD0005, also `99JHSD0005`, full-width digits read), the name, PRB-17 or a modifier says so (疑, R/O, s/o, rule out, suspected, a trailing ?); ruled out ("疑いなし", "ruled out") when one of them says that (refuted: the lake leaves it out); unknown when both are said, or PRB-13 holds a value of a table the reader does not know (unconfirmed); 主診断 not yet read by the lake |
| OMP-01, 02 | Partly | Every RXE of the message: ORC-1 (CA, OC, CR cancel; DC, OD, DR stop; HD, OH hold; NW, XO, SC, RE, OK, SN leave the status to ORC-5; any other, or none, is unknown, never active), ORC-2, 4, 5, 9; RXE-2, RXE-3 (one dose), RXE-5, RXE-31 (YJ); TQ1-3 (用法), TQ1-7/8, only when its ORC group holds one RXE and one TQ1; the daily dose only from the site's `usage.csv` or a text that is exactly "1日N回" with meal times. An order is keyed by the file's order number (with ORC-2 added when it says something else; ORC-2 alone under "ALL9"; neither: the message is set aside); in a message of several lines, each line by that key, Rp number (ORC-4) and drug code (RXE-2), and a line no newer version holds is deleted (one file is one order, 構築ガイドライン 3.1.2 (2)). An order number filed on several days (any flag): each day is its own record, keyed `<number>@<day>` from the first night, and the plain key is tombstoned; a delete deletes only its own day. **The reader's own caution, not the guideline's rule** (D-1252 P6): a day whose number another day holds with a newer file is read as unknown | JAMI 標準用法 codes are not decoded; RXE-12 refills; any other usage wording gives no daily dose |
| OMP-11, 12 | Partly | ORC-2, 5, 9; RXA-3/4, RXA-5, RXA-6/7 (the amount given); an administration fills the one line of its order that holds its drug, else it is a row of its own | Other RXA fields |
| OML-11 | Partly | OBX-2, 3, 5, 6, 7, 8, 11, 14, 21; OBR-2/3, 7; SPM-4, 17 | Microbiology shape untested (10B-9) |
| OML-01, OMG-01/02/03/11/12/13, OMD | Not | – | 10B-9, 10B-10 |
| Extended storage | Partly | Content folders (versioned and flagged by name; on an equal 発生日時 a deletion wins; symbolic links, hidden names and backup copies such as `.bak` not read), the LOINC code of a CWE data-type folder (`jp_core/document_loinc.csv`, each `verify`), the older layout; text, HTML/XML (tags dropped), Word, PDF with text | `_contents.xml`; CDA sections (HS032, HS008) |
| Character sets, dates | Partly | ISO-2022-JP (SO/SI katakana; a set left open at a segment end is set aside), UTF-8, EUC-JP and Shift_JIS as above; declared separators, `\.br\`, `\Xhh\`; `""` read as empty; impossible and era dates counted; a time part of another length counted and not read; a leap second counted as not a time of day; a time with an offset converted to the site's zone (`TB_TZ`); an offset beyond ±14:00 sets its message aside | With no site zone a time with an offset keeps only its day |

**What is set aside, and why** (counted in the reader's statistics by pattern, never by a patient's name; a quarantined
message is listed with its reason, STD-020). A site that finds these counts should ask its vendor:

| Set aside | Why | What the site can do |
| --- | --- | --- |
| A message in no readable encoding | No codec reads it strictly | Ask the vendor which encoding it writes |
| An 8-bit message MSH-18 does not name that could be more than one encoding, or whose Shift_JIS reading would lose a separator into a character | Guessing would store wrong text or shift every field after the lost separator | Set `TB_SSMIX2_ENCODING` to the vendor's encoding, or have MSH-18 name it |
| A message that is not the encoding it declares, or declared Shift_JIS that is also EUC-JP-shaped, or a decoded text holding a control character (an ESC, SO) | The declaration is wrong or the bytes are damaged | Ask the vendor to correct MSH-18 or the export |
| A message whose PID-3, or whose folders, name another patient (or another day or type folder) than its file name | It cannot be told whose record it is | Ask the vendor to correct the filing |
| A message with a time-zone offset beyond ±14:00; a file whose 発生日時 is not 17 digits of a real time | Its times cannot be placed, or it could replace the right version | Ask the vendor to correct the export |
| An order message with no order number in its file name or ORC-2 | It has no key | Ask the vendor to correct the export |
| An ISO-2022-JP message whose kanji or katakana set is still open at a segment end | Its separators may have been read as characters | Ask the vendor to close the set (ESC ( B) before each segment end |
| A record with no version in force: its newest file carries flag 2 (過去履歴), two live files share one 発生日時, or its newest file cannot be read | Which version is current cannot be told; the older one is never read as current (D-1252) | Diagnoses and orders: read as unknown, the reason in `version_note`; other types: set aside. Ask the vendor to write the newest version as flag 1 |
| A file at another depth, with an extension, with another number of name parts or another flag; a symbolic link; a hidden or backup document | Not a message or document file of the layout | Remove or move it |
| A delete, a newer version or an unreadable file filed under another day than an order's | The day is part of the record's key: it deletes only its own day | The other day's order is read as unknown and counted (OMP-01/02); declare `unique` if the vendor files amendments under the day they were sent |
| A drug line whose TQ1 the message structure does not tie to it | The timing could belong to another drug | Kept without a daily dose |
| An administration of a drug its order does not hold, of no drug code, or fitting several lines | It cannot be told which line it was given for | Kept as a row of its own, counted |

**Known limits (D-1252).** What the reader does in these cases, written down so a site can look for them; no test
pins any of it as right:

- Without the site's licensed MEDIS master, a qualifier written only in a coded diagnosis's display text is not read:
  "肺炎（未確定）", "肺炎の可能性あり", "肺炎 provisional", "肺炎既往", "肺炎家族歴" read as confirmed when nothing
  else says otherwise. With the master (`python -m adapter.licensed load --kind medis` and `--kind medis_modifier`)
  such a name is not the coded name and its modifiers, and reads as unknown. No word list is kept.
- The modifier classes 4 経過表現 and 5 状態表現 read as unknown even where a modifier leaves the diagnosis current:
  the master's documentation defines no finer class than the second character of 修飾語区分.
- **Scope:** the unknown reading of a record with no version in force (D-1252 P3 to P6) applies to PPR-01, OMP-01
  and OMP-02 only. The other types read keep #1095's reading: ADT-00, ADT-12, ADT-22 and ADT-52 (a newest file of
  flag 2 is set aside; a newest file that cannot be read is skipped, so a visit stored on an earlier night stays as
  it was), OMP-11 and OMP-12 (administrations, the same), OML-11 (the same; an order number on several days is
  counted only), and the extended storage's documents (versioned by content folder, as before).
- Encoding cases that cannot be told from valid text: EUC-JP bytes under a Shift_JIS declaration that decode as
  half-width katakana (lead bytes below 0xE0); a lead byte cut before `^`, `~`, `\` or an ASCII letter (it forms a
  valid character); one byte dropped in the middle of a name; EUC-JP declared as UTF-8 and the reverse only when the
  bytes happen to be valid in both. A site prevents them by declaring its encoding correctly (MSH-18, or
  `TB_SSMIX2_ENCODING`) and reads them in the first-load report's samples.

**Sources** (D-1252; cited, not copied): SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2j and
標準化ストレージ 仕様書 Ver.1.2j with its コード表 (日本医療情報学会, 2026-08-14, https://www.jami.jp/jamistd/ss-mix2/);
ICD10対応標準病名マスター Ver.5.18 仕様書 (MEDIS-DC, 2026-06, https://www2.medis.or.jp/stdcd/byomei/spc518.pdf).

Count: of the 26 types, **0 read in full**, **10 partly** (ADT-00, 12, 22, 52, PPR-01, OMP-01, 02, 11, 12, OML-11),
**16 not**.

**Code lists.** ICD-10-CM 2026 in full (98,186 codes, public domain) for lookups and family groupers. The licensed
Japanese lists (MEDIS 標準病名, JLAC10, YJ) are loaded by the site from its own licensed files
(`python -m adapter.licensed load --kind medis|medis_modifier|jlac10|yj --file … --version …`, D-137, D-1252); each release is kept with its
version, sha256 and who loaded it, and every load is audited. The demo rows are synthetic and marked `verify`.
The clinical item catalogue (scores, labs, findings and phenotypes mapped to LOINC, OMOP, OHDSI phenotypes and
CDISC QRS) is in `catalogue/`; its design is `docs/reviews/2026-11-09-clinical-item-catalogue.md`. Code reads its
score definitions through a generated file (§8) and its items through `tb_common.catalogue` (D-353):
`python -m omop.catalogue_load` gives each item one concept (LOINC from the vocabulary, a local item at its
TB-SHARED id; a LOINC code the vocabulary lacks is listed as unmapped), chart extraction drops item answers of an
instrument whose `storable` is `score`, and `/data/items` shows the items by specialty to the administrator.
The instrument copyright register (`catalogue/instruments.csv`, D-375) says, from public sources, who holds each
licensed scale or questionnaire and what its terms say; `/data/instruments` shows it to the administrator. A site
that holds a licence may keep more of an instrument than the catalogue allows only by giving its licence reference
(an empty one is refused and audited). TrialBox asks nobody for a licence. The phenotypes load with a status
(`tb_common.phenotypes`): seven ICD-10-CM sets are checked on the synthetic hospital, the other 157 are "not
validated here". An Athena load records one licence acknowledgement per licensed vocabulary in the bundle
(`python -m omop vocab status` lists them).

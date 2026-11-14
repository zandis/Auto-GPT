# D-745 A date of birth, a postal address and a chart number after any of its labels are masked in notes

- **Task:** NEW-B-44 (a safety defect; placed with lane B2 by the integrator on 2026-11-14, "first, together with
  D-744")
- **PR:** this branch (`agent/NEW-B-44-birth-dates-addresses-chart-labels-masked`), on top of NEW-B-43 (D-744)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** T-600 / FR-DEID-01 (note text masked before chunking, the full-text index and embedding), D-337
  (the masking version recorded), D-215 (the guard's date-of-birth value in `tb_common.dates`), PRIV-29 / S1-08 (the
  guard service's recognisers), D-744 (the English phone form, the version 2)

## Context

The owner ran the box's own masker (`tb_common.phi_guard.mask_note`) on a month of real hospital notes on his own
computer and sent **counts only** (no value left the hospital): about 34,500 discharge summaries and 31,200 admission
notes. National numbers, mobile and landline numbers: none survived. **Survived:** dates of birth (20 and 67),
postal addresses (1 and 52) and chart numbers after a label in a form the masker did not know (3 and 2). The masker
had no date-of-birth and no address pattern; the guard service had both, but the masker did not read them.

## Decision

1. **A date of birth** (`dob`) is masked after its label (出生日期, 出生年月日, 出生日, 出生, 生日, 生年月日, 誕生日,
   DOB, D.O.B., date of birth, birth date, born on) or before the word for born (…生, …出生, …生まれ; never 生化 or
   生理 and the like). The value: the guard's forms of D-215 (ISO, 年月日, 民國, 和暦 年月日, US slashed, month name)
   and the ROC year without 民國 (45年3月14日, 045/03/14), an era abbreviation (S31.3.14), day first (14/03/1956) and
   a day before the month's name (14 Mar 1956). A date with neither a label nor the word for born is a clinical date
   and stays.
2. **A postal address** (`address`) is masked: Taiwanese (縣市, 區鄉鎮, 村里 and 鄰, 路街, 段巷弄, 號, 樓),
   Japanese (都道府県, 市区町村, 丁目 番 号 or dashes) and English (a number, a street of a known type, a flat, a
   town; never a year before it), and whatever follows an address label (通訊地址, 戶籍地址, 居住地址, 聯絡地址,
   住址, 地址, 現住所, 住所, 居所 with a separator; "Address:" with a colon, not after IP, peer, email, public, web)
   to the end of the field.
3. **A chart number after any of its labels** (`mrn`): 病歷號(碼), 病歷編號, 病歷碼, 病历号, 病歴番号, カルテ番号,
   カルテNo., 患者ID, 患者番号, 患者No., 診察券番号, 病人ID, 病患ID, MRN, chart no./number, medical record
   no./number, hospital no./number, patient ID; the number may be written in full-width digits.
4. **One definition each** in `tb_common.phi_guard` (`DOB_LABELLED`, `DOB_BORN`, `ADDRESS_ZH`, `ADDRESS_JA`,
   `ADDRESS_EN`, `ADDRESS_LABELLED`, `MRN_LABELLED`). The guard service's recognisers name them (they moved from
   `guard.recognisers`, which held the address, birth-date and chart patterns): redaction, the tripwire and the
   masker cannot drift apart. The guard's date value of D-215 (`dates.DOB_SPAN`) is unchanged.
5. **The masking version is 3** (`NOTE_MASK_VERSION`): as for D-744, the vector search reads chunks of an older
   version as stale and the lake masks every note again at its next rebuild.

## What a person sees differently

In the full-text index, the chunks and the embedding inputs, a labelled date of birth, an address and a chart number
under one of the new labels are `○`; the lake's `document` table keeps the original under the `phi` label. The guard
service redacts the new shapes too (an English street of a newly known type, a date before 生, an address after its
label).

## Measured

- Over the repository's text (44 million characters: public protocols, IR fixtures, model cassettes, the guard's,
  consent, onboarding and reference fixtures, rulesets, documents) the new patterns find seven values, six of them a
  date of birth or a chart number in a document's example and one prose ("a locked address: 401"). Two kinds of
  false positive seen on the way (a year before "Court", "peer address:") are no longer matched and are cases in the
  tests.
- The synthetic notes of the Taiwanese and Japanese sites (planted names, chart numbers, phones, insurance numbers
  and now addresses): every planted value masked, every clinical finding kept, nothing else masked.
- No harm on the goldens: `make goldens-check` (in the PR's gates).

## Not in this card

- A date of birth without a label and without the word for born ("65歲, 1956/3/14") is not told from a clinical date.
- An address with no label and none of the shapes above (a building name alone, a 里 without 鄰 and no label).
- The owner's run counted survivors by shape; re-running his count after this card says what is left.

## Tests

`tests/unit/test_phi_note_dob_address.py` (62 tests; 41 fail on the parent; the others are the clinical texts, the chart labels the masker already knew and the shapes the guard service already redacted):
sixteen dates of birth (zh-TW, ja, en; ROC, era, western), ten addresses, fourteen chart labels, eight clinical texts
with dates, places and numbers that are none of them, and the guard service redacting the same. The planted-identifier
test of the synthetic notes (`tests/unit/test_phi_note_mask.py`) now asks every planted **address** masked too (it
found the English street type "Close" missing). D-744's version test reads "2 or later". No state change.

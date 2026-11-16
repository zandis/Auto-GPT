# D-745 A date of birth, a postal address, a chart number after any of its labels and an email are masked in notes

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
had no date-of-birth, no address and no email pattern; the guard service had them, but the masker did not read them.

## Decision

1. **A date of birth** (`dob`) is masked after its label (出生日期, 出生年月日, 出生日, 出生, 生日, 生年月日, 誕生日,
   DOB, D.O.B., date of birth, birth date, born on) or before the word for born: 生 at the end of the phrase
   (…生，, …生) and 生まれ, 出生; never the 生 of 生検, 生体, 生食, 生病, 生長, 生效, 生化 and the like. The value: the
   guard's forms of D-215 and 年月日 with spaces or full-width digits, 西元 and 民國 (in figures or in Chinese
   numerals), the ROC year without 民國 (45年3月14日, 045/03/14, 45.3.14), an era and its abbreviation (S31.3.14), day
   or month first with a two- or four-digit year, the month's name before or after the day; after a label also a
   compact date (19560314, the ROC 0450314 of a hospital system's header). A date with neither a label nor the word
   for born is a clinical date and stays.
2. **A postal address** (`address`) is masked:
   - Taiwanese (縣市, 區鄉鎮, 村里 and 鄰, 路街, 段巷弄, a number with 之 or a dash, 號, 之, 樓, 室), a village's
     address without a road (縣, 鄉, 村, 鄰, 號); Japanese (都道府県, 市区町村, 丁目 番地 号 の or dashes, 号室); English
     (a number, one to three capitalised words that are not a unit or a count, a street of a known type, a flat, a
     town, a state or province and a ZIP code or a British postcode; never a year before it, and only where the
     street ends the phrase);
   - after an address label (通訊地址, 戶籍地址, 居住地址, 聯絡地址, 住址, 地址, 戶籍地, 居住地, 現住所, 住所, 居所,
     現住 with a separator; 住: but never 入住:; "Address:" with a capital or after home, postal, mailing, current,
     permanent — "to address: renal dosing" is no label), whatever follows to the end of the field: punctuation, a
     line break, a tab, two spaces or **the next field's label** (`電話:`, `診斷:`, `Diagnosis:`), and only when its
     first word holds a figure or a word of an address (`地址 不詳` stays).
3. **A chart number after any of its labels** (`mrn`): 病歷號(碼)(為), 病歷編號, 病歷碼, 病歷No., 病历号, 病例號(碼),
   病歴番号, 住院號(碼), 門診號(碼), 病人編號, 歸檔號, カルテ番号, カルテNo., 患者ID, 患者番号, 患者No., 診察券番号,
   病人ID, 病患ID, MRN, chart no./number/#, medical record no./number, hospital no./number, admission no., visit no.,
   patient ID, insurance ID, ID:; also written against its number (`MRN` and the number with nothing between) and in
   brackets (`病歷號（…）`); the number may be in full-width digits and holds **four figures or more** (never a
   decision's number such as D-143).
4. **An email address** (`email`): the guard service's form.
5. **One definition each** in `tb_common.phi_guard` (`DOB_LABELLED`, `DOB_BORN`, `ADDRESS_ZH`, `ADDRESS_JA`,
   `ADDRESS_EN`, `ADDRESS_LABELLED`, `MRN_LABELLED`, `EMAIL`). The guard service's recognisers name them (the
   address, birth-date, chart and email patterns moved from `guard.recognisers`): redaction, the tripwire and the
   masker cannot drift apart. The guard's date value of D-215 (`dates.DOB_SPAN`) is unchanged.
6. **The masking version is 3** (`NOTE_MASK_VERSION`): as for D-744, the vector search reads chunks of an older
   version as stale (every patient, until indexed again) and the lake masks every note again at its next rebuild.

## What a person sees differently

In the full-text index, the chunks and the embedding inputs, a labelled date of birth, an address, a chart number
under one of the new labels and an email address are `○`; the lake's `document` table keeps the original under the
`phi` label. The guard service redacts the same shapes and its tripwire refuses a call that carries one. A chart
number written against its label (`MRN` and the number) is caught again: the first version of this card had lost it.

## Measured

- **The PHI evaluation set** (`eval/phi_synth`: 120 synthetic notes in zh-TW, ja and en, gold spans, 510 decoys),
  masked by the masker, master → D-744 → this card: addresses 0 → 0 → **102 of 104**; dates of birth (the gold
  `DATE` spans that are births) 0 → 0 → all but the spaced and Chinese-numeral forms now covered (93 of the 189 gold
  dates masked, every one a birth; no visit date masked); identifiers 125 → 125 → **132 of 136** (a superset of
  master's); emails 0 → 0 → **52 of 52**; phones 80 → 119 → 119 of 120; decoys masked 5 → 5 → 5 of 510.
- **The repository's text** (44 million characters: public protocols, IR fixtures, model cassettes, the guard's,
  consent, onboarding and reference fixtures, rulesets, documents): the new patterns find six values, each a date of
  birth or a chart number in a document's example. Seen on the way and no longer matched, each a case in the tests: a
  year before "Court", "peer address:", "to address:", decision numbers after "chart number", "入住:".
- **The synthetic hospital** (TW and JP styles, planted PHI): every planted name, chart number, phone, insurance
  number and address masked, every clinical finding kept, nothing else masked.
- **The goldens**: every funnel, ruleset result and lake table is unchanged except the chunk table's masked text,
  tokens and hashes of the four synthetic sets (`synthetic-jp-a`, its two later nights, `synthetic-tw-a`) and
  `ssmix2-jp`: the 1,151 planted addresses of the synthetic hospital's notes (住所, 住址, Address) are now masked, and
  nothing else is (compared span by span with master's masker on the `ci` hospital's 8,889 notes).
  `tests/golden/lake/tables@ci.json` is rewritten with that reason; `public-en` (the SIGIR notes) is unchanged.

## Not in this card

- A date of birth without a label and without the word for born ("65歲, 1956/3/14") is not told from a clinical date.
- An address split by spaces (`測試市 範例區 虛擬路 12號`), a building name alone, a Japanese address with neither a
  prefecture nor a label, an English street in lower case.
- A chart number after the bare word 病歷, or of fewer than four figures.
- The owner's run counted survivors by shape; re-running his count after this card says what is left.

## Tests

`tests/unit/test_phi_note_dob_address.py` (115 tests): twenty-nine dates of birth (zh-TW, ja, en; ROC, era, western,
spaced, full-width, compact, Chinese numerals), twenty addresses (with ZIP codes, postcodes, 之, 室, 号室, a village
without a road), thirty-two chart labels (with the label against the number and the bracketed form, through the
masker and the guard's tripwire), an email, header lines whose next field is kept, fourteen clinical texts that none of
the patterns touches nor the tripwire refuses (生検, 生体, 生病, 生效, "to address:", units before a street word,
decision numbers, 入住:), the guard service redacting the same, the version. The planted-identifier test of the
synthetic notes (`tests/unit/test_phi_note_mask.py`) now asks every planted **address** masked too. D-744's version
test reads "2 or later". No state change.

## Review

One adversarial read-only review by a fresh agent (about 150 probe strings; the PHI evaluation set; the synthetic
hospital; the guard over every tracked text line, parent against this card; 20,000-character adversarial strings:
linear, at most 35 ms; nine mutants). Findings, fixed test-first in the third commit: **a chart number written against
its label escaped the masker and the guard's tripwire** (a word boundary the first version added); an address label
swallowed the next fields of a header line; "to address:" read as a label (a refused call); 生 of 生検, 生体, 生病,
生長, 生效 read as born; spaced, full-width, compact, 西元 and Chinese-numeral dates of birth, ZIP codes and postcodes,
hyphenated and village addresses, 之 and 室, and nine chart labels missed; capitalised units before a street word read
as an address. The evaluation set then showed emails never masked (now the guard's form), 入住: read as 住:, and
decision numbers after a chart label (four figures now required). Said above, not changed: the forms listed.

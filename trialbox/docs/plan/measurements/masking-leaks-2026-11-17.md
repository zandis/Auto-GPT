# Masking hides identifiers in notes? Planted identifiers on synthetic notes, 2026-11-17 (card V-5, plan 8 V6)

**Reader:** the integrator, lane B2 (the note masker, `tb_common.phi_guard`) and lane A2 (the guard, `services/guard`)

**Verdict.** No. Of 3,318 synthetic notes with one planted identifier each, the masker left the identifier readable in
932 (281 per 1,000: zh-TW 258, ja 299, en 291). The gateway tripwire let 817 of them (246 per 1,000) through, so the
raw note could go to a route that leaves the box. Leaving out the line-break place, the masker still leaks 206 per
1,000 (587 of 2,844). Names are the worst kind: ja 767, en 546, zh-TW 476 per 1,000. Names leak even right after the
label 氏名, 姓名 or Name when the name is in kana or Latin letters, has a surname outside the masker's lists, or is
written "LAST, First". Classes missed entirely: e-mails with a full-width ＠ (1,000 per 1,000 in all three
languages), the Japanese insurance card's 記号・番号 after its label (1,000), compact ROC birth dates before 出生
(1,000). Classes missed partly: unlabelled Taiwan landlines and full-width mobiles (714), an unlabelled US SSN (714),
any value split by a line break (680 to 753). Over-masking: of the clinical strings criteria need, one kind is
altered: an 8-digit date (`20240503`) is masked every time (1,000 per 1,000) by the site chart pattern `^\d{8}$`.
Ages, lab values, doses, stage, scores, variants, NCT ids, codes, durations and every other date form are kept (0).

Every planted form is this card's estimate of how hospitals write. The first look at real data tells the true shapes
and how often each occurs; the per-1,000 figures here weigh every form the same.

## What ran, and what did not

The masker's own suite, at master `15108f46`, run on this machine (PostgreSQL 16 started by the test fixture):

| Suite | Files | Tests | Passed |
|---|---:|---:|---:|
| `tests/unit/test_phi_*.py` | 7 | 548 | 548 |
| `tests/unit/test_derived_phi.py` | 1 | 6 | 6 |
| `tests/unit/test_gateway_box_phi.py` | 1 | 9 | 9 |
| `tests/guard_sets.py` (a helper module, no tests) | 1 | 0 | 0 |
| `make guard` (every test marked `guard`) | - | 436 | 435, 1 skipped |

- `tests/property/` holds no masking test (its three files test generation, the judge loop and path independence).
  It was not run.
- The harness, full run `python -m tools.masking_leaks --write`: 3,318 planted notes and 2,700 clinical strings in
  6.0 seconds (`leaks.json`, field `seconds`; 5 to 6 seconds on each run). Its unit test
  `tests/unit/test_masking_leaks.py`: 18 passed, 33 xfailed, in 3 to 5 seconds.
- **Sight check** (not committed): with the masker's `TW_ID` and `ID_LABELLED` patterns replaced by a pattern that
  never matches, the case `mask-zh-TW-national_id` failed (6 of 24 planted values leaked). The guard's own Taiwan ID
  recogniser kept `tripwire-zh-TW-national_id` green. A clean case is clean because the masker replaced the value:
  the leak rule reads the value's own characters where they were planted, and the harness raises `PlantError` (never
  an assertion) when the value is not in the input. The control: 200 unplanted notes per language give 0 masked
  characters and 0 tripwire hits.
- **Not run: the carve on the owner's PC.** The real notes are only there. The true shapes and rates wait for it.
- **Not run: an outside de-identification tool** (D-1037 allows one for measurement only). The lane's rule 8 forbids
  a download here. What it would add: a second, independent detector, trained on real text, that finds names without
  a label or a list. That is the class this card shows the masker misses most. See the question at the end.

## The entry point traced

Note text leaves the lake by three roads. This card tests the two real entry points, not an inner helper.

1. To retrieval, and from there to a model: `lake.store.Lake.rebuild` reads `document.text` and calls
   `mask_note(note, self.mrn_regex)` before the chunks, the full-text index and the embeddings are made
   (`services/lake/store.py:1463`). The embed service does the same (`services/embed_service/app.py:81`), and so does
   the console for the note text it shows a person (`services/console/reveal.py:81`). The harness calls
   `tb_common.phi_guard.mask_note(text, site_mrn_regex())` (`libs/tb_common/phi_guard.py:847`). The site pattern of
   the test settings is `^\d{8}$`, the shipped example (`deploy/settings.example.yaml:28`).
2. To the judge and verifier models: the cascade reads the original `document.text` (`NOTES_SQL`,
   `services/matching/cascade/engine.py:369`) and sends excerpts of it through the gateway. The gateway runs
   `Guard.tripwire` on every call of class D0 to D2 (`services/gateway/core.py:579`). A hit keeps the call on the box;
   a miss lets the raw note go to an outside route. The harness calls `Guard.from_settings().tripwire(text)`, the
   guard the gateway builds (`services/gateway/core.py:293`).
3. On the box, the judge reads the note unmasked. D-337 section 4 rules this (the screening engines read the
   original). It is listed here, not filed.

## The leak rule and the date rule

- **Leaked (masker):** `mask_note` keeps the length, so the planted value's characters are read at their place. The
  value leaked when none of its characters other than separators (space, line break, dash, dot, slash, brackets,
  colon, plus, comma) was masked. Then its surface string and its width-folded, separator-free form are still in the
  output. A name leaked when its family name and at least one more letter of the name are unmasked. "Partly" means
  some but not all characters were masked; it is counted apart, not as a leak.
- **Leaked (tripwire):** a note with a plant gives no hit.
- **Dates (D-745):** a date of birth after its label (出生日期, 生年月日, DOB) or before the word for born (出生,
  生まれ) must be masked; it is the kind `dob`. A date with neither is a clinical date and must stay. Bare dates are
  in the clinical set, where a mask counts as over-masking.
- **Planting:** the harness invents every value: its own name pools, seeded random digits, Taiwan IDs with a valid
  check digit, NANP 555-01xx phones, example.com mail, streets named Example, Sample, Testing and Placeholder. Nothing
  is drawn from the masker's patterns. Base notes are the synthetic hospital's own sentences (`tools/synth/notes.py`,
  `notes_ja.py`, `notes_en.py`). One plant per note, at one of seven places: start, middle, end, after a label, in a
  tab-separated table line, against CJK (brackets in English) with no space, and split by a line break. Every form
  gets every place equally (21 notes per form and language).
- **Claimed against planted:** the masker claims `name, phone, mrn, id, dob, address, email, bed, room`
  (`phi_guard.py:815`). All were planted but `bed` and `room`. The US SSN was planted too; the masker does not claim
  it.

## Tables

Generated: `python -m tools.masking_leaks --check` compares them whole with `leaks.json`.

By language:

<!-- masking-leaks:summary:begin -->
| Language | Planted notes | Leaked (masker) | Per 1,000 | Partly masked | Tripwire missed | Per 1,000 |
|---|---:|---:|---:|---:|---:|---:|
| en | 1050 | 305 | 290.5 | 55 | 293 | 279.0 |
| ja | 1029 | 308 | 299.3 | 53 | 256 | 248.8 |
| zh-TW | 1239 | 319 | 257.5 | 58 | 268 | 216.3 |
| all | 3318 | 932 | 280.9 | 166 | 817 | 246.2 |
<!-- masking-leaks:summary:end -->

By kind:

<!-- masking-leaks:kinds:begin -->
| Language | Kind | Planted | Leaked | Per 1,000 | Tripwire missed | Per 1,000 |
|---|---|---:|---:|---:|---:|---:|
| en | address | 42 | 1 | 23.8 | 1 | 23.8 |
| en | chart | 168 | 33 | 196.4 | 33 | 196.4 |
| en | dob | 231 | 27 | 116.9 | 18 | 77.9 |
| en | email | 63 | 25 | 396.8 | 25 | 396.8 |
| en | name | 231 | 126 | 545.5 | 123 | 532.5 |
| en | national_id | 84 | 24 | 285.7 | 24 | 285.7 |
| en | phone | 231 | 69 | 298.7 | 69 | 298.7 |
| ja | address | 63 | 6 | 95.2 | 6 | 95.2 |
| ja | chart | 147 | 33 | 224.5 | 33 | 224.5 |
| ja | dob | 336 | 26 | 77.4 | 12 | 35.7 |
| ja | email | 63 | 25 | 396.8 | 25 | 396.8 |
| ja | name | 210 | 161 | 766.7 | 123 | 585.7 |
| ja | national_id | 105 | 30 | 285.7 | 30 | 285.7 |
| ja | phone | 105 | 27 | 257.1 | 27 | 257.1 |
| zh-TW | address | 63 | 8 | 127.0 | 8 | 127.0 |
| zh-TW | chart | 168 | 33 | 196.4 | 33 | 196.4 |
| zh-TW | dob | 462 | 66 | 142.9 | 33 | 71.4 |
| zh-TW | email | 63 | 25 | 396.8 | 25 | 396.8 |
| zh-TW | name | 210 | 100 | 476.2 | 82 | 390.5 |
| zh-TW | national_id | 84 | 12 | 142.9 | 12 | 142.9 |
| zh-TW | phone | 189 | 75 | 396.8 | 75 | 396.8 |
<!-- masking-leaks:kinds:end -->

By place:

<!-- masking-leaks:positions:begin -->
| Position | en leaked / planted (per 1,000) | ja leaked / planted (per 1,000) | zh-TW leaked / planted (per 1,000) |
|---|---:|---:|---:|
| start | 41 / 150 (273.3) | 39 / 147 (265.3) | 40 / 177 (226.0) |
| middle | 39 / 150 (260.0) | 39 / 147 (265.3) | 38 / 177 (214.7) |
| end | 39 / 150 (260.0) | 40 / 147 (272.1) | 38 / 177 (214.7) |
| label | 12 / 150 (80.0) | 25 / 147 (170.1) | 16 / 177 (90.4) |
| table | 22 / 150 (146.7) | 25 / 147 (170.1) | 14 / 177 (79.1) |
| cjk_adjacent | 39 / 150 (260.0) | 40 / 147 (272.1) | 41 / 177 (231.6) |
| line_break | 113 / 150 (753.3) | 100 / 147 (680.3) | 132 / 177 (745.8) |
<!-- masking-leaks:positions:end -->

Every form with a leak, a partial mask or a tripwire miss (up to five examples per cell in `leaks.json`, digits
written `d`):

<!-- masking-leaks:forms:begin -->
| Language | Kind | Form | Planted | Leaked | Per 1,000 | Partly | Tripwire missed | Leaked at |
|---|---|---|---:|---:|---:|---:|---:|---|
| en | address | en_apt | 21 | 1 | 47.6 | 11 | 1 | line_break 1 |
| en | address | en_full | 21 | 0 | 0.0 | 12 | 0 |  |
| en | chart | bare_7 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| en | chart | bare_8 | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | chart | label_Chart_No | 21 | 0 | 0.0 | 3 | 0 |  |
| en | chart | label_Hospital_No | 21 | 0 | 0.0 | 3 | 0 |  |
| en | chart | label_ID | 21 | 0 | 0.0 | 3 | 0 |  |
| en | chart | label_MRN | 42 | 0 | 0.0 | 6 | 0 |  |
| en | chart | letter_7 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| en | dob | label_compact8 | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | dob | label_day_month_abbr | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | dob | label_dotted | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| en | dob | label_iso | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| en | dob | label_month_name | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | dob | label_slash_dmy | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | dob | label_slash_mdy | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | dob | label_slash_ymd | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| en | dob | label_two_digit_year | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | email | ascii | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | email | fullwidth_at | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| en | email | plus | 21 | 1 | 47.6 | 2 | 1 | line_break 1 |
| en | name | dr | 21 | 0 | 0.0 | 6 | 0 |  |
| en | name | first_last | 21 | 18 | 857.1 | 0 | 18 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3, table 3 |
| en | name | initials | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| en | name | last_comma_first | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| en | name | middle_initial | 21 | 18 | 857.1 | 0 | 18 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3, table 3 |
| en | name | mr | 21 | 3 | 142.9 | 3 | 0 | label 3 |
| en | name | ms | 21 | 0 | 0.0 | 6 | 0 |  |
| en | name | pinyin_family_first | 21 | 18 | 857.1 | 0 | 18 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3, table 3 |
| en | name | pinyin_given_first | 21 | 18 | 857.1 | 0 | 18 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3, table 3 |
| en | name | wade_giles_family_first | 21 | 6 | 285.7 | 0 | 6 | line_break 3, start 2, table 1 |
| en | name | wade_giles_given_first | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | national_id | tw_arc_new | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | national_id | tw_arc_old | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | national_id | tw_id | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | national_id | us_ssn | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| en | phone | na_hyphen | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | na_intl | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | na_paren | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | tw_landline_ext | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| en | phone | tw_landline_hyphen | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| en | phone | tw_landline_paren | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| en | phone | tw_mobile_hyphen | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_intl | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_intl_space | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_plain | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_space | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | address | jp_full | 21 | 3 | 142.9 | 12 | 3 | line_break 3 |
| ja | address | jp_hyphen_building | 21 | 0 | 0.0 | 15 | 0 |  |
| ja | address | jp_no_postcode | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | chart | bare_7 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| ja | chart | bare_8 | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | chart | label_ID | 21 | 0 | 0.0 | 3 | 0 |  |
| ja | chart | label_カルテNo | 21 | 0 | 0.0 | 3 | 0 |  |
| ja | chart | label_カルテ番号 | 21 | 0 | 0.0 | 3 | 0 |  |
| ja | chart | label_患者ID | 21 | 0 | 0.0 | 3 | 0 |  |
| ja | chart | letter_7 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| ja | dob | born_compact8 | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | dob | born_dotted | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | dob | born_era_kanji | 21 | 0 | 0.0 | 2 | 0 |  |
| ja | dob | born_iso | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | dob | born_slash_ymd | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | dob | label_compact8 | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| ja | dob | label_dotted | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| ja | dob | label_era_kanji | 21 | 1 | 47.6 | 0 | 0 | line_break 1 |
| ja | dob | label_era_letter | 21 | 1 | 47.6 | 0 | 0 | line_break 1 |
| ja | dob | label_iso | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| ja | dob | label_slash_ymd | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| ja | email | ascii | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | email | fullwidth_at | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| ja | email | plus | 21 | 1 | 47.6 | 2 | 1 | line_break 1 |
| ja | name | hepburn_family_first | 21 | 21 | 1000.0 | 0 | 15 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| ja | name | hepburn_given_first | 21 | 21 | 1000.0 | 0 | 15 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| ja | name | hiragana_space | 21 | 21 | 1000.0 | 0 | 15 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| ja | name | kanji | 21 | 17 | 809.5 | 0 | 15 | cjk_adjacent 3, end 3, label 1, line_break 3, middle 3, start 3, table 1 |
| ja | name | kanji_space | 21 | 17 | 809.5 | 2 | 15 | cjk_adjacent 3, end 3, label 1, line_break 3, middle 3, start 3, table 1 |
| ja | name | kanji_さん | 21 | 9 | 428.6 | 0 | 5 | cjk_adjacent 1, end 1, label 2, line_break 3, table 2 |
| ja | name | kanji_先生 | 21 | 5 | 238.1 | 4 | 5 | cjk_adjacent 2, end 2, middle 1 |
| ja | name | kanji_様 | 21 | 10 | 476.2 | 1 | 8 | cjk_adjacent 1, end 1, label 1, line_break 1, middle 2, start 3, table 1 |
| ja | name | kanji_殿 | 21 | 19 | 904.8 | 0 | 15 | cjk_adjacent 3, end 3, label 2, line_break 3, middle 3, start 3, table 2 |
| ja | name | katakana_space | 21 | 21 | 1000.0 | 0 | 15 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| ja | national_id | insurance_symbol_no | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| ja | national_id | insurer_no | 21 | 0 | 0.0 | 3 | 0 |  |
| ja | national_id | my_number | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | national_id | my_number_fullwidth | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | national_id | my_number_spaced | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | phone | jp_fullwidth | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| ja | phone | jp_intl | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | phone | jp_landline | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | phone | jp_mobile | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| ja | phone | jp_plain | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | address | tw_floor_unit | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | address | tw_full | 21 | 3 | 142.9 | 12 | 3 | line_break 3 |
| zh-TW | address | tw_no_postcode | 21 | 2 | 95.2 | 1 | 2 | line_break 2 |
| zh-TW | chart | bare_7 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | chart | bare_8 | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | chart | label_ID | 21 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | chart | label_MRN | 21 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | chart | label_病歷號 | 21 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | chart | label_病歷號碼 | 42 | 0 | 0.0 | 6 | 0 |  |
| zh-TW | chart | letter_7 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | dob | born_compact8 | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_dotted | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | born_iso | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | born_roc_compact | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| zh-TW | dob | born_roc_dot | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_roc_numerals | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_roc_slash | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_slash_ymd | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_compact8 | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_dotted | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_iso | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_compact | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_dot | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_numerals | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_slash | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_slash_ymd | 21 | 3 | 142.9 | 0 | 0 | line_break 3 |
| zh-TW | email | ascii | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | email | fullwidth_at | 21 | 21 | 1000.0 | 0 | 21 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| zh-TW | email | plus | 21 | 1 | 47.6 | 2 | 1 | line_break 1 |
| zh-TW | name | han_2 | 21 | 16 | 761.9 | 0 | 15 | cjk_adjacent 3, end 3, label 1, line_break 3, middle 3, start 3 |
| zh-TW | name | han_3 | 21 | 16 | 761.9 | 2 | 13 | cjk_adjacent 3, end 2, label 2, line_break 3, middle 2, start 3, table 1 |
| zh-TW | name | han_3_先生 | 21 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | name | han_3_女士 | 21 | 2 | 95.2 | 2 | 2 | cjk_adjacent 2 |
| zh-TW | name | han_3_醫師 | 21 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | name | han_4 | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | name | pinyin_family_first | 21 | 21 | 1000.0 | 0 | 15 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| zh-TW | name | pinyin_given_first | 21 | 21 | 1000.0 | 0 | 15 | cjk_adjacent 3, end 3, label 3, line_break 3, middle 3, start 3, table 3 |
| zh-TW | name | wade_giles_family_first | 21 | 5 | 238.1 | 0 | 4 | line_break 3, start 1, table 1 |
| zh-TW | name | wade_giles_given_first | 21 | 4 | 190.5 | 0 | 3 | label 1, line_break 3 |
| zh-TW | national_id | tw_arc_new | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_arc_old | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_id | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_id_fullwidth | 21 | 3 | 142.9 | 18 | 3 | line_break 3 |
| zh-TW | phone | tw_landline_ext | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | phone | tw_landline_hyphen | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | phone | tw_landline_paren | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | phone | tw_mobile_fullwidth | 21 | 15 | 714.3 | 0 | 15 | cjk_adjacent 3, end 3, line_break 3, middle 3, start 3 |
| zh-TW | phone | tw_mobile_hyphen | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_intl | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_intl_space | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_plain | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_space | 21 | 3 | 142.9 | 0 | 3 | line_break 3 |

Clean cells (no leak, no partial mask, no tripwire miss): 13 of 156.
<!-- masking-leaks:forms:end -->

What the masker removes that criteria need (60 strings per kind and language, each planted in an unplanted note):

<!-- masking-leaks:over:begin -->
| Language | Clinical kind | Planted | Altered (masker) | Per 1,000 | Tripwire hits | Example (digits as d) |
|---|---|---:|---:|---:|---:|---|
| en | accession_10 | 60 | 0 | 0.0 | 0 |  |
| en | age | 60 | 0 | 0.0 | 0 |  |
| en | code | 60 | 0 | 0.0 | 0 |  |
| en | date_compact8 | 60 | 60 | 1000.0 | 60 | `dddddddd` → `○○○○○○○○` |
| en | date_iso | 60 | 0 | 0.0 | 0 |  |
| en | date_mdy | 60 | 0 | 0.0 | 0 |  |
| en | date_month_name | 60 | 0 | 0.0 | 0 |  |
| en | date_slash | 60 | 0 | 0.0 | 0 |  |
| en | dose | 60 | 0 | 0.0 | 0 |  |
| en | duration | 60 | 0 | 0.0 | 0 |  |
| en | gene_variant | 60 | 0 | 0.0 | 0 |  |
| en | lab_value | 60 | 0 | 0.0 | 0 |  |
| en | score | 60 | 0 | 0.0 | 0 |  |
| en | staging | 60 | 0 | 0.0 | 0 |  |
| en | trial_id | 60 | 0 | 0.0 | 0 |  |
| ja | accession_10 | 60 | 0 | 0.0 | 0 |  |
| ja | age | 60 | 0 | 0.0 | 0 |  |
| ja | code | 60 | 0 | 0.0 | 0 |  |
| ja | date_compact8 | 60 | 60 | 1000.0 | 60 | `dddddddd` → `○○○○○○○○` |
| ja | date_era | 60 | 0 | 0.0 | 0 |  |
| ja | date_iso | 60 | 0 | 0.0 | 0 |  |
| ja | date_nen | 60 | 0 | 0.0 | 0 |  |
| ja | date_slash | 60 | 0 | 0.0 | 0 |  |
| ja | dose | 60 | 0 | 0.0 | 0 |  |
| ja | duration | 60 | 0 | 0.0 | 0 |  |
| ja | gene_variant | 60 | 0 | 0.0 | 0 |  |
| ja | lab_value | 60 | 0 | 0.0 | 0 |  |
| ja | score | 60 | 0 | 0.0 | 0 |  |
| ja | staging | 60 | 0 | 0.0 | 0 |  |
| ja | trial_id | 60 | 0 | 0.0 | 0 |  |
| zh-TW | accession_10 | 60 | 0 | 0.0 | 0 |  |
| zh-TW | age | 60 | 0 | 0.0 | 0 |  |
| zh-TW | code | 60 | 0 | 0.0 | 0 |  |
| zh-TW | date_compact8 | 60 | 60 | 1000.0 | 60 | `dddddddd` → `○○○○○○○○` |
| zh-TW | date_iso | 60 | 0 | 0.0 | 0 |  |
| zh-TW | date_nen | 60 | 0 | 0.0 | 0 |  |
| zh-TW | date_roc | 60 | 0 | 0.0 | 0 |  |
| zh-TW | date_slash | 60 | 0 | 0.0 | 0 |  |
| zh-TW | dose | 60 | 0 | 0.0 | 0 |  |
| zh-TW | duration | 60 | 0 | 0.0 | 0 |  |
| zh-TW | gene_variant | 60 | 0 | 0.0 | 0 |  |
| zh-TW | lab_value | 60 | 0 | 0.0 | 0 |  |
| zh-TW | score | 60 | 0 | 0.0 | 0 |  |
| zh-TW | staging | 60 | 0 | 0.0 | 0 |  |
| zh-TW | trial_id | 60 | 0 | 0.0 | 0 |  |
<!-- masking-leaks:over:end -->

The control (unplanted notes):

<!-- masking-leaks:control:begin -->
| Language | Unplanted notes | Characters masked | Tripwire hits |
|---|---:|---:|---:|
| zh-TW | 200 | 0 | 0 |
| ja | 200 | 0 | 0 |
| en | 200 | 0 | 0 |
<!-- masking-leaks:control:end -->

## Findings

Lane B2 owns `phi_guard`; lane A2 owns `services/guard`. Basis *shown*: a leak counted in `leaks.json` by the full run
and held by an xfail case of `tests/unit/test_masking_leaks.py`.

| Id | Severity | Lane | Basis | Place (the recogniser that should catch it) | Expected | Happened |
|---|---|---|---|---|---|---|
| V5-01 | High | B2 | shown | `libs/tb_common/phi_guard.py:629` (氏名 and 担当医: a listed `_JP` surname, no kana, no Latin), `:84` (no 殿) | plan 8 V6; D-337 §1: names after a label or an honorific are masked | ja names leak 767 per 1,000. After 氏名： katakana, hiragana and Hepburn names leak 1,000; with 殿, 905 |
| V5-02 | High | B2 | shown | `phi_guard.py:643` (the Name and title pattern), `:316` | D-337 §1; D-923 | en names leak 546 per 1,000. "LAST, First" and initials leak after "Name:" (1,000); First Last 857 |
| V5-03 | High | B2 | shown | `phi_guard.py:631` (姓名 and 家屬: a listed `_ROC` surname, Han only) | D-337 §1 | zh-TW names leak 476 per 1,000. Pinyin after 姓名： leaks 1,000; Han names with a surname outside the list (闕, 冼, 粘) leak after 姓名 |
| V5-04 | High | B2 | shown | `phi_guard.py:299` (`ID_LABELLED`) | D-337 §1: insurance numbers after their label | 被保険者証 記号・番号：dddd・ddd leaks 1,000 per 1,000 |
| V5-05 | Medium | B2 | shown | `phi_guard.py:217` (`EMAIL`, ASCII @ only), `:601` (anchor "@") | D-745: e-mails are masked | an address with a full-width ＠ leaks 1,000 per 1,000 in every language |
| V5-06 | Medium | B2 | shown | `phi_guard.py:90` (`PHONE`) | D-337 §1: Taiwan and Japan phones | unlabelled 02-dddd-dddd, (02)dddd-dddd, with 分機, and full-width mobiles leak 714 per 1,000; after a label they are masked |
| V5-07 | Medium | B2 | shown | `phi_guard.py:100` (`_SP`: "never a line break") | plan 8 V6 | a line break inside a value defeats every recogniser: 680 to 753 per 1,000 at that place |
| V5-08 | Medium | B2 | shown | `phi_guard.py:161` (`DOB_BORN`), `:144` | D-745 §1 names the ROC compact form | a 7-digit ROC birth date before 出生 leaks 1,000 per 1,000; after 出生日期 it is masked |
| V5-09 | Medium | B2 | shown | `phi_guard.py:299` (no unlabelled SSN shape) | plan 8 V6: every identifier | an unlabelled US SSN leaks 714 per 1,000. Rare in Taiwan and Japan, so Medium |
| V5-10 | High | A2 | shown | `services/guard/recognisers.py` (one shape each with the masker, D-756), called at `services/gateway/core.py:579` | D-506: a call holding PHI never takes an outside route | the tripwire misses 246 per 1,000 planted notes; those raw notes may go to a route that leaves the box |
| V5-11 | Medium | B2 | shown (masking); hypothesis (screening effect) | `phi_guard.py:832` (the unlabelled site pattern), `deploy/settings.example.yaml:28` | D-745: a clinical date stays | every 8-digit date is masked in chunks and trips the tripwire (1,000 per 1,000). The judge reads the original (D-337 §4), so its text is unchanged. Retrieval and the S2b ranking from stored vectors (`vec.s2b`) lose the date, and an outside call holding one is refused. No exclusion path was shown |
| V5-12 | Medium | B2 | shown (unit sample) | `phi_guard.py:181` (`ADDRESS_EN`) | D-923: the English form of an address | an English address whose house number reads as a year (1900 to 2099) is not masked at all; held by `mask-en-address` |

Listed, not filed:

- A bare 7-digit, or letter and 7-digit, number with no label is kept (714 per 1,000). It is a chart number only at a
  site whose `mrn_regex` says so.
- 10-digit lab accession numbers are kept. An accession number can link a sample to a person; the criteria do not
  read it.
- The on-box judge reads raw notes (D-337 §4).

`findings.json` beside this page holds the same rows.

## Question for the integrator

question: D-1037 allows an outside open-source de-identification tool for measurement only. May the owner run one on
his PC against these synthetic notes and the carve? From memory, not checked: Microsoft Presidio (MIT licence, a
Python package of a few MB) finds names with a spaCy model it does not ship. `en_core_web_lg` is about 560 MB,
downloaded once by `python -m spacy download` at setup; Chinese and Japanese need `zh_core_web_lg` and
`ja_core_news_lg` (some hundreds of MB each, the same way). Nothing is downloaded at run time after that. It would add
an independent detector for unlabelled names, the class V5-01 to V5-03 show the masker misses most.

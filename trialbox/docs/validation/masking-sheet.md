# The masking sheet: which identifier forms the note masker masks, per language, at what measured rate

**Reader:** the people who build TrialBox

*Card F-3 (plan 10 review, ring 0 piece 25; rc1 checklist row 9). Living: re-measured by its tool. Generated from
the results: every block between `masking-sheet:` markers (the run line and all tables, the rows table included).
Written by hand: the prose, the encodings section (the bench's table, quoted) and "What was not measured".*

This sheet says, for English, Traditional Chinese and Japanese notes, which identifier forms the note masker
(`libs/tb_common/phi_guard.py`, `mask_note`, as the lake runs it before a note is indexed) masks, at what rate on this
run, and which forms it lets pass. It measures; it fixes nothing, and it states no bound and no promise. Every table
between the generated markers is the rendering of [`masking-sheet/results.json`](masking-sheet/results.json) by
`tools/masking_sheet.py`; `tests/unit/test_masking_sheet.py` fails when a table and the results differ.

## What was measured, on which commit, with which command

<!-- masking-sheet:run:begin -->
The measured code equals master commit `72a293ad3ded88f52c32cd0570b11866db27b7a3` (the merge base with `origin/master`) except: `tools/masking_sheet.py`. Blobs as read: `libs/tb_common/phi_guard.py` `84a72d1b4741b80b6ed2ac78a0b55930f2add977`; `tools/masking_leaks.py` `94843748867e83915b7ab49ae6877272a48d7a1c`; `libs/tb_common/logging.py` `d6f1fae4b1ccaa775be15896af46e3cc0fdf833c`. Site chart-number pattern in effect: `^\d{8}$`. Run 2026-11-22, command `PYTHONPATH=libs:services:. .venv/bin/python -m tools.masking_sheet --write` (from `trialbox/`). Entry point: `tb_common.phi_guard.mask_note(text, site_mrn_regex()), as lake.store.Lake.rebuild runs it before a note is chunked, indexed and embedded`. Harness seed 20261117, 21 notes per form (three at each of seven places); base notes kept: zh-TW 205, ja 274, en 235.
<!-- masking-sheet:run:end -->

- **The planted-identifier run** is card V-5's harness, `tools/masking_leaks.py` (its page:
  [masking-leaks-2026-11-17.md](../plan/measurements/masking-leaks-2026-11-17.md)): the synthetic hospital's own
  notes, kept only when the masker masks nothing in them, each with one identifier the harness invents (its own name
  pools, numbers in the real formats with valid check digits), at one of seven places. A value **leaked** when it
  stays readable by the harness's leak rule (all of it; a name's whole family name and one more letter; half the
  digits of a number; a postcode or an e-mail's local part); **partly** when some of it is readable but not enough
  for the rule; **masked** when nothing of it is readable.
- **Scope** is the harness's: *in scope* is a value after a label or in a table line, or a name with a role, title or
  honorific (D-337 section 1); *free-standing* is a name with none of these; *line break* is a value split by a hard
  wrap. The language tables give the in-scope figures, with the other two scopes beside them.
- **Four probe sets** ride with the run: V5-01's remainder, the J10C1 known gaps, the R22-23 probes and R22-21's log
  probes (section "Known to pass").
- **Small cells.** A rate cell over fewer than 20 probes shows its count (`18 probes`), not a rate: so few probes
  give a count, and a reader should read it as one. Every form has 18 in-scope probes or fewer (6 for a name
  with no title or honorific, in scope only after its label or in a table line), so the language tables give counts per form; the rates are in
  the summary and the rows table.
- Each example shape is one value from that form's generator with its letters and digits written as classes
  (`d` a digit, `A`/`a` a letter, `漢` a kanji, `カ`/`か` kana, full-width classes in full width, `◌` a combining
  mark, `⟨zwj⟩` a zero-width joiner, `⏎` a line break). No shape is an identifier.

## The rates, per language and scope

<!-- masking-sheet:summary:begin -->
| Language | Scope | Probes | Masked | Partly | Leaked | Masked per 1,000 | Leaked per 1,000 | Tripwire missed |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| en | in scope | 768 | 693 | 21 | 54 | 902.3 | 70.3 | 36 |
| en | free-standing | 96 | 21 | 0 | 75 | 218.8 | 781.2 | 75 |
| en | line break | 144 | 12 | 12 | 120 | 83.3 | 833.3 | 93 |
| en | names in scope | 102 | 68 | 0 | 34 | 666.7 | 333.3 | 25 |
| zh-TW | in scope | 942 | 850 | 30 | 62 | 902.3 | 65.8 | 34 |
| zh-TW | free-standing | 84 | 22 | 2 | 60 | 261.9 | 714.3 | 60 |
| zh-TW | line break | 171 | 25 | 9 | 137 | 146.2 | 801.2 | 89 |
| zh-TW | names in scope | 96 | 78 | 0 | 18 | 812.5 | 187.5 | 2 |
| ja | in scope | 792 | 771 | 13 | 8 | 973.5 | 10.1 | 8 |
| ja | free-standing | 72 | 5 | 0 | 67 | 69.4 | 930.6 | 67 |
| ja | line break | 144 | 26 | 16 | 102 | 180.6 | 708.3 | 75 |
| ja | names in scope | 108 | 99 | 1 | 8 | 916.7 | 74.1 | 8 |
<!-- masking-sheet:summary:end -->

## English

<!-- masking-sheet:forms-en:begin -->
| Kind | Form | Example shape | Probes | Masked | Partly | Leaked | Masked per 1,000 | Leaked per 1,000 | Free-standing: leaked | Line break: leaked | Tripwire missed |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| name | wade_giles_family_first | `Aaaa Aa-aaa` | 6 | 5 | 0 | 1 | 6 probes | 6 probes | 1 of 12 | 3 of 3 | 1 |
| name | wade_giles_given_first | `Aaa-aaaa Aaa` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 2 of 12 | 3 of 3 | 0 |
| name | pinyin_family_first | `Aaa Aaaaaa` | 6 | 3 | 0 | 3 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 3 |
| name | pinyin_given_first | `Aaaaaa Aa` | 6 | 3 | 0 | 3 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 3 |
| name | first_last | `Aaaaa Aaaaaaa` | 6 | 3 | 0 | 3 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 3 |
| name | last_comma_first | `AAAAAAAAA, Aaaa` | 6 | 0 | 0 | 6 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 6 |
| name | middle_initial | `Aaaa A. Aaaaaa` | 6 | 3 | 0 | 3 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 3 |
| name | dr | `Dr. Aaaaaaa` | 18 | 15 | 0 | 3 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| name | mr | `Mr. Aaaaaa Aaaaaaaaaa` | 18 | 15 | 0 | 3 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| name | ms | `Ms. Aaaaaaaaa` | 18 | 15 | 0 | 3 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| name | initials | `A.A.` | 6 | 0 | 0 | 6 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 6 |
| national_id | tw_id | `Addddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | tw_arc_old | `AAdddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | tw_arc_new | `Addddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | us_ssn | `ddd-dd-dddd` | 18 | 9 | 0 | 9 | 18 probes | 18 probes | - | 3 of 3 | 9 |
| chart | bare_8 | `dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_MRN | `MRN dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_MRN_colon | `MRN: dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_Chart_No | `Chart No. dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_Hospital_No_colon | `Hospital No.: dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_ID_colon | `ID: dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_hyphen | `dddd-ddd-ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_plain | `dddddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_space | `dddd ddd ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| phone | tw_mobile_intl | `+ddd-ddd-ddd-ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_intl_space | `+ddd ddd ddd ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| phone | tw_landline_paren | `(dd)ddd-dddd` | 18 | 16 | 0 | 2 | 18 probes | 18 probes | - | 3 of 3 | 2 |
| phone | tw_landline_hyphen | `dd-ddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_landline_ext | `dd-dddd-dddd 漢漢ddd` | 18 | 6 | 12 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | na_paren | `(ddd) ddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | na_hyphen | `ddd-ddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | na_intl | `+d ddd ddd dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| address | en_full | `dddd Aaaaaaaaaaa Aaaa, Aaaaaaaaaaa, AA ddddd` | 18 | 9 | 0 | 9 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| address | en_apt | `dddd Aaaaaaa Aaaaaa, Aaa d` | 18 | 9 | 9 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| email | ascii | `aaaaaadd@aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | plus | `aaaadd+aaaaaa@aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | fullwidth_at | `aadd＠aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_iso | `DOB: dddd-dd-dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_slash_ymd | `DOB: dddd/dd/dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_dotted | `DOB: dddd.dd.dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_compact8 | `DOB: dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_nen_gappi | `DOB: dddd漢d漢dd漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_nen_gappi_fullwidth | `DOB: ｄｄｄｄ漢ｄ漢ｄｄ漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_slash_dmy | `DOB: dd/dd/dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_slash_mdy | `DOB: dd/dd/dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_month_name | `DOB: Aaaa dd, dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_day_month_abbr | `DOB: dd Aaa dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_two_digit_year | `DOB: dd/dd/dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
<!-- masking-sheet:forms-en:end -->

Forms known to pass in English (in scope):

<!-- masking-sheet:pass-en:begin -->
| Kind | Form | Example shape | Leaked | Partly | Of | Leaked per 1,000 |
|---|---|---|---:|---:|---:|---:|
| name | wade_giles_family_first | `Aaaa Aa-aaa` | 1 | 0 | 6 | 6 probes |
| name | pinyin_family_first | `Aaa Aaaaaa` | 3 | 0 | 6 | 6 probes |
| name | pinyin_given_first | `Aaaaaa Aa` | 3 | 0 | 6 | 6 probes |
| name | first_last | `Aaaaa Aaaaaaa` | 3 | 0 | 6 | 6 probes |
| name | last_comma_first | `AAAAAAAAA, Aaaa` | 6 | 0 | 6 | 6 probes |
| name | middle_initial | `Aaaa A. Aaaaaa` | 3 | 0 | 6 | 6 probes |
| name | dr | `Dr. Aaaaaaa` | 3 | 0 | 18 | 18 probes |
| name | mr | `Mr. Aaaaaa Aaaaaaaaaa` | 3 | 0 | 18 | 18 probes |
| name | ms | `Ms. Aaaaaaaaa` | 3 | 0 | 18 | 18 probes |
| name | initials | `A.A.` | 6 | 0 | 6 | 6 probes |
| national_id | us_ssn | `ddd-dd-dddd` | 9 | 0 | 18 | 18 probes |
| phone | tw_landline_paren | `(dd)ddd-dddd` | 2 | 0 | 18 | 18 probes |
| phone | tw_landline_ext | `dd-dddd-dddd 漢漢ddd` | 0 | 12 | 18 | 18 probes |
| address | en_full | `dddd Aaaaaaaaaaa Aaaa, Aaaaaaaaaaa, AA ddddd` | 9 | 0 | 18 | 18 probes |
| address | en_apt | `dddd Aaaaaaa Aaaaaa, Aaa d` | 0 | 9 | 18 | 18 probes |

In scope, all forms: 54 of 768 leaked (70.3 per 1,000), 21 partly masked. Free-standing names: 75 of 96 leaked. A value split by a line break: 120 of 144 leaked.
<!-- masking-sheet:pass-en:end -->

## Traditional Chinese (zh-TW)

<!-- masking-sheet:forms-zh-TW:begin -->
| Kind | Form | Example shape | Probes | Masked | Partly | Leaked | Masked per 1,000 | Leaked per 1,000 | Free-standing: leaked | Line break: leaked | Tripwire missed |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| name | han_2 | `漢漢` | 6 | 4 | 0 | 2 | 6 probes | 6 probes | 11 of 12 | 3 of 3 | 0 |
| name | han_3 | `漢漢漢` | 6 | 4 | 0 | 2 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| name | han_4 | `漢漢漢漢` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 11 of 12 | 3 of 3 | 0 |
| name | han_3_先生 | `漢漢漢先生` | 18 | 17 | 0 | 1 | 18 probes | 18 probes | - | 0 of 3 | 1 |
| name | han_3_女士 | `漢漢漢女士` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| name | han_3_醫師 | `漢漢漢醫師` | 18 | 17 | 0 | 1 | 18 probes | 18 probes | - | 0 of 3 | 1 |
| name | wade_giles_family_first | `Aaaa Aaaa-aaaa` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 0 of 12 | 3 of 3 | 0 |
| name | wade_giles_given_first | `Aaa-aaa Aaaa` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 2 of 12 | 3 of 3 | 0 |
| name | pinyin_family_first | `Aaa Aaaaaa` | 6 | 0 | 0 | 6 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| name | pinyin_given_first | `Aaaaaaa Aaa` | 6 | 0 | 0 | 6 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| national_id | tw_id | `Addddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | tw_arc_old | `AAdddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | tw_arc_new | `Addddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | tw_id_fullwidth | `Ａｄｄｄｄｄｄｄｄｄ` | 18 | 0 | 18 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | bare_8 | `dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_病歷號_colon | `病歷號：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_病歷號碼 | `病歷號碼 dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_病歷號碼_colon | `病歷號碼：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_ID_colon | `ID:dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_MRN | `MRN dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_hyphen | `dddd-ddd-ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_plain | `dddddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_space | `dddd ddd ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| phone | tw_mobile_intl | `+ddd-ddd-ddd-ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_intl_space | `+ddd ddd ddd ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| phone | tw_landline_paren | `(dd)ddd-dddd` | 18 | 16 | 0 | 2 | 18 probes | 18 probes | - | 3 of 3 | 2 |
| phone | tw_landline_hyphen | `ddd-ddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_landline_ext | `ddd-dd-dddd 漢漢ddd` | 18 | 6 | 12 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | tw_mobile_fullwidth | `ｄｄｄｄ－ｄｄｄ－ｄｄｄ` | 18 | 6 | 0 | 12 | 18 probes | 18 probes | - | 3 of 3 | 12 |
| address | tw_full | `ddd漢漢漢漢漢漢漢漢漢漢漢dd漢d漢ddd漢d漢` | 18 | 6 | 0 | 12 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| address | tw_no_postcode | `漢漢漢漢漢漢漢漢漢漢dd漢dd漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 2 of 3 | 0 |
| address | tw_floor_unit | `漢漢漢漢漢漢漢漢漢漢ddd漢dd漢漢d` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | ascii | `aaaadd@aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | plus | `aaaaaadd+aaaaaa@aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | fullwidth_at | `a.aaaaaadd＠aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_iso | `出生日期：dddd-dd-dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_iso | `dddd-dd-dd出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_slash_ymd | `出生日期：dddd/dd/dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_slash_ymd | `dddd/dd/dd出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_dotted | `出生日期：dddd.dd.dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_dotted | `dddd.dd.dd出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_compact8 | `出生日期：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_compact8 | `dddddddd出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_nen_gappi | `出生日期：dddd漢dd漢dd漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_nen_gappi | `dddd漢d漢dd漢出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_nen_gappi_fullwidth | `出生日期：ｄｄｄｄ漢ｄ漢ｄ漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_nen_gappi_fullwidth | `ｄｄｄｄ漢ｄ漢ｄｄ漢出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_roc_nen | `出生日期：漢漢dd漢dd漢dd漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_roc_nen | `漢漢dd漢d漢dd漢出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_roc_slash | `出生日期：dd/dd/dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_roc_slash | `dd/dd/dd出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_roc_dot | `出生日期：dd.d.dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_roc_dot | `dd.d.d出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_roc_compact | `出生日期：ddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_roc_compact | `ddddddd出生` | 18 | 0 | 0 | 18 | 18 probes | 18 probes | - | 3 of 3 | 18 |
| dob | label_roc_numerals | `出生日期：漢漢漢漢漢漢漢漢漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_roc_numerals | `漢漢漢漢漢漢漢漢漢漢出生` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
<!-- masking-sheet:forms-zh-TW:end -->

Forms known to pass in Traditional Chinese (in scope):

<!-- masking-sheet:pass-zh-TW:begin -->
| Kind | Form | Example shape | Leaked | Partly | Of | Leaked per 1,000 |
|---|---|---|---:|---:|---:|---:|
| name | han_2 | `漢漢` | 2 | 0 | 6 | 6 probes |
| name | han_3 | `漢漢漢` | 2 | 0 | 6 | 6 probes |
| name | han_3_先生 | `漢漢漢先生` | 1 | 0 | 18 | 18 probes |
| name | han_3_醫師 | `漢漢漢醫師` | 1 | 0 | 18 | 18 probes |
| name | pinyin_family_first | `Aaa Aaaaaa` | 6 | 0 | 6 | 6 probes |
| name | pinyin_given_first | `Aaaaaaa Aaa` | 6 | 0 | 6 | 6 probes |
| national_id | tw_id_fullwidth | `Ａｄｄｄｄｄｄｄｄｄ` | 0 | 18 | 18 | 18 probes |
| phone | tw_landline_paren | `(dd)ddd-dddd` | 2 | 0 | 18 | 18 probes |
| phone | tw_landline_ext | `ddd-dd-dddd 漢漢ddd` | 0 | 12 | 18 | 18 probes |
| phone | tw_mobile_fullwidth | `ｄｄｄｄ－ｄｄｄ－ｄｄｄ` | 12 | 0 | 18 | 18 probes |
| address | tw_full | `ddd漢漢漢漢漢漢漢漢漢漢漢dd漢d漢ddd漢d漢` | 12 | 0 | 18 | 18 probes |
| dob | born_roc_compact | `ddddddd出生` | 18 | 0 | 18 | 18 probes |

In scope, all forms: 62 of 942 leaked (65.8 per 1,000), 30 partly masked. Free-standing names: 60 of 84 leaked. A value split by a line break: 137 of 171 leaked.
<!-- masking-sheet:pass-zh-TW:end -->

## Japanese (ja)

<!-- masking-sheet:forms-ja:begin -->
| Kind | Form | Example shape | Probes | Masked | Partly | Leaked | Masked per 1,000 | Leaked per 1,000 | Free-standing: leaked | Line break: leaked | Tripwire missed |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| name | kanji | `漢漢漢漢` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| name | kanji_space | `漢漢　漢漢` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 11 of 12 | 3 of 3 | 0 |
| name | katakana_space | `カカ　カカカ` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 8 of 12 | 3 of 3 | 0 |
| name | hiragana_space | `かかかか　かかか` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| name | kanji_様 | `漢漢漢漢様` | 18 | 12 | 1 | 5 | 18 probes | 18 probes | - | 3 of 3 | 5 |
| name | kanji_さん | `漢漢漢漢さん` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| name | kanji_殿 | `漢漢漢漢殿` | 18 | 17 | 0 | 1 | 18 probes | 18 probes | - | 0 of 3 | 1 |
| name | kanji_先生 | `漢漢漢漢先生` | 18 | 16 | 0 | 2 | 18 probes | 18 probes | - | 0 of 3 | 2 |
| name | hepburn_family_first | `AAAAAAAA Aaaaaa` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| name | hepburn_given_first | `Aaaa Aaaaa` | 6 | 6 | 0 | 0 | 6 probes | 6 probes | 12 of 12 | 3 of 3 | 0 |
| national_id | my_number | `dddddddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | my_number_spaced | `dddd dddd dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | my_number_fullwidth | `ｄｄｄｄｄｄｄｄｄｄｄｄ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | insurer_no | `保険者番号：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| national_id | insurance_symbol_no | `被保険者証 記号・番号：dddd・ddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| chart | bare_8 | `dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_カルテ番号_colon | `カルテ番号：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_カルテNo | `カルテNo.dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_患者ID_colon | `患者ID：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| chart | label_ID_colon | `ID:dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | jp_mobile | `ddd-dddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | jp_landline | `dd-dddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | jp_landline_3 | `ddd-ddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | jp_intl | `+dd-dd-dddd-dddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | jp_plain | `ddddddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| phone | jp_fullwidth | `ｄｄｄ－ｄｄｄｄ－ｄｄｄｄ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| address | jp_full | `〒ddd-dddd 漢漢漢漢漢漢漢漢漢漢漢d漢漢dd漢dd漢` | 18 | 6 | 12 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| address | jp_hyphen_building | `漢漢漢漢漢漢漢漢漢漢d-dd-d カカカカカカカddd漢漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| address | jp_no_postcode | `漢漢漢漢漢漢漢漢漢漢漢d漢漢dd漢d漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | ascii | `aaaadd@aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | plus | `aaaadd+aaaaaa@aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| email | fullwidth_at | `aaaadd＠aaaaaaa.aaa` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_iso | `生年月日：dddd-dd-dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_iso | `dddd-dd-dd生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_slash_ymd | `生年月日：dddd/dd/dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_slash_ymd | `dddd/dd/dd生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_dotted | `生年月日：dddd.dd.dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_dotted | `dddd.dd.dd生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_compact8 | `生年月日：dddddddd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | born_compact8 | `dddddddd生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 3 of 3 | 0 |
| dob | label_nen_gappi | `生年月日：dddd漢d漢dd漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_nen_gappi | `dddd漢d漢d漢生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_nen_gappi_fullwidth | `生年月日：ｄｄｄｄ漢ｄ漢ｄｄ漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_nen_gappi_fullwidth | `ｄｄｄｄ漢ｄｄ漢ｄｄ漢生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_era_kanji | `生年月日：漢漢dd漢d漢dd漢` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_era_kanji | `漢漢dd漢d漢d漢生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | label_era_letter | `生年月日：Add.dd.dd` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
| dob | born_era_letter | `Ad.d.dd生まれ` | 18 | 18 | 0 | 0 | 18 probes | 18 probes | - | 0 of 3 | 0 |
<!-- masking-sheet:forms-ja:end -->

Forms known to pass in Japanese (in scope):

<!-- masking-sheet:pass-ja:begin -->
| Kind | Form | Example shape | Leaked | Partly | Of | Leaked per 1,000 |
|---|---|---|---:|---:|---:|---:|
| name | kanji_様 | `漢漢漢漢様` | 5 | 1 | 18 | 18 probes |
| name | kanji_殿 | `漢漢漢漢殿` | 1 | 0 | 18 | 18 probes |
| name | kanji_先生 | `漢漢漢漢先生` | 2 | 0 | 18 | 18 probes |
| address | jp_full | `〒ddd-dddd 漢漢漢漢漢漢漢漢漢漢漢d漢漢dd漢dd漢` | 0 | 12 | 18 | 18 probes |

In scope, all forms: 8 of 792 leaked (10.1 per 1,000), 13 partly masked. Free-standing names: 67 of 72 leaked. A value split by a line break: 102 of 144 leaked.
<!-- masking-sheet:pass-ja:end -->

## Encodings: the bench's fuzz

Not re-run for this sheet. The bench ran an encoding fuzz on master `225100f4bf3e1a05d7c1435314467d2b2c385ba4`:
50,000 synthetic notes times 8 identifier kinds (name, chart number, phone, e-mail, address, date of birth,
national-style id, a fake secret) times 13 encodings, through 13 outputs by their public callers, every written byte
decoded every way and searched; one exact input per cell. Its table, as posted (issue comment 7078315395 on pull
request #639):

```
output                         plain   worst encodings
log line (text, %s, extras)     2 %    HTML entities 88 %, quoted-printable 87 %, base64 75 %
log extra: bytes / exception    91 / 100 % (not masked at all)
support bundle as built         52 %   base64 88 %, line wraps 83 %, QP 83 % (names, dates of birth, addresses, e-mails)
mail render (text and HTML)    100 %   (no masking: by design for the study's recipients?)
search index, trace store       15 %   QP 100 %, base64 88 % (note text on the box by design?)
```

- The note masker's row is **search index, trace store**: what the masker leaves is what the index holds. The two log
  rows are the log formatter's (R22-21 below), the bundle row the support bundle's scrub.
- Correction 7078367269: the support-bundle row ran on a 1-in-10 sample (5,000 of the 50,000 notes); the other rows
  ran on all 50,000.
- The bench's comment does not say per kind or per language which encodings pass; this sheet has no per-language
  figure for encodings beyond the rebuilt R22-23 probes below.

**The bundle by the real road.** The bench then logged each synthetic note through the log formatter
(`tb_common.logging.JsonFormatter`) into the log the support bundle collects, built the bundle with
`support_bundle.build` and read the archive back: at least 500 notes per kind and encoding, 52,000 notes, on master
`225100f4bf3e1a05d7c1435314467d2b2c385ba4` (issue comment 7079771762 on pull request #639). Leaked, plain / worst
encoding, through the formatter:

```
name                               18 % / zero-width joiner 100 %
e-mail                              0 % / zero-width joiner 100 %
address                             0 % / quoted-printable 99 %
date of birth                       0 % / full-width 100 %
chart number, phone, national id    0 % / base64 100 %
secret                              0 % / 0 %
```

- What a log line holds in an encoding leaves in a support bundle; secrets left by neither road. The encodings are
  generated, not seen in a hospital's feed, and the plain-name figure depends on the generator's name forms.

## Known to pass: the open register rows on masking

Every open masking row of the findings register (`docs/handover/findings-register.md`: the V5 rows of card V-5 and
the J10C1 rows of card 10C-1, over-masking rows included), and the plan 10 review's R22-21 and R22-23 (not register
rows), each with what this run measured. Where nothing leaked the figure says "0 of N leaked on this run" and claims
nothing more: a row closes in the register, not here. `tests/unit/test_masking_sheet.py` reads the register and fails
when an open masking row is missing here.

<!-- masking-sheet:rows:begin -->
| Row | What passes | Measured on this run |
|---|---|---|
| V5-01 | Japanese names in scope; what is left: a kanji surname outside the masker's list before 様, 先生 or 殿 | ja names in scope: 8 of 108 leaked (74.1 per 1,000); 1 partly masked; the surname readable in 12 of 24 probes of the remainder |
| V5-02 | English names in scope | en names in scope: 34 of 102 leaked (333.3 per 1,000) |
| V5-03 | Chinese names in scope | zh-TW names in scope: 18 of 96 leaked (187.5 per 1,000) |
| V5-04 | The insurance card's 記号・番号 after its label | 0 of 18 leaked on this run |
| V5-05 | An e-mail with a full-width ＠ (three languages) | 0 of 54 leaked on this run |
| V5-06 | Full-width mobiles; landlines with the area code in brackets | 16 of 72 leaked (222.2 per 1,000) |
| V5-07 | A value split by a hard wrap (all forms) | 359 of 459 leaked (782.1 per 1,000); 37 partly masked |
| V5-08 | A compact ROC birth date before 出生 | 18 of 18 leaked |
| V5-09 | A US SSN (no label) | 9 of 18 leaked |
| V5-10 | The gateway's tripwire on in-scope notes | the tripwire missed 78 of 2502 notes (31.2 per 1,000) |
| V5-11 | Over-masking: an 8-digit clinical date | 180 of 180 altered (1000.0 per 1,000) |
| V5-12 | The postcode of a masked full address | 21 of 54 leaked (388.9 per 1,000); 12 partly masked |
| V5-13 | Free-standing names (no label, role, title or honorific) | 202 of 252 leaked (801.6 per 1,000); 2 partly masked |
| J10C1-01 | A Japanese name with no label or honorific | 3 of 3 lines readable |
| J10C1-02 | A romaji name without a label | 1 of 1 lines readable |
| J10C1-03 | A name split by a line break after its label | 1 of 1 lines readable |
| J10C1-04 | An address without 市 | 2 of 2 lines readable |
| J10C1-05 | A pension number and a passport number | 2 of 2 lines readable |
| J10C1-06 | Over-masking: two ordinary Japanese lines | 1 of 2 lines altered |
| R22-23 | The review's: names without a label, and identifiers behind an encoding | 55 of 66 rebuilt probes readable (en 18 of 21; zh-TW 19 of 21; ja 18 of 24) |
| R22-21 | The review's: log extras that are not text (the log formatter, not the note masker) | 24 of 24 leaked (1000.0 per 1,000); text extras 0 of 6 |
<!-- masking-sheet:rows:end -->

- **V5-01's remainder** is 24 probes: the harness's four kanji family names outside the masker's surname list
  (丸山, 大塚, 吉川, 今井), each with a harness given name, directly before 様, 先生 or 殿, at a line's start and after
  a word. `tests/unit/test_masking_sheet.py` holds them as a strict expected failure, so CI says so the day the
  masker masks them.
- **J10C1-01 to -05** are the known-gap lines of `eval/phi_synth/ja_guard_probes.json` (by their `kind`), through
  the masker as the lake runs it; a line counts when any letter or digit of its identifier stays readable.
  **J10C1-06** is that file's two known over-masked lines; a line counts when the masker alters it.
- **V5-11** is the harness's clinical 8-digit dates (`date_compact8`, all three languages); a date counts when the
  masker alters it.
- **R22-23** was measured by the plan 10 review on 76 probes it did not commit (16 missed: ja 8 of 30, zh-TW 2 of
  24, en 6 of 22). This sheet **rebuilt** a probe set of the same kinds from the harness's generators, not the
  review's texts: three values per category below, each counted when any letter or digit stays readable after the
  masker. Its counts are not the review's and are not comparable one to one. Every encoded category sits after a
  label (`Name:`, `姓名：`, `氏名：`), so its misses are the encoding's, told apart from `no_label`; the review's own
  percent probe had no label.

<!-- masking-sheet:r22-23:begin -->
| Language | Category | Example shape | Probes | Readable after the masker | Tripwire missed |
|---|---|---|---:|---:|---:|
| en | label | `Name: Aaaaa Aaaaaaaa. History of diabetes.` | 3 | 0 | 0 |
| en | no_label | `Patient Aaaa Aaaaaaaaaa, male, presents with chest pain.` | 3 | 3 | 3 |
| en | percent | `Name: Aaaaa%ddAaaaaaa. History of diabetes.` | 3 | 3 | 0 |
| en | entities | `Name: &#dd;&#ddd;&#ddd;&#ddd;&#ddd;&#dd;&#dd;&#dd;&#ddd;&#dd;&#ddd;&#ddd;&#ddd;&#dd;. History of diabetes.` | 3 | 3 | 3 |
| en | zero_width_joiner | `Name: A⟨zwj⟩aaaa Aaaaaaaa. History of diabetes.` | 3 | 3 | 3 |
| en | fullwidth_number | `SSN ｄｄｄ－ｄｄ－ｄｄｄｄ. History of diabetes.` | 3 | 3 | 3 |
| en | phone_zero_width_joiner | `Phone: d⟨zwj⟩dd-ddd-dddd. History of diabetes.` | 3 | 3 | 3 |
| zh-TW | label | `姓名：漢漢漢。既往有糖尿病。` | 3 | 1 | 0 |
| zh-TW | no_label | `病人漢漢漢今日回診，既往有糖尿病。` | 3 | 3 | 2 |
| zh-TW | percent | `姓名：%Ad%Ad%dA%Ad%dd%dd%Ad%dd%dA。既往有糖尿病。` | 3 | 3 | 0 |
| zh-TW | entities | `姓名：&#ddddd;&#ddddd;&#ddddd;。既往有糖尿病。` | 3 | 3 | 0 |
| zh-TW | zero_width_joiner | `姓名：漢⟨zwj⟩漢漢。既往有糖尿病。` | 3 | 3 | 0 |
| zh-TW | fullwidth_number | `身分證號：Ａｄｄｄｄｄｄｄｄｄ。既往有糖尿病。` | 3 | 3 | 0 |
| zh-TW | phone_zero_width_joiner | `電話：d⟨zwj⟩ddd-ddd-ddd。既往有糖尿病。` | 3 | 3 | 3 |
| ja | label | `氏名：漢漢漢漢。既往歴に糖尿病。` | 3 | 0 | 0 |
| ja | no_label | `患者は漢漢漢漢。既往歴に糖尿病。` | 3 | 3 | 3 |
| ja | percent | `氏名：%Ad%Ad%Ad%Ad%Ad%Ad%Ad%dd%AA%Ad%AA%dd。既往歴に糖尿病。` | 3 | 3 | 0 |
| ja | entities | `氏名：&#ddddd;&#ddddd;&#ddddd;&#ddddd;。既往歴に糖尿病。` | 3 | 3 | 0 |
| ja | zero_width_joiner | `氏名：漢⟨zwj⟩漢漢漢。既往歴に糖尿病。` | 3 | 3 | 0 |
| ja | decomposed_macron | `氏名：A◌AAAAA Aaaaaaa。既往歴に糖尿病。` | 3 | 3 | 0 |
| ja | fullwidth_number | `番号：ｄｄｄｄｄｄｄｄｄｄｄｄ。既往歴に糖尿病。` | 3 | 0 | 0 |
| ja | phone_zero_width_joiner | `電話：d⟨zwj⟩dd-dddd-dddd。既往歴に糖尿病。` | 3 | 3 | 3 |
<!-- masking-sheet:r22-23:end -->

- **R22-21** is the log formatter (`libs/tb_common/logging.py`, `JsonFormatter`), not the note masker: six harness
  values (a name with an honorific and a phone, per language) put in a log record's extras as each value type. A
  probe counts when the identifier, or for bytes its UTF-8 escape, is in a field of the written line.

<!-- masking-sheet:r22-21:begin -->
| Extras value type | Probes | Identifier written readable |
|---|---:|---:|
| text | 6 | 0 |
| object | 6 | 6 |
| path | 6 | 6 |
| exception | 6 | 6 |
| bytes | 6 | 6 |
<!-- masking-sheet:r22-21:end -->

## What was not measured

- **Real notes.** Every form is the harness's estimate of how hospitals write; the per-1,000 figures weigh each form
  the same, not as often as it occurs. The real notes are only on the owner's PC.
- **The guard and the gateway's tripwire as a masker.** The tripwire column says only whether the tripwire fired on
  the note; the guard's own redaction (`services/guard`) was not read for this sheet.
- **Encodings per language and form.** Only the bench's aggregate rows (not re-run) and the rebuilt R22-23 probes.
- **Over-masking.** The clinical strings the masker alters are on the V-5 page, not here.
- **Forms the harness holds to be no identifier by themselves** (a bare 7-digit number, a letter and 7 digits): planted
  and counted in `results.json` (`not_held`), in no rate.
- **The review's exact R22-23 texts** (not committed), and the other outputs: the support bundle, mail, traces.
- **Kinds the harness does not plant**: pension and passport numbers (only the J10C1 lines), 公費 and 受給者 numbers,
  ages over 89, free-text relatives' names, images.

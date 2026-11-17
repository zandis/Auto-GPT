# Masking hides identifiers in notes? Planted identifiers on synthetic notes, 2026-11-17 (card V-5, plan 8 V6)

**Reader:** the integrator, lane B2 (the note masker, `tb_common.phi_guard`) and lane A2 (the guard, `services/guard`)

**Verdict.** No, not even within what D-337 rules the masker must do. The figures (generated from `leaks.json`):

<!-- masking-leaks:verdict:begin -->
In the ruling's scope, the masker left 285 of 2502 planted identifiers readable: **113.9 per 1,000** (en 96.4, ja 162.9, zh-TW 87.0); 68 more (27.2 per 1,000) were partly masked. Free-standing names, outside D-337 section 1: 207 of 252 leaked (**821.4 per 1,000**). Values split by a hard wrap: 370 of 459 leaked (**806.1 per 1,000**). The tripwire missed 189 of the 2502 in-scope notes (75.5 per 1,000). Forms not held to be identifiers (126 notes) are in no rate.
<!-- masking-leaks:verdict:end -->

Names are the worst kind inside the ruling's scope: ja 639, en 333, zh-TW 188 per 1,000. After 氏名, kana and
Hepburn names leak every time; after Name:, "LAST, First" and initials do; after 姓名, Pinyin names and surnames
outside the masker's list do. Classes missed entirely: e-mails with a full-width ＠, the Japanese insurance card's
記号・番号, compact ROC birth dates before 出生. Missed partly: full-width mobiles, landlines with a 3-digit area
code in brackets, the postcode of a masked address, an unlabelled US SSN. Over-masking: of the clinical strings
criteria need, only the 8-digit date (`20240503`) is altered, every time, by the site chart pattern `^\d{8}$`.

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

- `tests/property/` holds no masking test; it was not run.
- The harness, full run `python -m tools.masking_leaks --write`. Its run time is the field `seconds` of `leaks.json`.
- **Sight check** (first version of this card, not committed): with the masker's `TW_ID` and `ID_LABELLED` patterns
  replaced by a pattern that never matches, the Taiwan ID case of the mask failed and the guard's own recogniser kept
  the tripwire case green. The harness raises `PlantError` (never an assertion) when a value is not where it was
  planted.
- **Not run: the carve on the owner's PC.** The real notes are only there.
- **Not run: an outside de-identification tool** (D-1037 allows one for measurement only; the lane's rule 8 forbids a
  download here). It would add an independent detector for names without a label or a list. See the question below.

## The base notes and the planted values

- **Base notes:** the synthetic hospital's own notes (`tools.synth.generator.Generator`, 200 patients each at a
  Taiwan site writing zh-TW and English and a Japan site writing ja and English, seed 117), sorted into languages by
  script and split into sentences. A note is used only when the masker masks nothing in it and the tripwire does not
  fire on it:

<!-- masking-leaks:control:begin -->
| Language | Notes generated | Kept (nothing masked, no tripwire hit) |
|---|---:|---:|
| zh-TW | 205 | 205 |
| ja | 274 | 274 |
| en | 235 | 235 |
<!-- masking-leaks:control:end -->

- **Planted values:** invented by the harness in the real numbering formats, never drawn from the masker's patterns:
  Taiwan IDs and both forms of resident numbers with valid check digits, My Numbers and insurer numbers with valid
  check digits, US SSNs in the issued ranges, Taiwan landlines with each area code's true subscriber length,
  Japanese and NANP 555-01xx phones, real postcode shapes. `tests/unit/test_masking_leaks.py` asserts each format.
- **Places:** one plant per note, three notes per form at each of seven places: start, middle, end, after a label,
  in a tab-separated table line, against CJK (brackets in English) with no space, and split by a hard wrap.
- **Hard wrap:** the break falls at the separator between groups nearest the value's middle (a space becomes the
  break; after a dash, dot, slash or comma the break follows it), or, in a value with no separator, in the middle of
  the run, where a wrap at a fixed column falls. Line-break leaks are their own figure, in no other rate.

## The entry points traced

1. **To retrieval, and from there to a model:** `lake.store.Lake.rebuild` calls `mask_note(note, self.mrn_regex)`
   before the chunks, the full-text index and the embeddings are made (`services/lake/store.py:1463`); the embed
   service does the same (`services/embed_service/app.py:81`). Tested: `mask_note(text, site_mrn_regex())`
   (`libs/tb_common/phi_guard.py:847`) with the test settings' pattern `^\d{8}$`, the shipped example
   (`deploy/settings.example.yaml:28`).
2. **To the judge and verifier:** the cascade reads the original `document.text`
   (`services/matching/cascade/engine.py:369`). The gateway runs `Guard.tripwire` on calls of class D0 to D2
   (`services/gateway/core.py:579`); a hit keeps the call on the box. Tested: `Guard.from_settings().tripwire(text)`.
   A miss sends a note off the box only where an outside route exists: the shipped settings have
   `cloud_enabled: false` (`deploy/settings.example.yaml:30`), and the policy drops an external endpoint without a
   `g5_record` and a route whose `external_requires` flags are not set (`services/gateway/policy.py:391-397`).
3. **To a person.** The note text a console page shows is the evidence quote of each criterion in the candidate rows
   of a finished screen (`services/console/app.py:1785`), shown to administrators and coordinators and not to viewers
   (the role, not `phi.view`, decides). It is the judge's quote of the original note and goes through no masker.
   Not tested (hypothesis from reading). `services/console/reveal.py:81` (`clean_note`) masks the reason a staff
   member types, not a clinical note; it is not on this road.
4. **To traces and logs.** The trace store's body redaction is `Guard.redact_obj`
   (`services/tracestore/store.py:142`, the guard's recognisers without the v1 scan); the log scrubber is
   `tb_common.logging.redact` (`libs/tb_common/logging.py:105`), patterns of its own. Not tested here.
5. On the box, the judge reads notes unmasked: D-337 section 4 rules it. Listed, not filed.

## The leak rule and the date rule

- **Leaked (masker):** `mask_note` keeps the length, so the value's characters are read at their place (separators
  not counted). The value leaked when: every character is readable; or, for a name, the whole family name is
  readable and the value is the family name alone or one more letter is readable; or, for a national ID, chart number
  or phone number, at least half its digits are readable; or a part that identifies alone (a full postcode, an
  e-mail's local part) is wholly readable.
- **Partly:** at least one character readable, but none of the above. Its own column in every table.
- **Leaked (tripwire):** a note with a plant gives no hit.
- **Scope (D-337 section 1):** a name after a label (the label and table places) or with a role, title or honorific
  is in scope. A name with none of these is free-standing, counted apart and filed apart (V5-13).
- **Not held:** a bare 7-digit, or letter and 7-digit, number with no label is a chart number only at a site whose
  `mrn_regex` says so. These forms are listed in their own table and are in no rate.
- **Dates (D-745):** a date of birth after its label or before the word for born must be masked (kind `dob`); a date
  with neither is clinical and must stay, so bare dates are in the clinical table, where a mask is over-masking.

## Tables (generated; `python -m tools.masking_leaks --check` compares every block whole)

By language and scope:

<!-- masking-leaks:summary:begin -->
| Language | Scope | Planted | Leaked | Per 1,000 | Partly | Per 1,000 | Tripwire missed | Per 1,000 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| en | in scope | 768 | 74 | 96.4 | 21 | 27.3 | 56 | 72.9 |
| en | free-standing name | 96 | 75 | 781.2 | 0 | 0.0 | 75 | 781.2 |
| en | line break | 144 | 120 | 833.3 | 12 | 83.3 | 93 | 645.8 |
| ja | in scope | 792 | 129 | 162.9 | 17 | 21.5 | 79 | 99.7 |
| ja | free-standing name | 72 | 72 | 1000.0 | 0 | 0.0 | 72 | 1000.0 |
| ja | line break | 144 | 113 | 784.7 | 5 | 34.7 | 83 | 576.4 |
| zh-TW | in scope | 942 | 82 | 87.0 | 30 | 31.8 | 54 | 57.3 |
| zh-TW | free-standing name | 84 | 60 | 714.3 | 2 | 23.8 | 60 | 714.3 |
| zh-TW | line break | 171 | 137 | 801.2 | 9 | 52.6 | 89 | 520.5 |
| all | in scope | 2502 | 285 | 113.9 | 68 | 27.2 | 189 | 75.5 |
| all | free-standing name | 252 | 207 | 821.4 | 2 | 7.9 | 207 | 821.4 |
| all | line break | 459 | 370 | 806.1 | 26 | 56.6 | 265 | 577.3 |
<!-- masking-leaks:summary:end -->

By kind:

<!-- masking-leaks:kinds:begin -->
| Language | Kind | Scope | Planted | Leaked | Per 1,000 | Partly | Per 1,000 | Tripwire missed | Per 1,000 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| en | address | in scope | 36 | 9 | 250.0 | 9 | 250.0 | 0 | 0.0 |
| en | address | line break | 6 | 3 | 500.0 | 3 | 500.0 | 0 | 0.0 |
| en | chart | in scope | 108 | 0 | 0.0 | 0 | 0.0 | 0 | 0.0 |
| en | chart | line break | 18 | 18 | 1000.0 | 0 | 0.0 | 3 | 166.7 |
| en | dob | in scope | 198 | 0 | 0.0 | 0 | 0.0 | 0 | 0.0 |
| en | dob | line break | 33 | 27 | 818.2 | 0 | 0.0 | 18 | 545.5 |
| en | email | in scope | 54 | 18 | 333.3 | 0 | 0.0 | 18 | 333.3 |
| en | email | line break | 9 | 9 | 1000.0 | 0 | 0.0 | 9 | 1000.0 |
| en | name | free-standing name | 96 | 75 | 781.2 | 0 | 0.0 | 75 | 781.2 |
| en | name | in scope | 102 | 34 | 333.3 | 0 | 0.0 | 25 | 245.1 |
| en | name | line break | 33 | 24 | 727.3 | 9 | 272.7 | 24 | 727.3 |
| en | national_id | in scope | 72 | 9 | 125.0 | 0 | 0.0 | 9 | 125.0 |
| en | national_id | line break | 12 | 12 | 1000.0 | 0 | 0.0 | 12 | 1000.0 |
| en | phone | in scope | 198 | 4 | 20.2 | 12 | 60.6 | 4 | 20.2 |
| en | phone | line break | 33 | 27 | 818.2 | 0 | 0.0 | 27 | 818.2 |
| ja | address | in scope | 54 | 12 | 222.2 | 12 | 222.2 | 0 | 0.0 |
| ja | address | line break | 9 | 6 | 666.7 | 3 | 333.3 | 3 | 333.3 |
| ja | chart | in scope | 90 | 0 | 0.0 | 0 | 0.0 | 0 | 0.0 |
| ja | chart | line break | 15 | 15 | 1000.0 | 0 | 0.0 | 3 | 200.0 |
| ja | dob | in scope | 288 | 0 | 0.0 | 0 | 0.0 | 0 | 0.0 |
| ja | dob | line break | 48 | 24 | 500.0 | 0 | 0.0 | 12 | 250.0 |
| ja | email | in scope | 54 | 18 | 333.3 | 0 | 0.0 | 18 | 333.3 |
| ja | email | line break | 9 | 9 | 1000.0 | 0 | 0.0 | 9 | 1000.0 |
| ja | name | free-standing name | 72 | 72 | 1000.0 | 0 | 0.0 | 72 | 1000.0 |
| ja | name | in scope | 108 | 69 | 638.9 | 5 | 46.3 | 31 | 287.0 |
| ja | name | line break | 30 | 26 | 866.7 | 2 | 66.7 | 26 | 866.7 |
| ja | national_id | in scope | 90 | 18 | 200.0 | 0 | 0.0 | 18 | 200.0 |
| ja | national_id | line break | 15 | 15 | 1000.0 | 0 | 0.0 | 12 | 800.0 |
| ja | phone | in scope | 108 | 12 | 111.1 | 0 | 0.0 | 12 | 111.1 |
| ja | phone | line break | 18 | 18 | 1000.0 | 0 | 0.0 | 18 | 1000.0 |
| zh-TW | address | in scope | 54 | 12 | 222.2 | 0 | 0.0 | 0 | 0.0 |
| zh-TW | address | line break | 9 | 8 | 888.9 | 1 | 111.1 | 8 | 888.9 |
| zh-TW | chart | in scope | 108 | 0 | 0.0 | 0 | 0.0 | 0 | 0.0 |
| zh-TW | chart | line break | 18 | 18 | 1000.0 | 0 | 0.0 | 3 | 166.7 |
| zh-TW | dob | in scope | 396 | 18 | 45.5 | 0 | 0.0 | 18 | 45.5 |
| zh-TW | dob | line break | 66 | 48 | 727.3 | 0 | 0.0 | 15 | 227.3 |
| zh-TW | email | in scope | 54 | 18 | 333.3 | 0 | 0.0 | 18 | 333.3 |
| zh-TW | email | line break | 9 | 9 | 1000.0 | 0 | 0.0 | 9 | 1000.0 |
| zh-TW | name | free-standing name | 84 | 60 | 714.3 | 2 | 23.8 | 60 | 714.3 |
| zh-TW | name | in scope | 96 | 18 | 187.5 | 0 | 0.0 | 2 | 20.8 |
| zh-TW | name | line break | 30 | 21 | 700.0 | 8 | 266.7 | 21 | 700.0 |
| zh-TW | national_id | in scope | 72 | 0 | 0.0 | 18 | 250.0 | 0 | 0.0 |
| zh-TW | national_id | line break | 12 | 12 | 1000.0 | 0 | 0.0 | 12 | 1000.0 |
| zh-TW | phone | in scope | 162 | 16 | 98.8 | 12 | 74.1 | 16 | 98.8 |
| zh-TW | phone | line break | 27 | 21 | 777.8 | 0 | 0.0 | 21 | 777.8 |
<!-- masking-leaks:kinds:end -->

Every form with a leak, a partial mask or a tripwire miss (up to five examples per cell in `leaks.json`, digits
written `d`):

<!-- masking-leaks:forms:begin -->
| Language | Kind | Form | Scope | Planted | Leaked | Per 1,000 | Partly | Tripwire missed | Leaked at |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| en | address | en_apt | in scope | 18 | 0 | 0.0 | 9 | 0 |  |
| en | address | en_apt | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| en | address | en_full | in scope | 18 | 9 | 500.0 | 0 | 0 | middle 3, start 3, table 3 |
| en | address | en_full | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | chart | bare_8 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | chart | label_Chart_No | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | chart | label_Hospital_No_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | chart | label_ID_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | chart | label_MRN_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | chart | label_MRN | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | dob | label_compact8 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | dob | label_day_month_abbr | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | dob | label_dotted | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | dob | label_iso | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | dob | label_month_name | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | dob | label_slash_dmy | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | dob | label_slash_mdy | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | dob | label_slash_ymd | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| en | dob | label_two_digit_year | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | email | ascii | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | email | fullwidth_at | in scope | 18 | 18 | 1000.0 | 0 | 18 | cjk_adjacent 3, end 3, label 3, middle 3, start 3, table 3 |
| en | email | fullwidth_at | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | email | plus | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | dr | in scope | 18 | 3 | 166.7 | 0 | 0 | label 3 |
| en | name | dr | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| en | name | first_last | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| en | name | first_last | in scope | 6 | 3 | 500.0 | 0 | 3 | table 3 |
| en | name | first_last | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | initials | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| en | name | initials | in scope | 6 | 6 | 1000.0 | 0 | 6 | label 3, table 3 |
| en | name | initials | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | last_comma_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| en | name | last_comma_first | in scope | 6 | 6 | 1000.0 | 0 | 6 | label 3, table 3 |
| en | name | last_comma_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | middle_initial | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| en | name | middle_initial | in scope | 6 | 3 | 500.0 | 0 | 3 | table 3 |
| en | name | middle_initial | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | mr | in scope | 18 | 3 | 166.7 | 0 | 0 | label 3 |
| en | name | mr | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| en | name | ms | in scope | 18 | 3 | 166.7 | 0 | 0 | label 3 |
| en | name | ms | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| en | name | pinyin_family_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| en | name | pinyin_family_first | in scope | 6 | 3 | 500.0 | 0 | 3 | table 3 |
| en | name | pinyin_family_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | pinyin_given_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| en | name | pinyin_given_first | in scope | 6 | 3 | 500.0 | 0 | 3 | table 3 |
| en | name | pinyin_given_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | wade_giles_family_first | free-standing name | 12 | 1 | 83.3 | 0 | 1 | start 1 |
| en | name | wade_giles_family_first | in scope | 6 | 1 | 166.7 | 0 | 1 | table 1 |
| en | name | wade_giles_family_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | name | wade_giles_given_first | free-standing name | 12 | 2 | 166.7 | 0 | 2 | cjk_adjacent 1, middle 1 |
| en | name | wade_giles_given_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | national_id | tw_arc_new | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | national_id | tw_arc_old | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | national_id | tw_id | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | national_id | us_ssn | in scope | 18 | 9 | 500.0 | 0 | 9 | cjk_adjacent 3, end 2, middle 2, start 2 |
| en | national_id | us_ssn | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | na_hyphen | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | na_intl | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | na_paren | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | tw_landline_ext | in scope | 18 | 0 | 0.0 | 12 | 0 |  |
| en | phone | tw_landline_ext | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | tw_landline_hyphen | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | tw_landline_paren | in scope | 18 | 4 | 222.2 | 0 | 4 | cjk_adjacent 3, middle 1 |
| en | phone | tw_landline_paren | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_hyphen | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_intl | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| en | phone | tw_mobile_plain | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | address | jp_full | in scope | 18 | 12 | 666.7 | 0 | 0 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | address | jp_full | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | address | jp_hyphen_building | in scope | 18 | 0 | 0.0 | 12 | 0 |  |
| ja | address | jp_hyphen_building | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| ja | address | jp_no_postcode | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | chart | bare_8 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | chart | label_ID_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | chart | label_カルテNo | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | chart | label_カルテ番号_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | chart | label_患者ID_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | dob | born_compact8 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | dob | born_dotted | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | dob | born_iso | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | dob | born_slash_ymd | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | dob | label_compact8 | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | dob | label_dotted | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | dob | label_iso | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | dob | label_slash_ymd | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | email | ascii | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | email | fullwidth_at | in scope | 18 | 18 | 1000.0 | 0 | 18 | cjk_adjacent 3, end 3, label 3, middle 3, start 3, table 3 |
| ja | email | fullwidth_at | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | email | plus | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | hepburn_family_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | name | hepburn_family_first | in scope | 6 | 6 | 1000.0 | 0 | 0 | label 3, table 3 |
| ja | name | hepburn_family_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | hepburn_given_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | name | hepburn_given_first | in scope | 6 | 6 | 1000.0 | 0 | 0 | label 3, table 3 |
| ja | name | hepburn_given_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | hiragana_space | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | name | hiragana_space | in scope | 6 | 6 | 1000.0 | 0 | 0 | label 3, table 3 |
| ja | name | hiragana_space | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | kanji_space | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | name | kanji_space | in scope | 6 | 3 | 500.0 | 1 | 0 | table 3 |
| ja | name | kanji_space | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | kanji_さん | in scope | 18 | 11 | 611.1 | 0 | 7 | cjk_adjacent 2, end 2, label 3, middle 1, start 2, table 1 |
| ja | name | kanji_さん | line break | 3 | 2 | 666.7 | 0 | 2 | line_break 2 |
| ja | name | kanji_先生 | in scope | 18 | 8 | 444.4 | 0 | 6 | cjk_adjacent 2, end 2, label 2, middle 2 |
| ja | name | kanji_先生 | line break | 3 | 0 | 0.0 | 2 | 0 |  |
| ja | name | kanji_様 | in scope | 18 | 8 | 444.4 | 4 | 6 | cjk_adjacent 2, end 1, label 1, middle 1, start 2, table 1 |
| ja | name | kanji_様 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | kanji_殿 | in scope | 18 | 13 | 722.2 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3, table 1 |
| ja | name | kanji_殿 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | kanji | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | name | kanji | in scope | 6 | 2 | 333.3 | 0 | 0 | label 1, table 1 |
| ja | name | kanji | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | name | katakana_space | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | name | katakana_space | in scope | 6 | 6 | 1000.0 | 0 | 0 | label 3, table 3 |
| ja | name | katakana_space | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | national_id | insurance_symbol_no | in scope | 18 | 18 | 1000.0 | 0 | 18 | cjk_adjacent 3, end 3, label 3, middle 3, start 3, table 3 |
| ja | national_id | insurance_symbol_no | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | national_id | insurer_no | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| ja | national_id | my_number_fullwidth | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | national_id | my_number_spaced | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | national_id | my_number | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | phone | jp_fullwidth | in scope | 18 | 12 | 666.7 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| ja | phone | jp_fullwidth | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | phone | jp_intl | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | phone | jp_landline_3 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | phone | jp_landline | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | phone | jp_mobile | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| ja | phone | jp_plain | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | address | tw_floor_unit | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | address | tw_full | in scope | 18 | 12 | 666.7 | 0 | 0 | cjk_adjacent 3, end 3, middle 3, start 3 |
| zh-TW | address | tw_full | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | address | tw_no_postcode | line break | 3 | 2 | 666.7 | 1 | 2 | line_break 2 |
| zh-TW | chart | bare_8 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | chart | label_ID_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | chart | label_MRN | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | chart | label_病歷號_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | chart | label_病歷號碼_colon | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | chart | label_病歷號碼 | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | born_compact8 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_dotted | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | born_iso | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | born_roc_compact | in scope | 18 | 18 | 1000.0 | 0 | 18 | cjk_adjacent 3, end 3, label 3, middle 3, start 3, table 3 |
| zh-TW | dob | born_roc_compact | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_roc_dot | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_roc_numerals | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_roc_slash | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | dob | born_slash_ymd | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_compact8 | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_dotted | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_iso | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_compact | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_dot | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_numerals | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_roc_slash | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | dob | label_slash_ymd | line break | 3 | 3 | 1000.0 | 0 | 0 | line_break 3 |
| zh-TW | email | ascii | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | email | fullwidth_at | in scope | 18 | 18 | 1000.0 | 0 | 18 | cjk_adjacent 3, end 3, label 3, middle 3, start 3, table 3 |
| zh-TW | email | fullwidth_at | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | email | plus | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | han_2 | free-standing name | 12 | 11 | 916.7 | 1 | 11 | cjk_adjacent 3, end 3, middle 2, start 3 |
| zh-TW | name | han_2 | in scope | 6 | 2 | 333.3 | 0 | 0 | label 1, table 1 |
| zh-TW | name | han_2 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | han_3_先生 | in scope | 18 | 1 | 55.6 | 0 | 1 | cjk_adjacent 1 |
| zh-TW | name | han_3_先生 | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | name | han_3_女士 | line break | 3 | 0 | 0.0 | 2 | 0 |  |
| zh-TW | name | han_3_醫師 | in scope | 18 | 1 | 55.6 | 0 | 1 | cjk_adjacent 1 |
| zh-TW | name | han_3_醫師 | line break | 3 | 0 | 0.0 | 3 | 0 |  |
| zh-TW | name | han_3 | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| zh-TW | name | han_3 | in scope | 6 | 2 | 333.3 | 0 | 0 | label 1, table 1 |
| zh-TW | name | han_3 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | han_4 | free-standing name | 12 | 11 | 916.7 | 1 | 11 | cjk_adjacent 3, end 3, middle 3, start 2 |
| zh-TW | name | han_4 | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | pinyin_family_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| zh-TW | name | pinyin_family_first | in scope | 6 | 6 | 1000.0 | 0 | 0 | label 3, table 3 |
| zh-TW | name | pinyin_family_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | pinyin_given_first | free-standing name | 12 | 12 | 1000.0 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| zh-TW | name | pinyin_given_first | in scope | 6 | 6 | 1000.0 | 0 | 0 | label 3, table 3 |
| zh-TW | name | pinyin_given_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | wade_giles_family_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | name | wade_giles_given_first | free-standing name | 12 | 2 | 166.7 | 0 | 2 | cjk_adjacent 1, end 1 |
| zh-TW | name | wade_giles_given_first | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_arc_new | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_arc_old | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_id_fullwidth | in scope | 18 | 0 | 0.0 | 18 | 0 |  |
| zh-TW | national_id | tw_id_fullwidth | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | national_id | tw_id | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_landline_ext | in scope | 18 | 0 | 0.0 | 12 | 0 |  |
| zh-TW | phone | tw_landline_ext | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_landline_hyphen | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_landline_paren | in scope | 18 | 4 | 222.2 | 0 | 4 | cjk_adjacent 2, end 1, middle 1 |
| zh-TW | phone | tw_landline_paren | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_fullwidth | in scope | 18 | 12 | 666.7 | 0 | 12 | cjk_adjacent 3, end 3, middle 3, start 3 |
| zh-TW | phone | tw_mobile_fullwidth | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_hyphen | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_intl | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |
| zh-TW | phone | tw_mobile_plain | line break | 3 | 3 | 1000.0 | 0 | 3 | line_break 3 |

Clean cells (no leak, no partial mask, no tripwire miss): 130 of 327.
<!-- masking-leaks:forms:end -->

Forms not held to be identifiers (in no rate):

<!-- masking-leaks:not_held:begin -->
| Language | Kind | Form | Scope | Planted | Leaked | Per 1,000 | Partly | Per 1,000 | Tripwire missed | Per 1,000 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| en | chart | bare_7 | in scope | 18 | 12 | 666.7 | 0 | 0.0 | 12 | 666.7 |
| en | chart | bare_7 | line break | 3 | 3 | 1000.0 | 0 | 0.0 | 3 | 1000.0 |
| en | chart | letter_7 | in scope | 18 | 12 | 666.7 | 0 | 0.0 | 12 | 666.7 |
| en | chart | letter_7 | line break | 3 | 3 | 1000.0 | 0 | 0.0 | 3 | 1000.0 |
| ja | chart | bare_7 | in scope | 18 | 12 | 666.7 | 0 | 0.0 | 12 | 666.7 |
| ja | chart | bare_7 | line break | 3 | 3 | 1000.0 | 0 | 0.0 | 3 | 1000.0 |
| ja | chart | letter_7 | in scope | 18 | 12 | 666.7 | 0 | 0.0 | 12 | 666.7 |
| ja | chart | letter_7 | line break | 3 | 3 | 1000.0 | 0 | 0.0 | 3 | 1000.0 |
| zh-TW | chart | bare_7 | in scope | 18 | 12 | 666.7 | 0 | 0.0 | 12 | 666.7 |
| zh-TW | chart | bare_7 | line break | 3 | 3 | 1000.0 | 0 | 0.0 | 3 | 1000.0 |
| zh-TW | chart | letter_7 | in scope | 18 | 12 | 666.7 | 0 | 0.0 | 12 | 666.7 |
| zh-TW | chart | letter_7 | line break | 3 | 3 | 1000.0 | 0 | 0.0 | 3 | 1000.0 |
<!-- masking-leaks:not_held:end -->

What the masker removes that criteria need (60 strings per kind and language, each planted in a base note):

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

## Findings (generated from `findings.json`)

Lane B2 owns `phi_guard`; lane A2 owns `services/guard`. Basis *shown*: counted in `leaks.json` by the full run and
held by xfail cases of `tests/unit/test_masking_leaks.py`. V5-11's effect on screening is a hypothesis: the judge
reads the original note (D-337 section 4), so its text is unchanged; retrieval and the S2b ranking from stored
vectors (`vec.s2b`) lose the date. No exclusion path was shown.

<!-- masking-leaks:findings:begin -->
| Id | Severity | Lane | Basis | Ruling | Place | Claim |
|---|---|---|---|---|---|---|
| V5-01 | High | B2 | shown | - | `libs/tb_common/phi_guard.py:629` | Japanese names in the ruling's scope leak 639 per 1,000: after 氏名 katakana, hiragana and Hepburn names leak every time; with さん, 様, 殿 or 先生 a surname outside the masker's list leaks |
| V5-02 | High | B2 | shown | - | `libs/tb_common/phi_guard.py:643` | English names in the ruling's scope leak 333 per 1,000: after Name: a LAST, First name, initials, and the surname after Dr./Mr./Ms. stay readable; in a Name table line every form leaks |
| V5-03 | High | B2 | shown | - | `libs/tb_common/phi_guard.py:631` | Chinese names in the ruling's scope leak 188 per 1,000: Pinyin after 姓名 every time; a surname outside the masker's list (闕, 冼, 諶) after 姓名 or before 先生 or 醫師 |
| V5-04 | High | B2 | shown | - | `libs/tb_common/phi_guard.py:299` | The Japanese insurance card's 記号・番号 leaks after its label every time |
| V5-05 | Medium | B2 | shown | - | `libs/tb_common/phi_guard.py:217` | An e-mail address with a full-width ＠ is never masked, in all three languages |
| V5-06 | Medium | B2 | shown | - | `libs/tb_common/phi_guard.py:90` | Unlabelled full-width Taiwan and Japan mobiles (667 per 1,000 of the form) and landlines with a 3-digit area code in brackets, (037)dd-dddd, leak; well-formed 02, 04 and other landlines are masked |
| V5-07 | Medium | B2 | shown | - | `libs/tb_common/phi_guard.py:100` | A value split by a hard wrap (at a separator between groups, or mid-run) leaks 806 per 1,000 |
| V5-08 | Medium | B2 | shown | - | `libs/tb_common/phi_guard.py:161` | A compact 7-digit ROC birth date before 出生 is never masked (after 出生日期 it is) |
| V5-09 | Medium | B2 | shown | - | `libs/tb_common/phi_guard.py:299` | An unlabelled US SSN leaks (500 per 1,000 of the form; masked after a label); rare in Taiwan and Japan |
| V5-10 | Medium | A2 | shown | D-506 | `services/guard/recognisers.py; services/gateway/core.py:579; services/gateway/policy.py:391` | The tripwire misses 75 per 1,000 in-scope planted notes. Medium by default (cloud_enabled false; no approved external endpoint). High at a site with cloud_enabled true and an external endpoint with a g5_record on a route whose external_requires flags are set |
| V5-11 | Medium | B2 | shown | D-337 section 4 | `libs/tb_common/phi_guard.py:832; deploy/settings.example.yaml:28` | Every 8-digit clinical date is masked in chunks and trips the tripwire (site pattern ^\d{8}$); the effect on retrieval and S2b ranking is a hypothesis, no exclusion path shown |
| V5-12 | Medium | B2 | shown | - | `libs/tb_common/phi_guard.py:167` | The postcode of a masked address stays readable: the 〒 code, the Taiwan 3-digit code and the US ZIP (500 to 667 per 1,000 of the full-address forms) |
| V5-13 | High | B2 | shown | D-337 | `libs/tb_common/phi_guard.py:578` | Free-standing names (no label, role, title or honorific) leak 821 per 1,000. Outside D-337 section 1; plan 8's V6 claim 'masking hides identifiers in notes' asks for more |
<!-- masking-leaks:findings:end -->

Listed, not filed: lab accession numbers are kept (one can link a sample to a person; the criteria do not read it);
the on-box judge reads raw notes (D-337 section 4).

## Question for the integrator

question: D-1037 allows an outside open-source de-identification tool for measurement only. May the owner run one on
his PC against these synthetic notes and the carve? From memory, not checked: Microsoft Presidio (MIT licence, a
Python package of a few MB) finds names with a spaCy model it does not ship. `en_core_web_lg` is about 560 MB,
downloaded once by `python -m spacy download` at setup; Chinese and Japanese need `zh_core_web_lg` and
`ja_core_news_lg` (some hundreds of MB each, the same way). Nothing is downloaded at run time after that.

# D-743 An English site in the synthetic hospital

- **Task:** NEW-B-42 (lane B2; from the D-502 reply on #579: every data set end to end in en, ja and zh-TW)
- **PR:** this branch (`agent/NEW-B-42-english-site-style`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-502 (the owner: every data set runs end to end with real models in en, ja and zh-TW), TB-DS-21
  (the synthetic hospital), T-503 / T-504 (its site styles and mixes)

## Context

A site of `tools.synth_hospital` was written in one of two record styles, `JP` or `TW`. English was 10 % of each
site's notes, on patients whose records were Japanese or Taiwanese (Chinese or Japanese names and doctors, a
Taiwanese national number's form, Taiwanese or Japanese phone numbers). No data set was English from end to end,
so an English run of D-502 had nothing to read.

## Decision

1. **A third record style, `EN`**: the Taiwanese table layout (the one `services/adapter/mapping/tw_core/demo_his.yaml`
   reads; the drug, diagnosis, lab and procedure names of the catalogue are already English) with English contents:
   - patient names from `tools/synth/names_en.py`, never a reserved name (as for the other styles);
   - the identifier `SYN` and seven digits: the form of no country's national number, so it cannot be one;
   - phone numbers 555-0100 to 555-0199, the range kept for fiction;
   - the doctors' names English;
   - every note English (the language mix `{"en": 1.0}`).
2. **The profile `ci-en`**: two English sites of 2,500 patients (`en-a:EN:2500,en-b:EN:2500`), the size of `ci-ja`
   and `ci-zh-TW`. `--sites ...:EN:...` is accepted.
3. **No new mapping**: the existing Taiwanese mapping reads an English site (tested through the real adapter).
4. **The `TW` and `JP` styles are unchanged**: the default generator stays byte-identical to the fixtures.

## Not in this card

- The demo's `TB_DEMO_SITE_LANG` (`tools/feas_demo.py`, not this lane's file) takes `ja` or `zh-TW`; a value `en`
  that picks `ci-en` is a one-line change there.
- An English 50k hospital: D-502 names the 50k hospital for ja and zh-TW only.

## Tests

`tests/unit/test_synth_english_site.py` (4 tests; all fail on the parent): an English site's identities, practitioners
and notes (no Chinese or Japanese character in any table); the profile and the sites option; a 600-patient run that
passes the hospital's own checks and is deterministic; a night of an English site read by the Taiwanese mapping
through the real adapter (patients, conditions and notes). No state change.

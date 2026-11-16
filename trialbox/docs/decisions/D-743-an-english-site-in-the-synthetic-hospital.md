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
   - the identifier `SYN` and seven digits: not the form of the Taiwanese or Japanese numbers, nor of a US social
     security number (letters first);
   - phone numbers 555-0100 to 555-0199, the range kept for fiction;
   - the doctors' names English;
   - every note English: the style's language mix is `{"en": 1.0}`, and a mix with another language on an `EN`
     site is refused (by the generator and by `--sites`/`--lang-mix`).
2. **The profile `ci-en`**: two English sites of 2,500 patients (`en-a:EN:2500,en-b:EN:2500`), the size of `ci-ja`
   and `ci-zh-TW`. `--sites ...:EN:...` is accepted.
3. **No new mapping**: the existing Taiwanese mapping reads an English site (tested through the real adapter).
4. **The hospital's checks look at an English site's identities**: an identifier that is not `SYN` and seven
   digits, or a phone outside 555-0100 to 555-0199, fails the run (as a valid Taiwanese check digit fails a `TW`
   site).
5. **The `TW` and `JP` styles are unchanged**: the default generator and the profiles `ci`, `ci-ja`, `ci-zh-TW`,
   `jp-ad` and `tw-ra` stay byte-identical (compared with the parent by the review).

## Found, not fixed here: the PHI guard has no English phone form (a safety defect for D-502's English runs)

`libs/tb_common/phi_guard.py` (not this lane's file) knows Taiwanese and Japanese phone forms only. On an English
site with planted PHI, the 555-01xx phones in the notes are masked in **0 of 357** spans by `note_spans`/`mask_note`
(which the lake calls before the full-text index and the embeddings) and are not found by `scan` (the gate before
any cloud call); on Taiwanese and Japanese sites every planted phone is masked. The numbers are fictional, so nothing
real is exposed, but an English run indexes and embeds them and the cloud gate clears them. The fix is the guard's
(an English phone form in `PHONE` and in the note recognisers, and an `en` case in
`tests/unit/test_phi_note_mask.py`'s planted-identifier test); sent to the integrator as a card of its own. The
`SYN` identifiers are masked through their "Insurance no." label, as the Japanese insurer numbers are.

## Not in this card

- The demo's `TB_DEMO_SITE_LANG` (`tools/feas_demo.py`, not this lane's file) takes `ja` or `zh-TW`; a value `en`
  that picks `ci-en` is a one-line change there.
- `tools/complete_run.py` and `tools/bench_embed.py` know the languages `ja` and `zh-TW` only (not this lane's).
- An English 50k hospital: D-502 names the 50k hospital for ja and zh-TW only.
- The pools are small: 100 phone numbers (the fiction range) and about 400 names per 2,500 patients, and the
  doctors' names come from the patients' name list (about 2 % of patients share a doctor's name; 1 % on a Japanese
  site). Nothing links records by name or phone.
- The FHIR of an English site is the Taiwanese mapping's: TW Core profiles and the NHI payer, by design.

## Tests

`tests/unit/test_synth_english_site.py` (6 tests; all fail on the parent): an English site's identities and doctors,
every value of every table plain ASCII with no Taiwanese or Japanese identifier or phone form, no planted name a
reserved one; the style is English whatever the mix (no mix gives English notes, a mix with zh-TW is refused); the
hospital's checks fail an English identity of a real form; the profile and the sites option; a 600-patient run that
passes the hospital's own checks and is deterministic; a night of an English site read by the Taiwanese mapping
through the real adapter: every note read, and nothing more left unread than in a Taiwanese site of the same size.
No state change.

## Review

One adversarial read-only review by a fresh agent (every table of English sites of the three patient mixes, with and
without planted PHI; TW and JP digests against the parent; nights through the real adapter; mutants). Findings,
fixed test-first in the second commit: the style alone did not make a site English (no mix gave Chinese notes, a
mixed one Chinese names beside `SYN`); the hospital's checks had no English identity check; the tests did not check
identifier forms in the whole site, and the night test did not count the notes or the unread fields. Said above,
not changed: the PHI guard's missing English phone form (another lane's file, a card of its own); the small pools;
the languages of `complete_run`/`bench_embed`.

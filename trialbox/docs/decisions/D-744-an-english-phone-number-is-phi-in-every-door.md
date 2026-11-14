# D-744 An English phone number is PHI in every door of the guard

- **Task:** NEW-B-43 (a safety defect found by NEW-B-42's review, D-743; placed with lane B2 by the integrator on
  2026-11-14, "do it first")
- **PR:** this branch (`agent/NEW-B-43-english-phones-are-masked`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** T-600 / FR-DEID-01 (note text masked before chunking, the full-text index and embedding), D-337
  (the masking version recorded with the chunks), PRIV-29 / S1-08 (the guard service's recognisers and the v1 guard
  folded in), D-743 (the English site of the synthetic hospital)

## Context

The guard has three doors for a phone number: the note masker (`tb_common.phi_guard.note_spans` / `mask_note`, what
the lake and the vector index apply before the full-text index and the embeddings), the gate before any call leaves
the box (`tb_common.phi_guard.scan`) and the guard service's recognisers (`guard.recognisers`, redaction and the
tripwire). All three knew Taiwanese and Japanese forms only. On an English site of the synthetic hospital with planted
PHI, the review of D-743 measured the planted 555-01xx phones masked in **0 of 357** spans by the masker and found by
neither `scan` nor the recognisers; every planted Taiwanese and Japanese phone was masked. English notes are 10 % of
every site's notes, and D-502 asks for English runs end to end.

## Decision

1. **One English phone form, `tb_common.phi_guard.EN_PHONE`**, read by all three doors (the guard service names it in
   `PHONE_PATTERNS`, not a copy):
   - anywhere: a number with its country code (`+1 555 010 0199`, `+44 20 7946 0958`); a North American number with
     its area code (`(555) 010-0133`, `555-010-0133`, `555.010.0150`); a British national number (`020 7946 0958`,
     `07700 900123`); never inside a code (a letter or digit before it: the JLAC10 lab code `3D046 0000 019`);
   - a local number of seven digits (`555-0133`) only after a word that says it is one: `tel`, `telephone`,
     `phone`, `ph`, `mobile`, `cell`, `fax`, `contact`, `call`, `number (is)`. Only the number is masked; the word
     stays.
   - Clinical ranges (`100-300 mg`, `4.5-11.0`, `540-600`), dates, times, blood pressures and trial numbers have
     neither shape.
2. **The masking version is 2** (`NOTE_MASK_VERSION`): chunks masked by version 1 say so. The vector search reads
   a note whose stored chunks carry another version as stale and ranks on the fly from the newly masked text until
   the note is indexed again; the lake masks every note again at its next rebuild and records the version in
   `lake_meta.note_mask` (D-337).

## What a person sees differently

An English phone number in a note is masked (`○`) in the full-text index, the chunks and the embedding inputs; the
lake's `document` table keeps the original under the `phi` label, as for every other identifier. A call to a cloud
model whose variables hold one is refused by the gate as for a Taiwanese phone. A protocol whose criteria quote a
contact number (`+1-555-0103`) is refused by the cloud gate of the criteria compiler, as one quoting a Taiwanese
number already was.

## Measured

Over the repository's text (44 million characters: public protocols, IR fixtures, model cassettes, the guard's and
the synthetic hospital's fixtures, rulesets, the documents) the form finds three numbers, all phone numbers (the
contact fixtures of the injection tests). It found a fourth, a JLAC10 lab code written with spaces; the form no longer
matches inside a code.

## Not in this card

- A seven-digit number with no word before it (`555-0133` alone) is not masked: in English notes that shape is also
  a range of counts. The synthetic hospital writes it after "Contact".
- Phone numbers of other countries without their country code.
- The planted-identifier test of the synthetic notes (`tests/unit/test_phi_note_mask.py`) gains an English site
  once D-743's `EN` style is on master (PR #591); until then the English sentence of that style is a case here.

## Tests

`tests/unit/test_phi_english_phones.py` (39 tests; the 32 for a phone, the version and the one form fail on the parent; the 7 clinical texts pass on both): ten English
phone forms through each of the three doors (the masker masks the number and keeps the word, the gate refuses, the
guard service redacts); seven English clinical texts (a lab code among them) left alone by all three; the masking version is 2; the guard
service reads the one form. No state change.

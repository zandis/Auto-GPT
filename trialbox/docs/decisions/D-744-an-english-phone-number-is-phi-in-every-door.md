# D-744 An English phone number is PHI in the guard's three doors

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

1. **One English phone form, `tb_common.phi_guard.EN_PHONE`**, read by all three doors (the guard service reads it at
   each call, not a copy):
   - anywhere: a number with its country code, `+` or `00`, at least nine digits (`+1 555 010 0199`,
     `+44 20 7946 0958`, `001 555 010 0133`); a North American number with its area code in brackets or followed by a
     dash, and a dashed exchange (`(555) 010-0133`, `555-010-0133`, `555.010.0150`, `1-800-555-0199`); a British
     national number with its area code followed by a separator or in brackets (`01632 960958`, `07700-900123`,
     `(01632) 960 123`). Hyphens, dots and the Unicode dashes separate; a separator never crosses a line.
   - after a word that says it is a phone (`tel`, `telephone`, `phone`, `ph`, `mobile`, `mob`, `cell(phone)`, `fax`,
     `pager`, `landline`, `helpline`, `contact`, `call`, `dial`, `home`, `number is`, `T:`, `M:`, each optionally
     followed by `no.`, `number`, `#` or `details`): also a seven-digit local number (`555-0133`, `555 0133`,
     `5550133`) and a number written without separators (`07700900123`, `5550100133`). Only the number is masked;
     the word stays.
   - never inside a code or a number (a letter, digit, `+`, dot or comma before it; a letter or digit after it; a
     dash and a digit after it), and never after a digit and a space as the next group of a spaced code (JLAC10
     `3D046 0000 019 062 02`).
2. **The masking version is 2** (`NOTE_MASK_VERSION`): chunks masked by version 1 say so. The vector search reads a
   patient whose stored chunks carry another version as stale and ranks on the fly from the newly masked text: every
   patient, until the index is built again. A lake snapshot built before this change keeps its full-text index and
   chunks as masked then until the lake's next rebuild masks every note again and records the version in
   `lake_meta.note_mask` (D-337); nothing reads that record back to refuse an older snapshot.

## What a person sees differently

An English phone number in a note is masked (`○`) in the full-text index, the chunks and the embedding inputs; the
lake's `document` table keeps the original under the `phi` label, as for every other identifier. A call to a cloud
model whose variables hold one is refused by the gate as for a Taiwanese phone. A protocol whose criteria quote a
contact number (`+1-555-0103`) is refused by the cloud gate of the criteria compiler, as one quoting a Taiwanese
number already was.

## Measured

- **The PHI evaluation set** (`eval/phi_synth`, 120 synthetic notes in zh-TW, ja and en with gold spans and 510
  decoys): the masker masked **80 of 120** gold phones before, **119 of 120** after (the one left: a British area code
  of five digits followed by a seven-digit number in two groups); decoys masked: 5 of 510 before and after.
- **The repository's text** (58 million characters: every test fixture, `eval/`, `spec/`, rulesets, documents): the
  form matches the gold phones of the evaluation set, the contact numbers of the injection tests' fixtures and the
  examples in this record and its tests; nothing else. Seen on the way and no longer matched (each now a case in the
  tests): a spaced JLAC10 code, decimal fractions of the evaluation results (`0.0031023784901758012`), a resource id
  (`0020305175026d62…`).
- **The synthetic hospital** (TW and JP styles with English notes, planted PHI): every planted phone masked, nothing
  outside the planted PHI masked (`tests/unit/test_phi_note_mask.py`).

## Known, not changed here

- **Other exits without an English phone form.** `tools/data_scan` (which `tools/support_bundle.py` uses to scrub a
  bundle before it leaves the box, and the console's comment export and demo guard use) knows Taiwanese and Japanese
  phones only. Adding one there makes the repository's own scan find every synthetic English phone in the tests and
  `eval/`, which needs their allow-list entries: a card of its own (sent to the integrator).
- `scan` (the gate) has no Japanese phone form (the guard service and the masker have one): older than this card.
- After `contact` or `call`, a dashed seven-digit range (`Contact 250-5000 IU`) is read as a phone.
- A second number after the first (`Tel 555-0133 or 555-0134`), a number split over a line, full-width digits, a
  five-digit British area code followed by a seven-digit number, and a seven-digit number with no word before it are
  not masked.

## Tests

`tests/unit/test_phi_english_phones.py` (96 tests): twenty-five English phone forms through each of the three doors
(the masker masks the number and keeps the word, the gate refuses, the guard service redacts); thirteen English
clinical and data texts left alone by all three (ranges, doses, times, study, lot and kit numbers, spaced lab codes,
decimals, a resource id); a prompt's numbers on separate lines are not one phone; the guard service keeps the word;
the masking version; the guard service reads the shared form at each call (replacing it changes what is found). On
the parent the phone, version and wiring tests fail. No state change.

## Review

One adversarial read-only review by a fresh agent (about 110 probe strings through the three doors; the PHI
evaluation set; the synthetic hospital; 58 million characters of repository text; 100,000-character adversarial
strings: linear, 42 ms for the masker; ten mutants). Findings, fixed test-first in the second commit: common forms
missed (`Phone no:`, British numbers unspaced, bracketed or hyphenated, Unicode dashes, ten digits unseparated,
`Ph 555 0133`, `Pager`, `T:`, `00` prefixes, `1-800`, a number followed by `-ext`); false positives that the gate
would refuse a call on (`number` before study, lot and kit numbers, 24-hour times, runs of three numbers, `+100000`,
numbers on separate lines, the full spaced JLAC10 code); the wiring test read a constant production did not use; the
record overstated "every door", "never inside a code", what has neither shape, what was measured and what goes
stale. Said above, not changed: the data scan's exits, the gate's missing Japanese form, the forms listed.

# H90: the bundle check reads the embedder's measured files by their hash

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-90 (walk step 0, the release bundle; ruled go by the integrator)
- **Date:** 2026-11-22
- **Decision:** none given. The ruling below is the integrator's; if it needs a decision record, the lead asks for a
  number.
- **Findings:** [`h90-bundle-check-measured-files-2026-11-22/findings.json`](h90-bundle-check-measured-files-2026-11-22/findings.json)
  (H90-01, H90-02)
- **Files:** `tools/vocab_bundle_check.py`, `tests/unit/test_vocab_bundle_measured_h90.py`

## What failed

Every site bundle carries the embedder whole in `embedder/` (`tools/release.py`, `embedder_problems`), and
`tools/make_bundle.sh` runs `tools.vocab_bundle_check --models` on the models folder before the first image is saved.
The embedder's tokenizer file is binary and its extension is not among the weights, fonts and images the check lists
as not terminology, so the check refused it as "binary content of an unknown kind": every real site bundle stopped
there.

## The ruling, and what changed

A file listed in the embedder's measured record is checked by its measured hash, never skipped by extension; a binary
file not in a measured record is still refused. `.model` is not added to the skip list.

- `measured_files()` reads the record that the embedder's registry row names as `expected.source`
  (`deploy/measured/embedder_files.e-embed-1.json`) and keys each listed file as `embedder/<path>`.
- In a models folder, binary content of no known kind passes, as a note, only when its path under the folder is a
  listed one and its sha256 is the record's. With another sha256 it is refused, naming both hashes. A binary file the
  record does not list is refused as before ("binary content of an unknown kind").
- Nothing else changed: containers, the weights, fonts and images listed as not terminology, and every text file
  (the record's `config.json`, `README.md` and `tokenizer.json` among them) are read as before.

## Tests

`tests/unit/test_vocab_bundle_measured_h90.py`, synthetic bytes only:

| Test | On master | On the branch |
| --- | --- | --- |
| `test_the_real_records_tokenizer_passes_by_its_measured_hash` | fails (refused) | passes |
| `test_the_tokenizers_name_with_another_hash_fails` | fails (refused, without the hash) | passes |
| `test_an_unlisted_model_file_fails` | passes (the refusal was there) | passes |

The real tokenizer file is not in the repository, so the first test stands the synthetic file's sha256 in for the
record's (the record's own entry is read). No existing test changed.

## Open

- **H90-01.** The ruling says "never skipped by extension". The record's weights file still takes the not-terminology
  path by its extension, and its text files are read, not hashed. Hashing every listed file would refuse the stand-in
  weights of `test_a_models_folder_lists_weights_and_reads_the_rest` (a changed assertion), so it waits for a ruling.
- **H90-02.** Not run on a real site bundle: the real tokenizer file was not fetched here (no network fetch of the
  weights, nothing paid).

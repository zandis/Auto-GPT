# H90: the bundle check reads measured model files by their hash

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** H-90 (walk step 0, the release bundle; ruled go by the integrator, and H90-01 ruled go in this card)
- **Date:** 2026-11-22
- **Decision:** none given. The rulings below are the integrator's; if they need a decision record, the lead asks for
  a number.
- **Findings:** [`h90-bundle-check-measured-files-2026-11-22/findings.json`](h90-bundle-check-measured-files-2026-11-22/findings.json)
  (H90-01 to H90-03)
- **Files:** `tools/vocab_bundle_check.py`, `tests/unit/test_vocab_bundle_measured_h90.py`,
  `tests/unit/test_vocab_bundle_check_22_4.py` (one test's folder)

## What failed

Every site bundle carries the embedder whole in `embedder/` (`tools/release.py`, `embedder_problems`), and
`tools/make_bundle.sh` runs `tools.vocab_bundle_check --models` on the models folder before the first image is saved.
The embedder's tokenizer file is binary and its extension is not among the weights, fonts and images the check lists
as not terminology, so the check refused it as "binary content of an unknown kind": every real site bundle stopped
there. On the bench the check also refused the verifier folder's `recipe.yaml` as YAML that does not parse.

## The rulings, and what changed

Every file a measured record lists passes only on its recorded sha256, weights, text and binary alike; a listed file
with another hash is refused; an unlisted file goes through the vocabulary check unchanged. No extension is added to
the skip list.

- `measured_files()` reads, for each build of a deployed pair (`tools.pin_model.PROFILE_PAIRS`, every profile) and for
  the embedder (`EMBED_PIN`), the record its registry row names as `expected.source`, takes that record's server of
  the row's source repository (as `tools.fetch_weights` does) and keys each listed file as `<folder>/<path>`, the
  folder being the build's default folder. A record is used only when its files give the row's
  `expected.manifest_sha256`.
- In a models folder, a listed file is hashed (in chunks) and not read: it passes, as a note, on a recorded sha256,
  and is refused with both hashes otherwise. Other files are read as before.
- The registry is the one `tools.release` reads: `TB_RELEASE_REGISTRY` (the unit tests' synthetic registry only), else
  `models/registry.yaml`. The release tests' synthetic embedder sets its own expected manifest there, so the record
  does not apply to it and its stand-in files are read as before.

**Covered.** The embedder's record (`deploy/measured/embedder_files.*.json`) for `embedder/` (18 files); the serving
record (`deploy/measured/serving_config.*.json`) for the judge's folder (12 files) and the verifier's folder (17 files,
`recipe.yaml` among them), each the default folder `tools.pin_model` names. Every profile's pair names the serving
record.

**Not covered.** A judge or verifier folder renamed with `JUDGE_MODEL_DIR` or `VERIFIER_MODEL_DIR` (its files are read
as unlisted ones); the judge's chat template (a single file under the models root; its sha256 is in the registry row,
not in a measured record); the builds whose rows name no record (`expected.manifest_sha256: null`);
`deploy/measured/ingest_memory.json` and `orchestrator_memory.json`, which list no model files.

## The box rehearsal (train 132's red)

The rehearsal (`tools/rehearse_box/rehearse.sh`) stages its placeholder weights under the pair's real folder names,
which the install pins by folder, so the records applied to them and the rehearsal's bundle was refused. The
integrator's bound: no path may let a real build ship a listed file without its recorded hash. Chosen: the bundle
names the rehearsal explicitly, not new folder names (those would change what the rehearsal box pins).
`tools/make_bundle.sh --rehearsal` (the flag that already marks `release.json`, which a site box refuses, D-726) now
passes `--rehearsal` to the check. With it, a folder whose `config.json` names the placeholder architecture
(`tools.pin_model.is_placeholder`) is read as an unlisted folder; without it, every file of such a folder is refused,
under any folder name. No environment variable selects the form; every other folder keeps the hash rule in both.

## Tests

`tests/unit/test_vocab_bundle_measured_h90.py`, synthetic bytes only. On master the file does not collect
(`measured_files` is not there), so every test fails there. Where a recorded hash must match, a synthetic file's
digest stands in for the record's (the record's own entry is read): the real files are not in the repository.

- The records cover the three folders, keyed by the record's full paths.
- The record's tokenizer passes on its hash; the same name with another hash fails; an unlisted `.model` file fails.
- A listed text file with one changed byte is refused.
- A listed `recipe.yaml` with the recorded hash passes while it does not parse; unlisted, the same bytes are refused.
- Stand-in weights, text and README under `embedder/` are refused (three problems).
- A record that is not its row's expected manifest covers nothing.
- **The invariant** (for the independent review): `test_no_listed_file_passes_with_a_hash_other_than_the_records`,
  one case per listed file (47).

**The changed test.** `test_a_models_folder_lists_weights_and_reads_the_rest` (`test_vocab_bundle_check_22_4.py`) put
its stand-in files in `models/embedder/`, which a record now covers; its folder is now `models/invented-model/`, no
record's, and its assertions are unchanged. The old setup is the new "stand-in weights" test, which asserts the
refusals (go by the integrator).

**Mutants** planted in `tools/vocab_bundle_check.py`, each run against the card's tests and the 22-4 file: a hash
mismatch passes; the measured route skipped; files keyed by base name; only a 12-character prefix compared; the
embedder's record only; the expected-manifest guard dropped. Six planted, six caught (the base-name mutant only after
a test pinning the keys to the record's full paths was added).

## Open

- **H90-02.** Not run on a real site bundle: the real model files were not fetched here (no network fetch of the
  weights, nothing paid).

## Closed

- **H90-01.** Fixed in b4bd3f721f0bf8433464a8c6cc7ef28378bf264f: every listed file is hash-checked, not skipped by
  extension.
- **H90-03.** Fixed in b4bd3f721f0bf8433464a8c6cc7ef28378bf264f: the verifier's `recipe.yaml` is listed in
  the serving record under `deploy/measured/` (and named as the provenance recipe in `models/registry.yaml`),
  so it is hash-checked, not parsed. Why the bench's copy does not parse as YAML is not shown: the file is not in the
  repository.

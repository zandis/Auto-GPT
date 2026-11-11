# D-392 Model provenance, the judge's pinned chat template, the bake-off builds

- **Task:** T-674 (TB-PLAN-06 §6.2.4, dependency batch 2, models first)
- **PR:** this branch (`agent/T-674-model-provenance`)
- **Date:** 2026-11-11
- **Status:** proposed
- **Closes:** DEP-007, DEP-008, DEP-009; PLAN-036 (candidate half). Builds on D-358 (T-012b).

## Context

The deep review of 2026-11-10 found three things about the models. The judge's weights carry the quantiser's copy
of the chat template, older than the developer's fix of 2026-07-15, and vLLM uses it because no `--chat-template` is
passed (DEP-007). The verifier comes from a personal account whose history was squashed, and no row said where the
files came from (DEP-008). The judge challenger has no build (DEP-009). A hospital may refuse a PRC-origin verifier,
so a second candidate must be on record (PLAN-036, RSK-60).

## Decision

1. **Provenance per local build.** `models/registry.yaml` gives each local build a `provenance` block: `copy`
   (`publisher-quantisation`, `own-copy` or `own-quantisation`), `source` and `revision`, the `base` model, the
   quantisation `recipe` and the `licence_file`, each file with its sha256. The weight manifest sha256 stays in
   `expected` (D-358). A deployed build (a profile pair in `tools/pin_model.py` `PROFILE_PAIRS`, and the front desk
   on the judge's server) has no `null` revision: `tests/unit/test_model_provenance.py` holds this.
2. **The verifier: own copy of the publisher's quantisation, licence file kept.** This is the default while the
   owner's question on the verifier copy is open (`provenance.default: true`). The copy is the files of
   `cyankiwi/Qwen3.5-9B-AWQ-4bit` at `e4d2d39cede8c5d1716d824cd843e2889c648083`, the release already measured, in the
   vendor's own model store. Its `LICENSE` and `recipe.yaml` are files of that release, so they are in its weight
   manifest; their sha256 are in the row and equal the measured record. The other choice, an own quantisation of
   `Qwen/Qwen3.5-9B` with the same public recipe, is a new build with a new expected manifest.
3. **The judge's chat template.** Judge builds name `chat_template`: the developer's file
   (`google/gemma-4-26B-A4B-it`, revision `4d7ae4984b7d`) at `chat-templates/gemma-4-26b-a4b-it/chat_template.jinja`
   under the models root. Every profile's compose file starts the judge with `--chat-template` on it
   (`JUDGE_CHAT_TEMPLATE` moves it). `pin_model` records the file's sha256, source and revision in the pin
   (`weights.chat_template`, and `manifests/<build>.template.sha256`), refuses a file whose sha256 differs from the
   row's, and `--verify-all` re-checks it. `--install` does not pin a judge whose template is missing, because vLLM
   would not start. The weight manifest and its digest do not change. The serving record (`tools/serving_config.py`)
   reads `--chat-template` and writes `chat_template_sha256`; a record that names a template without its sha256 is
   incomplete.
4. **The challenger.** `gemma-4-31b-it-qat-challenger` (Google's own 4-bit QAT checkpoint, DEP-009) is a candidate of
   `j-workhorse` with `bakeoff: {ledger: S4, state: queued}`. Its run is row S4 of `docs/plan/gpu-ledger.md`. It has
   not run.
5. **The second verifier candidate.** `ministral-3-14b-verifier-candidate` (Mistral AI, France; deep review 03a row
   2) is a candidate of `v-verifier` with `bakeoff: {state: unmeasured, risk: RSK-60}`. It would be an own 4-bit
   build from the developer's release.
6. **Nothing is guessed.** A revision or sha256 not read from its source is `null`. Short revision ids read by the
   review are kept as read.

## Remains

- The full revision id and the sha256 of the judge's template, from a download of the developer's repository (no
  network from here). Until then `pin_model` records the site's file as `trust: first_use`.
- A test that renders one judge prompt with the developer's template and compares it with the upstream output
  (DEP-007 acceptance), once the file is in hand. The developer's `tokenizer_config.json` is not used yet.
- A serving record taken with `--chat-template` (the committed one is from 2026-11-08, before it), then the judge
  canary and N-12 on it.
- The cloud run scripts (`deploy/gcp/*.sh`) and the platform manifests start the judge without the template.
- The challenger's and the second candidate's revisions and licence files, at download; the S4 run itself.

## Consequences

- A box installed after this change needs the template file in `deploy/models` before the judge is pinned.
- A box pinned before keeps its weight pins; the next install adds the template to the judge's pin when the file is
  there, and reports the judge otherwise.

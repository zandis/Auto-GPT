# D-567 The judge's chat template is named by its hash: nothing is trusted at first use

- **Task:** HW-005 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md`, wave 1, lane D; finding HW-005 of
  `docs/reviews/2026-11-12-deep-review/13-final-build-hardware-install.md`)
- **PR:** this branch (`agent/HW-005-chat-template-hash`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-392 (provenance of a build; the judge starts with `--chat-template` on the developer's file,
  DEP-007; `pin_model` hashes the file into the site pin), T-674 (the pin's `chat_template` entry, `trust`)
- **Read by:** lane G (test G-1: the canary and one hospital part with this template), HW-003 and LLM-005 (the
  vendor qualification record names the template's hash)

## Context

Compose starts the judge with `--chat-template` on the developer's template file. The registry row named that
file's source and a short revision, and `sha256: null`: `pin_model` then recorded whatever file the site had,
marked `first_use`. The file is placed by hand and is in no manifest. A wrong file would have been pinned and
served.

## Decision

1. **The seven judge and front-desk rows name the template in full**: source `google/gemma-4-26B-A4B-it`,
   revision `4d7ae4984b7db7de8f8457170b3f1a419ee76d52`, sha256
   `ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4` (18,683 bytes). Read on 2026-11-12 from the
   publisher's public repository at that revision (a text file; no token, no weights). `pin_model` refuses any
   other file for these builds (the existing rule for a row with a hash), and the pin says `trust: expected`.
2. **A deployed judge or front-desk build without a template hash fails the provenance test.** `first_use` stays
   in `pin_model` for a row someone is still preparing; it cannot ship.
3. **The flag stays.** The weight folder's own template is another file: sha256 `94899c0f…` (16,934 bytes; the
   measured record `deploy/measured/serving_config.rtxpro6000.json`, and the publisher's file at the weights'
   revision read the same day). They are not identical, so `--chat-template` is not dropped. A test holds the two
   hashes apart: when they become equal, the flag can go.
4. **What the accuracy evidence was taken with is lane G's to redo.** The measured record and G1 ran with the
   folder's template. The canary and one hospital part are run again with the developer's file before anything
   else is measured (test G-1).

## Consequences

- A box whose template file is not the named one is refused at the pin, before the judge starts.
- The model cards show the full revision.
- No setting, no limit, no new store.

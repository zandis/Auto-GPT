# D-358 `champion` only through `qualify`

- **Task:** T-012b (TB-PLAN-06 §6.2.4; second half of TB-ASSESS-01 T-012)
- **PR:** this branch (`agent/T-012b-champion-qualify`)
- **Date:** 2026-11-11
- **Status:** proposed
- **Closes:** LLM-007, LLM-029 (control half), CR-079

## Context

`pin_model --install` hashed whatever was in the model folder and pinned it as `champion`. A folder holding one
16-byte file passed, and `--verify-all` then proved only "unchanged since install" (LLM-007). D-313 (T-012a) added
`trialbox eval qualify` and its record, but nothing tied the record to the status a PRODUCTION route accepts.

## Decision

1. **Expected weights per build.** Every local build in `models/registry.yaml` has `expected.manifest_sha256` and
   `expected.revision`. The values of the deployed pair come from the measured serving record
   (`deploy/measured/serving_config.rtxpro6000.json`): `pin_model.manifest_sha256_of_files` turns its file list
   into the manifest digest `pin_model` computes over a folder, so there is one hash format. A build whose release is
   not measured has `null` values. A site override cannot set `expected`.
2. **No trust on first use.** `pin_model` refuses a folder whose manifest is not the expected one. When nothing is
   expected it refuses too, unless `--trust-first-use` is given; such a pin is a `candidate` marked
   `weights.trust: first_use`, for evaluation only, and is never promoted.
3. **Install pins `candidate`.** `pin` never writes `champion`, and a re-pin drops the status and the record.
4. **Promotion from a record.** `pin_model --promote BUILD --record <file>` runs `tools.qualify.check_record` (passed,
   every step, body not edited, this build, PRODUCTION), checks that the record qualified exactly the pinned
   weights, and writes `status: champion` with a `qualification` reference (record id, file, sha256, profile, the
   weights, `qualifies_production`, date).
5. **The gateway rule.** `Registry.resolve` refuses in PRODUCTION a champion whose reference does not qualify
   PRODUCTION for exactly its pinned weights: `champion_unqualified`, returned by the gateway as a 403 with that
   code. In any environment it refuses a pin that is not the expected release: `weights_unexpected`. The rule sits
   in the registry, where the gateway resolves every build, so `services/gateway/core.py` and `policy.py` are not
   changed (T-603 edits `core.py` at the same time).
6. **Qualify on a box.** `qualify` sends D0 calls; a gateway in TEST routes `candidate` builds, so a box is
   qualified with its gateway in TEST, then promoted, then started in PRODUCTION. `tools.qualify.profile_builds`
   takes a local build's weights from `expected` when the committed file has no pin.
7. **Measurement harness.** `tools.scenarios.installed_registry` (complete run, bench profile) measures builds
   before any record exists. It pins as install does, against a registry copy when its weights are synthetic, and
   marks the pair champion with the reference `harness:measurement` in its own override under its work folder. A
   box's override is written by `pin_model` alone.
8. **Admin page.** The Models tile lists each pinned build with its status and record, and flags a champion without
   a record and weights that are not the expected release. It reads the gateway's `/registry/v1/builds`.

## Consequences

- A box installed after this change routes nothing in PRODUCTION until its pair is qualified and promoted. A box
  installed before keeps its `champion` pins and is refused with `champion_unqualified` until promoted.
- The expected manifest assumes the site's folder holds the files of the measured snapshot (hidden files such as
  `.gitattributes` and `.cache/` are not in the manifest). A folder made another way is refused, by design.
- The gateway trusts the reference in the override; it does not re-read the record file. Re-reading it at start is
  for T-677 (weights and pins checked at gateway start).

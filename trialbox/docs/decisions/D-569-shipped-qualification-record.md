# D-569 The vendor's qualification record ships in the bundle; the install promotes the pair it qualified

- **Task:** HW-003 with LLM-005 (TB-PLAN-07 v7.2, `docs/plan/33-plan-v7.md`, wave 1, lane D; findings HW-003 of
  `docs/reviews/2026-11-12-deep-review/13-final-build-hardware-install.md` and LLM-005 of `06-llm.md`)
- **PR:** this branch (`agent/HW-003-vendor-record-promote`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** T-012b (champion only through a passing qualification record: `pin_model --promote`,
  `tools.qualify.check_record`; a PRODUCTION gateway routes a champion only with a record for exactly its pinned
  weights), D-313 (the qualification record), D-367 (the host tree of a bundle: `deploy/` rides in it, signed with
  the bundle), D-392 and D-567 (the judge's chat template in the pin), the canary gate (the orchestrator's self-test
  at start and before each night)
- **Read by:** lane G (the first real record), OPS-004 (the installer in the rehearsal), T-114 (shared quota)

## Context

`install.sh` pins the pair as `candidate`; a PRODUCTION gateway routes a `champion` only. `pin_model --promote`
needs a passing qualification record, and `trialbox eval qualify` needs a development checkout, three evidence
files of the same commit, public data and a gateway in TEST. None of that is on a site box, no record ships, and
neither installer promotes. A PRODUCTION box screened no note, and a field engineer had no documented way forward.

## Decision

1. **Where a shipped record lives.** `deploy/qualification/<profile>/<record>.json`. `deploy/` is in the bundle's
   host tree, so the record is covered by the bundle's signature and the tree's checksums. The vendor qualifies a
   pair once per hardware profile on the same card type and commits the record there with the release.
2. **What a record now says about the serving.** The `serving_record` step also writes the model server image
   of the release the run was made from (the reference and digest of `deploy/images.lock` at the run's commit) and
   the sha256 of the chat template in the judge's site pin. These are the release's and the pin's values, not read
   back from the server that answered: the weights are tied to the answers (step `pin`), these two are not. A
   record without them cannot be used for a shipped promotion (it still promotes by hand with `--promote`).
3. **`pin_model --promote-shipped <profile>`** promotes the profile's pinned pair when one shipped record:
   passes `check_record` for that profile and PRODUCTION; names both builds of the pair; qualified exactly the
   pinned weight manifests; names the model server image the box's `deploy/images.lock` names; and the chat
   template the judge's pin holds. A judge whose registry row names a template and whose pin holds none is never
   promoted. Both builds are promoted from that one record, or neither (whatever error stops the second, the
   override is put back). No record, or none that matches, is said by name with the first difference, and the
   pair stays `candidate`. A profile with no qualification profile (the judge-alone `rtx4090`) says so.
4. **A promotion waits for the box's canary.** The promotion writes `deploy/site/shipped-promotion.pending.json`
   first. `install.sh` then restarts the gateway, waits for it, and runs the canary (`trialbox selftest`: the
   orchestrator's self-test cases, through the PRODUCTION gateway). When it passes, `--confirm-shipped` removes
   the mark and the orchestrator is restarted, so that its own start canary opens its canary gate on the promoted
   pair. When the canary fails, cannot run, or the gateway does not come back, `--demote-pair` puts back the
   builds that record promoted (a build that is champion on another record is not touched) and the install's FAIL
   list says so; when the demotion itself fails the line says that instead, with the command. An install that is
   interrupted finds the mark the next time and runs the canary again: it never says "already champion" for a
   pair that was not canaried.
5. **A shipped promotion is checked again at every install.** A pair that is champion on a shipped record whose
   release no longer matches it (another model server image after an update, another template) is put back.
6. **Links are resolved before they are mounted.** On a box installed from a bundle `deploy/qualification` and
   `deploy/images.lock` are links into the release tree; the install mounts what they point at.
7. **Another driver or card edition than the record's is a line, not a refusal**: the canary on the box is the
   check that this card answers as the qualified one did. The line names the record's card and driver.
8. **By hand stays as it was**: `--promote BUILD --record FILE` for a record made on the box.

## What this does not do (open)

- **The prompt set is not matched.** A record carries the prompts' hashes, but the active set differs by
  environment (the record is taken through a gateway in TEST; a PRODUCTION box runs the set its prompts'
  own qualification entries allow), so a comparison here would refuse every record. The prompts' qualification is
  LLM-005's other half and not in this card.
- **An update does not run this.** `tools/apply_update.sh` runs neither the pin steps nor the canary; a promoted
  pair is checked again at the next install (rule 5), not at the update.
- **Between a promotion and its canary the gateway routes the pair** (the canary itself needs that). What keeps a
  model that fails the canary from excluding anyone is the orchestrator's canary gate, which is shut until its own
  canary has passed on this pair.
- **A record is not signed on its own.** Its body hash is recomputable. Its integrity on the way to the box is the
  bundle's signature and the host tree's checksums at unpack; whoever can write `deploy/` on the box can also write
  the site override.

## Consequences

- With a shipped record for its weights, a box installed by the script ends with a champion pair that passed the
  canary on that box, and an orchestrator whose canary gate was run on that pair. Without one it ends as today, and the FAIL line names the missing record.
- No record exists yet: the first one is lane G's (real weights, the cloud card). Until it is committed under
  `deploy/qualification/`, every install ends with the FAIL line.
- No new setting, no limit, no new store. No new audit event: the promotion is the site override's
  `qualification` entry; the orchestrator's start canary after the restart is the one that is audited.

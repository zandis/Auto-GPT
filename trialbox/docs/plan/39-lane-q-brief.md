# Lane Q: qualify and model serving on an installed box (brief, 2026-11-15)

**Withdrawn on 2026-11-15 02:15 UTC; do not start this lane.** Lane D had already built five of the seven items
(blockers 1, 5, 6, 8, 9: #642, D-737 to D-739, the doctor FAILs). The two left (3: the v5 record, after lane G's
qualify run; 7: unattended approval, an owner decision) stay with lane D. Status: `40-status-2026-11-15.md`.

A new lane, carved out of lane D at the owner's request on 2026-11-15 so that lane D keeps CI, nightly, installer,
backup and supply chain, and lane Q takes the model-qualification path that R2 and R4 wait on. Read this page, then
`38-handover-2026-11-15.md` (the owner's 11 rules: they bind you exactly), `37-remaining-work-split.md`,
`36-how-sessions-talk.md` and `33-plan-v7.md` (plan v7.3), all on branch `train/17` until train 17 lands on master.

## Why this lane exists

Lane G's paid runs did not test the shipped box (no install, no shipped chat template, code before trains 15 to 17).
Its reset (accepted 2026-11-14) runs in this order: signed bundle, install with the real installer on the GPU VM,
G-1 on the shipped template, pair canary, `qualify` v5, promote; then accuracy (NEW-LLM-6), data paths and capacity.
Lane G found nine blockers to qualifying the v5 pair on an installed box. Two went to lane A2 (repin rulesets from
`judge_v4` to v5; N-12 evidence from SCREEN). The other seven were lane D's; **they are now lane Q's**:

| # | Card | What passes |
| --- | --- | --- |
| Q-1 | `qualify` without a git checkout | `trialbox eval qualify` runs on an installed box (no `.git`): the commit comes from the release manifest, not `git rev-parse`; the evidence files' HEAD check reads the same source |
| Q-2 | Box-side qualify wrapper | one box command supplies `--model-dir`, `--server-log` and `--audit-dir` from the box's own layout, so lane G runs one line on the installed box |
| Q-3 | v5 qualification record in the release | the release bundle carries the v5 pair's `passed` record (schema `schemas/qualification_record.schema.json`); the box refuses to promote a pair without one |
| Q-4 | `pin_model --resolve` | `tools/pin_model.py --resolve` turns a model name and revision into the digest pin the site file needs, offline-checkable |
| Q-5 | Unattended study approval | G-6 and G-9 can approve a study without a person clicking, only in a run profile that says so, refused on production |
| Q-6 | `/tokenize` through model-guard | the gateway's `/tokenize` passes model-guard (`services/model_guard/`) like every other model route, never around it |
| Q-7 | Expected doctor FAILs, stated | on a fresh cloud box, the `doctor` FAILs that are expected (no hospital CA, no mail, ...) are named in the run profile and the runbook, so lane G can tell an expected FAIL from a real one |

Order: Q-1 and Q-2 first (they unblock every later step of lane G's reset), then Q-3, Q-4, Q-6, Q-5, Q-7. Size each
S to M. Lane G's own blocker table (on the old inbox #593 and lane G's PR #585, 2026-11-14) is the source; read it
for the exact symptoms before each card.

## Where the code is

`tools/qualify.py`, `tools/b200_qualify.py`, `tools/pin_model.py`, `tools/trialbox/doctor.py`,
`deploy/platform/base/doctor.yaml`, `deploy/qualification/`, `eval/qualification/`, `services/model_guard/`,
`services/orchestrator/scenarios/approve.py`, `schemas/qualification_record.schema.json`,
`docs/runbook/11-qualify.md`; tests `tests/unit/test_qualify.py`, `test_pin_model.py`, `test_model_guard.py`,
`test_trialbox_doctor.py`, `test_doctor_serving.py`, `test_b200_qualify.py`, `test_champion_qualify.py`.

## File ownership

Lane Q owns the files listed above. Lane D keeps the installer (`deploy/install.sh`, `deploy/box-install.sh`),
images, CI workflows, backup, supply chain and the rest of `tools/trialbox/` except `doctor.py`'s expected-FAIL list.
A change in another lane's file is a small card asked for on the inbox, as rule 5 of page 37 says. The release
bundle (`tools/release.py`, `tools/make_bundle.sh`) stays lane D's; for Q-3, ask lane D on the inbox for the hook and
write only the record and its check.

## How lane Q works

- Decision numbers: **D-800 to D-819**.
- Card branches `agent/Q-<n>-<slug>` from master; one PR per card; run the whole unit suite once per card
  (`make test`, output to a file, then read it: never pipe a test into tail or head inside an `&&` chain).
- When a card is done: mark the PR ready for review, then post on the integrator inbox PR (named in
  `36-how-sessions-talk.md` on master; #639 as of 2026-11-15):
  `train-ready: #<PR> <full head sha> base <sha> [unblocks R2|R4]`, the whole-suite result line, gates, and anything
  the integrator must know. The integrator builds trains; never merge to master yourself.
- Tell lane G what landed by a comment on lane G's open PR (#585 or its newest); lane G is not reachable by
  `send_message`.
- No paid run: lane Q builds and tests with stubs; lane G runs on the GPU VM, on the owner's yes.
- Commit trailer exactly `Co-Authored-By: Claude <noreply@anthropic.com>` and `Claude-Session: <your session URL>`;
  no model names or IDs in commits, PR titles or bodies.

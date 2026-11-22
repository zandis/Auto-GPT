# rc1 checklist

**Reader:** the owner. **Kept by:** lane R. **Source:** the ten lines of the plan 10 review's section 3.4 (#1327),
under the owner's rulings of 2026-11-20 (comment 7052603473) and 2026-11-22 (comment 7077918101) on #639.
rc1 is a supervised demonstration on synthetic or public data.

**Last checked against master:** `225100f4` (train 122), 2026-11-22. **Ring 0** (the owner's ruling of 2026-11-22,
#639 7078327677) is done when all ten lines are ticked; the holders below are the integrator's schedule (7078338161).

**How a line is ticked.** A line is ticked only when its evidence exists on master or is a recorded run that names
its commit. An open pull request does not tick anything.

| # | Line | Evidence that ticks it | State on master `225100f4` | Owner |
| --- | --- | --- | --- | --- |
| 1 | Master is green on a train, and the two scheduled nightlies have been green three nights running | The CI run of a train's merge on master; three scheduled runs in a row of `trialbox-e2e.yml` (TrialBox nightly) and `trialbox-nightly-quality.yml`, each green | **Not met.** CI on master is green (run 45006358043, train 122). Both nightlies failed every scheduled night from 11-14 to 11-21 (last: 44940558518 and 44926835146). In the e2e nightly, `pure` and `public-e2e` pass; `compose`, the random-order shards and `perf-5k` fail (card 9i-1) | Lane R (9i-1, 9l-22; 9i-2 after lane H's nightlies table) |
| 2 | No path excludes a patient on a negated, family-history or suspected quote: one rule, one test that drives every scenario | One shared function for "what a note answer may do" (ruling 1 of 11-22), called by the cascade and the older evaluator; one test that runs every screening scenario through it with the review's four quotes | **Not met.** The D-985 check runs only in the cascade (`services/matching/cascade/engine.py:1229`). The older evaluator (`services/orchestrator/scenarios/evaluate.py`, `services/matching/decision.py`) does not call it (R22-16, High). An inclusion "not met" from notes still excludes on any quote (R22-17, High) | Lane E |
| 3 | The four shipped synthetic protocols compile, and every released line passes the strict rule or carries a labelled demonstration approval. A ruleset with demonstration approvals is refused outside DEV and TEST where it is loaded, not only where it is compiled | Gate 1's strict rule on master; a test that compiles the four protocols; a test that loads a ruleset with demonstration approvals with the environment set to VALIDATION, then to PRODUCTION, then unset, and sees each refused | **Not met.** Gate 1 is open (#1301). Nothing reads the demonstration label where a ruleset is published or loaded (R22-19). Lines that compile to the wrong population (R22-18, card 9c-6) are open | Lane G (gate 1), with lane E for R22-18 |
| 4 | Every count shown in the demonstration can be reproduced from a named lake generation and rule version | Gate 4's first slice (#1300) on master, or a recorded statement of the inputs of each demonstration run, with a test that re-runs one count from them | **Not met.** Gate 4 is open (#1300). Lake generations exist (`libs/tb_common/generation.py`); no demonstration run records the generation and rule version it used | Lane G |
| 5 | One table lists what rc1 refuses outside DEV and TEST (live patient lists, EDC writes from screening, patient mail and downloads, ad hoc support exports, unattended updates, key ceremonies), each with the test that proves the refusal | The table and its invariant test, which enumerates the six refusals from the table so a seventh cannot be left out; one test per refusal, with an unset environment counting as PRODUCTION | **Not met.** No refusal by environment exists for any of the six (R22-34). The only switch is the demonstration mode (`services/console/demo_guard.py`), which refuses uploads and pasted chart text | Lane R (waits for the owner's answer on which environments refuse) |
| 6 | A person who did not write it installs the bundle on a clean machine; the nightly backup runs; a restore from that backup is rehearsed; all three are recorded | Three records under `docs/validation/release-records/`, each naming the bundle and the machine; a test that runs every scheduled and runbook command with a bare interpreter | **Not met.** The nightly backup fails on every installed box (R22-31, F-32); its fix is on #1302, open. The restore and the drill do not run as the runbook types them (F-33, R22-32; fix on #1305, reviewed not ready). 44 of 71 host commands on the runbook's pages fail on a bare host (R22-48). The backup, wipe and restore rehearsal (#1079) is open | Lane H (#1302 on train 123; the runbook commands run bare); #1305 with the integrator; the install by a stranger, the backup and the rehearsed restore: the bench's MVP walk |
| 7 | The demonstration is walked from the console in English, Traditional Chinese and Japanese without a command line, and the walk is recorded | One walk record per language, naming the commit and the steps, with screenshots | **Not met.** No such record on master | Lane K |
| 8 | The accuracy sheet says what was measured, on which set, with which labels, on which path; it states no bound | One sheet under `docs/validation/`: per-criterion false-block rate and decided share per language on physician-checked sets, and the product-path figure of D-918 with its labels checked (ruling 1 of 11-22) | **Not met.** No sheet. The product-path figure has never been run | The researcher, with the bench's product-path run (#1332 proposes the bar) |
| 9 | The masking sheet says which identifier forms are masked in each language at what measured rate, and which are not | One sheet under `docs/validation/`: the forms probed per language, the measured rate, the forms known to pass | **Not met.** No sheet. Measured by the review: 16 of 76 probes missed (ja 8 of 30, zh-TW 2 of 24, en 6 of 22; R22-23). Log values that are not text are not scrubbed (R22-21) | Lane F, with the bench's encoding fuzz (7078315395) and lane H's log formatter (H-79) |
| 10 | The findings register holds every High of the independent reviews since 11-19, and no High on a path the demonstration uses is open | `tools.findings_register --check` with the reviews' `findings.json` files added; a list of the demonstration's paths, and no open High on them | **Not met.** The register's last change is 11-19 (`6ad56e80`). `--check --release` reports 252 findings that stop the release. The review of 11-22 (57 findings, 9 High) is not in it | Lane F |

**Count today:** 0 of 10 met.

## What would change a state

- Line 1 ticks after three green scheduled nights of both workflows, counted from the night after the fix.
- Lines 2, 3 and 4 tick when the gate or rule is merged with its cross-path test, not when its pull request opens.
- Line 6 needs three records. A green test alone does not tick it.

## History

| Date | Master | Met | Change |
| --- | --- | ---: | --- |
| 2026-11-22 | `225100f4` | 0 of 10 | First version |

# Deep review of 2026-11-13: architecture, the plan against the code, tests and CI

| Field | Value |
| --- | --- |
| Slug | `architecture` |
| Date | 2026-11-13 |
| Ordered by | Changfu Kuo (owner), through the cloud-run session (lane G) |
| Code read | `master` at `c7dcd5e7` (train 8); the 41 open pull requests by their changed files |
| Method | One lead and four sub-reviewers: the plan against the code, the architecture, test quality, and an adversarial reviewer who tried to refute the top findings. CI was measured from the GitHub Actions job records of 2026-11-12 and 2026-11-13. Machine: 4 cores, 16 GB, local PostgreSQL 16; no GPU and no Docker daemon. |
| Rules kept | Synthetic data only. No secret read. Nothing that costs money. No CI proof removed, no test weakened or skipped, no scan allow-list entry, no decision number taken. Files touched by an open lane pull request were not edited. |

**Terms.** *Verified* means the reviewer ran a command or a test and saw the result; *by reading* means file and
line only. *Fast tier* and *full tier* are the two sets of CI jobs of D-564. A *train* is the integrator's
`train/<n>` branch that merges several card heads and runs the full tier once. *Billed minute* is a started minute
of one job on one runner.

## 1. The reading in ten lines

1. **The safety core holds where it was fixed.** The judge-in-the-loop expected-failure table is empty and
   `tests/property` gives 47 passed, 0 expected failures (8 on 2026-11-12). D-333 (no cross-role fallback), D-640
   (no example ruleset outside DEV and TEST), D-522 (hold after restore) and ARCH-001 (job lease) are real in code.
2. **The CI cost is already cut.** The 30,000 minutes of 2026-11-12 came from the full tier on every card push
   before D-564; a draft push now costs about 12 billed minutes, a train about 186 (§5).
3. **Two nightly proofs never finished.** Branch coverage was cancelled at its limit on both scheduled runs; nobody
   was told. Fixed here (CI-01). The random-order run had the same fault and was fixed by D-560.
4. **A box stores patient spreadsheets and uploads in clear** although D-354 is counted as closing CR-041: nothing
   on a box runs `tools.keys seal-objects` (PT-01). Four services that share the volume could not read a sealed
   store today.
5. **A hand-written registry override can route an unqualified `champion` in PRODUCTION** (PT-03, reproduced).
6. **"Which checks gate a merge" has four answers in four documents**, and the required set leaves goldens,
   e2e-simple, property and security out (CI-05).
7. **The note mask failed open** when a box's site configuration could not be read: an unlabelled chart number
   stayed in the lake and the embed input. Fixed here (AR-01).
8. **Module boundaries keep eroding**: the orchestrator now imports the console's stores; no import-direction test
   exists (AR-04). `TB_ENV` is read by hand in 35 places with four rules (AR-02).
9. **Tests**: see §4 (test quality).
10. **The train loses most time on the slowest shard and on "one train a day"** (§5.4), not on CI cost.

## 2. Ranked list: most quality and speed for the least work

| Rank | Change | Gain | Work | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Shard the nightly branch coverage (CI-01) | a proof that has never run starts to run | S | D | **done here** |
| 2 | Note mask falls back to the contract pattern outside DEV/TEST (AR-01) | a patient-data leak path closed | S | C2 | **done here** |
| 3 | Image gates skip a master push a train proved (CI-02) | about 45 billed minutes per train | S | D | **done here** |
| 4 | Opt-out worker's scheduler gets the box's misfire grace (ARCH-003 remainder) | an opt-out is not delayed a whole interval under load | S | B2 | **done here** |
| 5 | Make the required checks one list, in one place, and require goldens, e2e-simple, property and security (CI-05, PT-04) | a red golden cannot be merged | S | owner, D | owner's decision |
| 6 | A notice on every red or cancelled nightly (CI-06) | the nightly is read on the day it fails | S | D | proposed |
| 7 | Seal the object store at install, a doctor check, mount the KEK where the volume is mounted (PT-01) | patient files encrypted at rest as D-354 says | M | C2, D | proposed |
| 8 | Gateway start re-reads the qualification record (PT-03) | D-358 holds against a hand edit | S | A2 | proposed |
| 9 | Refuse `TB_TODAY` outside DEV and TEST (PT-02) | the box's "today" cannot be frozen by a stray line | S | B2 | proposed (file in open PRs) |
| 10 | Balance unit shards by measured time (CI-03) | the train's critical path about 8 minutes shorter | S | D | proposed |
| 11 | `make train-check` generated from the `checks` job (CI-07) | fewer reds that reach CI | S | D | proposed (Makefile in #381) |
| 12 | Import-direction test with an allow-list of today's edges (AR-04) | stops new reverse edges | S | C2 | proposed |
| 13 | One `TB_ENV` reader; a test that forbids `os.environ.get("TB_ENV"` (AR-02) | removes a class of environment mix-ups | M | D, C2 | proposed |
| 14 | Changed files only for the data scan on a draft (CI-04) | about 30 % of a draft push's minutes | S | D | owner's decision |

Size: S under half a session-day, M one to two.

## 3. Findings: the plan, the decisions and the documents against the code

Severity: Critical (wrong exclusion or inclusion of a patient, data loss, a secret or patient data exposed, who may
act broken), High, Medium, Low. The adversarial reviewer's verdict is in the last column; where it proposed a lower
severity, the table uses the lower one and says so.

| Id | Sev. | Finding | Evidence | Root cause | Fix | Owner | Adversarial |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PT-01 | Medium | **D-354 is counted as closing CR-041, but no box is sealed.** Without `<objects>/.sealed.json` the object store is plain, so `attachments/`, `outputs/` (the `phi` sheets) and `twpas/` are written in clear. And `tb-secrets` is mounted only in the adapter and the orchestrator, while `objects-data` is also mounted by doc-parser, compiler, mail-gateway and console: sealing today would break those four. | Verified by search: `seal-objects` appears only in `libs/tb_common/objstore.py`, `tools/keys.py:16-17,59`, two tests and the decision; not in `deploy/install.sh`, `deploy/box-install.sh`, `deploy/hardening/seal_keys.sh` or `tools/trialbox/doctor.py`. `deploy/docker-compose.yml:204,224,247,293,309,360`. | The card built the store and the command; D-354 left the install step and the compose wiring as consequences; no card took them. | `seal_keys.sh` runs `tools.keys seal-objects` after the KEK exists; doctor `objects_sealed` FAILs in VALIDATION and PRODUCTION without it; mount the KEK where `objects-data` is mounted; mark CR-041 open until then. | C2, D | Confirmed; lowered from High: `check_host.sh:125-134` requires LUKS under Docker's data root and the backups are encrypted, so the exposure is on a running box. Partly recorded in D-354 and `2026-11-12-architecture/trust.md` F6; the claim "closes CR-041" is the new part. |
| PT-03 | Medium | **D-358 can be bypassed by a hand edit.** A site override with `status: champion` and a typed `qualification` block (record file missing, sha256 all zeros) resolves as champion in PRODUCTION. The comment at `services/registry/registry.py:264` says a hand edit cannot do this. | Verified twice: "PRODUCTION resolved: … champion \| record_id: typed-by-hand \| record file exists: False". `registry.py:171-174` checks the override's own fields only. | D-358 deferred the record re-read to T-677; T-677 (D-393) checked weights only. | Gateway start (or `Registry.load` in PRODUCTION) re-reads `qualification.record` with `tools.qualify.check_record`; doctor check `qualification_record`; correct the comment. The weights check still holds: unknown weights cannot route. | A2 | Confirmed |
| PT-02 | Low | **`TB_TODAY` is honoured in PRODUCTION** and switches off D-529's refusal of a future-dated night. `deploy/.env` reaches every service. | Verified: "PRODUCTION pinned today -> 2026-01-01". `services/orchestrator/app.py:63-71`, `services/lake/store.py:455`, `deploy/docker-compose.yml:31`. | The pin is declared "test stack" (`libs/tb_common/config.py:852`) but no reader checks the environment. | Read it only when `environment_name()` is DEV or TEST; a doctor FAIL when it is set elsewhere. Not edited here: both files are in open PRs (#472, #478, #482, #485 to #488, #492). | B2 | Confirmed; lowered from High: only `docker-compose.test.yml:45` sets it, and reports print the pin. |
| PT-05 | Medium | **The owner's answer "one lake source: omop" (plan v7 Q6) has no card in any wave.** `lake.source` defaults to `legacy`, `omop.dual_write` to off, and nothing in `deploy/` sets either, so OMOP, which `docs/ARCHITECTURE.md:97` calls the store of record, gets no data on an installed box. CI still runs e2e-simple and goldens on both sources. | Verified by reading code and config: `libs/tb_common/flags.py:113-115`, `deploy/docker-compose.yml:172`, `adapter/publish.py:302`. | The decision was recorded; the card was not. | A dated card: flip on the acceptance box (`tools.omop_parity flip`), then delete flatten and the `legacy` legs of e2e-simple and goldens (about 11 billed minutes a train). Until then ARCHITECTURE says the store of record is off. | B2, integrator | not tested |
| PT-04 | Medium | **Four documents name four sets of required merge checks**, one with job names (`lint`, `contracts`) that no longer exist. | By reading: `docs/runbook/03-accounts.md:32`; `.github/workflows/trialbox-ci.yml` header; `docs/decisions/D-578-ci-fewer-runner-minutes.md`; `docs/plan/35-handover-2026-11-13.md` §3. The live rule could not be read (HTTP 403). | Each change of the rule edited one document. | One list in the runbook, the others link to it; a test that the listed names are job names of `trialbox-ci.yml`. See CI-05 for which checks. | D, owner | Confirmed |
| PT-06 | Low | **The limits lint reads `services/` only.** 13 fixed limits in `libs/` are unlisted, among them `ServiceClient`'s 300 s default and the 10 s probe that decides "two models". | Verified: `tools/limits_lint.py` scan root. | The lint was written for services. | Scan `libs/` too; list the 13 with reasons. | B2 | not tested |
| PT-07 | Low | 58 rows in `docs/decisions/REGISTRY.md` say `reserved` though their decision file is on master. | Verified by command. | Lanes reserve, the file lands, nobody updates the row. | `tools.decisions_index --check` warns when a reserved number has a file. | integrator | not tested |
| PT-08 | Low | **Documents out of date**: ARCHITECTURE's service table lacks `audit-writer` and `model-guard` and describes the old TLS proxy and HAPI; runbook §3 lists jobs that D-578 folded; DEVELOPING describes the limits lint's old rule; the handover says train 6 is being built (master is at train 8); `D-475-ci-unit-shards.md:74` says the nightly runs the whole suite on one runner; the handover says the nightly starts at 19:22 (cron `17 19 * * *`). | By reading. | Documents are edited by the card that changes the code, and these cards did not. | Correct them; doclint cannot catch meaning. | D, integrator | – |

**Marked done and confirmed in the code:** PLAN-001 (no strict expected failure left; the property job runs 333
tests); T-652 and T-709 (one decision table, one status function, on both the v1 and cascade paths); D-333; D-640;
D-522; D-561 and D-562 (the installers enable the ops timer and the nightly signing of audit heads);
`tools/ci_proved_tree.py` (any doubt runs the full tier).

## 4. Findings: architecture

| Id | Sev. | Finding | Evidence | Fix | Owner | Adversarial |
| --- | --- | --- | --- | --- | --- | --- |
| AR-01 | Medium | **The note mask's chart-number rule failed open.** `phi_guard.site_mrn_regex()` answered `None` when the site configuration could not be read, which means "labelled chart numbers only": an unlabelled chart number stayed in the lake, the embed input and a revealed note. The lake, embed and adapter start without `settings.yaml`. The log scrubber already fell back to the contract default. | Verified: with `TB_ENV=PRODUCTION` and a missing settings file, the old code returns `None`, the new returns `^\d{8}$`. | **Fixed here**: outside DEV and TEST the note mask uses the contract's default pattern and logs the error type; `tests/unit/test_phi_guard_site_rule_fallback.py` (5 of 7 cases fail on the old code). | C2 | Confirmed, reachable narrowly (orchestrator and console fail loudly in that state). The fallback equals `settings.example.yaml:28`, so it masks nothing a default box does not already mask. |
| AR-02 | Low | **`TB_ENV` is read by hand in 35 places with four rules.** The one rule (`tb_common.config.environment_name`) says unset is PRODUCTION. Doctor defaults to `"DEV"` in 9 checks without upper-casing, so `note_block` with `TB_SCREEN_JUDGE=single` gives WARN, not FAIL, on an unset or lower-case `TB_ENV`. `adapter/pidmap.load_map_key` makes a new pid-map key when `TB_ENV` is unset (documented for demos). | Verified: `doctor.py:201,213,328,401,431,479,560,571,622`; `pidmap.py:153`. | All reads through `environment_name()`; a test forbidding `.get("TB_ENV"`; demos set `TB_ENV=DEV` explicitly. Not edited here: `doctor.py` is in open PR #490. | D, C2 | Confirmed; lowered: `install.sh:279-280` always writes `TB_ENV=PRODUCTION`. |
| AR-03 | Low | **The orchestrator's `verifier_client()` can call `LLM_VERIFIER_BASE_URL` directly in PRODUCTION**, past the gateway rule T-604 enforces in `LlmClient.from_config`. | Verified: `services/orchestrator/app.py:88-91`, `libs/tb_llm/llm.py:246`. | No direct client in PRODUCTION; delete the direct path (ARCH-016). | A2 | Confirmed; Low on compose (no network route; doctor FAILs it under `both_agree`). Remaining hole: `TB_NOTE_BLOCK=never` with a direct verifier passes doctor. |
| AR-04 | Low | **Package dependency direction has no rule, and it is getting worse.** The orchestrator imports the console's break-glass and team stores (`orchestrator/grants.py:44,75,87`); the console imports `tools` in 5 places; `tb_common` and `tb_llm` import each other; library packages import back into the orchestrator. The console's database role reaches 23 schemas. | Verified by an import graph of `libs/` and `services/`. | A test with today's edges as an allow-list, so a new edge fails; move the shared stores into `tb_common`. | C2 | Confirmed; lowered: the grants are deliberate and `rc_sim` is imported only in DEV and TEST. |
| AR-05 | Low | **A job lease is lost silently when its database session ends**; a second orchestrator then took the same job in a throwaway test. | Verified on a throwaway cluster. | The worker checks its lease before each step; or a PostgreSQL-backed job library after go-live (AR-12). | B2 | not tested |
| AR-06 | Medium | **The site-key and chart-number-rule check against the pid map runs only on the adapter's night path**; the orchestrator's chart-number lookups (CASE, opt-out by chart number, registry rows) and site set-up skip it. Already in the handover's §6 as a finding; this names the call sites. | By reading. | One door: every pseudonym through the pid map's check. | C2, E | not tested |
| AR-07 | Low | **Two audit write paths** (services through the journal, host tools to the chain directly, held together by one file lock); the lake has no audit settings in compose, so `lake.rebuild.source` is never written on a box. | By reading. | Host tools write through the journal; audit settings for the lake. | C2 | not tested |
| AR-08 | Low | **Declared and coded `TB_*` defaults differ in 36 places**; product ones: `TB_LAKE_EMBEDDER` (the adapter's lake build defaults to the test `hash` embedder) and `TB_DATA_CLASS` (`D0`). | Verified by script over `DECLARED`. | A test that each reader's default equals the declared default. | D | not tested |
| AR-09 | Low | **Needless weight** (§7). | Verified by import graph. | Delete. | D | – |
| AR-10 | Low | **Production screening falls back to `HashEmbedder`, a test embedder, to rank excerpts.** It cannot exclude anyone; it lowers recall silently. | By reading. | Refuse the fallback in PRODUCTION; say it on the run page. | A2 | – |
| AR-11 | Low | 188 broad `except` handlers that do not re-raise. Most are justified. Three fail open or hide a record: AR-01 (fixed), the lake source audit, `console/studies.py:50`. None was found on exclusion, opt-out, pid-map or EDC writes. | Verified by AST scan. | Fix the two left. | C2 | – |
| ARCH-003 | Low | **The opt-out worker's scheduler had APScheduler's one-second misfire grace**, unlike the other two schedulers. A late tick was dropped and an opt-out waited a whole interval more. | Verified: the old code gives `misfire_grace_time == 1`. | **Fixed here**: `SCHEDULER_JOB_DEFAULTS`; `tests/unit/test_optout_worker_misfire.py`. | B2 | – |

Earlier findings whose status changed: **ARCH-001 closed** (lease, attempt count, `TB_JOB_MAX_RESTARTS`; 35 tests
passed), **ARCH-004 closed** (stale "durable steps, outbox" text left in `deploy/docker/db-init/10-trialbox-wf.sh:3`
and `deploy/topology_a/podman-compose.yml:1`), **ARCH-021 closed**. **ARCH-002 half closed**: the 409 is followed;
an adapter restart still loses the run (`adapter/app.py:43-46`); the night's `dataops.batch` row records each step
but nothing reads it. **ARCH-003 partly**: three schedulers remain. **ARCH-005 worse** (AR-04). ARCH-008, -009,
-012, -013, -014, -018 and -020 unchanged; `DECLARED` grew from 366 to 413 settings. ENG-011 is now fixed; ENG-009 is
still open (`lake/app.py:96`, `adapter/app.py:106,200` echo raw error text).

## 5. CI and the merge train

### 5.1 What a run costs today (measured)

Read from the GitHub Actions job records of 2026-11-12 and 2026-11-13 (job start and end times; a billed minute is a
started minute per job).

| Run | Jobs | Billed minutes (about) | Longest job (the wall time) |
| --- | --- | --- | --- |
| A draft card's push (fast tier), e.g. run 43456028050 | changes, checks, cross-card, differential, powershell, data-scan | 12 | data-scan 3.6 min |
| A train (full tier), train 8, run 43444135883 | 22 jobs | 186 | unit-shard 3/6, 28.2 min |
| The image gates on that train, run 43444135840 | amd64 and arm64 legs | about 45 | 23 min |
| The push of the train's merge commit to master, CI (proved, fast tier), run 43449399166 | 6 jobs | 12 | data-scan 3.7 min |
| The same push, image gates, run 43449399182 | amd64 and arm64 legs | about 45 | 26 min |
| The nightly quality, run 43263190179 | mutation × 3, branch coverage | about 500 | mutation (engine), 209 min |

**Where the 30,000 minutes of 2026-11-12 came from.** Before D-564 (tiers) and D-578 landed in the afternoon of
2026-11-12, every push to a card's pull request ran the full tier (about 186 minutes) and the image gates. Between
15:39 and 18:32 UTC that day the CI workflow started 100 runs on pull requests; 54 were cancelled by a newer push of
the same pull request after minutes of work, and runs waited up to 150 minutes for a runner. Today a draft push costs
about 12 minutes. **The big cut is already made; do not undo it.** On 2026-11-13 between 08:00 and 16:00 UTC there
were 49 CI runs (two trains, three master pushes, the rest drafts): roughly 2 × 186 + 47 × 12 ≈ 940 billed minutes, plus
about 180 for image gates.

### 5.2 Findings

| Id | Severity | Finding | Evidence | Fix | Owner |
| --- | --- | --- | --- | --- | --- |
| CI-01 | High | **The nightly branch coverage never ran to its end.** The scheduled run of 2026-11-12 was cancelled at the job's 60-minute limit, and so was the whole run of 2026-11-11 (run 43062540368): the whole unit suite on one runner under the classic tracer. The ratchet step was skipped, so the branch baseline has never been checked. The random-order run had the same fault and was moved to the shards (D-560); branch coverage was not. | VERIFIED: run 43263190179, job 131339649001, step "pytest -n auto with branch coverage" cancelled at 18:27:29 after 59.6 min; `trialbox-nightly-quality.yml` `branch-coverage` `timeout-minutes: 60`. Tracer cost measured here: 40.6 s against 17.8 s on four safety test files (2.2 times). | **Fixed in this PR**: the job runs in the six shards of `unit-shard`, limit 90 (40 × 2.2, rounded up), and `branch-coverage-ratchet` combines the shards and is red when a shard did not pass. `tests/unit/test_nightly_quality_shards.py` (three checks; each fails on the old workflow). | D (fixed here) |
| CI-02 | Medium | **The image gates build twice per train.** The train's run builds and scans both legs; the push of the merge commit to master builds and scans the same tree again. `tools/ci_proved_tree.py` already spares the CI workflow this; the image workflow did not use it. | VERIFIED: train 8 image gates run 43444135840 (head `015fc5a`) and master push run 43449399182 (`c7dcd5e`, whose tree is the train head's), 23 and 26 minutes, two legs each. | **Fixed in this PR**: a `proved` job on a push to master (`tools/ci_proved_tree.py --image-legs`, which also needs a passed image leg on the train's head); the images build unless it says a definite "true". A tag, a train, the weekly run and a run by hand always build. Tests in `tests/unit/test_ci_tiers.py` and `test_ci_proved_tree.py`. | D (fixed here) |
| CI-03 | Medium | **Hash sharding leaves the unit shards unbalanced: the train waits for the slowest.** Shards took 23.3, 22.3, 28.2, 13.1, 14.6 and 13.7 minutes on train 8. The mean is 19.2. | VERIFIED: run 43444135883 job times. `tools/test_shard.py:55` (`sha256(path) mod N`). | Assign files to shards by their measured time (longest first into the lightest shard), from a committed file of per-file seconds that the `unit` job writes from the shards' `--durations`; a file not in it falls back to the hash. Same billed minutes; the train's critical path drops by about 8 minutes. `tools.test_shard check` still proves every test ran once. | D |
| CI-04 | Medium | **The data scan is the dearest job of the fast tier and rescans 3,310 unchanged files on every draft push.** 3.4 to 3.7 minutes per push, about 30 % of a draft's minutes. | VERIFIED: 3.4 min in runs 43456028050 and 43449399166; 2 min 21 s here for 3,310 files (`data_scan: clean (3310 file(s), 10 patterns)`). | On a draft: scan the files the pull request changes (`git diff --name-only base...head`; the tool already takes paths) plus the allow-list and pattern files. On a train, master and the nightly: the whole tree, as now. No proof is removed: every merged tree is still scanned whole. **Owner's decision** (it changes when a required check proves what). | D, owner |
| CI-05 | Medium | **Branch protection requires 4 checks; the train's other proofs do not block a merge.** `unit`, `data-scan`, `cross-card`, `checks` are required. `goldens`, `e2e-simple`, `property`, `security`, `standards` and `demo-boot` are not: a train with a red golden can be merged by the button. The integrator's rule ("merge when green") is the only guard. | By reading: handover `35-…` §3 point 6; `trialbox-ci.yml` header says goldens and e2e-simple are required (stale). | Require `goldens`, `goldens (omop)`, `e2e-simple`, `e2e-simple (omop)`, `property`, `security`. They are skipped on drafts, and a skipped required check does not block, so cards are not held. **Owner's decision** (branch protection is his). | owner |
| CI-06 | Medium | **The nightly results reach nobody.** Every scheduled e2e run since 2026-11-10 is red; the nightly quality run was cancelled on both nights; the handover says nobody read them until 2026-11-13. A scheduled run notifies only the person who last edited its cron line. | VERIFIED: runs 42884579222, 43086595086, 43289457082 (failure), 43062540368, 43263190179 (cancelled). | A last job in each nightly workflow, `if: failure() || cancelled()`, that opens or comments on one pinned issue ("nightly red: <job> <run url>") with `issues: write`; lane D's daily item then starts from that issue. Cheap and needs no new service. | D |
| CI-07 | Low | **The local pre-train set is a hand-kept list and drifts from CI.** `make ci` lacks `tools.limits_lint`, `cross-card` and `differential`, all of which CI runs on every push. The handover records that each check missing from the local set let a red reach CI on 2026-11-12. | By reading: `Makefile:203-224` against `trialbox-ci.yml` `checks` steps and `tests/unit/test_ci_tiers.py` `FOLDED`. | One target `make train-check` that runs exactly the steps of `checks` (generated from `FOLDED` or tested against it), `cross-card`, the whole unit suite, goldens, `test_e2e_simple.py` and the demo walks, writing each output to a file. A test that every `checks` step is in it. Not done here: the Makefile is in open PR #381. | D |
| CI-08 | Low | **Two documents say something the workflows do not.** The header of `trialbox-ci.yml` says branch protection requires `unit, checks, goldens, data-scan and e2e-simple`; it requires `unit, data-scan, cross-card, checks`. The handover says the nightly starts at 19:22 UTC; the cron is `17 19 * * *` (GitHub starts it a few minutes late). `DEVELOPING.md` says `unit` on a draft "shows as skipped, never as success": a skipped required check counts as passing for branch protection; a draft simply cannot be merged. | By reading. | Correct the three texts. | D, integrator |

### 5.3 What each tier proves

| Tier | Runs on | Proves | Does not prove |
| --- | --- | --- | --- |
| Fast (12 min) | every push to a pull request | lint, types, docs, decisions, limits, contracts, rulesets, shell; no identifier in the tree; the cross-card tests; the Windows scripts; the three-engine boundary table | any unit test outside the cross-card list; goldens; the end-to-end walk |
| Full (186 min) | a train, master (unless proved), by hand | the whole unit suite once, coverage ratchet, goldens on both lake sources, the e2e walk on both, property, security scan, standards, the demo image boots and every walk passes | a compose stack, backup, update, scale (the nightly's) |
| Nightly | 19:17 UTC | compose stack, backup and update drills, public e2e, random order with the network off, 50,000-patient scale, mutation score, branch coverage | |

The fast tier tests a pull request merged into master **as master was at the push** (GitHub's `pull_request` event
checks out the merge ref). A card's green fast tier is therefore stale once master moves; this is harmless because
the train's full tier is the proof, but it is a reason not to rerun a card's fast tier before a train.

### 5.4 The merge train: where time is lost

| Where | What happens | Change |
| --- | --- | --- |
| One train a day, closed when opened | A card that misses the train waits up to a day, though its fast tier is green. | Two fixed train times a day (for example 03:00 and 13:00 UTC). The full tier costs the same per train; more trains carry fewer cards each and a red drops fewer. |
| A card head that is behind master | The integrator merges heads with `git merge --no-ff`; a head behind master merges cleanly unless a file conflicts. Passing a card over because it is behind is not needed: the train's run tests the merged tree. Only a textual conflict needs the lane. | Write it in the train rules: "behind master" is not a reason to skip a head; a conflict is, and goes back to the lane at once with the file names. Keep a queue (one file or a label `train-ready`) so a passed-over card is first in the next train. |
| The local set before the train | Hand-kept, drifts (CI-07). | `make train-check` (CI-07). |
| The slowest shard | 28 of the train's 29 minutes are the slowest shard (CI-03). | Balance by time (CI-03). |
| A red in one card holds the train | The train is rebuilt without the card and the full tier reruns (186 minutes). | Keep the rule; the cross-card list and `make train-check` catch most reds before the run. |
| GitHub merge queue | By the reviewer's knowledge of GitHub (not checked here), merge queues need a repository owned by an organisation; this one is owned by a user account. | none |

## 6. Test quality

The test-quality reviewer's results are added in the second push of this pull request.

## 7. What is good, and where the project carries needless weight

**Keep as it is:**

- `tb_common` imports no service; one configuration reader; one pseudonym function; one door for chart numbers in
  the orchestrator.
- The judge-in-the-loop suite and the empty strict expected-failure table.
- The registry's check of model weights against the committed expected manifest.
- The fail-closed restore hold, study-state hold, grant and delegation-log reads; the opt-out worker's read-back.
- The site time zone rule that refuses to fall back to UTC.
- `tools/ci_proved_tree.py` and the D-564 tiers: they are the reason CI now costs a fraction of 2026-11-12.
- `tools.test_shard check`: every collected test ran exactly once.

**Delete or move (each verified by an import graph or a search):**

- Undeployed HTTP apps: `services/guard/app.py`, `services/tracestore/app.py`.
- No importer outside tests: `phenotypes.py`, `omop/catalogue_load.py`, `registry_match/sync_prompts.py`,
  `libs/tb_testkit/req.py`.
- About 3,200 lines used only by tools: `deliverables`, `opportunity_hub`, `registry_match`.
- The second screening engine behind `TB_SCREEN_PIPELINE=v1` and `TB_SCREEN_ENGINE`.
- The direct verifier path (`LLM_VERIFIER_BASE_URL`, AR-03).
- `site_params.yaml` at the root, `deploy/topology_a`, `pgbackrest`, the second `settings.example.yaml`, which plan v7
  already lists as dropped.
- `tools/` in the service image: four functions are used by the console; move them under `services/console` or
  `tb_common`.
- The `legacy` legs of e2e-simple and goldens, once Q6's flip is done (PT-05).
- After go-live: the home-grown job runner, for a PostgreSQL-backed job library (DBOS or Procrastinate), which would
  remove AR-05, the open half of ARCH-002 and one scheduler together (AR-12).

## 8. Fixes made in this pull request

Each has a test that fails on `master` and passes here; none weakens or skips a test or removes a CI proof.

| Commit | Finding | Change | Test |
| --- | --- | --- | --- |
| 1 | CI-01 | Nightly branch coverage in the six shards of `unit-shard`, limit 90, a combine job before the ratchet | `tests/unit/test_nightly_quality_shards.py` (three checks fail on the old workflow) |
| 2, 5 | CI-02 | Image gates: a `proved` job on a push to master; `tools/ci_proved_tree.py --image-legs` also needs a passed image leg (the adversarial reviewer found that the hadolint job named `images` met the rule alone) | `tests/unit/test_ci_tiers.py`, `tests/unit/test_ci_proved_tree.py` |
| 3 | AR-01 | Note mask falls back to the contract pattern outside DEV and TEST | `tests/unit/test_phi_guard_site_rule_fallback.py` |
| 4 | ARCH-003 | Opt-out worker's scheduler with `SCHEDULER_JOB_DEFAULTS` | `tests/unit/test_optout_worker_misfire.py` |

The CI fixes prove themselves only on GitHub: the image-gate change at the next train's master push, the branch
coverage at the next scheduled nightly quality run (00:47 Taipei). Lane D reads both.

## 9. For the owner's decision

| Question | Recommendation |
| --- | --- |
| Which checks does branch protection require? (CI-05, PT-04) | Add `goldens`, `goldens (omop)`, `e2e-simple`, `e2e-simple (omop)`, `property`, `security`. They are skipped on drafts, so cards are not held. |
| May a draft's data scan read only the files the pull request changes? (CI-04) | Yes; every train, master push and nightly still scans the whole tree. |
| Two trains a day instead of one? (§5.4) | Yes, at fixed times; the cost per train is the same. |
| Is CR-041 open until a box is sealed at install? (PT-01) | Yes. |
| A dated card for Q6 (one lake source)? (PT-05) | Yes, owner B2, with the deletion of the legacy legs. |

## 10. What was not run

No GPU, no Docker daemon: no image built, no compose stack, no installer. The CI fixes were checked by their unit
tests and by reading; their first real run is on GitHub. The branch-protection rule could not be read (HTTP 403).
The CQL compiler tests fail on this machine for want of the translator jars (not related to this change).

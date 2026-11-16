# PoC-1 evidence: the box on one GPU VM, 2026-11-15 and 16

This page is lane G's evidence for PoC-1. Every figure names its commit. The two columns are never mixed:

- **Frozen:** `1157c9bfa514e71cdd4f6e430250665c0c9481a2`, lane G's run tooling with master train 28 (`0d9ebeb3`) merged.
- **Master:** `b266f9b7f45194afb86b217619f0da78156f0eaf`, lane G's run tooling with master train 37 (`2d354036`) merged.

The machine-readable results are in [poc-1-2026-11-15/](poc-1-2026-11-15/). They hold counts only. The raw answers, which are both models' outputs per call, stay in the bucket and in the operator's run folder and are never committed. The VM hand-over is [docs/handover/gpu-vm-handover-2026-11-16.md](../../handover/gpu-vm-handover-2026-11-16.md).

## What was run, on what, and by which route

**Hardware.**

- One Google Cloud VM, `tb-gpu-sim`, in `asia-east1-a`: `g4-standard-48`, spot, US$2.74 an hour.
- One NVIDIA RTX PRO 6000 (96 GB), driver 580.
- Ubuntu 24.04. Docker 29.9.3 with overlay2 and the classic image store.
- A 400 GiB hyperdisk-balanced boot disk.

**Mode.** A VALIDATION box (`TB_ENV=VALIDATION`) on public and synthetic data only. The site is the synthetic one in `deploy/gcp/validation-site-answers.yaml`.

**Route.**

1. The commit's images were built on the VM from its own checkout: `make images` and the demo image.
2. Its host tree became the box's release.
3. The stack came up by the **direct route**, which is the product's own commands in the installer's order:
   - `trialbox secrets init`;
   - `pin_model --install` as root;
   - `adapter keys-init`;
   - the database and `trialbox db-up`;
   - `docker compose up --wait`;
   - `trialbox doctor --serving`.
4. The accuracy sets came in as mail through the box's own intake (FEAS, then APPROVE by the site's reviewer, then SCREEN). They were scored outside the box by ids only.

**Not exercised in either column:**
- **The bundle.** One validation bundle was built from an earlier commit (`val-ac36aa21fdc1`, 29.6 GB) and signed with a throwaway key made on the VM. Its gates ran in report mode. It is not a release, and neither column used it.
- **The vendor-key signature.**
- **Key sealing.** The site keys were made but not sealed (the owner's ruling for a public-data PoC box; F9).
- **The installer.** `install.sh --answers` stopped twice (F9, F10). That route was closed, and the direct route was used from then on.

**Serving.** Both columns ran the shipped serving settings (`--max-num-seqs 16`, `--enforce-eager`). The owner's tuned-serving exception was cancelled before any tuned job ran.

## The table

How to read a row:
- **What it measures.**
  - "The compiler" means the compile decided the figure.
  - "The judge" is the criterion level: each gold criterion is matched to the compiled criterion. A "fail" on one the gold says is met is a wrong block; a "fail" on one the gold says is not met is a catch.
  - "The product's rule" is the pair level: the patient's tier, which is excluded, listed or open.
- **may_block.** A note-read "not met" excludes only when note_block is on. That needs three things (lane A2, #639, 01:13 UTC):
  - `TB_NOTE_BLOCK=both_agree`;
  - a second, different verifier;
  - the box's own canary gate holding a passing record under 36 hours old.
- **Intervals.** Every rate has an exact 95 % interval (Clopper-Pearson) and counts only the rows the box answered.
- **Partial sets** say "partial: X of Y".

| Set | What it measures | Frozen, 1157c9bf | Master, b266f9b7 (train 37) |
| --- | --- | --- | --- |
| tcga | the judge (criterion level) | 5 of 10 protocols, 500 patients each, all 2,500 rows answered. Wrongly blocked **1 of 250** (0.4 %, 0.01 to 2.2). Caught **1,867 of 2,250** (83.0 %, 81.4 to 84.5). Left open 401 of 2,500 | BRCA only (1 of 10, as the scope says), 500 rows answered, two jobs on one compile. Gate open: wrongly blocked **0 of 50** (0 to 7.1), caught **384 of 450** (85.3 %, 81.7 to 88.5), left open 68. Gate shut: 0 of 50, 377 of 450 (83.8 %, 80.0 to 87.1), 75 open. The 7 extra catches are the run-to-run difference of the pair, not the gate (the gate acts at pair level) |
| tcga | the product's rule (pair level) | Excluded **0 of 2,250** that should be: every "not met" went to review. Eligible lost 0 of 250 (0 to 1.5). note_block off: lane A2's rule (no passing box-gate canary record); `judging.may_block` was not kept (F32) | **With the gate open** (`may_block` true, `note_block_code` "ok", both models must say fail): excluded caught **384 of 450** (85.3 %, 81.7 to 88.5); eligible lost **0 of 50** (0 to 7.1); wrong among the box's exclusions **0 of 384** (0 to 0.96); left open 68 of 500. **Before the gate opened** (`may_block` false, `note_block_code` "failed": the box's start-up canary had met model servers not yet up): excluded 0 of 450, every "not met" to review |
| jmed | the compiler, not the judge | 2 protocols, 297 patients each, 594 rows, 0 judge calls. Wrongly excluded **231 of 355** (65.1 %, 59.9 to 70.0). Caught 66 of 239 (27.6 %, 22.1 to 33.8). Cause: a negated exclusion with no coded diagnoses (C1) | 2 protocols, 297 patients each, all 594 rows answered. Wrongly excluded **1 of 355** (0.28 %, 0.01 to 1.56). Caught **33 of 239** (13.8 %, 9.7 to 18.8). Left open 417 of 594. The diabetes exclusion was rewritten from its negated form (`negated_logic_rewritten`, D-796) and compiled as mixed, so it is read from the notes. The hypertension exclusion stayed structured and "needs review". Pair level: `may_block` false, `note_block_code` "failed" (see B2) |
| sigir | the judge (criterion level) | **Partial: 109 rows answered; 21 of 104 protocols screened, 34 started in the budget.** Wrongly blocked 0 of 103 (0 to 3.5). Caught 3 of 6 (50 %, 11.8 to 88.2). Re-run pending on the compiler fixes | not run: deferred to the integrator's pass after lane A2's compiler fixes |
| sigir | the product's rule (pair level) | Partial: 9 of 46 pairs answered. Eligible lost 1 of 9 (11.1 %, 0.3 to 48.2) | not run (deferred) |
| trec2023 | the compiler and the coded data (pair level; no criterion gold) | **Partial: 81 of 500 pairs answered; 17 of 297 protocols screened, 46 started in the budget.** Eligible lost 10 of 41 (24.4 %, 12.4 to 40.3). Excluded caught 6 of 40 (15.0 %, 5.7 to 29.8). Re-run pending on the compiler fixes | not run (deferred) |
| chia | the compiler (compile level) | Partial: 48 of 99 protocols started, 35 compiled, 13 failed; 395 criteria. Class agrees with the annotators' entity kinds on 219 of 395 (55.4 %, 50.4 to 60.4). A compiler that no longer ships (D-796, trains 32 to 37) | not run (deferred) |
| jrct, tfda | the compiler (compile level) | not run on 1157c9bf (re-planned onto master) | not run (deferred) |

Pair agreement and left open, frozen column:

| Set | Judge items seen by both models | Disagreed | Judge only (it said "unknown", so no second opinion) | Left open |
| --- | --- | --- | --- | --- |
| tcga | 2,327 | 11 (0.5 %) | 183 | 401 of 2,500 rows |
| sigir | 16 | 3 | 62 | 77 "unknown" and 81 "for a person" verdicts |
| trec2023 | 80 | 1 | 357 | 65 of 500 pairs |
| jmed | 0 | 0 | 0 | 297 of 594 rows (the hypertension protocol: "unknown") |

Master column (b266f9b7): tcga BRCA, gate open: 467 items seen by both models, 3 disagreed, 35 judge only, 68 of 500 rows left open; gate shut: 469 items seen by both models, 4 disagreed, 31 judge only, 75 of 500 rows left open. jmed 111 seen by both, 0 disagreed, 157 judge only, 417 of 594 rows left open.

### Notes per set

**tcga** (frozen column):
- The data are 500 public pathology reports. Each protocol is "histologically confirmed <cancer type>", screened against all 500 patients.
- The criterion compiled as mixed with an unmapped concept, so the cascade read the notes. Each job made about 1,000 model calls.
- These jobs ran with the embed service at 16 GB (F27). At the 4 GB default the service died mid-SCREEN on both protocols tried.

**jmed** (frozen column), never to be shown as screening accuracy:
- The diabetes exclusion compiled as a structured atom "none of diabetes". The prompt forbids that, and the compiler did not flag it.
- With no coded diagnoses on the public site, that atom was true for all 297 patients.
- The hypertension exclusion mapped only "for review", so all 297 of its answers were "unknown".

**trec2023** (frozen column):
- All 16 exclusions came from coded criteria.
- These patients have no age, no sex and no coded rows; their facts are a questionnaire written into a note.
- The 10 wrong ones are structured inclusions on a medication or observation code, which a site with no coded medications or observations reads as "not met", plus one exclusion whose duration compiled as -90 days.
- Each is listed on #649 (part A2). They are the box's own answers, not the scorer's.

**sigir and trec2023 failures** (frozen column), by class, in the red of 01:53:
- (A) the compile gave only "for a person" criteria;
- (B) ir_extract refused by the gateway as `upstream_failed`;
- (C) criteria-compiler HTTP 500;
- (D) criteria count not equal to lines;
- (E) the CQL translator's logger line taken as its output.

Class B protocols are the longest (trec2023 median 3,254 characters against 1,484 for those that passed). Class C protocols are short.

## Speed: one 500-patient SCREEN job

| | Frozen, 1157c9bf | Master, b266f9b7 |
| --- | --- | --- |
| Wall time (tcga, 500 patients) | median 1,275 s over 5 jobs (1,224 to 1,352) | **325 s** and **317 s** (BRCA, two jobs on the same compile; frozen BRCA: 1,352 s) |
| Where the time went | about 16 min of CPU embedding (the note stage embeds every window sentence before any judge call), then about 1,000 judge-pair calls | S0 and S1: 500 patients in scope. S2: no lexicon hit (500 zero-hit). S2b: 0 embed batches. S3: the judge on 500 pairs. S4: the second opinion on 48. 1,014 model calls; 1.50 M tokens in, 117 k out |
| Windows that fit the excerpt budget, so S2b was skipped (D-904) | not measured (D-904 is not in 1157c9bf) | **500 of 500** windows fit, so S2b embedded nothing (0 embed batches) |
| Embed service | 16 GB limit (F27 work-around); peak sampled 2.8 GB; not killed | at master's 6 GB limit: peak **908 MiB** (162 samples), not killed, 0 restarts. (The first job ran with a 16 GB limit left in deploy/.env, F37: peak 1.27 GiB) |
| Judge calls and latency | 969 calls in the BRCA job: median 3.45 s, p95 5.8 s, max 31.2 s; none over 60 s | 972 calls in the job's audit: median 3.41 s, p95 5.69 s, max 101.15 s (one call over 60 s); about 190 calls a minute |

## G-1, the canary and qualify

| | Frozen, 1157c9bf | Master, b266f9b7 |
| --- | --- | --- |
| G-1 identity: the served template is the pinned one (`ae53464b`); both model servers on the images.lock digest (`sha256:befccf0e...`); the weights match their pins; the served prompts named | PASS | PASS |
| G-1 tokens: the server's ids against the offline tokenizer's, 20 prompts, 2,268 tokens | differ on the 10 prompts with a system message: one extra token at position 22 (D-880: the server rendered a system message's content as a list of parts, which adds one trailing space; fixed in train 30) | **equal on all 20 prompts**, so there is no differing position to show (D-880 confirmed) |
| The pair canary, host selftest (54 cases) | PASS: the judge had 53 right, the second opinion 48; the pair had 52 right, 2 left to a person, 0 decided wrong | PASS |
| The pair canary through the box's own gate (B2) | not run (F32) | **Gate open:** the orchestrator, restarted once the model servers answered, ran its own pair canary at start, and the next SCREEN recorded `may_block` true, `note_block_code` "ok". Before that, the gate held a failed record from the first start ("gateway refused judge: upstream_down", 0 of 54 answered). The admin "Run now" (`POST /models/canary`) refused lane G's tokens (HTTP 403, F35), and `GET /models` needs a token, so lane G's step kept no record of its own |
| `qualify --box` | not run in full; a 300 s probe passed pin, licence, schema, longest_prompt, log_marker and canary, and failed serving_record | 30-minute time box (`TB_HOST_PROFILE=poc`, image digest, host GPU facts). **pin failed**, but by lane G's fault F36: an earlier run's `eval/` was mounted over the image's. **serving_record passed** (D-881, D-889). licence, schema, longest_prompt, log_marker and canary passed. **pair_gate not finished in the box:** 1,468 of 2,986 items at 1,500 s. determinism, planted defects, injection and the rest were not reached. The three TREC 2021/22 evidence steps are not run in this phase (D-826) |

The served prompts on both columns are judge@5, ir_extract@3 and concept_map@2, plus 10 others at their pinned versions; their hashes are in `poc-1-2026-11-15/identity.json`.

**The chat rendering each column served.**
- **Frozen:** the pinned template, with one extra space token after a system message (D-880's fault).
- **Master:** the pinned template, rendered as the offline tokenizer renders it (`--chat-template-content-format=string`).

## What broke

### Product faults

| Fault | Seen | Fix (decision, train) or open |
| --- | --- | --- |
| G-1: one extra token after a system message | frozen | D-880, train 30 |
| A negated exclusion atom, and an empty code list, read as true (jmed: 297 of 297 excluded) | frozen | D-796, train 32 |
| The embed service died mid-SCREEN at 4 GB: one model load per concurrent first request; batch 64 with no length cap | frozen | D-900 and D-890 (6 GB default), train 33 |
| SCREEN failed instead of waiting when the embed service went away | frozen | D-902, train 34 |
| Qualify needs files the image lacks; it names no code outside a signed tree; no GPU facts in its container (serving_record) | frozen | D-838 and D-881, train 30; D-889, train 32 |
| The services mount `settings.example.yaml` on a start path other than `install.sh` | frozen | D-888, train 35 |
| S2b embeds every window even when the window fits | frozen | D-904, train 36 |
| Generic diabetes mellitus and the C50 breast-cancer synonyms do not map | frozen | D-906, train 37 |
| FEAS fails on a ruleset with nothing to count | frozen | D-901, train 33 |
| The compiler's class for the same text is not stable (structured in one compile, mixed in another) | frozen | open (red, 2026-11-15) |
| Compile failures in five classes (A to E above) | frozen | open (red of 01:53; lane A2's six compiler cards) |
| Structured inclusions on medication or observation codes read "not met" on a site with no coded rows; ClinicalTrials.gov's age and sex fields folded into medication atoms; a duration compiled as -90 days | frozen | open (part A2's post; lane A2's queue) |
| SCREEN's load at start, numpy similarities, the criterion text in the judge cache key | | open (D-907, lane A2) |
| The test-only mail images carry CVEs; the demo image is built only by CI | the build | open (red, lane D) |
| `make_bundle.sh` lists no image without `TB_TZ` (`tools/make_bundle.sh:104`) | the build | open (red, lane D) |
| bundle-check reads the local image Id, which under the containerd store is the index digest (`tools/supply_chain/__main__.py:113`) | the build | open (red, lane D) |
| `install.sh` cannot re-run a half install (F10); `pin_model --install` as uid 10001 cannot write `deploy/site` (F11) | the installer | D-833 (train 29), D-835 (train 30) |
| Key sealing checked the device, not that it works | the installer | D-836, train 30 |

### Lane G's own tooling faults (F1 to F34)

- **The build route, F1 to F8:**
  - no Maven or JDK on the build VM;
  - a resume lost the launch's metadata;
  - the demo image was missing for the gates;
  - `TB_TZ` was missing for the bundle's image list;
  - the containerd store's image digests (worked around with the classic store);
  - the disk was full twice at signing.
- **The installer route, F9 to F12:**
  - the TSS2 libraries were missing for the TPM;
  - the half install was not cleared;
  - the pins were not written;
  - `timeout` was called on a shell function.
- **Bring-up and qualify, F13 to F16:**
  - qualify's missing files, with no heartbeat during its pair gate;
  - qualify started while the models were still loading;
  - the weights mount was lost at reboot;
  - the settings file.
- **The accuracy runs, F17 to F24:**
  - the tables a public site lacks;
  - a stale reviewer;
  - a jRCT record returning HTTP 500 (outside source);
  - the FHIR validation threshold;
  - a shared accuracy folder;
  - a set that answered nobody scored 0 % and set every later budget (fixed: a set with no answer is "not scored, because");
  - the note stage was invisible in the progress line;
  - a stale collect.
- **Scoring and visibility, F25 to F26:** the product's excluded list was read as "no block" (jmed was rescored); the embed facts were on a second line.
- **Repeat runs on one box, F28 to F30, F33 and F34:**
  - the intake keeps one job per mail id;
  - the box keeps an approved ruleset version;
  - one command-line argument is capped at 128 KiB;
  - the second ingest into a snapshot that is already current;
  - a resume dropped the qualify time box.
- **Master runs, F31 to F32:** the run's settings variable leaked into master's build; the `judging` block was not kept for the frozen column.
- F27 is the product's (above).

## What it cost

Spot price: US$2.74 a VM hour. The hours come from the VM's own start and stop times; the running total is the run log's.

| Phase | Launches | VM hours | US$ |
| --- | --- | --- | --- |
| Builds (four; one complete bundle) | L1, L2, L3, L5 | 1.75 | 4.80 |
| Probe | L4 | 0.09 | 0.25 |
| Start: installer, then direct route, G-1, canary, qualify shake-down | L6 | 1.52 | 4.20 |
| The frozen commit's first launch: images, stack, G-1, canary, a full qualify stopped after 1 h 52 min | L7 | 2.10 | 5.75 |
| Phase B probes (qualify 300 s, jmed) | L8 | 0.55 | 1.52 |
| The frozen column's accuracy sets (10 boots) | L9 | 6.85 | 18.77 |
| Master at train 36, stopped at the build (F31) | L10 | 0.06 | 0.16 |
| The master column: images, G-1, canary, qualify (30 min), jmed, tcga BRCA twice (5 boots; F33 to F38) | M1 | 2.32 | 6.35 |

- Spent before step 1: US$59.00.
- Running total: US$100.79. The limit is US$200 (the owner, 2026-11-16), and part B's hard stop was US$130.
- **What bills while stopped** (list prices for Taiwan, read 2026-11-16; not the invoice):
  - the GPU VM's 400 GiB hyperdisk-balanced disk, US$58.20 a month (about US$1.91 a day);
  - the bucket, 28.65 GiB, US$0.57 a month;
  - the two demo VMs' disks, US$3.00 and US$6.00 a month.
- The disk-days so far are not in the running total.

## What was not run, and why

- **TREC 2021 and 2022** (1,225 pairs): not in this phase. Qualify's three evidence steps that need a TREC 2021/22 screen (D-826) cannot pass without them.
- **G-6** (the 50,000-patient night), **G-9** (restarts and an outage mid-screen) and **G-10** (a new model-server image): not in PoC-1's scope.
- **Promotion:** qualify never wrote a passing record, so the pair stays a candidate that a VALIDATION box routes. Promotion is for a hospital install.
- **Deferred to one pass by the integrator after lane A2's compiler fixes** (the owner, 2026-11-16 03:01):
  - B5, the other four tcga protocols on master;
  - B6, sigir and trec2023 in full;
  - B7, chia, jrct and tfda;
  - B9, the determinism re-run;
  - B10, `deploy/poc.sh` from a clean start;
  - B11, a reboot;
  - B12, the disk and Docker sizes;
  - part C.
- **A tcga protocol with its ruleset approved and note_block on:** run on master: the gated tcga BRCA job above screened under an approved ruleset with note_block on, and excluded 384 of 450 with no wrong exclusion.

## How this setup differs from a hospital install

| What | Hospital install | This evidence run | Why |
| --- | --- | --- | --- |
| Install route | the signed bundle and `install.sh` | images built on the VM from the commit; the direct route; no bundle, no signature | the installer route was closed after F10 and F11 (the owner's ruling D-511) |
| Environment | PRODUCTION | VALIDATION | promotion is not in this phase |
| Site keys | sealed (systemd-creds, TPM) | not sealed (`TB_BOX_DEFER_SEAL=1`) | F9; the owner's ruling |
| PHI tripwire | on | off, recorded at step 51 | the gateway refused public protocols as PHI |
| Per-sender job and mail limits | the hospital's | lifted (`TB_JOBS_PER_SENDER_PER_DAY=0`, `TB_MAIL_PER_RECIPIENT_PER_DAY=0`) | hundreds of protocols in one run (D-775) |
| Feed completeness | every table required | `feed_completeness.optional_tables` from the public feed | a public set lacks tables (F17) |
| FHIR validation threshold | 0.5 % | 10 % | public patients without a birth date (F20) |
| Embed memory | 4 GB on 1157c9bf; 6 GB on master (D-890) | 16 GB on 1157c9bf's tcga jobs; master's default 6 GB on master | F27 |
| Reference data pack | loaded from the bundle | not loaded | no bundle; its Japanese synonyms would not change these compiles |
| Patient data | the hospital's coded records | public sets: facts in notes, no coded diagnoses, medications or observations | codes would have to be invented from the gold |
| Serving | shipped | shipped (the tuned exception was cancelled) | |

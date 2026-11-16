# Lane G hand-over to the integrator: everything lane G knows and has (2026-11-16)

**Reader:** the people who build TrialBox

Lane G covers measurement, performance and the validation figures. This page is its complete hand-over, as of
2026-11-16 06:30 UTC.

The integrator takes over every open item listed here. From now on lane G starts nothing unless the integrator asks
on #649 or #639. The one exception is Tuesday's demo VM (section 4).

This page is the index. The detail lives in the pages it links:

- [The PoC-1 evidence page](../../plan/measurements/poc-1-evidence.md): every figure, both columns, faults and cost.
- [The GPU VM hand-over](../gpu-vm-handover-2026-11-16.md): the machines, the driver, every command, the traps, the
  spend log, billing (section 12), access (section 13), and lane A2's scorer points (section 14).
- [The demo walkthrough](../demo-2026-11-17.md): 17 steps, with the closing table filled from the evidence page.
- The working notes in this folder (section 11), copied from lane G's session so that nothing stays only there.

## 1. Where everything stands

| Thing | State |
| --- | --- |
| GPU VM `tb-gpu-sim` (asia-east1-a, g4-standard-48, one RTX PRO 6000 96 GB, spot) | TERMINATED. Metadata reset to the startup script; no launch in flight. **The integrator controls it.** |
| Its disk (400 GiB hyperdisk-balanced) | Kept, by the owner's decision of 2026-11-16. About US$58 a month while stopped (Taiwan list price). Hyperdisk cannot shrink. |
| Demo VM `tb-demo-vm` (asia-east1-a) | TERMINATED. Lane G's scheduled task starts it at 23:30 UTC on 2026-11-16 (Tuesday 07:30 Taipei) for the owner's walkthrough. **Do not touch it on Tuesday.** |
| Old VM `trialbox-demo` (asia-east1-b, 60 GiB disk) | TERMINATED since 2026-11-08. Kept, by the owner's decision. About US$6 a month. |
| Bucket `gs://trialbox-demo-runs` | `boxruns/<run id>/` holds runs, checkpoints, logs and records. `trialbox-demo.tar.gz` (sha256 `2e7b8257…82de`) is Monday's demo image. `trialbox-demo-2026-11-15.tar.gz` is Sunday's, kept. `r2/` holds the validation bundle (not a release). |
| Money (D-505, D-516) | **US$100.79 spent** of the US$200 cap. Part B's stop was a running total of US$130. Step 1 used 15.24 VM hours and US$41.79, of which the master column cost US$6.35. |
| GPU quota | `GPUS_ALL_REGIONS` = 1, so only one GPU VM can run at a time. Lane G could not raise it. To run in parallel, the owner raises it in the console (the access notes, section 13 of the VM hand-over). |

**Pull requests**

| PR | What | State |
| --- | --- | --- |
| #628 | Public data screened by the product: fetchers, item builders, scorer | train-ready at `ae403a1e`, green |
| #649 | The box run, VALIDATION mode, the public-accuracy sets, the evidence page, the VM hand-over, this folder | train-ready at `f34d8b7d`. Later commits on it are documents only. Re-post the head sha before the train |
| #789 | The demo VM hands out one-time links (D-776); Monday's walkthrough | draft, green. Please merge before 23:30 UTC; if not merged, the scheduled start uses its branch `claude/lane-g-demo-monday` |
| #772 | Note-processing fixes | closed: it duplicated lane A2's D-900, D-904 and D-905; D-907 takes the rest |
| #717, #621, #585, #613, #670 | Installer first contact, validation reset, batches 1 to 5, demo seed, walkthrough | merged |

**The driver** is on `claude/lane-g-box-accuracy`: `deploy/gcp/box-run.sh`, `tools/box_run.py`,
`deploy/gcp/box-install-run.sh`, `deploy/gcp/box_vm.py` and `tools/public_accuracy/`. A resume needs the
`.cache/box-run/<run id>/md/` folders; trap T10 in the VM hand-over says where they are.

## 2. What the evidence shows

Each figure names its commit. The frozen column is `1157c9bf` (train 28); the master column is `b266f9b7`
(train 37). The evidence page has every interval and count.

- **tcga BRCA on master, 500 public pathology reports, the box's canary gate open** (`may_block` true,
  `note_block_code` "ok"):
  - excluded 384 of 450 (85.3 %, 81.7 to 88.5);
  - eligible lost 0 of 50 (0 to 7.1);
  - 0 wrong among its 384 exclusions (0 to 0.96);
  - 68 left to a person;
  - about 320 s per 500 patients.
- **The same set with the gate shut:** nobody excluded. Every "not met" goes to review, by lane A2's rule (#639,
  01:13 UTC).
- **jmed:** wrongly excluded fell from 231 of 355 on the frozen commit to 1 of 355 on master (D-796). This
  measures the compiler, never screening accuracy.
- **Frozen tcga, 5 protocols, criterion level:** caught 1,867 of 2,250 (83.0 %); wrongly blocked 1 of 250.
- **sigir and trec2023:** partial on the frozen commit only. A re-run is pending on lane A2's compiler fixes.
- **Speed:** a 500-patient SCREEN took a median of 1,275 s frozen and about 320 s on master (D-904 skips S2b
  when the window fits; 500 of 500 fitted). The embed peak was 908 MiB under the 6 GB default. Judge latency:
  median 3.4 s, p95 5.7 s.
- **G-1:** the identity check passes on both columns. On master the token check also passes on all 20 prompts
  (D-880 confirmed).
- **Canary:** passes. Qualify is not a passing record:
  - in a 30-minute box, serving_record, licence, schema, longest_prompt, log_marker and canary passed;
  - pin failed on lane G's own mount fault (F36, fixed);
  - the pair gate reached 1,468 of 2,986 items and did not finish. It needs about 75 minutes.
- **Safe to say on Tuesday:** "On public data, with the gate open, the pair excluded 85 % of the patients it
  should, with no wrong exclusion and no eligible patient lost, in about 5 minutes per 500 patients."
- **Not to say on Tuesday:** any sigir or trec2023 figure as complete; jmed as screening accuracy; any
  compile-agreement figure on master.

## 3. What broke

**Product faults now fixed on master:**

- D-880 (train 30): the extra token after a system message.
- D-796 (train 32): the negated exclusion and the empty code list.
- D-900 with D-890 (train 33): embed memory, with a 6 GB default.
- D-902 (train 34): SCREEN waits out an embed outage.
- D-838, D-881 and D-889 (trains 30 and 32): qualify's files, code identity, and the host GPU facts.
- D-888 (train 35): the settings file on every start path.
- D-904 (train 36): S2b is skipped when the window fits.
- D-906 (train 37): the terminology.
- D-901: FEAS with nothing to count.
- The installer, through #717: D-833, D-835 and D-836.

**Product faults still open**, all with reds on #639:

- The compiler's class is not stable for the same text.
- Five compile failure classes in trec2023 and sigir (the red of 01:53 UTC, 2026-11-16):
  - (A) only "for a person" criteria;
  - (B) the gateway refuses `upstream_failed` on long protocols;
  - (C) criteria-compiler HTTP 500;
  - (D) the criteria count does not equal the line count;
  - (E) the CQL translator's logger line is read as its output.
- Structured medication or observation inclusions on a site with no coded rows: the 10 cases in part A2 on #649.
- D-907 (lane A2): the load at start, numpy similarities, and the criterion text in the judge cache key.
- Lane D's three build reds: the mail-image CVEs, `TB_TZ` in `make_bundle.sh`, and the bundle-check digest.
- The start-up canary meets model servers that are still loading, so note_block stays off until the orchestrator
  restarts. The card is #808 (D-915). Until it lands, run step 07g, or restart the orchestrator once the models
  answer, before any SCREEN whose pair level matters.
- The admin "Run now" (`POST /models/canary`) refused the operator's token with HTTP 403 (F35). Worth a look by
  its owner.

**Lane G's own faults:** F1 to F38, all fixed in the driver. There is one line each in the evidence page and the
run log.

## 4. Tuesday's demo (lane G keeps this one)

- **The image:** rebuilt from master `2d354036` (train 37) and seeded in zh-TW (`TB_DEMO_LANG=zh-TW`), with
  one-time sign-in links. The local rehearsal passed 26 of 26.
- **The walk:** all 17 steps passed as owner and as guest, plus the CASE step.
- **Three cosmetic reds on #639:**
  - lane C2: the investigator still sees the SAE set-up notes;
  - lane B2: the English GZQO-EXC-14 label is cut off;
  - lane B2: the CASE sheet is mostly "unknown".
- **The scheduled start** (23:30 UTC on 2026-11-16) uses worktree `lgdemo5`, or master if #789 has merged.
  - It checks the image sha.
  - It runs `TB_DEMO_ALLOW=any demo-vm.sh up --yes`, waits for `boot: DEMO-VM-READY`, then runs `links` once.
  - It gives the owner the address, the stop time and the two links in lane G's session only, never on GitHub.
  - After the demo it runs `down` and confirms TERMINATED.
- The local walk showed "data more than two days old", because Monday's walk used Friday's seed. Tuesday's start
  seeds Monday's data (D-757), so this is not expected then. That is the design; it was not observed directly.

## 5. Credentials (no secret is in this repository)

- **Google Cloud:**
  - The owner gave the integrator's session the deployer service-account key as a file. Lane G uses the same key.
  - Use it by path only, with a private `CLOUDSDK_CONFIG`. Never print it, commit it or put it in a comment.
  - The least-privilege roles and the steps for a `tb-integrator` account of its own are in the VM hand-over,
    section 13.
  - The owner will rotate the key once the integrator has its own account.
- **The external code model:** an API key from the owner, held only in lane G's session. The procedure is
  `docs/plan/41-external-worker.md` with `tools/external_worker.py`.
  - The PR wording is "drafted by an external model through the harness; checked and audited by <the session>".
  - Name no model.
  - Never send it the exclusion logic, the cascade, prompts, masking, key sealing, opt-out, hospital sources or
    the private bucket.
  - The owner will rotate this key too.
- **The demo:** sign-in links are made on the VM at boot and are one-time. They exist only in lane G's session.

## 6. The owner's rulings that bear on this work

| Ruling | Says |
| --- | --- |
| D-505 / D-516 | The budget: first US$150, then US$210. Before each launch, post the estimate, the worst case and the running total. Stop a launch that runs more than 50 % over its estimate. |
| D-506 | The PHI tripwire applies only on routes that leave the box, and has a setting. |
| D-507 | The limits are settings. |
| D-508 / D-509 | The demo is open to any address, gated by password and TLS. People set their own passwords; the owner does nothing in Cloud Shell. |
| D-510 | Sessions do the work; the owner gets decisions, not chores. |
| D-511 | PoC-1. |
| D-512 | A de-identified hospital carve may come later. It is a separate cost question and never goes on GitHub. |
| D-515 | Evidence on two commits, never mixed. |
| D-517 | The gold set is route A: labelled notes from the de-identified carve, English first, then zh-TW. |
| D-519 | The judged-pair store is approved; lane A2 designs it. |
| Owner, 2026-11-16 | Keep the 400 GiB disk and the old VM. The tuned-serving exception was given, then cancelled by the 03:01 relay: shipped serving only. |

**Held by the owner:** serving changes (max-num-seqs, enforce-eager, speculative decoding), a deterministic note
extractor that may decide, hardware tiers, and the judged-pair store's design.

## 7. Open work handed over, with what each waits for

| Item | Waits for | Estimate (from the VM hand-over) |
| --- | --- | --- |
| A pass on master after lane A2's compiler fixes: sigir (104) and trec2023 (297 protocols, 500 pairs) in full; chia, jrct and tfda at compile level; tcga COAD, HNSC, KIRC and LIHC (about 5 min each now); B9 determinism; B10 `poc.sh` from clean; B11 reboot; B12 lane D's disk sizes; C1 (the failed protocols and the 10 cases); C2 (when the judged-pair store lands, its hit rate) | lane A2's six compiler cards | VM hand-over, section 11 |
| A full qualify (`--box`, about a 75-minute box, `TB_HOST_PROFILE=poc`) | the integrator's next launch | about 1.5 h |
| NEW-LLM-6: an accuracy set with gold per criterion, per language and stratum | the D-517 gold set | – |
| T-667: the capacity statement (the Linux figure) | G-3 at 4, 8 and 16, and G-6 (a dense night at 50k under the caps), on an installed box after T-692 | – |
| The 500k capacity measurement (HW-007) | the incremental night (T-694, T-702, T-703) | – |
| P3, P4, P5 from lane G's findings of 2026-11-13 | their card owners | – |
| G-6, G-9 (restarts and power cycle), G-10 (vLLM image move), G-11 (embedder), TREC 2021/22, promotion | an installed box and a job API; outside this phase (D-826) | – |
| Lane A2's four scorer points | whoever takes up #614's scorer; VM hand-over, section 14 | – |
| zh-TW gold from real cases rewritten by clinicians | CGRD, through the integrator | – |
| The PRO 6000 against a 32 GB (5090-like) setting; Spark on a real unit | the owner's hardware decision | about US$6 on the VM; Spark needs a unit |

## 8. Reviews that need decisions (in this folder)

- **[review-note-processing.md](review-note-processing.md):** the path from note ingest to the judge, with
  file:line.
  - S2b embedding cost about 75 % of a SCREEN for no change in any prompt; now fixed by D-904.
  - Embedding was redone per criterion; D-900's cache addresses it.
  - There was no input length cap; D-905 adds one.
  - Nothing survives a job. The spec's persistent cache (CAS-5) and dirty set (CAS-6) are not built. D-519
    approves the store; its key must hold the criterion wording, the exact excerpt set, the prompt and model
    shas, and the index date. Refusals are never stored, D-478 is re-applied on read, and audit samples bypass
    the store.
- **[review-textmining-hardware-serving.md](review-textmining-hardware-serving.md):** cited sources, estimates
  marked as estimates.
  - The structured side already has strong classical tools. The note side has almost none: a 31-word S2 table.
    Negation rules exist only on the chart-upload path.
  - Under D-131/D-135 and D-478, a rule can only rank evidence or widen an answer to unknown, unless a new
    D-number lets it decide.
  - Hardware:
    - the RTX PRO 6000 holds both models at a 32k context;
    - a DGX Spark runs at about 273 GB/s, so it is slow; it is a small-site candidate once measured;
    - an RTX 5090 needs sleep-swap and an 8k context, and has never been measured on a physical card.
  - Serving is current (vLLM 0.32), but cautious: `--enforce-eager`, and 16 in flight. Those changes are the
    owner's to make, through MC-6.

## 9. Traps (all in the VM hand-over, with their fixes)

- The root file system grows only at boot.
- The mail intake keeps one job per mail id: use `--redo`, which mails under new ids (F28).
- The box keeps an approved ruleset version: use `--acc-rs-tag`, and expect FEAS of a kept version to be "done"
  on master (F29, F38).
- The weights mount is lost after a reboot (F15).
- The kernel limits one command-line argument to 128 KiB (F30).
- The accuracy folder must belong to one run (F21).
- A bare `gcloud compute instances start tb-gpu-sim` replays the last run's metadata (T7). Always use
  `box-run.sh`, whose `--stop` resets the VM.
- A run's settings variable must not leak into the build (F31).
- Leave `TB_MEM_EMBED` at master's default; the 16g left in `deploy/.env` (F37) must not come back.
- The start-up canary needs healthy model servers (#808).
- Only one GPU VM can run at a time (the quota).
- Never remove a lock you did not create. On 2026-11-16 at 02:26 one was removed by mistake and restored within
  a minute.

## 10. What lane G advises next, in order

1. Merge #789 before 23:30 UTC. Train #628, then #649.
2. Land #808 (D-915), so the gate is open without a restart.
3. Land lane A2's compiler cards. Then run the pass in section 7 on master, with the estimate posted on #639
   first. Measure sigir's per-protocol time before you launch trec2023.
4. Run a full qualify in a 75-minute box.
5. Build the judged-pair store (D-519), then run C2.
6. When the D-517 gold arrives: NEW-LLM-6 per language.
7. When T-692, T-694, T-702 and T-703 land: G-3 and G-6 under the caps, then the 500k statement.

## 11. The files in this folder

These are lane G's working notes, copied so that nothing stays only in its session. Model names are replaced by
their roles. No address, key or sign-in code is in them.

| File | What |
| --- | --- |
| [owner-plan-2026-11-16.md](owner-plan-2026-11-16.md) | The owner's plan for the rest of PoC-1 and the hand-over (parts A to E) |
| [run-log-poc1.md](run-log-poc1.md) | Every launch: time, commit, run id, hours, US$ and running total; faults F1 to F38 |
| [plan-poc1-rest.md](plan-poc1-rest.md) | The gated plan: phases A to D and their stop rules |
| [review-note-processing.md](review-note-processing.md) | The note path, from ingest to the judge |
| [review-textmining-hardware-serving.md](review-textmining-hardware-serving.md) | Text mining, hardware and serving |
| [review-build-chain.md](review-build-chain.md) | The build and installer chain review of 2026-11-15 |
| [audit-a-models.md](audit-a-models.md), [audit-b-data.md](audit-b-data.md), [audit-c-lane-g.md](audit-c-lane-g.md) | Audits of the models, the data and lane G's own tooling |
| [public-data-en.md](public-data-en.md), [public-data-zh-ja.md](public-data-zh-ja.md) | Catalogues of public clinical data, with their licences |
| [plan-public-accuracy-run.md](plan-public-accuracy-run.md), [plan-first-accuracy-run.md](plan-first-accuracy-run.md) | The accuracy run plans and their sizes |
| [cost-table-d502.md](cost-table-d502.md), [r2-bundle-plan.md](r2-bundle-plan.md) | The D-502 cost table and the R2 bundle plan |
